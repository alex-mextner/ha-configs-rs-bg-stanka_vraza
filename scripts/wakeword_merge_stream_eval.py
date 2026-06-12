#!/usr/bin/env python3
"""Merge wakeword_stream_eval shard reports."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=50)
    return parser


def score_quantile(histogram: list[int], quantile: float) -> float | None:
    total = sum(histogram)
    if total <= 0:
        return None
    target = max(1, int(math.ceil(total * quantile)))
    running = 0
    for index, count in enumerate(histogram):
        running += count
        if running >= target:
            return index / max(1, len(histogram) - 1)
    return 1.0


def merge_histograms(reports: list[dict[str, Any]]) -> list[int] | None:
    histograms = []
    for report in reports:
        histogram = report.get("score_histogram")
        if not histogram:
            return None
        histograms.append(histogram["counts"])

    if not histograms:
        return None

    bins = len(histograms[0])
    if any(len(histogram) != bins for histogram in histograms):
        return None

    merged = [0 for _ in range(bins)]
    for histogram in histograms:
        for index, count in enumerate(histogram):
            merged[index] += int(count)
    return merged


def merge_reports(reports: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    audio_seconds = sum(float(report.get("audio_seconds", 0.0)) for report in reports)
    audio_hours = audio_seconds / 3600.0
    score_count = sum(int(report.get("score_summary", {}).get("count") or 0) for report in reports)
    score_sum = sum(
        int(report.get("score_summary", {}).get("count") or 0)
        * float(report.get("score_summary", {}).get("mean") or 0.0)
        for report in reports
    )
    score_max = max((float(report.get("score_summary", {}).get("max") or 0.0) for report in reports), default=0.0)

    crossings: dict[str, int] = {}
    detections: dict[str, dict[str, Any]] = {}
    for report in reports:
        for threshold, count in report.get("raw_chunk_crossings", {}).items():
            crossings[threshold] = crossings.get(threshold, 0) + int(count)

        for key, row in report.get("detections_with_refractory", {}).items():
            target = detections.setdefault(
                key,
                {
                    "threshold": row["threshold"],
                    "refractory_seconds": row["refractory_seconds"],
                    "detections": 0,
                    "examples": [],
                },
            )
            target["detections"] += int(row.get("detections", 0))
            target["examples"].extend(row.get("examples", []))

    for row in detections.values():
        row["false_positives_per_hour"] = row["detections"] / audio_hours if audio_hours > 0 else None
        row["examples"] = sorted(row["examples"], key=lambda item: item.get("score", 0.0), reverse=True)[:top_n]

    top_scores = sorted(
        (score for report in reports for score in report.get("top_scores", [])),
        key=lambda item: item.get("score", 0.0),
        reverse=True,
    )[:top_n]

    histogram = merge_histograms(reports)
    score_summary = {
        "count": score_count,
        "mean": score_sum / score_count if score_count else None,
        "max": score_max,
    }
    if histogram is not None:
        score_summary.update(
            {
                "p95": score_quantile(histogram, 0.95),
                "p99": score_quantile(histogram, 0.99),
                "p999": score_quantile(histogram, 0.999),
                "p9999": score_quantile(histogram, 0.9999),
            }
        )

    return {
        "complete": all(bool(report.get("complete")) for report in reports),
        "shards": len(reports),
        "model_path": reports[0].get("model_path") if reports else None,
        "model_name": reports[0].get("model_name") if reports else None,
        "runtime": reports[0].get("runtime") if reports else None,
        "files_total": sum(int(report.get("files_total", 0)) for report in reports),
        "files_processed": sum(int(report.get("files_processed", 0)) for report in reports),
        "files_skipped": sum(int(report.get("files_skipped", 0)) for report in reports),
        "chunks_processed": sum(int(report.get("chunks_processed", 0)) for report in reports),
        "audio_seconds": audio_seconds,
        "audio_hours": audio_hours,
        "score_summary": score_summary,
        "raw_chunk_crossings": dict(sorted(crossings.items(), key=lambda item: float(item[0]))),
        "detections_with_refractory": dict(sorted(detections.items())),
        "top_scores": top_scores,
        "source_reports": [str(report.get("_path", "")) for report in reports],
    }


def main() -> None:
    args = build_parser().parse_args()
    reports = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        report["_path"] = str(path)
        reports.append(report)

    merged = merge_reports(reports, args.top_n)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(merged, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
