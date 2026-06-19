#!/usr/bin/env python3
# ruff: noqa: B905, D101, D102, D103, D213, E501, EM101, FBT001, FBT002, FURB110, I001, PERF401, PLR0913, PLR2004, RET504, RUF046, S311, S324, T201, TC003, TRY003, UP012
"""Offline wake-word smoke training, evaluation, and fragment manifest builder.

This is intentionally not a replacement for the openWakeWord training pipeline.
It provides a dependency-light smoke loop that works with stdlib + numpy:

* generate local synthetic wake/non-wake samples when real positives are scarce
* train a tiny prototype scorer and choose a threshold
* scan accumulated WAV recordings for short voice-like fragments
* emit a JSON manifest that the UI can consume or review tooling can inspect
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import random
import time
import wave
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np


SR = 16_000
TARGET_SECONDS = 1.6
TARGET_SAMPLES = int(SR * TARGET_SECONDS)
DEFAULT_DATASET_ROOT = Path("/home/ultra/oww-dataset")
DEFAULT_DEBUG_ROOT = Path("/home/ultra/wyoming-debug")
DEFAULT_SMOKE_ROOT = Path("/home/ultra/oww-models/smoke")
DEFAULT_MODEL = DEFAULT_SMOKE_ROOT / "ey_milosh_smoke_model.json"
DEFAULT_REPORT = DEFAULT_SMOKE_ROOT / "smoke_train_eval_report.json"
DEFAULT_MANIFEST = DEFAULT_SMOKE_ROOT / "short_wake_fragments_manifest.json"
DEFAULT_CLIPS = DEFAULT_SMOKE_ROOT / "short_wake_fragments"


@dataclasses.dataclass(frozen=True)
class LabeledAudio:
    name: str
    label: int
    source: str
    samples: np.ndarray
    source_path: str | None = None


@dataclasses.dataclass(frozen=True)
class Fragment:
    source_path: Path
    start_seconds: float
    end_seconds: float
    samples: np.ndarray
    energy: float

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds


def stable_ratio(text: str) -> float:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def split_name(name: str, label: int) -> str:
    ratio = stable_ratio(f"{label}:{name}")
    if ratio < 0.70:
        return "train"
    if ratio < 0.85:
        return "val"
    return "test"


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def read_wav(path: Path, max_seconds: float | None = None) -> tuple[np.ndarray, int] | None:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frames = handle.getnframes()
            if channels <= 0 or sample_rate <= 0 or frames <= 0:
                return None
            if sample_width not in (1, 2, 4):
                return None
            if max_seconds is not None:
                frames = min(frames, int(max_seconds * sample_rate))
            raw = handle.readframes(frames)
    except (EOFError, OSError, wave.Error):
        return None

    if sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    else:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0

    if channels > 1:
        usable = len(data) - (len(data) % channels)
        if usable <= 0:
            return None
        data = data[:usable].reshape(-1, channels).mean(axis=1)

    if sample_rate != SR:
        data = resample_linear(data, sample_rate, SR)
        sample_rate = SR

    return data.astype(np.float32, copy=False), sample_rate


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(data.tobytes())


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    old_x = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    new_size = max(1, int(round(samples.size * target_rate / source_rate)))
    new_x = np.linspace(0.0, 1.0, num=new_size, endpoint=False)
    return np.interp(new_x, old_x, samples).astype(np.float32)


def normalize_peak(samples: np.ndarray, target_peak: float = 0.85) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 1e-6:
        return samples.astype(np.float32, copy=True)
    return (samples * (target_peak / peak)).astype(np.float32)


def active_center(samples: np.ndarray) -> int:
    if samples.size == 0:
        return 0
    energy = np.square(samples.astype(np.float64))
    total = float(np.sum(energy))
    if total <= 1e-12:
        return samples.size // 2
    indexes = np.arange(samples.size, dtype=np.float64)
    return int(np.clip(np.sum(indexes * energy) / total, 0, samples.size - 1))


def centered_window(samples: np.ndarray, length: int = TARGET_SAMPLES) -> np.ndarray:
    if samples.size >= length:
        center = active_center(samples)
        start = int(np.clip(center - (length // 2), 0, samples.size - length))
        return samples[start : start + length].astype(np.float32, copy=True)

    output = np.zeros(length, dtype=np.float32)
    start = (length - samples.size) // 2
    output[start : start + samples.size] = samples
    return output


def frame_rms(samples: np.ndarray, frame: int = 400, hop: int = 160) -> np.ndarray:
    if samples.size < frame:
        value = math.sqrt(float(np.mean(np.square(samples)))) if samples.size else 0.0
        return np.asarray([value], dtype=np.float32)
    count = 1 + ((samples.size - frame) // hop)
    values = np.empty(count, dtype=np.float32)
    for index in range(count):
        start = index * hop
        chunk = samples[start : start + frame]
        values[index] = math.sqrt(float(np.mean(np.square(chunk))) + 1e-12)
    return values


def resample_vector(values: np.ndarray, size: int) -> np.ndarray:
    if values.size == size:
        return values.astype(np.float32, copy=True)
    if values.size == 0:
        return np.zeros(size, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=values.size)
    x_new = np.linspace(0.0, 1.0, num=size)
    return np.interp(x_new, x_old, values).astype(np.float32)


def spectral_bands(samples: np.ndarray, bands: int = 16) -> np.ndarray:
    windowed = centered_window(samples) * np.hanning(TARGET_SAMPLES)
    spectrum = np.abs(np.fft.rfft(windowed)) ** 2
    freqs = np.fft.rfftfreq(TARGET_SAMPLES, 1.0 / SR)
    edges = np.geomspace(90.0, 4_000.0, bands + 1)
    values = np.empty(bands, dtype=np.float32)
    for index in range(bands):
        mask = (freqs >= edges[index]) & (freqs < edges[index + 1])
        values[index] = float(np.sum(spectrum[mask]))
    values = np.log1p(values)
    norm = float(np.linalg.norm(values))
    if norm > 1e-9:
        values /= norm
    return values


def zero_crossing_rate(samples: np.ndarray) -> float:
    if samples.size < 2:
        return 0.0
    signs = np.signbit(samples)
    return float(np.count_nonzero(signs[1:] != signs[:-1]) / (samples.size - 1))


def feature_vector(samples: np.ndarray) -> np.ndarray:
    centered = centered_window(normalize_peak(samples, target_peak=0.8))
    envelope = np.log1p(frame_rms(centered) * 80.0)
    envelope = resample_vector(envelope, 48)
    env_norm = float(np.linalg.norm(envelope))
    if env_norm > 1e-9:
        envelope /= env_norm

    bands = spectral_bands(centered, 16)
    rms_value = math.sqrt(float(np.mean(np.square(centered))) + 1e-12)
    summary = np.asarray(
        [
            min(1.0, rms_value * 8.0),
            min(1.0, zero_crossing_rate(centered) * 12.0),
            min(1.0, float(np.count_nonzero(np.abs(centered) > 0.02)) / centered.size),
        ],
        dtype=np.float32,
    )
    return np.concatenate([envelope, bands, summary]).astype(np.float32)


def chirp(length: int, start_freq: float, end_freq: float, phase: float) -> np.ndarray:
    if length <= 0:
        return np.empty((0,), dtype=np.float32)
    freqs = np.linspace(start_freq, end_freq, length, dtype=np.float64)
    phase_values = phase + (2.0 * math.pi * np.cumsum(freqs) / SR)
    return np.sin(phase_values).astype(np.float32)


def envelope(length: int, attack: float = 0.18, release: float = 0.18) -> np.ndarray:
    if length <= 0:
        return np.empty((0,), dtype=np.float32)
    env = np.ones(length, dtype=np.float32)
    attack_n = max(1, int(length * attack))
    release_n = max(1, int(length * release))
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n)
    env[-release_n:] = np.linspace(1.0, 0.0, release_n)
    return env


def add_syllable(
    output: np.ndarray,
    start: int,
    duration: float,
    base_freq: float,
    drift: float,
    amp: float,
    rng: random.Random,
) -> None:
    length = max(1, int(duration * SR))
    end = min(output.size, start + length)
    if end <= start:
        return
    length = end - start
    phase = rng.random() * 2.0 * math.pi
    fundamental = chirp(length, base_freq, base_freq + drift, phase)
    second = 0.45 * chirp(length, base_freq * 2.0, (base_freq + drift) * 2.0, phase / 2.0)
    third = 0.18 * chirp(length, base_freq * 3.0, (base_freq + drift) * 3.0, phase / 3.0)
    output[start:end] += amp * (fundamental + second + third) * envelope(length)


def synthetic_positive(index: int, rng: random.Random) -> np.ndarray:
    duration = rng.uniform(1.15, 1.45)
    output = np.zeros(int(duration * SR), dtype=np.float32)
    speed = rng.uniform(0.92, 1.12)
    amp = rng.uniform(0.18, 0.36)
    add_syllable(output, int(rng.uniform(0.05, 0.14) * SR), 0.30 / speed, rng.uniform(360, 520), rng.uniform(60, 180), amp, rng)
    add_syllable(output, int(rng.uniform(0.42, 0.52) * SR), 0.44 / speed, rng.uniform(190, 280), rng.uniform(-35, 55), amp * 1.08, rng)
    add_syllable(output, int(rng.uniform(0.82, 0.92) * SR), 0.26 / speed, rng.uniform(520, 760), rng.uniform(-120, 80), amp * 0.70, rng)
    noise = np.asarray([rng.gauss(0.0, 0.006) for _ in range(output.size)], dtype=np.float32)
    room_tone = 0.004 * chirp(output.size, 120.0 + index % 20, 120.0 + index % 20, 0.0)
    return normalize_peak(output + noise + room_tone, target_peak=rng.uniform(0.45, 0.85))


def synthetic_negative(index: int, rng: random.Random) -> np.ndarray:
    duration = rng.uniform(0.9, 1.9)
    output = np.asarray([rng.gauss(0.0, rng.uniform(0.006, 0.025)) for _ in range(int(duration * SR))], dtype=np.float32)
    mode = index % 4
    if mode == 0:
        add_syllable(output, int(rng.uniform(0.15, 0.45) * SR), rng.uniform(0.25, 0.55), rng.uniform(700, 1_200), rng.uniform(-100, 100), rng.uniform(0.04, 0.14), rng)
    elif mode == 1:
        add_syllable(output, int(rng.uniform(0.05, 0.20) * SR), rng.uniform(0.55, 0.95), rng.uniform(130, 210), rng.uniform(-30, 30), rng.uniform(0.05, 0.18), rng)
    elif mode == 2:
        start = int(rng.uniform(0.2, 0.8) * SR)
        length = min(output.size - start, int(rng.uniform(0.08, 0.20) * SR))
        if length > 0:
            output[start : start + length] += rng.uniform(0.08, 0.22) * chirp(length, rng.uniform(900, 2_200), rng.uniform(900, 2_200), 0.0)
    else:
        output *= rng.uniform(0.15, 0.55)
    return normalize_peak(output, target_peak=rng.uniform(0.15, 0.65))


def iter_wavs(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    yield from sorted(path for path in root.rglob("*.wav") if path.is_file() and path.stat().st_size > 44)


def load_existing_audio(
    root: Path,
    label: int,
    source: str,
    limit: int,
    max_seconds: float,
) -> list[LabeledAudio]:
    items: list[LabeledAudio] = []
    for path in iter_wavs(root):
        if len(items) >= limit:
            break
        loaded = read_wav(path, max_seconds=max_seconds)
        if loaded is None:
            continue
        samples, _sample_rate = loaded
        if samples.size < int(0.15 * SR):
            continue
        items.append(
            LabeledAudio(
                name=str(path),
                label=label,
                source=source,
                samples=samples,
                source_path=str(path),
            )
        )
    return items


def build_training_items(args: argparse.Namespace) -> list[LabeledAudio]:
    rng = random.Random(args.seed)
    items: list[LabeledAudio] = []
    positives_root = args.dataset_root / "positives"
    negatives_root = args.dataset_root / "negatives"

    if args.max_existing_positives > 0:
        for child in sorted(positives_root.iterdir()) if positives_root.exists() else []:
            if len([item for item in items if item.label == 1]) >= args.max_existing_positives:
                break
            remaining = args.max_existing_positives - len([item for item in items if item.label == 1])
            if child.is_dir():
                items.extend(load_existing_audio(child, 1, f"positive_existing/{child.name}", remaining, args.max_existing_seconds))

    if args.max_existing_negatives > 0:
        for child in sorted(negatives_root.rglob("*")) if negatives_root.exists() else []:
            if len([item for item in items if item.label == 0]) >= args.max_existing_negatives:
                break
            if not child.is_dir():
                continue
            remaining = args.max_existing_negatives - len([item for item in items if item.label == 0])
            items.extend(load_existing_audio(child, 0, f"negative_existing/{child.name}", remaining, args.max_existing_seconds))

    for index in range(args.generated_positives):
        items.append(
            LabeledAudio(
                name=f"generated_positive_{index:04d}",
                label=1,
                source="positive_generated_smoke",
                samples=synthetic_positive(index, rng),
            )
        )
    for index in range(args.generated_negatives):
        items.append(
            LabeledAudio(
                name=f"generated_negative_{index:04d}",
                label=0,
                source="negative_generated_smoke",
                samples=synthetic_negative(index, rng),
            )
        )
    return items


def train_model(items: Sequence[LabeledAudio]) -> dict[str, Any]:
    train_items = [item for item in items if split_name(item.name, item.label) == "train"]
    if not any(item.label == 1 for item in train_items) or not any(item.label == 0 for item in train_items):
        raise RuntimeError("training split needs at least one positive and one negative sample")

    x_train = np.vstack([feature_vector(item.samples) for item in train_items])
    y_train = np.asarray([item.label for item in train_items], dtype=np.int32)
    pos = x_train[y_train == 1]
    neg = x_train[y_train == 0]
    all_std = np.std(x_train, axis=0) + 0.03
    model = {
        "kind": "wakeword_smoke_prototype",
        "feature_version": 1,
        "sample_rate": SR,
        "target_seconds": TARGET_SECONDS,
        "created_at_epoch": time.time(),
        "positive_mean": np.mean(pos, axis=0).tolist(),
        "negative_mean": np.mean(neg, axis=0).tolist(),
        "feature_scale": all_std.tolist(),
        "threshold": 0.5,
    }
    return model


def score_with_model(model: dict[str, Any], samples: np.ndarray) -> float:
    features = feature_vector(samples)
    pos = np.asarray(model["positive_mean"], dtype=np.float32)
    neg = np.asarray(model["negative_mean"], dtype=np.float32)
    scale = np.asarray(model["feature_scale"], dtype=np.float32)
    pos_dist = float(np.mean(np.square((features - pos) / scale)))
    neg_dist = float(np.mean(np.square((features - neg) / scale)))
    margin = (neg_dist - pos_dist) / max(0.25, (pos_dist + neg_dist) * 0.5)
    return sigmoid(3.5 * margin)


def metrics_at(scores: Sequence[float], labels: Sequence[int], threshold: float) -> dict[str, float | int]:
    tp = fp = tn = fn = 0
    for score, label in zip(scores, labels):
        detected = score >= threshold
        if detected and label == 1:
            tp += 1
        elif detected and label == 0:
            fp += 1
        elif not detected and label == 0:
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "detected_positives": tp,
        "missed_positives": fn,
    }


def choose_threshold(model: dict[str, Any], items: Sequence[LabeledAudio]) -> tuple[float, list[dict[str, float | int]]]:
    val_items = [item for item in items if split_name(item.name, item.label) == "val"]
    if not val_items:
        val_items = list(items)
    scores = [score_with_model(model, item.samples) for item in val_items]
    labels = [item.label for item in val_items]
    sweep = [metrics_at(scores, labels, threshold / 100.0) for threshold in range(5, 96, 5)]
    viable = [row for row in sweep if float(row["recall"]) >= 0.90]
    if viable:
        selected = max(viable, key=lambda row: (float(row["precision"]), float(row["f1"]), float(row["threshold"])))
    else:
        selected = max(sweep, key=lambda row: (float(row["f1"]), float(row["recall"])))
    return float(selected["threshold"]), sweep


def evaluate_split(model: dict[str, Any], items: Sequence[LabeledAudio], split: str) -> dict[str, Any]:
    selected = [item for item in items if split_name(item.name, item.label) == split]
    scores = [score_with_model(model, item.samples) for item in selected]
    labels = [item.label for item in selected]
    threshold = float(model["threshold"])
    by_source: dict[str, dict[str, int]] = {}
    for item, score in zip(selected, scores):
        row = by_source.setdefault(item.source, {"items": 0, "detected": 0, "positives": 0, "negatives": 0})
        row["items"] += 1
        row["detected"] += int(score >= threshold)
        row["positives"] += int(item.label == 1)
        row["negatives"] += int(item.label == 0)
    return {
        "items": len(selected),
        "metrics": metrics_at(scores, labels, threshold) if selected else {},
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "score_mean": float(np.mean(scores)) if scores else None,
        "by_source": by_source,
    }


def run_train_eval(args: argparse.Namespace) -> dict[str, Any]:
    items = build_training_items(args)
    if len(items) < 4:
        raise RuntimeError("not enough audio for smoke training")

    model = train_model(items)
    threshold, sweep = choose_threshold(model, items)
    model["threshold"] = threshold
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    args.model_output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "created_at_epoch": time.time(),
        "model_path": str(args.model_output),
        "dataset_root": str(args.dataset_root),
        "items_total": len(items),
        "items_by_source": count_sources(items),
        "threshold": threshold,
        "validation_sweep": sweep,
        "train": evaluate_split(model, items, "train"),
        "val": evaluate_split(model, items, "val"),
        "test": evaluate_split(model, items, "test"),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return model


def count_sources(items: Sequence[LabeledAudio]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for item in items:
        row = counts.setdefault(item.source, {"items": 0, "positives": 0, "negatives": 0})
        row["items"] += 1
        row["positives"] += int(item.label == 1)
        row["negatives"] += int(item.label == 0)
    return counts


def load_model(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_audio_roots(values: Sequence[Path] | None) -> list[Path]:
    values = values or [DEFAULT_DEBUG_ROOT]
    roots = [path for path in values if path.exists()]
    return roots if roots else [DEFAULT_DEBUG_ROOT]


def list_scan_wavs(roots: Sequence[Path], max_files: int | None) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        paths.extend(iter_wavs(root))
    paths = sorted(set(paths), key=lambda path: (path.stat().st_mtime, str(path)), reverse=True)
    if max_files is not None:
        return paths[:max_files]
    return paths


def segment_energy(samples: np.ndarray) -> float:
    return math.sqrt(float(np.mean(np.square(samples))) + 1e-12) if samples.size else 0.0


def spectral_centroid(samples: np.ndarray) -> float:
    if samples.size < 16:
        return 0.0
    windowed = samples * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    total = float(np.sum(spectrum))
    if total <= 1e-9:
        return 0.0
    freqs = np.fft.rfftfreq(samples.size, 1.0 / SR)
    return float(np.sum(freqs * spectrum) / total)


def find_voice_like_fragments(
    path: Path,
    samples: np.ndarray,
    min_duration: float,
    max_duration: float,
    sensitivity: float,
    min_rms: float,
    max_segments: int,
) -> list[Fragment]:
    frame = int(0.03 * SR)
    hop = int(0.01 * SR)
    rms = frame_rms(samples, frame=frame, hop=hop)
    if rms.size == 0 or float(np.max(rms)) < min_rms:
        return []

    floor = float(np.median(rms))
    mad = float(np.median(np.abs(rms - floor)))
    dynamic = floor + (sensitivity * max(mad, 0.002))
    threshold = max(min_rms, dynamic, float(np.percentile(rms, 65)) * 0.55)
    active = rms >= threshold

    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            segments.append((start, index))
            start = None
    if start is not None:
        segments.append((start, active.size))

    merged: list[tuple[int, int]] = []
    merge_gap = int(0.18 / 0.01)
    for begin, end in segments:
        if merged and begin - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((begin, end))

    fragments: list[Fragment] = []
    pad = int(0.08 * SR)
    for begin_frame, end_frame in merged:
        start_sample = max(0, (begin_frame * hop) - pad)
        end_sample = min(samples.size, (end_frame * hop) + frame + pad)
        duration = (end_sample - start_sample) / SR
        if duration < min_duration or duration > max_duration:
            continue
        clip = samples[start_sample:end_sample].astype(np.float32, copy=True)
        energy = segment_energy(clip)
        zcr = zero_crossing_rate(clip)
        centroid = spectral_centroid(clip)
        if energy < min_rms or not (0.005 <= zcr <= 0.40) or not (80.0 <= centroid <= 4_500.0):
            continue
        fragments.append(
            Fragment(
                source_path=path,
                start_seconds=start_sample / SR,
                end_seconds=end_sample / SR,
                samples=clip,
                energy=energy,
            )
        )
    fragments.sort(key=lambda item: item.energy, reverse=True)
    return fragments[:max_segments]


def clip_name(fragment: Fragment, index: int) -> str:
    digest = hashlib.sha1(
        f"{fragment.source_path}:{fragment.start_seconds:.3f}:{fragment.end_seconds:.3f}".encode("utf-8")
    ).hexdigest()[:12]
    stem = fragment.source_path.stem[:40].replace(" ", "_")
    return f"{index:05d}_{stem}_{fragment.start_seconds:.2f}s_{digest}.wav"


def run_mine(args: argparse.Namespace) -> dict[str, Any]:
    model = load_model(args.model)
    roots = discover_audio_roots(args.audio_root)
    paths = list_scan_wavs(roots, args.max_files)
    args.clip_root.mkdir(parents=True, exist_ok=True)

    fragments: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    files_processed = 0
    threshold = float(model["threshold"])

    for path in paths:
        loaded = read_wav(path, max_seconds=args.max_file_seconds)
        if loaded is None:
            skipped["unreadable"] = skipped.get("unreadable", 0) + 1
            continue
        samples, _sample_rate = loaded
        files_processed += 1
        candidates = find_voice_like_fragments(
            path=path,
            samples=samples,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            sensitivity=args.sensitivity,
            min_rms=args.min_rms,
            max_segments=args.max_candidates_per_file,
        )
        for candidate in candidates:
            score = score_with_model(model, candidate.samples)
            detected = score >= threshold
            output_path = args.clip_root / clip_name(candidate, len(fragments) + 1)
            write_wav(output_path, candidate.samples)
            fragments.append(
                {
                    "path": str(output_path),
                    "source_path": str(candidate.source_path),
                    "start_seconds": round(candidate.start_seconds, 3),
                    "end_seconds": round(candidate.end_seconds, 3),
                    "duration": round(candidate.duration, 3),
                    "score": score,
                    "energy": candidate.energy,
                    "detected_by_model": detected,
                    "missed_by_model": not detected,
                }
            )
            if len(fragments) >= args.max_candidates:
                break
        if len(fragments) >= args.max_candidates:
            break

    fragments.sort(key=lambda item: (item["missed_by_model"], item["energy"]), reverse=True)
    manifest = {
        "created_at_epoch": time.time(),
        "model_path": str(args.model),
        "model_kind": model.get("kind"),
        "threshold": threshold,
        "audio_roots": [str(path) for path in roots],
        "files_seen": len(paths),
        "files_processed": files_processed,
        "skipped": skipped,
        "candidate_count": len(fragments),
        "detected_by_model_count": sum(1 for item in fragments if item["detected_by_model"]),
        "missed_by_model_count": sum(1 for item in fragments if item["missed_by_model"]),
        "fragments": fragments,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train-eval", help="train and evaluate the local smoke model")
    add_train_args(train)
    train.set_defaults(func=run_train_eval)

    mine = subparsers.add_parser("mine-fragments", help="scan WAV files and write a short-fragment manifest")
    add_mine_args(mine)
    mine.set_defaults(func=run_mine)

    all_cmd = subparsers.add_parser("all", help="run train-eval and then mine-fragments")
    add_train_args(all_cmd)
    add_mine_args(all_cmd, include_model=False)
    all_cmd.set_defaults(func=run_all)
    return parser


def add_train_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--model-output", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=20260619)
    parser.add_argument("--generated-positives", type=int, default=96)
    parser.add_argument("--generated-negatives", type=int, default=160)
    parser.add_argument("--max-existing-positives", type=int, default=400)
    parser.add_argument("--max-existing-negatives", type=int, default=400)
    parser.add_argument("--max-existing-seconds", type=float, default=3.0)


def add_mine_args(parser: argparse.ArgumentParser, include_model: bool = True) -> None:
    if include_model:
        parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--audio-root", type=Path, action="append", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--clip-root", type=Path, default=DEFAULT_CLIPS)
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-file-seconds", type=float, default=180.0)
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--max-candidates-per-file", type=int, default=12)
    parser.add_argument("--min-duration", type=float, default=0.28)
    parser.add_argument("--max-duration", type=float, default=2.4)
    parser.add_argument("--sensitivity", type=float, default=2.5)
    parser.add_argument("--min-rms", type=float, default=0.006)


def run_all(args: argparse.Namespace) -> None:
    run_train_eval(args)
    args.model = args.model_output
    run_mine(args)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
