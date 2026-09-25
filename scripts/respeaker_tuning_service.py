#!/usr/bin/env python3
"""ReSpeaker USB Mic Array v2.0 (XMOS XVF-3000) tuning reader.

Polls the chip's own direction-of-arrival and voice detectors over the USB
vendor control endpoint (read-only requests; audio keeps flowing through the
ALSA driver) and publishes them for the rest of the voice stack:

- <dataset>/wakeword_doa.json      latest reading, rewritten every 0.2 s (HA sensor, UI)
- <dataset>/wakeword_doa_stats.json hourly histograms of the direction while the chip
                                    detects speech, kept for 48 h (where do voices come from:
                                    the TV shows up as a fixed sector)
- <dataset>/raw_live/<UTC day>/doa.jsonl  1 Hz direction log while a noise session records,
                                    aligned with the raw_live WAV segments

The device node is opened as root (USB nodes are root:root 0664 and control
transfers need write access), then the process drops to uid/gid 1000 so every
file it writes belongs to the dataset owner. On any USB error it exits and the
container restart policy reopens the device (covers unplug/replug).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import struct
import sys
import time
from collections import deque
from pathlib import Path

VID, PID = 0x2886, 0x0018
# name: (parameter id, offset, type) from respeaker/usb_4_mic_array tuning.py
PARAMS = {
    "DOAANGLE": (21, 0, "int"),
    "VOICEACTIVITY": (19, 32, "int"),
    "SPEECHDETECTED": (19, 22, "int"),
    "AGCONOFF": (19, 0, "int"),
    "AGCGAIN": (19, 3, "float"),
}
BINS = 36  # 10 degree histogram bins


def log(msg: str) -> None:
    print(f"[respeaker-tuning] {msg}", file=sys.stderr, flush=True)


def read_param(dev, name: str) -> float:
    import usb.util  # noqa: PLC0415

    param_id, offset, kind = PARAMS[name]
    cmd = 0x80 | offset | (0x40 if kind == "int" else 0)
    raw = dev.ctrl_transfer(
        usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE, 0, cmd, param_id, 8, 1000
    )
    value, exponent = struct.unpack("ii", bytes(raw))
    return float(value) if kind == "int" else value * (2.0 ** exponent)


def atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def noise_session_active(session_file: Path) -> bool:
    try:
        s = json.loads(session_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(s.get("started_at")) and not s.get("completion_notification_sent_at") and not s.get("stopped_at")


def drop_privileges(uid: int, gid: int) -> None:
    if os.getuid() != 0:
        return
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=Path("/dataset"))
    ap.add_argument("--interval", type=float, default=0.1)
    ap.add_argument("--uid", type=int, default=1000)
    ap.add_argument("--gid", type=int, default=1000)
    args = ap.parse_args()

    import usb.core  # noqa: PLC0415

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        log("ReSpeaker 2886:0018 not found; retrying in 10 s")
        time.sleep(10)
        return 1
    try:
        read_param(dev, "DOAANGLE")  # opens the device handle while still root
    except Exception as exc:  # noqa: BLE001
        log(f"cannot open device: {exc}")
        time.sleep(10)
        return 1
    drop_privileges(args.uid, args.gid)
    log(f"reading XVF-3000 tuning at {1 / args.interval:.0f} Hz as uid {os.getuid()}")

    latest_path = args.dataset / "wakeword_doa.json"
    stats_path = args.dataset / "wakeword_doa_stats.json"
    session_file = args.dataset / "raw_live_session.json"
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stats = {"bin_degrees": 360 // BINS, "hours": {}}
    recent = deque(maxlen=int(1.0 / args.interval))  # last second of readings
    trail = deque(maxlen=30)  # last 3 s of speech directions for the UI
    last_write = last_second = last_stats = last_agc = 0.0
    agc_on, agc_gain = None, None
    session_active, session_checked = False, 0.0

    while True:
        t0 = time.time()
        try:
            doa = int(read_param(dev, "DOAANGLE")) % 360
            va = int(read_param(dev, "VOICEACTIVITY"))
            sd = int(read_param(dev, "SPEECHDETECTED"))
            if t0 - last_agc > 5:
                last_agc = t0
                try:
                    agc_on = int(read_param(dev, "AGCONOFF"))
                    agc_gain = round(read_param(dev, "AGCGAIN"), 3)
                except Exception:  # noqa: BLE001
                    agc_on, agc_gain = -1, None
        except Exception as exc:  # noqa: BLE001
            log(f"USB read failed ({exc}); exiting so the container reopens the device")
            return 1
        now = dt.datetime.now(dt.UTC)
        recent.append((doa, va, sd))
        if sd:
            trail.append(doa)
            hour = now.strftime("%Y-%m-%dT%H")
            hist = stats["hours"].setdefault(hour, [0] * BINS)
            hist[doa * BINS // 360] += 1

        if t0 - last_write >= 0.2:
            atomic_write(latest_path, {
                "updated_at": now.isoformat(),
                "source": "xvf3000_doa",
                "direction_degrees": doa,
                "voice_activity": va,
                "speech_detected": sd,
                "speech_trail_degrees": list(trail),
                "agc_on": agc_on,
                "agc_gain": agc_gain,
            })
            last_write = t0

        if t0 - session_checked > 5:
            session_active = noise_session_active(session_file)
            session_checked = t0
        if t0 - last_second >= 1.0:
            if session_active and recent:
                day_dir = args.dataset / "raw_live" / now.strftime("%Y-%m-%d")
                day_dir.mkdir(parents=True, exist_ok=True)
                n = len(recent)
                row = {"t": round(t0, 1), "doa": recent[-1][0],
                       "va": round(sum(r[1] for r in recent) / n, 2), "sd": round(sum(r[2] for r in recent) / n, 2)}
                with (day_dir / "doa.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
            last_second = t0

        if t0 - last_stats >= 60:
            cutoff = (now - dt.timedelta(hours=48)).strftime("%Y-%m-%dT%H")
            stats["hours"] = {h: v for h, v in stats["hours"].items() if h >= cutoff}
            stats["updated_at"] = now.isoformat()
            atomic_write(stats_path, stats)
            last_stats = t0

        time.sleep(max(0.0, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
