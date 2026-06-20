#!/usr/bin/env python3
"""Confirm or reject wake-word review candidates without touching HA storage."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("confirm", "negative"))
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("/config/www/wakeword/wakeword-sample-candidates.json"))
    parser.add_argument("--dataset-root", type=Path, default=Path("/config/oww-dataset"))
    parser.add_argument("--www-root", type=Path, default=Path("/config/www/wakeword"))
    parser.add_argument("--status-path", type=Path, default=None)
    return parser.parse_args()


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def slug(value: object) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    text = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ_.-]+", "_", text)
    return text.strip("_") or "sample"


def candidate_key(sample: dict[str, Any], index: int) -> str:
    if sample.get("id"):
        return str(sample["id"])
    seed = "|".join(
        str(sample.get(key, ""))
        for key in ("path", "url", "source_path", "start_seconds", "end_seconds", "duration")
        if sample.get(key) not in (None, "")
    )
    return seed or f"sample-{index}"


def load_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    for key in ("samples", "fragments", "candidates", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def find_sample(samples: list[dict[str, Any]], sample_id: str) -> tuple[dict[str, Any], str]:
    for index, sample in enumerate(samples):
        key = candidate_key(sample, index)
        aliases = {
            key,
            str(sample.get("id", "")),
            str(sample.get("path", "")),
            str(sample.get("url", "")),
        }
        if sample_id in aliases:
            return sample, key
    raise SystemExit(f"sample id not found in manifest: {sample_id}")


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def map_sample_path(raw_value: object, www_root: Path, dataset_root: Path) -> Path:
    raw = str(raw_value or "").strip()
    if not raw:
        raise SystemExit("sample path is empty")

    if raw.startswith("/local/wakeword/"):
        return www_root / raw[len("/local/wakeword/") :]
    if raw.startswith("/home/ultra/homeassistant/www/wakeword/"):
        return www_root / raw[len("/home/ultra/homeassistant/www/wakeword/") :]
    if raw.startswith("/home/ultra/oww-dataset/"):
        return dataset_root / raw[len("/home/ultra/oww-dataset/") :]
    if raw.startswith("www/wakeword/"):
        return www_root / raw[len("www/wakeword/") :]
    return Path(raw)


def resolve_allowed_sample(sample: dict[str, Any], www_root: Path, dataset_root: Path) -> Path:
    path = map_sample_path(sample.get("path") or sample.get("url"), www_root, dataset_root)
    path = path.resolve()
    allowed_roots = (www_root.resolve(), dataset_root.resolve())
    if not any(is_relative_to(path, root) for root in allowed_roots):
        raise SystemExit(f"sample path is outside allowed roots: {path}")
    if path.suffix.lower() != ".wav":
        raise SystemExit(f"sample is not a wav file: {path}")
    if not path.exists():
        raise SystemExit(f"sample file not found: {path}")
    return path


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": {}}
    if not isinstance(data, dict):
        return {"items": {}}
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def copy_candidate(action: str, sample_id: str, sample: dict[str, Any], source: Path, dataset_root: Path) -> Path:
    destination_root = dataset_root / ("positives/review_confirmed" if action == "confirm" else "negatives/review_rejected")
    destination_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{sample_id}:{source}".encode("utf-8")).hexdigest()[:12]
    destination = destination_root / f"{slug(sample_id)[:56]}_{digest}.wav"
    shutil.copy2(source, destination)
    meta = {
        "sample_id": sample_id,
        "action": action,
        "status": "confirmed" if action == "confirm" else "negative",
        "source_path": str(source),
        "destination_path": str(destination),
        "created_at": now_iso(),
        "sample": sample,
    }
    write_json_atomic(destination.with_suffix(".json"), meta)
    return destination


def main() -> None:
    args = parse_args()
    www_root = args.www_root
    dataset_root = args.dataset_root
    status_path = args.status_path or (www_root / "review-status.json")
    samples = load_manifest(args.manifest)
    sample, canonical_id = find_sample(samples, args.sample_id)
    source = resolve_allowed_sample(sample, www_root, dataset_root)
    destination = copy_candidate(args.action, canonical_id, sample, source, dataset_root)

    status = load_status(status_path)
    item = status["items"].setdefault(canonical_id, {})
    item.update(
        {
            "status": "confirmed" if args.action == "confirm" else "negative",
            "confirmed_for_training": args.action == "confirm",
            "negative_added": args.action == "negative",
            "destination_path": str(destination),
            "source_path": str(source),
            "updated_at": now_iso(),
        }
    )
    status["updated_at"] = now_iso()
    write_json_atomic(status_path, status)
    print(json.dumps({"ok": True, "sample_id": canonical_id, "destination_path": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
