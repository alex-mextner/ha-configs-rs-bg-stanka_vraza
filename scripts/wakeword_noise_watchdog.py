#!/usr/bin/env python3
"""Watch one-week wakeword background-noise recording and notify Home Assistant."""

from __future__ import annotations

import argparse
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


def summarize_raw_live(dataset_root: Path, started_at: dt.datetime | None) -> dict[str, Any]:
    raw_live = dataset_root / "raw_live"
    files = sorted(raw_live.rglob("*.wav")) if raw_live.exists() else []
    selected = []
    latest_path: Path | None = None
    latest_mtime: dt.datetime | None = None

    for path in files:
        stat = path.stat()
        mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC)
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path
        if stat.st_size <= 44:
            continue
        if started_at is not None and mtime < started_at:
            continue
        duration = wav_duration(path)
        if duration <= 0:
            continue
        selected.append((path, duration, stat.st_size, mtime))

    newest_age_seconds = None
    if latest_mtime is not None:
        newest_age_seconds = max(0.0, (now_utc() - latest_mtime).total_seconds())

    return {
        "files": len(files),
        "nonempty_files_since_start": len(selected),
        "hours_since_start": round(sum(row[1] for row in selected) / 3600.0, 4),
        "latest_file": str(latest_path) if latest_path else None,
        "latest_mtime": latest_mtime.isoformat() if latest_mtime else None,
        "latest_age_seconds": newest_age_seconds,
    }


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


def session_status(args: argparse.Namespace) -> dict[str, Any]:
    session = load_json(args.session_file)
    started_at = parse_time(session.get("started_at"))
    raw_live = summarize_raw_live(args.dataset_root, started_at)
    target_hours = float(session.get("target_hours", args.target_hours))
    return {
        "session_file": str(args.session_file),
        "active": bool(session),
        "session": session,
        "raw_live": raw_live,
        "target_hours": target_hours,
        "complete": raw_live["hours_since_start"] >= target_hours,
    }


def command_start(args: argparse.Namespace) -> int:
    started_at = now_utc()
    data = {
        "started_at": started_at.isoformat(),
        "target_hours": args.target_hours,
        "purpose": "wakeword background-noise recording",
        "completion_notification_sent_at": None,
        "stale_notification_sent_at": None,
        "recovered_notification_sent_at": None,
    }
    save_json(args.session_file, data)
    print(json.dumps(session_status(args), ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    print(json.dumps(session_status(args), ensure_ascii=False, indent=2))
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

    if not status["complete"]:
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

    if changed and not args.dry_run:
        save_json(args.session_file, session)

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
    start.set_defaults(func=command_start)

    status = sub.add_parser("status")
    status.set_defaults(func=command_status)

    check = sub.add_parser("check")
    check.add_argument("--stale-seconds", type=float, default=180)
    check.add_argument("--stale-repeat-hours", type=float, default=6)
    check.add_argument("--dry-run", action="store_true")
    check.set_defaults(func=command_check)

    notify_test = sub.add_parser("notify-test")
    notify_test.set_defaults(func=command_notify_test)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
