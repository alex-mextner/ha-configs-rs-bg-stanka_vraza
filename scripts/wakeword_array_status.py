#!/usr/bin/env python3
"""Read live ReSpeaker array status for Home Assistant command_line sensors."""

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


def scalar(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path, default=Path("/home/ultra/oww-dataset/wakeword_array_status.json"))
    parser.add_argument("field", choices=("json", "direction", "level", "confidence"), default="json", nargs="?")
    args = parser.parse_args()

    status = load_status(args.status_file)
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
