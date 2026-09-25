#!/usr/bin/env python3
"""Read live ReSpeaker array status for Home Assistant command_line sensors.

Level and per-channel energy come from the capture tee (wakeword_array_status.json).
Direction comes from the XVF-3000 chip itself (wakeword_doa.json, written by
respeaker_tuning_service.py); the old 4-mic energy ratio is kept only as
energy_direction_degrees and as a fallback when the chip reading is stale.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"state": "missing", "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        return {"state": "invalid", "updated_at": None, "error": str(err)}

    updated_at = parse_time(data.get("updated_at"))
    age = None
    if updated_at is not None:
        age = max(0.0, (dt.datetime.now(dt.UTC) - updated_at).total_seconds())
    data["age_seconds"] = None if age is None else round(age, 1)
    data["state"] = "stale" if age is None or age > 10.0 else "ok"
    return data


def merge_doa(status: dict[str, Any], doa_path: Path) -> dict[str, Any]:
    doa = load_status(doa_path)
    status["energy_direction_degrees"] = status.get("direction_degrees")
    if doa.get("state") == "ok" and doa.get("age_seconds") is not None and doa["age_seconds"] <= 3.0:
        status["direction_degrees"] = doa.get("direction_degrees")
        status["direction_source"] = "xvf3000_doa"
        for key in ("voice_activity", "speech_detected", "speech_trail_degrees", "agc_on", "agc_gain"):
            status[key] = doa.get(key)
    else:
        status["direction_source"] = "energy_fallback"
        status["doa_state"] = doa.get("state")
    return status


def scalar(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path, default=Path("/home/ultra/oww-dataset/wakeword_array_status.json"))
    parser.add_argument("--doa-file", type=Path, help="default: wakeword_doa.json next to --status-file")
    parser.add_argument("field", choices=("json", "direction", "level", "confidence"), default="json", nargs="?")
    args = parser.parse_args()

    status = load_status(args.status_file)
    status = merge_doa(status, args.doa_file or args.status_file.with_name("wakeword_doa.json"))
    if args.field == "json":
        print(json.dumps(status, ensure_ascii=False))
    elif status.get("state") != "ok":
        print("unknown")
    elif args.field == "direction":
        print(scalar(status.get("direction_degrees")))
    elif args.field == "level":
        print(scalar(status.get("level_dbfs")))
    elif args.field == "confidence":
        print(scalar(status.get("confidence")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
