#!/usr/bin/env python3
"""Collect controlled real-user wake word positives from Wyoming debug files."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import re
from pathlib import Path


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def session_dir(dataset_root: Path) -> Path:
    return dataset_root / "positive_sessions"


def current_session_path(dataset_root: Path) -> Path:
    return session_dir(dataset_root) / "current.json"


def slug(value: str) -> str:
    value = value.strip().lower().replace(" ", "_")
    value = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ_.-]+", "_", value)
    return value.strip("_") or "wake"


def read_current(dataset_root: Path) -> dict:
    path = current_session_path(dataset_root)
    if not path.exists():
        raise SystemExit(f"No active session: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def command_start(args: argparse.Namespace) -> int:
    sessions = session_dir(args.dataset_root)
    sessions.mkdir(parents=True, exist_ok=True)
    started_at = now_utc()
    session = {
        "id": started_at.strftime("%Y%m%dT%H%M%SZ"),
        "started_at": started_at.isoformat(),
        "phrase": args.phrase,
        "speaker": args.speaker,
        "style": args.style,
        "location": args.location,
        "expected_attempts": args.expected_attempts,
    }
    current_session_path(args.dataset_root).write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(session, ensure_ascii=False, indent=2))
    return 0


def wake_files_since(debug_root: Path, started_at: dt.datetime) -> list[Path]:
    files = []
    for path in sorted(debug_root.glob("*-wake.wav")):
        modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
        if modified >= started_at and path.stat().st_size > 44:
            files.append(path)
    return files


def command_finish(args: argparse.Namespace) -> int:
    session = read_current(args.dataset_root)
    started_at = parse_time(session["started_at"])
    files = wake_files_since(args.debug_root, started_at)
    session_slug = "_".join(
        slug(str(session.get(key) or ""))
        for key in ("phrase", "speaker", "style", "location")
        if session.get(key)
    )
    out_dir = args.dataset_root / "positives" / "real_user" / f"{session['id']}_{session_slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for index, src in enumerate(files, start=1):
        dst = out_dir / f"{session['id']}_{index:03d}_{src.name}"
        shutil.copy2(src, dst)
        copied.append({"source": str(src), "output": str(dst), "bytes": dst.stat().st_size})

    expected_attempts = args.expected_attempts or session.get("expected_attempts")
    summary = {
        **session,
        "finished_at": now_utc().isoformat(),
        "debug_root": str(args.debug_root),
        "output_dir": str(out_dir),
        "copied_wake_files": len(copied),
        "expected_attempts": expected_attempts,
        "observed_trigger_recall": (len(copied) / expected_attempts) if expected_attempts else None,
        "files": copied,
    }
    summary_path = session_dir(args.dataset_root) / f"{session['id']}.summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    current_session_path(args.dataset_root).unlink(missing_ok=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_report(args: argparse.Namespace) -> int:
    positive_root = args.dataset_root / "positives" / "real_user"
    positive_files = list(positive_root.glob("**/*.wav")) if positive_root.exists() else []
    summaries = sorted(session_dir(args.dataset_root).glob("*.summary.json")) if session_dir(args.dataset_root).exists() else []
    try:
        session = read_current(args.dataset_root)
        started_at = parse_time(session["started_at"])
        files = wake_files_since(args.debug_root, started_at)
        report = {
            **session,
            "active": True,
            "wake_files_since_start": len(files),
            "debug_root": str(args.debug_root),
            "real_positive_files_total": len(positive_files),
            "session_summaries_total": len(summaries),
        }
    except SystemExit:
        report = {
            "active": False,
            "real_positive_files_total": len(positive_files),
            "session_summaries_total": len(summaries),
        }
    if summaries:
        report["latest_summary"] = str(summaries[-1])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("/home/ultra/oww-dataset"))
    parser.add_argument("--debug-root", type=Path, default=Path("/home/ultra/wyoming-debug"))
    sub = parser.add_subparsers(required=True)

    start = sub.add_parser("start")
    start.add_argument("--phrase", default="эй Милош")
    start.add_argument("--expected-attempts", type=int)
    start.add_argument("--speaker", default="speaker_1_owner")
    start.add_argument("--style", default="normal")
    start.add_argument("--location", default="near_satellite_1m_quiet")
    start.set_defaults(func=command_start)

    finish = sub.add_parser("finish")
    finish.add_argument("--expected-attempts", type=int)
    finish.set_defaults(func=command_finish)

    report = sub.add_parser("report")
    report.set_defaults(func=command_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
