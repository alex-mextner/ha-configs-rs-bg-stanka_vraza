from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import struct
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "wakeword_noise_watchdog.py"
SPEC = importlib.util.spec_from_file_location("wakeword_noise_watchdog", MODULE_PATH)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


def write_bad_published_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        16_000,
        32_000,
        2,
        16,
        b"data",
        0,
    )
    path.write_bytes(header + (b"\x01\x00" * 100))


def test_summary_reports_structurally_invalid_published_wav(tmp_path: Path) -> None:
    bad = tmp_path / "raw_live" / "2026-09-28" / "broken.wav"
    write_bad_published_wav(bad)
    started = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)

    summary = watchdog.summarize_raw_live(tmp_path, started)

    assert summary["invalid_files_since_start"] == 1
    assert summary["invalid_segments"] == ["2026-09-28/broken.wav"]
    assert summary["nonempty_files_since_start"] == 0


def test_check_dry_run_warns_about_invalid_published_wav(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "raw_live" / "2026-09-28" / "broken.wav"
    write_bad_published_wav(bad)
    session = tmp_path / "raw_live_session.json"
    session.write_text(
        json.dumps(
            {
                "started_at": (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)).isoformat(),
                "target_hours": 168.0,
                "completion_notification_sent_at": None,
                "stopped_at": None,
            }
        )
    )
    args = argparse.Namespace(
        dataset_root=tmp_path,
        session_file=session,
        target_hours=168.0,
        ha_url="http://localhost:8123",
        stale_seconds=180.0,
        stale_repeat_hours=6.0,
        dry_run=True,
        min_free_gb=0.0,
    )

    assert watchdog.command_check(args) == 0

    output = capsys.readouterr().out
    assert "structurally invalid" in output
    assert "2026-09-28/broken.wav" in output
