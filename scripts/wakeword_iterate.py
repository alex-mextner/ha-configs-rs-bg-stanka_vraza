#!/usr/bin/env python3
# ruff: noqa: ANN201, ANN202, ANN205, ARG004, BLE001, D101, D102, D103, D213, E501, EM102, EXE001, FBT001, I001, N806, NPY002, PERF401, PLC0415, PLR0402, PLR0912, PLR0913, PLR0915, PLR2004, PLW2901, RUF046, RUF100, S311, S324, T201, TRY003, UP035
"""Iterative openWakeWord training and evaluation for the local ey_milosh model.

Run from the training container, for example:

    docker run --rm --user 1000:1000 \
      -v /home/ultra/homeassistant:/workspace/homeassistant \
      -v /home/ultra/oww-dataset:/workspace/dataset:ro \
      -v /home/ultra/oww-models:/workspace/models \
      -v /home/ultra/wyoming-debug:/workspace/wyoming-debug:ro \
      -v /home/ultra/openWakeWord/openwakeword/resources/models:/workspace/openWakeWord/openwakeword/resources/models:ro \
      oww-train:latest \
      python3 /workspace/homeassistant/scripts/wakeword_iterate.py iterate

The script intentionally keeps model artifacts outside the Home Assistant git
tree. It writes run reports to /workspace/models/<run-name>/.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import random
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import soundfile as sf


SR = 16000
EMBEDDING_DIM = 96
DEFAULT_SEED = 20260601
THRESHOLDS = np.unique(
    np.concatenate(
        [
            np.round(np.arange(0.05, 1.0, 0.01), 2),
            np.round(np.arange(0.991, 1.0, 0.001), 3),
        ]
    )
)


@dataclasses.dataclass(frozen=True)
class AudioItem:
    path: Path
    label: int
    bucket: str
    source: str
    duration: float
    split: str
    windows: int = 1
    offsets: tuple[float, ...] = ()

    @property
    def item_id(self) -> str:
        return f"{self.source}:{self.path.name}"


def stable_ratio(text: str) -> float:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def choose_split(path: Path, label: int, salt: str = "") -> str:
    ratio = stable_ratio(f"{salt}:{label}:{path.as_posix()}")
    if ratio < 0.70:
        return "train"
    if ratio < 0.85:
        return "val"
    return "test"


def wav_duration(path: Path) -> float | None:
    try:
        info = sf.info(str(path))
        if info.samplerate <= 0 or info.frames <= 0:
            return None
        return float(info.frames) / float(info.samplerate)
    except Exception:
        try:
            with wave.open(str(path), "rb") as wav_file:
                rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                if rate <= 0 or frames <= 0:
                    return None
                return float(frames) / float(rate)
        except Exception:
            return None


def valid_wavs(root: Path) -> Iterable[tuple[Path, float]]:
    if not root.exists():
        return

    for path in sorted(root.rglob("*.wav")):
        if path.stat().st_size <= 44:
            continue

        duration = wav_duration(path)
        if duration is None or duration <= 0.1:
            continue

        yield path, duration


def discover_dataset(
    dataset_root: Path,
    debug_root: Path,
    max_stt_windows: int,
    salt: str,
) -> tuple[list[AudioItem], dict[str, Any]]:
    items: list[AudioItem] = []
    skipped = Counter()

    positives_root = dataset_root / "positives"
    for path, duration in valid_wavs(positives_root):
        bucket = path.relative_to(positives_root).parts[0]
        items.append(
            AudioItem(
                path=path,
                label=1,
                bucket=bucket,
                source="positive_synthetic",
                duration=duration,
                split=choose_split(path, 1, salt),
            )
        )

    adversarial_root = dataset_root / "negatives" / "adversarial"
    for path, duration in valid_wavs(adversarial_root):
        bucket = path.relative_to(adversarial_root).parts[0]
        items.append(
            AudioItem(
                path=path,
                label=0,
                bucket=f"adversarial/{bucket}",
                source="negative_adversarial",
                duration=duration,
                split=choose_split(path, 0, salt),
            )
        )

    hard_root = dataset_root / "negatives" / "home_recordings"
    for path, duration in valid_wavs(hard_root):
        items.append(
            AudioItem(
                path=path,
                label=0,
                bucket="home_false_wake",
                source="negative_home_false_wake",
                duration=duration,
                split=choose_split(path, 0, salt),
            )
        )

    # STT debug files can be very long. Use them only as an evaluation sample;
    # training on them without labels would make the iteration slow and muddy.
    stt_files = [(path, duration) for path, duration in valid_wavs(debug_root) if path.name.endswith("-stt.wav")]
    total_stt_duration = sum(duration for _, duration in stt_files)
    if stt_files and max_stt_windows > 0:
        # Allocate sampled 2-second windows proportionally to file duration.
        by_path: list[tuple[Path, float, int]] = []
        for path, duration in stt_files:
            count = max(1, round(max_stt_windows * (duration / total_stt_duration)))
            by_path.append((path, duration, count))

        # Keep the exact cap deterministic.
        while sum(count for _, _, count in by_path) > max_stt_windows:
            by_path.sort(key=lambda row: (row[2], row[1]), reverse=True)
            path, duration, count = by_path[0]
            by_path[0] = (path, duration, count - 1)

        for path, duration, count in by_path:
            if count <= 0:
                continue
            items.append(
                AudioItem(
                    path=path,
                    label=0,
                    bucket="debug_stt_sample",
                    source="negative_debug_stt_sample",
                    duration=duration,
                    split="test",
                    windows=count,
                )
            )

    raw_root = dataset_root / "raw"
    raw_files = list(raw_root.rglob("*.wav")) if raw_root.exists() else []
    for path in raw_files:
        if path.stat().st_size <= 44:
            skipped["raw_empty_or_header_only"] += 1
        else:
            skipped["raw_nonempty_unlabeled"] += 1

    summary = {
        "positive_files": sum(1 for item in items if item.label == 1),
        "negative_files": sum(1 for item in items if item.label == 0),
        "debug_stt_files": len(stt_files),
        "debug_stt_hours_available": total_stt_duration / 3600.0,
        "debug_stt_windows_sampled": sum(
            item.windows for item in items if item.source == "negative_debug_stt_sample"
        ),
        "skipped": dict(skipped),
    }
    return items, summary


def context_samples(context_frames: int) -> int:
    # openWakeWord embeddings use a 76-melspec-frame receptive field and an
    # 8-frame hop. The +3 matches the melspectrogram frame formula in utils.py.
    return (76 + (context_frames - 1) * 8 + 3) * 160


def read_audio(path: Path, target_sr: int = SR) -> np.ndarray:
    samples, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if sr != target_sr:
        if len(samples) == 0:
            return np.zeros(0, dtype=np.float32)
        new_len = max(1, int(round(len(samples) * target_sr / sr)))
        samples = np.interp(
            np.linspace(0, len(samples) - 1, new_len),
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)
    return samples.astype(np.float32)


def read_audio_window(path: Path, start_sec: float, seconds: float, target_sr: int = SR) -> np.ndarray:
    info = sf.info(str(path))
    start = max(0, int(start_sec * info.samplerate))
    frames = max(1, int(seconds * info.samplerate))
    samples, sr = sf.read(str(path), start=start, frames=frames, dtype="float32", always_2d=False)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if sr != target_sr:
        new_len = max(1, int(round(len(samples) * target_sr / sr)))
        samples = np.interp(
            np.linspace(0, len(samples) - 1, new_len),
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)
    return samples.astype(np.float32)


def to_fixed_clip(
    samples: np.ndarray,
    clip_samples: int,
    rng: random.Random,
    label: int,
    train: bool,
    add_noise: bool,
) -> np.ndarray:
    if len(samples) >= clip_samples:
        if train:
            start = rng.randint(0, len(samples) - clip_samples)
        else:
            start = max(0, (len(samples) - clip_samples) // 2)
        clip = samples[start : start + clip_samples].copy()
    else:
        clip = np.zeros(clip_samples, dtype=np.float32)
        if train:
            start = rng.randint(0, clip_samples - len(samples))
        else:
            start = max(0, (clip_samples - len(samples)) // 2)
        clip[start : start + len(samples)] = samples

    if train:
        gain = rng.uniform(0.65, 1.25) if label == 1 else rng.uniform(0.8, 1.15)
        clip *= gain
        if add_noise and rng.random() < 0.35:
            noise_level = rng.uniform(0.0005, 0.004)
            noise = np.array([rng.gauss(0.0, noise_level) for _ in range(clip_samples)], dtype=np.float32)
            clip += noise

    clip = np.clip(clip, -1.0, 1.0)
    return (clip * 32767.0).astype(np.int16)


def stt_window_offsets(duration: float, windows: int, clip_sec: float, key: str) -> list[float]:
    if windows <= 0:
        return []
    if duration <= clip_sec:
        return [0.0]

    rng = random.Random(int(stable_ratio(key) * 10_000_000))
    max_start = max(0.0, duration - clip_sec)
    return sorted(rng.uniform(0.0, max_start) for _ in range(windows))


def import_audio_features(openwakeword_root: Path):
    import sys

    sys.path.insert(0, str(openwakeword_root))
    from openwakeword.utils import AudioFeatures  # noqa: PLC0415

    return AudioFeatures


def extract_features(
    items: list[AudioItem],
    context_frames: int,
    split: str,
    openwakeword_root: Path,
    batch_size: int,
    ncpu: int,
    positive_augmentations: int,
    add_noise: bool,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    selected: list[tuple[AudioItem, int, float | None]] = []
    clip_samples = context_samples(context_frames)
    clip_sec = clip_samples / SR

    for item in items:
        if item.split != split:
            continue

        if item.source.startswith("negative_debug_stt_"):
            offsets = list(item.offsets) if item.offsets else stt_window_offsets(item.duration, item.windows, clip_sec, item.item_id)
            for offset in offsets:
                selected.append((item, 0, offset))
            continue

        aug_count = positive_augmentations if (split == "train" and item.label == 1) else 1
        for aug_idx in range(aug_count):
            selected.append((item, aug_idx, None))

    if not selected:
        return (
            np.empty((0, EMBEDDING_DIM, context_frames), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            [],
        )

    AudioFeatures = import_audio_features(openwakeword_root)
    audio_features = AudioFeatures(
        melspec_model_path=str(openwakeword_root / "openwakeword/resources/models/melspectrogram.onnx"),
        embedding_model_path=str(openwakeword_root / "openwakeword/resources/models/embedding_model.onnx"),
        device="cpu",
    )

    features: list[np.ndarray] = []
    labels: list[int] = []
    metas: list[dict[str, Any]] = []

    batch_clips: list[np.ndarray] = []
    batch_meta: list[tuple[AudioItem, int, float | None]] = []

    def flush_batch() -> None:
        if not batch_clips:
            return
        clips = np.stack(batch_clips, axis=0)
        embeddings = audio_features.embed_clips(clips, batch_size=min(batch_size, len(batch_clips)), ncpu=ncpu)
        if embeddings.shape[1] < context_frames:
            raise RuntimeError(f"expected at least {context_frames} frames, got {embeddings.shape}")
        embeddings = embeddings[:, -context_frames:, :].astype(np.float32)
        embeddings = np.transpose(embeddings, (0, 2, 1))
        features.append(embeddings)
        for item, aug_idx, offset in batch_meta:
            labels.append(item.label)
            metas.append(
                {
                    "path": str(item.path),
                    "label": item.label,
                    "bucket": item.bucket,
                    "source": item.source,
                    "split": item.split,
                    "duration": item.duration,
                    "augment": aug_idx,
                    "offset": offset,
                }
            )
        batch_clips.clear()
        batch_meta.clear()

    for item, aug_idx, offset in selected:
        rng = random.Random(int(stable_ratio(f"{item.item_id}:{split}:{aug_idx}:{offset}") * 10_000_000))
        if offset is None:
            samples = read_audio(item.path)
        else:
            samples = read_audio_window(item.path, offset, clip_sec)

        clip = to_fixed_clip(
            samples,
            clip_samples=clip_samples,
            rng=rng,
            label=item.label,
            train=(split == "train"),
            add_noise=add_noise,
        )
        batch_clips.append(clip)
        batch_meta.append((item, aug_idx, offset))
        if len(batch_clips) >= batch_size:
            flush_batch()

    flush_batch()

    return np.concatenate(features, axis=0), np.asarray(labels, dtype=np.float32), metas


def summarize_items(items: list[AudioItem]) -> dict[str, Any]:
    by_split_label = Counter((item.split, item.label) for item in items)
    by_source = defaultdict(lambda: {"files": 0, "hours": 0.0, "windows": 0})
    for item in items:
        row = by_source[item.source]
        row["files"] += 1
        row["hours"] += item.duration / 3600.0
        row["windows"] += item.windows

    return {
        "by_split_label": {
            f"{split}_{'pos' if label else 'neg'}": count
            for (split, label), count in sorted(by_split_label.items())
        },
        "by_source": dict(sorted(by_source.items())),
    }


class DnnModel:
    name = "dnn"

    @staticmethod
    def build(context_frames: int, hidden: int, dropout: float):
        import torch.nn as nn

        return nn.Sequential(
            nn.Flatten(),
            nn.Linear(EMBEDDING_DIM * context_frames, hidden),
            nn.LayerNorm(hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden),
            nn.LayerNorm(hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 1),
        )


class GruModel:
    name = "gru"

    @staticmethod
    def build(context_frames: int, hidden: int, dropout: float):
        import torch
        import torch.nn as nn

        class Model(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.gru = nn.GRU(
                    input_size=EMBEDDING_DIM,
                    hidden_size=hidden,
                    batch_first=True,
                    bidirectional=True,
                )
                self.dropout = nn.Dropout(dropout)
                self.fc = nn.Linear(hidden * 2, 1)

            def forward(self, x):  # noqa: ANN001
                # Input is [batch, 96, context] for deployment parity.
                seq = torch.transpose(x, 1, 2)
                out, _ = self.gru(seq)
                pooled = out[:, -1, :]
                return self.fc(self.dropout(pooled))

        return Model()


def torch_predict(model: Any, x: np.ndarray, batch_size: int) -> np.ndarray:
    import torch

    device = next(model.parameters()).device
    outputs: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(x), batch_size):
            xb = torch.from_numpy(x[start : start + batch_size]).to(device)
            logits = model(xb)
            outputs.append(torch.sigmoid(logits).detach().cpu().numpy().reshape(-1))
    return np.concatenate(outputs, axis=0) if outputs else np.empty((0,), dtype=np.float32)


def metric_at_threshold(y_true: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    pred = scores >= threshold
    pos = y_true == 1
    neg = ~pos
    tp = int(np.logical_and(pred, pos).sum())
    fp = int(np.logical_and(pred, neg).sum())
    tn = int(np.logical_and(~pred, neg).sum())
    fn = int(np.logical_and(~pred, pos).sum())

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    accuracy = (tp + tn) / len(y_true) if len(y_true) else 0.0
    return {
        "threshold": float(threshold),
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


def estimate_negative_hours(metas: list[dict[str, Any]], clip_seconds: float) -> float:
    total_seconds = 0.0
    for meta in metas:
        if meta["label"] == 1:
            continue
        if meta["source"] == "negative_debug_stt_sample":
            total_seconds += clip_seconds
        else:
            total_seconds += min(float(meta["duration"]), clip_seconds)
    return total_seconds / 3600.0


def evaluate_scores(
    y_true: np.ndarray,
    scores: np.ndarray,
    metas: list[dict[str, Any]],
    thresholds: np.ndarray,
    clip_seconds: float,
    target_fpr_per_hour: float,
    selection_recall_tolerance: float,
) -> dict[str, Any]:
    neg_hours = estimate_negative_hours(metas, clip_seconds)
    sweep = []
    for threshold in thresholds:
        row = metric_at_threshold(y_true, scores, float(threshold))
        row["fpr_per_hour"] = (row["fp"] / neg_hours) if neg_hours > 0 else math.inf
        sweep.append(row)

    feasible = [row for row in sweep if row["fpr_per_hour"] <= target_fpr_per_hour]
    if feasible:
        best_recall = max(row["recall"] for row in feasible)
        robust = [
            row
            for row in feasible
            if row["recall"] >= max(0.0, best_recall - selection_recall_tolerance)
        ]
        selected = max(robust, key=lambda row: (row["threshold"], -row["fpr_per_hour"]))
    else:
        selected = min(sweep, key=lambda row: (row["fpr_per_hour"], -row["recall"]))

    bucket_rows: dict[str, dict[str, Any]] = {}
    threshold = selected["threshold"]
    for bucket in sorted({meta["bucket"] for meta in metas}):
        idx = np.asarray([meta["bucket"] == bucket for meta in metas])
        if not idx.any():
            continue
        row = metric_at_threshold(y_true[idx], scores[idx], threshold)
        row["count"] = int(idx.sum())
        row["score_max"] = float(scores[idx].max())
        row["score_p95"] = float(np.quantile(scores[idx], 0.95))
        bucket_rows[bucket] = row

    return {
        "selected": selected,
        "negative_hours_estimated": neg_hours,
        "bucket_metrics_at_selected_threshold": bucket_rows,
        "sweep": sweep,
        "score_summary": {
            "positive_p05": float(np.quantile(scores[y_true == 1], 0.05)) if (y_true == 1).any() else None,
            "positive_median": float(np.median(scores[y_true == 1])) if (y_true == 1).any() else None,
            "negative_p95": float(np.quantile(scores[y_true == 0], 0.95)) if (y_true == 0).any() else None,
            "negative_max": float(scores[y_true == 0].max()) if (y_true == 0).any() else None,
        },
    }


def predict_tflite_scores(model_path: Path, x: np.ndarray, batch_size: int) -> np.ndarray:
    import ai_edge_litert.interpreter as tflite

    interpreter = tflite.Interpreter(model_path=str(model_path))
    input_details = interpreter.get_input_details()[0]
    input_index = input_details["index"]
    output_index = interpreter.get_output_details()[0]["index"]
    input_shape = list(input_details["shape"])
    if len(input_shape) != 3:
        raise RuntimeError(f"unexpected TFLite input shape: {input_shape}")

    if input_shape[1] == EMBEDDING_DIM:
        layout = "training"
    elif input_shape[2] == EMBEDDING_DIM:
        layout = "pyopen"
    else:
        raise RuntimeError(f"unexpected TFLite input shape: {input_shape}")

    outputs = []
    for start in range(0, len(x), batch_size):
        xb = x[start : start + batch_size].astype(np.float32)
        if layout == "pyopen":
            xb = np.transpose(xb, (0, 2, 1))
        interpreter.resize_tensor_input(input_index, xb.shape, strict=False)
        interpreter.allocate_tensors()
        interpreter.set_tensor(input_index, xb)
        interpreter.invoke()
        outputs.append(interpreter.get_tensor(output_index).reshape(-1))
    return np.concatenate(outputs, axis=0) if outputs else np.empty((0,), dtype=np.float32)


def tflite_context_frames(model_path: Path) -> int:
    import ai_edge_litert.interpreter as tflite

    interpreter = tflite.Interpreter(model_path=str(model_path))
    input_details = interpreter.get_input_details()[0]
    shape = list(input_details["shape"])
    if len(shape) != 3:
        raise RuntimeError(f"unexpected TFLite input shape: {shape}")
    if shape[1] == EMBEDDING_DIM:
        return int(shape[2])
    if shape[2] == EMBEDDING_DIM:
        return int(shape[1])
    raise RuntimeError(f"unexpected TFLite input shape: {shape}")


def allocate_windows_by_duration(
    files: list[tuple[Path, float]],
    total_windows: int,
) -> list[tuple[Path, float, int]]:
    if not files or total_windows <= 0:
        return []

    total_duration = sum(duration for _, duration in files)
    by_path: list[tuple[Path, float, int]] = []
    for path, duration in files:
        count = max(1, round(total_windows * (duration / total_duration)))
        by_path.append((path, duration, count))

    while sum(count for _, _, count in by_path) > total_windows:
        by_path.sort(key=lambda row: (row[2], row[1]), reverse=True)
        path, duration, count = by_path[0]
        by_path[0] = (path, duration, count - 1)

    return [(path, duration, count) for path, duration, count in by_path if count > 0]


def reserved_debug_offsets(
    items: list[AudioItem],
    clip_sec: float,
) -> dict[Path, list[float]]:
    offsets_by_path: dict[Path, list[float]] = defaultdict(list)
    for item in items:
        if item.source != "negative_debug_stt_sample":
            continue
        offsets_by_path[item.path].extend(stt_window_offsets(item.duration, item.windows, clip_sec, item.item_id))
    return offsets_by_path


def overlaps_reserved(offset: float, reserved: list[float], clip_sec: float) -> bool:
    return any(abs(offset - candidate) < clip_sec for candidate in reserved)


def mine_debug_hard_negatives(
    base_items: list[AudioItem],
    debug_root: Path,
    model_path: Path,
    context_frames: int,
    openwakeword_root: Path,
    candidate_windows: int,
    hard_windows: int,
    score_floor: float,
    fill_below_floor: bool,
    seed: int,
    feature_batch_size: int,
    batch_size: int,
    ncpu: int,
) -> tuple[list[AudioItem], dict[str, Any]]:
    if hard_windows <= 0 or candidate_windows <= 0:
        return [], {"enabled": False}

    model_context = tflite_context_frames(model_path)
    if model_context != context_frames:
        raise RuntimeError(
            f"hard negative model context {model_context} does not match requested context {context_frames}"
        )

    stt_files = [(path, duration) for path, duration in valid_wavs(debug_root) if path.name.endswith("-stt.wav")]
    clip_sec = context_samples(context_frames) / SR
    reserved = reserved_debug_offsets(base_items, clip_sec)

    candidates: list[AudioItem] = []
    skipped_overlap = 0
    for path, duration, count in allocate_windows_by_duration(stt_files, candidate_windows):
        offsets = stt_window_offsets(duration, count, clip_sec, f"hard-mine:{seed}:{path.as_posix()}")
        kept_offsets = []
        for offset in offsets:
            if overlaps_reserved(offset, reserved.get(path, []), clip_sec):
                skipped_overlap += 1
                continue
            kept_offsets.append(offset)
        if kept_offsets:
            candidates.append(
                AudioItem(
                    path=path,
                    label=0,
                    bucket="debug_stt_hard_mine_candidates",
                    source="negative_debug_stt_hard_candidate",
                    duration=duration,
                    split="mine",
                    windows=len(kept_offsets),
                    offsets=tuple(kept_offsets),
                )
            )

    if not candidates:
        return [], {
            "enabled": True,
            "model": str(model_path),
            "candidate_windows_requested": candidate_windows,
            "selected_windows_requested": hard_windows,
            "candidate_windows_after_overlap_filter": 0,
            "skipped_reserved_overlap": skipped_overlap,
            "selected_windows": 0,
        }

    x_mine, y_mine, meta_mine = extract_features(
        candidates,
        context_frames=context_frames,
        split="mine",
        openwakeword_root=openwakeword_root,
        batch_size=feature_batch_size,
        ncpu=ncpu,
        positive_augmentations=1,
        add_noise=False,
    )
    if not len(x_mine) or (y_mine == 1).any():
        error_message = "hard negative mining expected negative-only candidate features"
        raise RuntimeError(error_message)

    scores = predict_tflite_scores(model_path, x_mine, batch_size=batch_size)
    order = np.argsort(scores)[::-1]
    above_floor = [int(idx) for idx in order if scores[idx] >= score_floor]
    selected_indices = above_floor[:hard_windows]
    if len(selected_indices) < hard_windows and fill_below_floor:
        selected = set(selected_indices)
        for idx in order:
            if int(idx) in selected:
                continue
            selected_indices.append(int(idx))
            if len(selected_indices) >= hard_windows:
                break

    selected_by_path: dict[str, list[tuple[float, float]]] = defaultdict(list)
    duration_by_path: dict[str, float] = {}
    for idx in selected_indices:
        meta = meta_mine[idx]
        path = meta["path"]
        selected_by_path[path].append((float(meta["offset"]), float(scores[idx])))
        duration_by_path[path] = float(meta["duration"])

    hard_items = [
        AudioItem(
            path=Path(path),
            label=0,
            bucket="debug_stt_hard_mined",
            source="negative_debug_stt_hard_mined",
            duration=duration_by_path[path],
            split="train",
            windows=len(rows),
            offsets=tuple(offset for offset, _score in sorted(rows)),
        )
        for path, rows in sorted(selected_by_path.items())
    ]

    selected_scores = scores[selected_indices] if selected_indices else np.asarray([], dtype=np.float32)
    return hard_items, {
        "enabled": True,
        "model": str(model_path),
        "candidate_windows_requested": candidate_windows,
        "selected_windows_requested": hard_windows,
        "candidate_windows_after_overlap_filter": int(len(meta_mine)),
        "skipped_reserved_overlap": skipped_overlap,
        "selected_windows": int(len(selected_indices)),
        "score_floor": score_floor,
        "fill_below_score_floor": fill_below_floor,
        "selected_above_score_floor": int(sum(float(score) >= score_floor for score in selected_scores)),
        "selected_score_min": float(selected_scores.min()) if len(selected_scores) else None,
        "selected_score_median": float(np.median(selected_scores)) if len(selected_scores) else None,
        "selected_score_max": float(selected_scores.max()) if len(selected_scores) else None,
        "top_candidates": [
            {
                "path": meta_mine[int(idx)]["path"],
                "offset": float(meta_mine[int(idx)]["offset"]),
                "score": float(scores[int(idx)]),
            }
            for idx in order[: min(20, len(order))]
        ],
    }


def train_model(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    architecture: str,
    context_frames: int,
    hidden: int,
    dropout: float,
    epochs: int,
    lr: float,
    batch_size: int,
    negative_weight: float,
    seed: int,
) -> tuple[Any, dict[str, Any]]:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler

    torch.manual_seed(seed)
    np.random.seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    builder = DnnModel if architecture == "dnn" else GruModel
    model = builder.build(context_frames=context_frames, hidden=hidden, dropout=dropout).to(device)

    train_x = torch.from_numpy(x_train).float()
    train_y = torch.from_numpy(y_train.reshape(-1, 1)).float()
    dataset = TensorDataset(train_x, train_y)

    weights = np.where(y_train == 1, 1.0, negative_weight).astype(np.float64)
    sampler = WeightedRandomSampler(weights=weights, num_samples=len(weights), replacement=True)
    loader = DataLoader(dataset, batch_size=batch_size, sampler=sampler)

    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, epochs))

    history = []
    best_state = None
    best_val_loss = float("inf")
    patience_left = 8

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        total = 0
        for xb, yb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(xb)
            total += len(xb)

        scheduler.step()
        val_scores = torch_predict(model, x_val, batch_size=batch_size)
        eps = 1e-7
        val_loss = -np.mean(
            y_val * np.log(np.clip(val_scores, eps, 1 - eps))
            + (1 - y_val) * np.log(np.clip(1 - val_scores, eps, 1 - eps))
        )
        val_metrics = metric_at_threshold(y_val, val_scores, 0.5)
        row = {
            "epoch": epoch,
            "train_loss": total_loss / max(1, total),
            "val_loss": float(val_loss),
            "val_accuracy_at_0_5": val_metrics["accuracy"],
            "val_recall_at_0_5": val_metrics["recall"],
            "val_fp_at_0_5": val_metrics["fp"],
        }
        history.append(row)

        if val_loss < best_val_loss:
            best_val_loss = float(val_loss)
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience_left = 8
        else:
            patience_left -= 1
            if patience_left <= 0 and epoch >= 12:
                break

        if epoch == 1 or epoch % 5 == 0:
            print(
                f"{architecture} epoch {epoch:03d}: "
                f"loss={row['train_loss']:.4f} val_loss={row['val_loss']:.4f} "
                f"val_acc={row['val_accuracy_at_0_5']:.4f} val_fp={row['val_fp_at_0_5']}"
            )

    if best_state is not None:
        model.load_state_dict(best_state)

    return model, {
        "device": str(device),
        "epochs_ran": len(history),
        "best_val_loss": best_val_loss,
        "history": history,
        "parameters": int(sum(parameter.numel() for parameter in model.parameters())),
    }


def export_onnx(model: Any, path: Path, context_frames: int) -> None:
    import torch

    model.eval()
    dummy = torch.randn(1, EMBEDDING_DIM, context_frames, device=next(model.parameters()).device)
    torch.onnx.export(
        model,
        dummy,
        str(path),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch_size"}, "logits": {0: "batch_size"}},
        opset_version=13,
    )


def run_iterate(args: argparse.Namespace) -> None:
    import torch

    started = time.strftime("%Y%m%d_%H%M%S")
    run_name = args.run_name or f"ey_milosh_iter_{started}"
    run_dir = args.output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    items, discovery = discover_dataset(
        dataset_root=args.dataset_root,
        debug_root=args.debug_root,
        max_stt_windows=args.max_stt_windows,
        salt=str(args.seed),
    )
    hard_negative_report = {"enabled": False}
    if args.hard_negative_model:
        hard_items, hard_negative_report = mine_debug_hard_negatives(
            base_items=items,
            debug_root=args.debug_root,
            model_path=args.hard_negative_model,
            context_frames=args.context_frames,
            openwakeword_root=args.openwakeword_root,
            candidate_windows=args.hard_negative_candidates,
            hard_windows=args.hard_negative_windows,
            score_floor=args.hard_negative_score_floor,
            fill_below_floor=args.hard_negative_fill_below_floor,
            seed=args.seed,
            feature_batch_size=args.feature_batch_size,
            batch_size=args.batch_size,
            ncpu=args.ncpu,
        )
        items.extend(hard_items)
        discovery["debug_stt_hard_mined_windows_train"] = sum(item.windows for item in hard_items)
        discovery["debug_stt_hard_mined_files_train"] = len(hard_items)
    dataset_summary = summarize_items(items)
    print(
        json.dumps(
            {"discovery": discovery, "dataset": dataset_summary, "hard_negative_mining": hard_negative_report},
            ensure_ascii=False,
            indent=2,
        )
    )

    feature_cache = run_dir / f"features_context{args.context_frames}.npz"
    meta_cache = run_dir / f"features_context{args.context_frames}.meta.json"

    if feature_cache.exists() and meta_cache.exists() and not args.rebuild_features:
        print(f"Loading cached features: {feature_cache}")
        data = np.load(feature_cache)
        metas_by_split = json.loads(meta_cache.read_text(encoding="utf-8"))
        x_train, y_train = data["x_train"], data["y_train"]
        x_val, y_val = data["x_val"], data["y_val"]
        x_test, y_test = data["x_test"], data["y_test"]
        meta_train = metas_by_split["train"]
        meta_val = metas_by_split["val"]
        meta_test = metas_by_split["test"]
    else:
        x_train, y_train, meta_train = extract_features(
            items,
            context_frames=args.context_frames,
            split="train",
            openwakeword_root=args.openwakeword_root,
            batch_size=args.feature_batch_size,
            ncpu=args.ncpu,
            positive_augmentations=args.positive_augmentations,
            add_noise=True,
        )
        x_val, y_val, meta_val = extract_features(
            items,
            context_frames=args.context_frames,
            split="val",
            openwakeword_root=args.openwakeword_root,
            batch_size=args.feature_batch_size,
            ncpu=args.ncpu,
            positive_augmentations=1,
            add_noise=False,
        )
        x_test, y_test, meta_test = extract_features(
            items,
            context_frames=args.context_frames,
            split="test",
            openwakeword_root=args.openwakeword_root,
            batch_size=args.feature_batch_size,
            ncpu=args.ncpu,
            positive_augmentations=1,
            add_noise=False,
        )
        np.savez_compressed(
            feature_cache,
            x_train=x_train,
            y_train=y_train,
            x_val=x_val,
            y_val=y_val,
            x_test=x_test,
            y_test=y_test,
        )
        meta_cache.write_text(
            json.dumps({"train": meta_train, "val": meta_val, "test": meta_test}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(
        "Feature shapes: "
        f"train={x_train.shape}/{y_train.shape} val={x_val.shape}/{y_val.shape} "
        f"test={x_test.shape}/{y_test.shape}"
    )

    clip_sec = context_samples(args.context_frames) / SR
    report: dict[str, Any] = {
        "run_name": run_name,
        "context_frames": args.context_frames,
        "clip_seconds": clip_sec,
        "seed": args.seed,
        "discovery": discovery,
        "dataset_summary": dataset_summary,
        "hard_negative_mining": hard_negative_report,
        "feature_shapes": {
            "train": list(x_train.shape),
            "val": list(x_val.shape),
            "test": list(x_test.shape),
        },
        "architectures": {},
    }

    best_architecture = None
    best_score = (-1.0, -math.inf)

    for architecture in args.architectures:
        arch_dir = run_dir / architecture
        arch_dir.mkdir(exist_ok=True)
        model, train_report = train_model(
            x_train=x_train,
            y_train=y_train,
            x_val=x_val,
            y_val=y_val,
            architecture=architecture,
            context_frames=args.context_frames,
            hidden=args.hidden,
            dropout=args.dropout,
            epochs=args.epochs,
            lr=args.lr,
            batch_size=args.batch_size,
            negative_weight=args.negative_weight,
            seed=args.seed,
        )

        val_scores = torch_predict(model, x_val, batch_size=args.batch_size)
        test_scores = torch_predict(model, x_test, batch_size=args.batch_size)
        val_report = evaluate_scores(
            y_val,
            val_scores,
            meta_val,
            thresholds=THRESHOLDS,
            clip_seconds=clip_sec,
            target_fpr_per_hour=args.target_fpr_per_hour,
            selection_recall_tolerance=args.selection_recall_tolerance,
        )
        selected_threshold = val_report["selected"]["threshold"]
        test_report = evaluate_scores(
            y_test,
            test_scores,
            meta_test,
            thresholds=np.asarray([selected_threshold], dtype=float),
            clip_seconds=clip_sec,
            target_fpr_per_hour=args.target_fpr_per_hour,
            selection_recall_tolerance=args.selection_recall_tolerance,
        )
        test_sweep_report = evaluate_scores(
            y_test,
            test_scores,
            meta_test,
            thresholds=THRESHOLDS,
            clip_seconds=clip_sec,
            target_fpr_per_hour=args.target_fpr_per_hour,
            selection_recall_tolerance=args.selection_recall_tolerance,
        )

        pt_path = arch_dir / f"{run_name}_{architecture}.pt"
        onnx_path = arch_dir / f"{run_name}_{architecture}.onnx"
        torch.save(
            {
                "state_dict": model.state_dict(),
                "architecture": architecture,
                "context_frames": args.context_frames,
                "hidden": args.hidden,
                "dropout": args.dropout,
                "threshold": selected_threshold,
            },
            pt_path,
        )
        if architecture == "dnn":
            export_onnx(model, onnx_path, args.context_frames)

        arch_report = {
            "train": train_report,
            "validation": val_report,
            "test_at_validation_threshold": test_report,
            "test_sweep_for_audit": test_sweep_report,
            "artifacts": {
                "pt": str(pt_path),
                "onnx": str(onnx_path) if onnx_path.exists() else None,
            },
        }
        (arch_dir / "metrics.json").write_text(json.dumps(arch_report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["architectures"][architecture] = arch_report

        selected = val_report["selected"]
        candidate_score = (selected["recall"], -selected["fpr_per_hour"])
        if candidate_score > best_score:
            best_score = candidate_score
            best_architecture = architecture

        print(
            f"{architecture}: threshold={selected_threshold:.2f} "
            f"val_recall={selected['recall']:.3f} val_fpr/h={selected['fpr_per_hour']:.3f} "
            f"test_recall={test_report['selected']['recall']:.3f} "
            f"test_fpr/h={test_report['selected']['fpr_per_hour']:.3f}"
        )

    report["best_architecture"] = best_architecture
    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")


def run_evaluate_tflite(args: argparse.Namespace) -> None:
    context_frames = tflite_context_frames(args.model)
    items, discovery = discover_dataset(
        dataset_root=args.dataset_root,
        debug_root=args.debug_root,
        max_stt_windows=args.max_stt_windows,
        salt=str(args.seed),
    )
    x_val, y_val, meta_val = extract_features(
        items,
        context_frames=context_frames,
        split="val",
        openwakeword_root=args.openwakeword_root,
        batch_size=args.feature_batch_size,
        ncpu=args.ncpu,
        positive_augmentations=1,
        add_noise=False,
    )
    x_test, y_test, meta_test = extract_features(
        items,
        context_frames=context_frames,
        split="test",
        openwakeword_root=args.openwakeword_root,
        batch_size=args.feature_batch_size,
        ncpu=args.ncpu,
        positive_augmentations=1,
        add_noise=False,
    )

    val_scores = predict_tflite_scores(args.model, x_val, args.batch_size)
    test_scores = predict_tflite_scores(args.model, x_test, args.batch_size)
    clip_sec = context_samples(context_frames) / SR
    val_report = evaluate_scores(
        y_val,
        val_scores,
        meta_val,
        thresholds=THRESHOLDS,
        clip_seconds=clip_sec,
        target_fpr_per_hour=args.target_fpr_per_hour,
        selection_recall_tolerance=args.selection_recall_tolerance,
    )
    selected_threshold = val_report["selected"]["threshold"]
    test_report = evaluate_scores(
        y_test,
        test_scores,
        meta_test,
        thresholds=np.asarray([selected_threshold], dtype=float),
        clip_seconds=clip_sec,
        target_fpr_per_hour=args.target_fpr_per_hour,
        selection_recall_tolerance=args.selection_recall_tolerance,
    )
    test_sweep_report = evaluate_scores(
        y_test,
        test_scores,
        meta_test,
        thresholds=THRESHOLDS,
        clip_seconds=clip_sec,
        target_fpr_per_hour=args.target_fpr_per_hour,
        selection_recall_tolerance=args.selection_recall_tolerance,
    )
    report = {
        "model": str(args.model),
        "context_frames": context_frames,
        "clip_seconds": clip_sec,
        "discovery": discovery,
        "dataset_summary": summarize_items(items),
        "feature_shapes": {"val": list(x_val.shape), "test": list(x_test.shape)},
        "validation": val_report,
        "test_at_validation_threshold": test_report,
        "test_sweep_for_audit": test_sweep_report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {args.output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("/workspace/dataset"))
    parser.add_argument("--debug-root", type=Path, default=Path("/workspace/wyoming-debug"))
    parser.add_argument("--openwakeword-root", type=Path, default=Path("/workspace/openWakeWord"))
    parser.add_argument("--output-root", type=Path, default=Path("/workspace/models"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--ncpu", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    parser.add_argument("--feature-batch-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--target-fpr-per-hour", type=float, default=1.0)
    parser.add_argument("--selection-recall-tolerance", type=float, default=0.005)
    parser.add_argument("--max-stt-windows", type=int, default=1200)

    subparsers = parser.add_subparsers(dest="command", required=True)

    iterate = subparsers.add_parser("iterate")
    iterate.add_argument("--run-name")
    iterate.add_argument("--context-frames", type=int, default=16)
    iterate.add_argument("--architectures", nargs="+", choices=["dnn", "gru"], default=["dnn", "gru"])
    iterate.add_argument("--hidden", type=int, default=128)
    iterate.add_argument("--dropout", type=float, default=0.20)
    iterate.add_argument("--epochs", type=int, default=45)
    iterate.add_argument("--lr", type=float, default=1e-3)
    iterate.add_argument("--negative-weight", type=float, default=1.8)
    iterate.add_argument("--positive-augmentations", type=int, default=2)
    iterate.add_argument("--hard-negative-model", type=Path)
    iterate.add_argument("--hard-negative-candidates", type=int, default=6000)
    iterate.add_argument("--hard-negative-windows", type=int, default=0)
    iterate.add_argument("--hard-negative-score-floor", type=float, default=0.50)
    iterate.add_argument("--hard-negative-fill-below-floor", action="store_true")
    iterate.add_argument("--rebuild-features", action="store_true")
    iterate.set_defaults(func=run_iterate)

    evaluate = subparsers.add_parser("evaluate-tflite")
    evaluate.add_argument("--model", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.set_defaults(func=run_evaluate_tflite)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
