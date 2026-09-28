from __future__ import annotations

import importlib.util
import os
import wave
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "wakeword_channel0_tee.py"
SPEC = importlib.util.spec_from_file_location("wakeword_channel0_tee", MODULE_PATH)
assert SPEC and SPEC.loader
wakeword = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wakeword)


def make_writer(tmp_path: Path, *, sync_frames: int = 4):
    return wakeword.SegmentWriter(
        tmp_path,
        sample_rate=16_000,
        sample_width=2,
        segment_frames=16_000,
        sync_frames=sync_frames,
        record_always=True,
        min_free_bytes=0,
        drop_silent_peak=-1,
    )


def test_segment_is_not_published_until_close(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.write(b"\x01\x00" * 200)

    assert list(tmp_path.rglob("*.wav")) == []
    partials = list(tmp_path.rglob("*.wav.partial"))
    assert len(partials) == 1

    writer.close()

    assert list(tmp_path.rglob("*.wav.partial")) == []
    wavs = list(tmp_path.rglob("*.wav"))
    assert len(wavs) == 1
    with wave.open(str(wavs[0]), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 16_000
        assert handle.getnframes() == 200


def test_sync_error_leaves_no_published_or_partial_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = make_writer(tmp_path, sync_frames=1)

    def fail_fsync(_fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="No space left on device"):
        writer.write(b"\x02\x00" * 4)

    assert list(tmp_path.rglob("*.wav")) == []
    assert list(tmp_path.rglob("*.wav.partial")) == []


def test_stale_partial_is_removed_before_recording(tmp_path: Path) -> None:
    day = tmp_path / "2026-09-28"
    day.mkdir()
    stale = day / "000000_000000.wav.partial"
    stale.write_bytes(b"broken")

    writer = make_writer(tmp_path)
    writer.write(b"\x03\x00" * 10)

    partials = list(tmp_path.rglob("*.wav.partial"))
    assert stale not in partials
    assert len(partials) == 1

    writer.close()
