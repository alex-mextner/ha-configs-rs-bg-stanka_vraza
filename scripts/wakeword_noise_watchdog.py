#!/usr/bin/env python3
"""Run and watch the wakeword background-noise recording session.

The capture pipeline (wakeword_channel0_tee.py) records raw_live/ segments only
while the session in raw_live_session.json is active, so `start` and `stop`
here control recording without restarting any container.

`check` (cron) measures every new segment once (duration, peak, RMS) into a
level cache, counts only non-silent audio toward the target, and alerts when
recording stalls, when the microphone delivers digital silence (the June 2026
session recorded 222 h of zeros unnoticed), or when the disk runs low. It also
writes noise_session_status.json for the Home Assistant UI.
"""

from __future__ import annotations

import argparse
import array
import math
import shutil
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any


DEFAULT_SESSION_FILE = Path("/home/ultra/oww-dataset/raw_live_session.json")
DEFAULT_DATASET_ROOT = Path("/home/ultra/oww-dataset")
DEFAULT_HA_URL = "http://localhost:8123"
DEFAULT_TARGET_HOURS = 24 * 7


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return frames / rate if rate else 0.0
    except Exception:
        return 0.0


SILENT_PEAK = 2  # |sample| <= 2 everywhere: digital silence, not a quiet room
LEVEL_CACHE = ".levels.json"


def measure_wav(path: Path) -> dict[str, float] | None:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except Exception:
        return None
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % 2])
    if not samples or not rate:
        return {"duration": 0.0, "peak": 0, "rms_dbfs": -120.0}
    peak = max(max(samples), -min(samples))
    step = samples[::8]
    mean_sq = sum(v * v for v in step) / len(step)
    rms_dbfs = 20 * math.log10(math.sqrt(mean_sq) / 32768) if mean_sq > 0 else -120.0
    return {"duration": len(samples) / rate, "peak": int(peak), "rms_dbfs": round(rms_dbfs, 1)}


def summarize_raw_live(dataset_root: Path, started_at: dt.datetime | None, update_cache: bool = True) -> dict[str, Any]:
    raw_live = dataset_root / "raw_live"
    cache_path = raw_live / LEVEL_CACHE
    cache: dict[str, Any] = load_json(cache_path) if cache_path.exists() else {}
    files = sorted(raw_live.rglob("*.wav")) if raw_live.exists() else []
    latest_path: Path | None = None
    latest_mtime: dt.datetime | None = None
    seconds = silent_seconds = 0.0
    counted = silent_files = 0
    recent: list[dict[str, Any]] = []
    changed = False
    newest_sound: dt.datetime | None = None

    for path in files:
        stat = path.stat()
        mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC)
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime, latest_path = mtime, path
        if stat.st_size <= 44 or (started_at is not None and mtime < started_at):
            continue
        key = str(path.relative_to(raw_live))
        entry = cache.get(key)
        # The newest segment is still being written: measure it, but do not cache it yet.
        still_writing = (now_utc() - mtime).total_seconds() < 90
        if entry is None or entry.get("size") != stat.st_size:
            if not update_cache and entry is None:
                continue
            measured = measure_wav(path)
            if measured is None:
                continue
            entry = {"size": stat.st_size, **measured}
            if not still_writing:
                cache[key] = entry
                changed = True
        counted += 1
        if entry["peak"] <= SILENT_PEAK:
            silent_files += 1
            silent_seconds += entry["duration"]
        else:
            seconds += entry["duration"]
            newest_sound = mtime if newest_sound is None or mtime > newest_sound else newest_sound
        recent.append({"file": key, **{k: entry[k] for k in ("duration", "peak", "rms_dbfs")}})

    if changed and update_cache:
        save_json(cache_path, cache)
    # The capture tee deletes digital-silence segments and logs them here.
    skipped_files, last_skip = 0, None
    skip_log = raw_live / "silence_skipped.jsonl"
    if skip_log.exists():
        for line in skip_log.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                end = dt.datetime.fromisoformat(item["end"])
            except (ValueError, KeyError, TypeError):
                continue
            if started_at is not None and end < started_at:
                continue
            skipped_files += 1
            silent_files += 1
            silent_seconds += float(item.get("seconds") or 0)
            last_skip = end if last_skip is None or end > last_skip else last_skip
    if last_skip is not None and (latest_mtime is None or last_skip > latest_mtime):
        latest_mtime = last_skip
    newest_age_seconds = None
    if latest_mtime is not None:
        newest_age_seconds = max(0.0, (now_utc() - latest_mtime).total_seconds())
    recent = recent[-5:]
    return {
        "files": len(files),
        "nonempty_files_since_start": counted,
        "hours_since_start": round(seconds / 3600.0, 4),
        "silent_files_since_start": silent_files,
        "silent_hours_since_start": round(silent_seconds / 3600.0, 4),
        "recent_segments": recent,
        "recent_all_silent": (bool(recent) and all(r["peak"] <= SILENT_PEAK for r in recent[-3:]))
        or (last_skip is not None and (not recent or recent[-1]["peak"] <= SILENT_PEAK)
            and (newest_sound is None or last_skip >= newest_sound)),
        "silence_skipped_files_since_start": skipped_files,
        "latest_file": str(latest_path) if latest_path else None,
        "latest_mtime": latest_mtime.isoformat() if latest_mtime else None,
        "latest_age_seconds": newest_age_seconds,
    }


