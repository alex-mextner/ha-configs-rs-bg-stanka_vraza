#!/usr/bin/env python3
"""Report real wakeword data collection status."""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return frames / rate if rate else 0.0
    except Exception:
        return 0.0


def summarize_wavs(root: Path) -> dict[str, float | int]:
    files = sorted(root.rglob("*.wav")) if root.exists() else []
    durations = [wav_duration(path) for path in files if path.stat().st_size > 44]
    return {
        "files": len(files),
        "nonempty_files": len(durations),
        "hours": round(sum(durations) / 3600.0, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("/home/ultra/oww-dataset"))
    parser.add_argument("--debug-root", type=Path, default=Path("/home/ultra/wyoming-debug"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = {
        "raw_live": summarize_wavs(args.dataset_root / "raw_live"),
        "legacy_raw": summarize_wavs(args.dataset_root / "raw"),
        "real_positive_candidates": summarize_wavs(args.debug_root),
        "curated_real_positives": summarize_wavs(args.dataset_root / "positives" / "real_user"),
        "curated_false_wakes": summarize_wavs(args.dataset_root / "negatives" / "home_false_wake"),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("Wakeword real-data collection status")
    for name, values in report.items():
        print(
            f"- {name}: files={values['files']} nonempty={values['nonempty_files']} "
            f"hours={values['hours']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
