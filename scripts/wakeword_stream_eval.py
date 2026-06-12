#!/usr/bin/env python3
"""Streaming false-positive evaluation for the local openWakeWord model.

This evaluates a deployed TFLite wake-word model on long negative recordings
as a continuous stream. By default it uses the pyopen_wakeword runtime from
rhasspy/wyoming-openwakeword, which matches the active Home Assistant service.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


SR = 16000
DEFAULT_THRESHOLDS = (0.97, 0.99, 0.991, 0.992, 0.995, 0.999)
DEFAULT_REFRACTORY_SECONDS = (2.0, 5.0)
OUTPUT_STEP_SECONDS = 0.08


@dataclass
class EvalState:
    started_at: float
    model_path: Path
    raw_live_root: Path
    runtime: str
    thresholds: tuple[float, ...]
    refractory_seconds: tuple[float, ...]
    chunk_frames: int
    warmup_frames: int
    top_n: int
    hist_bins: int
    complete: bool = False
    model_name: str | None = None
    files_total: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    chunks_processed: int = 0
    audio_seconds: float = 0.0
    score_max: float = 0.0
    score_sum: float = 0.0
    score_count: int = 0
    top_score_seq: int = 0
    last_path: str | None = None
    skip_reasons: dict[str, int] | None = None
    above_counts: dict[str, int] | None = None
    detections: dict[str, dict[str, Any]] | None = None
    top_scores: list[tuple[float, int, dict[str, Any]]] | None = None
    histogram: list[int] | None = None

    def __post_init__(self) -> None:
        self.skip_reasons = {}
        self.above_counts = {format_threshold(threshold): 0 for threshold in self.thresholds}
        self.detections = {}
        for threshold in self.thresholds:
            for refractory in self.refractory_seconds:
                key = detection_key(threshold, refractory)
                self.detections[key] = {
                    "threshold": threshold,
                    "refractory_seconds": refractory,
                    "count": 0,
                    "last_detection_audio_second": -math.inf,
                    "examples": [],
                }
        self.top_scores = []
        self.histogram = [0 for _ in range(self.hist_bins)]


def parse_float_list(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in value.split(",") if item.strip())


def format_threshold(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def detection_key(threshold: float, refractory: float) -> str:
    return f"threshold_{format_threshold(threshold)}_refractory_{format_threshold(refractory)}s"


def iter_wavs(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.wav") if path.is_file())


def add_skip(state: EvalState, reason: str) -> None:
    assert state.skip_reasons is not None
    state.files_skipped += 1
    state.skip_reasons[reason] = state.skip_reasons.get(reason, 0) + 1


def wav_samples(raw: bytes, channels: int) -> np.ndarray:
    samples = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        usable = len(samples) - (len(samples) % channels)
        if usable <= 0:
            return np.empty((0,), dtype=np.int16)
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
        return samples.astype(np.int16)
    return samples.astype(np.int16, copy=False)


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


def serializable_top_scores(state: EvalState) -> list[dict[str, Any]]:
    assert state.top_scores is not None
    return [
        row
        for _score, _seq, row in sorted(
            state.top_scores,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
    ]


def report(state: EvalState) -> dict[str, Any]:
    assert state.above_counts is not None
    assert state.detections is not None
    assert state.histogram is not None

    hours = state.audio_seconds / 3600.0
    detection_rows: dict[str, dict[str, Any]] = {}
    for key, row in state.detections.items():
        count = int(row["count"])
        detection_rows[key] = {
            "threshold": row["threshold"],
            "refractory_seconds": row["refractory_seconds"],
            "detections": count,
            "false_positives_per_hour": count / hours if hours > 0 else None,
            "examples": row["examples"],
        }

    return {
        "complete": state.complete,
        "started_at_epoch": state.started_at,
        "elapsed_seconds": time.time() - state.started_at,
        "model_path": str(state.model_path),
        "model_name": state.model_name,
        "runtime": state.runtime,
        "raw_live_root": str(state.raw_live_root),
        "thresholds": list(state.thresholds),
        "refractory_seconds": list(state.refractory_seconds),
        "chunk_frames": state.chunk_frames,
        "chunk_seconds": state.chunk_frames * 1280 / SR,
        "warmup_frames": state.warmup_frames,
        "files_total": state.files_total,
        "files_processed": state.files_processed,
        "files_skipped": state.files_skipped,
        "skip_reasons": state.skip_reasons,
        "chunks_processed": state.chunks_processed,
        "audio_seconds": state.audio_seconds,
        "audio_hours": hours,
        "last_path": state.last_path,
        "score_summary": {
            "count": state.score_count,
            "mean": state.score_sum / state.score_count if state.score_count else None,
            "max": state.score_max,
            "p95": score_quantile(state.histogram, 0.95),
            "p99": score_quantile(state.histogram, 0.99),
            "p999": score_quantile(state.histogram, 0.999),
            "p9999": score_quantile(state.histogram, 0.9999),
        },
        "raw_chunk_crossings": state.above_counts,
        "detections_with_refractory": detection_rows,
        "top_scores": serializable_top_scores(state),
    }


def write_report(path: Path | None, state: EvalState) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class RuntimeAdapter:
    model_name: str | None = None

    def predict_scores(self, samples: np.ndarray) -> list[float]:
        raise NotImplementedError


class PyOpenWakeWordRuntime(RuntimeAdapter):
    def __init__(self, model_path: Path) -> None:
        from pyopen_wakeword import OpenWakeWord, OpenWakeWordFeatures  # noqa: PLC0415

        self.features = OpenWakeWordFeatures.from_builtin()
        self.detector = OpenWakeWord.from_model(model_path)
        self.model_name = model_path.stem

    def predict_scores(self, samples: np.ndarray) -> list[float]:
        scores: list[float] = []
        audio = samples.astype("<i2", copy=False).tobytes()
        for features in self.features.process_streaming(audio):
            scores.extend(float(probability) for probability in self.detector.process_streaming(features))
        return scores


class OpenWakeWordRuntime(RuntimeAdapter):
    def __init__(self, openwakeword_root: Path, model_path: Path) -> None:
        self.model = load_openwakeword_model(openwakeword_root, model_path)

    def predict_scores(self, samples: np.ndarray) -> list[float]:
        predictions = self.model.predict(samples)
        if self.model_name is None:
            if len(predictions) != 1:
                raise RuntimeError(f"expected exactly one model prediction, got {sorted(predictions)}")
            self.model_name = next(iter(predictions))
        return [float(predictions[self.model_name])]


def load_openwakeword_model(openwakeword_root: Path, model_path: Path):
    sys.path.insert(0, str(openwakeword_root))
    from openwakeword.model import Model  # noqa: PLC0415

    return Model(
        wakeword_models=[str(model_path)],
        inference_framework="tflite",
    )


def load_runtime(args: argparse.Namespace, model_path: Path) -> RuntimeAdapter:
    if args.runtime == "pyopen-wakeword":
        return PyOpenWakeWordRuntime(model_path)
    if args.runtime == "openwakeword":
        return OpenWakeWordRuntime(args.openwakeword_root.resolve(), model_path)
    raise ValueError(f"unsupported runtime: {args.runtime}")


def observe_score(
    state: EvalState,
    score: float,
    path: Path,
    file_offset_sec: float,
    audio_second: float,
) -> None:
    assert state.above_counts is not None
    assert state.detections is not None
    assert state.top_scores is not None
    assert state.histogram is not None

    state.score_count += 1
    state.score_sum += score
    state.score_max = max(state.score_max, score)
    hist_index = min(len(state.histogram) - 1, max(0, int(round(score * (len(state.histogram) - 1)))))
    state.histogram[hist_index] += 1

    row = {
        "score": score,
        "path": str(path),
        "file_offset_seconds": file_offset_sec,
        "audio_second": audio_second,
    }
    if len(state.top_scores) < state.top_n:
        heapq.heappush(state.top_scores, (score, state.top_score_seq, row))
        state.top_score_seq += 1
    elif score > state.top_scores[0][0]:
        heapq.heapreplace(state.top_scores, (score, state.top_score_seq, row))
        state.top_score_seq += 1

    for threshold in state.thresholds:
        if score < threshold:
            continue
        threshold_key = format_threshold(threshold)
        state.above_counts[threshold_key] += 1
        for refractory in state.refractory_seconds:
            key = detection_key(threshold, refractory)
            detection_row = state.detections[key]
            last = float(detection_row["last_detection_audio_second"])
            if audio_second - last < refractory:
                continue
            detection_row["count"] += 1
            detection_row["last_detection_audio_second"] = audio_second
            if len(detection_row["examples"]) < state.top_n:
                detection_row["examples"].append(row)


def evaluate_file(
    state: EvalState,
    runtime: RuntimeAdapter,
    path: Path,
    chunk_samples: int,
    model_calls_seen: int,
) -> tuple[int, str | None]:
    try:
        wav = wave.open(str(path), "rb")
    except (EOFError, wave.Error):
        return model_calls_seen, "invalid_wav"

    with wav:
        if wav.getframerate() != SR:
            return model_calls_seen, "unexpected_sample_rate"
        if wav.getsampwidth() != 2:
            return model_calls_seen, "unexpected_sample_width"
        if wav.getnframes() <= 0:
            return model_calls_seen, "empty"

        channels = wav.getnchannels()
        file_offset_sec = 0.0
        while True:
            read_samples = 1280 if model_calls_seen < state.warmup_frames else chunk_samples
            raw = wav.readframes(read_samples)
            if not raw:
                break

            samples = wav_samples(raw, channels)
            if samples.size == 0:
                continue

            scores = runtime.predict_scores(samples)
            state.model_name = runtime.model_name
            model_calls_seen += 1

            seconds = samples.size / SR
            if scores:
                if len(scores) == 1:
                    offsets = [0.0]
                else:
                    offsets = [min(seconds, index * OUTPUT_STEP_SECONDS) for index in range(len(scores))]
                for score, offset in zip(scores, offsets):
                    observe_score(
                        state,
                        score,
                        path,
                        file_offset_sec + offset,
                        state.audio_seconds + offset,
                    )

            file_offset_sec += seconds
            state.audio_seconds += seconds
            state.chunks_processed += 1

    return model_calls_seen, None


def run(args: argparse.Namespace) -> None:
    model_path = args.model_path.resolve()
    raw_live_root = args.raw_live_root.resolve()
    paths = iter_wavs(raw_live_root)
    if args.max_files is not None:
        paths = paths[: args.max_files]

    state = EvalState(
        started_at=time.time(),
        model_path=model_path,
        raw_live_root=raw_live_root,
        runtime=args.runtime,
        thresholds=args.thresholds,
        refractory_seconds=args.refractory_seconds,
        chunk_frames=args.chunk_frames,
        warmup_frames=args.warmup_frames,
        top_n=args.top_n,
        hist_bins=args.hist_bins,
        files_total=len(paths),
    )

    runtime = load_runtime(args, model_path)
    chunk_samples = args.chunk_frames * 1280
    model_calls_seen = 0
    last_progress = time.monotonic()

    for index, path in enumerate(paths, start=1):
        before_seconds = state.audio_seconds
        model_calls_seen, skip_reason = evaluate_file(
            state,
            runtime,
            path,
            chunk_samples=chunk_samples,
            model_calls_seen=model_calls_seen,
        )
        if skip_reason is not None:
            add_skip(state, skip_reason)
        else:
            state.files_processed += 1
            state.last_path = str(path)

        if (
            index == len(paths)
            or index % args.checkpoint_every_files == 0
            or time.monotonic() - last_progress >= args.progress_every_seconds
        ):
            last_progress = time.monotonic()
            hours = state.audio_seconds / 3600.0
            delta = state.audio_seconds - before_seconds
            print(
                json.dumps(
                    {
                        "files": f"{index}/{len(paths)}",
                        "audio_hours": round(hours, 4),
                        "last_file_seconds": round(delta, 3),
                        "score_max": state.score_max,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            write_report(args.output, state)

    state.complete = True
    write_report(args.output, state)
    print(json.dumps(report(state), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, default=Path("/workspace/models/ey_milosh.tflite"))
    parser.add_argument("--raw-live-root", type=Path, default=Path("/workspace/dataset/raw_live"))
    parser.add_argument("--openwakeword-root", type=Path, default=Path("/workspace/openWakeWord"))
    parser.add_argument("--runtime", choices=("pyopen-wakeword", "openwakeword"), default="pyopen-wakeword")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--thresholds", type=parse_float_list, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--refractory-seconds", type=parse_float_list, default=DEFAULT_REFRACTORY_SECONDS)
    parser.add_argument("--chunk-frames", type=int, default=12)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=25)
    parser.add_argument("--hist-bins", type=int, default=10001)
    parser.add_argument("--checkpoint-every-files", type=int, default=250)
    parser.add_argument("--progress-every-seconds", type=float, default=30.0)
    parser.add_argument("--max-files", type=int)
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
