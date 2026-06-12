#!/usr/bin/env python3
"""Wait for stream-eval shard reports and merge them."""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

from wakeword_merge_stream_eval import merge_reports


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-glob", required=True)
    parser.add_argument("--expected", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--timeout-hours", type=float, default=8.0)
    return parser


def load_complete_reports(pattern: str) -> tuple[list[dict], list[tuple[str, bool, int, int, float]]]:
    reports = []
    progress = []
    for path_text in sorted(glob.glob(pattern)):
        path = Path(path_text)
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        complete = bool(report.get("complete"))
        processed = int(report.get("files_processed", 0))
        total = int(report.get("files_total", 0))
        hours = float(report.get("audio_hours", 0.0))
        progress.append((path.name, complete, processed, total, hours))
        if complete:
            report["_path"] = str(path)
            reports.append(report)

    return reports, progress


def main() -> None:
    args = build_parser().parse_args()
    deadline = time.monotonic() + args.timeout_hours * 3600.0

    while True:
        reports, progress = load_complete_reports(args.reports_glob)
        print(
            json.dumps(
                {
                    "complete_reports": len(reports),
                    "expected": args.expected,
                    "progress": progress,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        if len(reports) >= args.expected:
            merged = merge_reports(reports[: args.expected], args.top_n)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"merged": str(args.output), "audio_hours": merged["audio_hours"]}, ensure_ascii=False))
            return

        if time.monotonic() >= deadline:
            print("Timed out waiting for stream-eval reports", file=sys.stderr)
            raise SystemExit(1)

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