def disk_status(dataset_root: Path) -> dict[str, float]:
    usage = shutil.disk_usage(dataset_root)
    return {"free_gb": round(usage.free / 1e9, 1), "total_gb": round(usage.total / 1e9, 1)}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def ha_token() -> str:
    load_env_file(Path("/home/ultra/.env"))
    token = os.environ.get("HA_TOKEN")
    if not token:
        raise RuntimeError("HA_TOKEN is not set and was not found in /home/ultra/.env")
    return token


def call_ha_service(ha_url: str, domain: str, service: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{ha_url.rstrip('/')}/api/services/{domain}/{service}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {ha_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    return {"status": "ok", "url": url, "response": body}


def notify_ha(ha_url: str, title: str, message: str, notification_id: str) -> list[dict[str, Any]]:
    results = []
    persistent_payload = {
        "title": title,
        "message": message,
        "notification_id": notification_id,
    }
    results.append(call_ha_service(ha_url, "persistent_notification", "create", persistent_payload))

    notify_payload = {
        "title": title,
        "message": message,
    }
    try:
        results.append(call_ha_service(ha_url, "notify", "notify", notify_payload))
    except (urllib.error.URLError, RuntimeError) as err:
        results.append({"status": "notify.notify failed", "error": str(err)})
    return results


def session_status(args: argparse.Namespace, update_cache: bool = True) -> dict[str, Any]:
    session = load_json(args.session_file)
    started_at = parse_time(session.get("started_at"))
    raw_live = summarize_raw_live(args.dataset_root, started_at, update_cache)
    target_hours = float(session.get("target_hours", args.target_hours))
    recording = bool(session.get("started_at")) and not session.get("completion_notification_sent_at") and not session.get("stopped_at")
    if recording:
        state = "recording"
    elif session.get("completion_notification_sent_at"):
        state = "complete"
    elif session.get("stopped_at"):
        state = "stopped"
    else:
        state = "idle"
    hours = raw_live["hours_since_start"]
    elapsed = (now_utc() - started_at).total_seconds() / 3600 if started_at else 0.0
    return {
        "updated_at": now_utc().isoformat(),
        "session_file": str(args.session_file),
        "active": recording,
        "state": state,
        "session": session,
        "raw_live": raw_live,
        "disk": disk_status(args.dataset_root),
        "target_hours": target_hours,
        "progress": round(min(1.0, hours / target_hours), 4) if target_hours else 0.0,
        "eta_hours": round((target_hours - hours) * elapsed / hours, 1) if recording and hours > 0.05 else None,
        "complete": hours >= target_hours,
    }


def write_status_file(args: argparse.Namespace, status: dict[str, Any]) -> None:
    compact = {k: v for k, v in status.items() if k != "session"}
    compact["started_at"] = status["session"].get("started_at")
    compact["stopped_at"] = status["session"].get("stopped_at")
    compact["purpose"] = status["session"].get("purpose")
    save_json(args.dataset_root / "noise_session_status.json", compact)


def command_start(args: argparse.Namespace) -> int:
    previous = load_json(args.session_file)
    running = previous.get("started_at") and not previous.get("completion_notification_sent_at") and not previous.get("stopped_at")
    if running and not args.force:
        print("A noise session is already recording; use --force to replace it", file=sys.stderr)
        return 1
    if previous:
        archive = args.session_file.with_name(f"raw_live_session.{now_utc().strftime('%Y%m%dT%H%M%SZ')}.json")
        save_json(archive, previous)
    data = {
        "started_at": now_utc().isoformat(),
        "target_hours": args.target_hours,
        "purpose": args.purpose,
        "rule": "Do not say the chosen wake phrase near the microphone while this session records.",
        "completion_notification_sent_at": None,
        "stopped_at": None,
        "stale_notification_sent_at": None,
        "recovered_notification_sent_at": None,
        "silence_notification_sent_at": None,
        "disk_notification_sent_at": None,
    }
    save_json(args.session_file, data)
    status = session_status(args)
    write_status_file(args, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def command_stop(args: argparse.Namespace) -> int:
    session = load_json(args.session_file)
    if not session.get("started_at") or session.get("stopped_at") or session.get("completion_notification_sent_at"):
        print("No recording session to stop", file=sys.stderr)
        return 1
    session["stopped_at"] = now_utc().isoformat()
    save_json(args.session_file, session)
    status = session_status(args)
    write_status_file(args, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    status = session_status(args, update_cache=not args.no_cache_update)
    if args.write:
        write_status_file(args, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def stale_repeat_allowed(session: dict[str, Any], repeat_hours: float) -> bool:
    last = parse_time(session.get("stale_notification_sent_at"))
    if last is None:
        return True
    return (now_utc() - last).total_seconds() >= repeat_hours * 3600


def command_check(args: argparse.Namespace) -> int:
    session = load_json(args.session_file)
    if not session:
        print(f"No active session at {args.session_file}")
        return 0

    status = session_status(args)
    raw_live = status["raw_live"]
    target_hours = float(status["target_hours"])
    latest_age = raw_live.get("latest_age_seconds")
    ha_url = args.ha_url
    changed = False

    if status["complete"] and not session.get("completion_notification_sent_at"):
        message = (
            "Недельная запись фонового шума для wake word завершена.\n"
            f"Recorded hours: {raw_live['hours_since_start']:.4f}/{target_hours:.1f}\n"
            f"Dataset: {args.dataset_root / 'raw_live'}\n"
            "Можно запускать full streaming evaluation и следующую итерацию модели."
        )
        if args.dry_run:
            print(message)
        else:
            print(json.dumps(notify_ha(ha_url, "Wakeword noise recording complete", message, "wakeword_noise_complete"), ensure_ascii=False, indent=2))
        session["completion_notification_sent_at"] = now_utc().isoformat()
        changed = True

    if status["active"] and not status["complete"]:
        if latest_age is None or latest_age > args.stale_seconds:
            if stale_repeat_allowed(session, args.stale_repeat_hours):
                message = (
                    "Wakeword background-noise recording appears stalled.\n"
                    f"Recorded hours: {raw_live['hours_since_start']:.4f}/{target_hours:.1f}\n"
                    f"Latest file: {raw_live.get('latest_file')}\n"
                    f"Latest age seconds: {latest_age}"
                )
                if args.dry_run:
                    print(message)
                else:
                    print(json.dumps(notify_ha(ha_url, "Wakeword recording stalled", message, "wakeword_noise_stalled"), ensure_ascii=False, indent=2))
                session["stale_notification_sent_at"] = now_utc().isoformat()
                changed = True
        elif session.get("stale_notification_sent_at") and not session.get("recovered_notification_sent_at"):
            message = (
                "Wakeword background-noise recording is receiving audio again.\n"
                f"Recorded hours: {raw_live['hours_since_start']:.4f}/{target_hours:.1f}\n"
                f"Latest file: {raw_live.get('latest_file')}"
            )
            if args.dry_run:
                print(message)
            else:
                print(json.dumps(notify_ha(ha_url, "Wakeword recording recovered", message, "wakeword_noise_recovered"), ensure_ascii=False, indent=2))
            session["recovered_notification_sent_at"] = now_utc().isoformat()
            changed = True

    recording = status["active"]
    silence_repeat = stale_repeat_allowed(
        {"stale_notification_sent_at": session.get("silence_notification_sent_at")}, args.stale_repeat_hours
    )
    if recording and raw_live.get("recent_all_silent") and silence_repeat:
        message = (
            "Запись шума для wake word пишет цифровую тишину: у последних сегментов нулевая амплитуда.\n"
            "Скорее всего записывается не то устройство или микрофон отвалился. Эти часы не засчитываются.\n"
            f"Latest file: {raw_live.get('latest_file')}"
        )
        if args.dry_run:
            print(message)
        else:
            print(json.dumps(notify_ha(ha_url, "Wakeword recording is silent", message, "wakeword_noise_silent"), ensure_ascii=False, indent=2))
        session["silence_notification_sent_at"] = now_utc().isoformat()
        changed = True

    disk = status["disk"]
    disk_repeat = stale_repeat_allowed(
        {"stale_notification_sent_at": session.get("disk_notification_sent_at")}, args.stale_repeat_hours
    )
    if recording and disk["free_gb"] < args.min_free_gb and disk_repeat:
        message = (
            f"На диске осталось {disk['free_gb']} GB. Запись шума сама встает на паузу ниже 30 GB, "
            "чтобы не уронить Home Assistant. Освободите место или остановите сессию."
        )
        if args.dry_run:
            print(message)
        else:
            print(json.dumps(notify_ha(ha_url, "Wakeword recording: low disk", message, "wakeword_noise_disk"), ensure_ascii=False, indent=2))
        session["disk_notification_sent_at"] = now_utc().isoformat()
        changed = True

    if changed and not args.dry_run:
        save_json(args.session_file, session)

    write_status_file(args, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def command_notify_test(args: argparse.Namespace) -> int:
    message = "Wakeword background-noise recording watchdog notification path is working."
    print(json.dumps(notify_ha(args.ha_url, "Wakeword recording watchdog", message, "wakeword_noise_watchdog_test"), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--session-file", type=Path, default=DEFAULT_SESSION_FILE)
    parser.add_argument("--target-hours", type=float, default=DEFAULT_TARGET_HOURS)
    parser.add_argument("--ha-url", default=os.environ.get("HA_URL", DEFAULT_HA_URL))
    sub = parser.add_subparsers(required=True)

    start = sub.add_parser("start")
    start.add_argument("--purpose", default="wakeword background-noise recording (no wake phrase spoken)")
    start.add_argument("--force", action="store_true")
    start.set_defaults(func=command_start)

    stop = sub.add_parser("stop")
    stop.set_defaults(func=command_stop)

    status = sub.add_parser("status")
    status.add_argument("--write", action="store_true", help="also write noise_session_status.json")
    status.add_argument("--no-cache-update", action="store_true")
    status.set_defaults(func=command_status)

    check = sub.add_parser("check")
    check.add_argument("--stale-seconds", type=float, default=180)
    check.add_argument("--stale-repeat-hours", type=float, default=6)
    check.add_argument("--dry-run", action="store_true")
    check.add_argument("--min-free-gb", type=float, default=40.0)
    check.set_defaults(func=command_check)

    notify_test = sub.add_parser("notify-test")
    notify_test.set_defaults(func=command_notify_test)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
