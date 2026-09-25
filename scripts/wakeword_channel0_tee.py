#!/usr/bin/env python3
"""Tee ReSpeaker 6-channel raw PCM into channel-0 stdout and WAV segments.

The satellite still receives the same 16 kHz mono S16_LE stream on stdout.
In parallel, this writes the channel-0 stream into dated WAV files for real
home-noise wake word evaluation and hard-negative mining.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import shutil
import struct
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--status-interval-seconds", type=float, default=0.5)
    parser.add_argument("--positive-session-file", type=Path)
    parser.add_argument("--positive-root", type=Path)
    parser.add_argument("--positive-pre-roll-seconds", type=float, default=0.6)
    parser.add_argument("--positive-end-silence-seconds", type=float, default=0.6)
    parser.add_argument("--positive-min-seconds", type=float, default=1.0)
    parser.add_argument("--positive-max-seconds", type=float, default=3.0)
    parser.add_argument("--positive-start-margin-db", type=float, default=8.0)
    parser.add_argument("--positive-end-margin-db", type=float, default=4.0)
    parser.add_argument("--positive-min-start-dbfs", type=float, default=-40.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels-in", type=int, default=6)
    parser.add_argument("--sample-width", type=int, default=2)
    parser.add_argument("--segment-seconds", type=int, default=600)
    parser.add_argument("--frames-per-read", type=int, default=1024)
    parser.add_argument("--sync-seconds", type=int, default=5)
    parser.add_argument(
        "--session-file",
        type=Path,
        help="noise-recording session JSON; segments are written only while it is active",
    )
    parser.add_argument("--record-always", action="store_true", help="ignore the session file and always record")
    parser.add_argument("--min-free-gb", type=float, default=30.0, help="skip segments below this free disk space")
    parser.add_argument(
        "--positive-cooldown-seconds",
        type=float,
        default=90.0,
        help="keep noise recording paused this long after a positive (wake phrase) session ends",
    )
    return parser.parse_args()


def session_active(session_file: Path | None) -> bool:
    """A noise session is active when it has started and was neither completed nor stopped."""
    if session_file is None or not session_file.exists():
        return False
    try:
        session = json.loads(session_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(session.get("started_at")) and not session.get("completion_notification_sent_at") and not session.get("stopped_at")


class SegmentWriter:
    """Writes 60 s WAV segments while recording is allowed.

    Every segment boundary re-checks the session file and free disk space, so a
    noise session can be started or stopped without restarting the capture
    pipeline, and a filling disk stops recording instead of starving Home Assistant.
    Skipped segments keep their timing, so the next written file starts on time.

    Noise recordings must never contain the wake phrase: while a positive
    (phrase) collection session is active, and for a cooldown after it, the
    segment being written is discarded and recording stays paused.
    """

    def __init__(
        self,
        output_dir: Path,
        sample_rate: int,
        sample_width: int,
        segment_frames: int,
        sync_frames: int,
        session_file: Path | None = None,
        record_always: bool = False,
        min_free_bytes: int = 0,
        positive_session_file: Path | None = None,
        positive_cooldown_seconds: float = 90.0,
    ) -> None:
        self.output_dir = output_dir
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.segment_frames = segment_frames
        self.sync_frames = sync_frames
        self.session_file = session_file
        self.record_always = record_always
        self.min_free_bytes = min_free_bytes
        self.frames_written = 0
        self.frames_since_sync = 0
        self.current = None
        self.skipping = False
        self.last_reason: str | None = None
        self.current_path: Path | None = None
        self.positive_session_file = positive_session_file
        self.positive_cooldown_seconds = positive_cooldown_seconds
        self.positive_block_until = 0.0

    def _watch_positive_session(self) -> None:
        if self.positive_session_file is None or not self.positive_session_file.exists():
            return
        self.positive_block_until = time.monotonic() + self.positive_cooldown_seconds
        if self.current is not None:
            path = self.current_path
            self.current.close()
            self.current = None
            self.skipping = True
            if path is not None:
                path.unlink(missing_ok=True)
            print(f"[wakeword-recorder] positive session active: discarded {path}", file=sys.stderr, flush=True)

    def _recording_allowed(self) -> bool:
        reason = None
        if not self.record_always and not session_active(self.session_file):
            reason = "no active noise session"
        elif time.monotonic() < self.positive_block_until:
            reason = "positive phrase session active or cooling down"
        else:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(self.output_dir).free
            if free < self.min_free_bytes:
                reason = f"free disk {free / 1e9:.1f} GB below floor {self.min_free_bytes / 1e9:.1f} GB"
        if reason != self.last_reason:
            state = f"paused: {reason}" if reason else "recording"
            print(f"[wakeword-recorder] {state}", file=sys.stderr, flush=True)
            self.last_reason = reason
        return reason is None

    def _open_next(self) -> None:
        now = dt.datetime.now()
        day_dir = self.output_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / f"{now.strftime('%H%M%S_%f')}.wav"
        self.current = path.open("w+b")
        self.current_path = path
        self.frames_written = 0
        self.frames_since_sync = 0
        self._write_header()
        print(f"[wakeword-recorder] writing {path}", file=sys.stderr, flush=True)

    def _write_header(self) -> None:
        if self.current is None:
            return

        data_size = self.frames_written * self.sample_width
        byte_rate = self.sample_rate * self.sample_width
        block_align = self.sample_width
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            self.sample_rate,
            byte_rate,
            block_align,
            self.sample_width * 8,
            b"data",
            data_size,
        )
        current_pos = self.current.tell()
        self.current.seek(0)
        self.current.write(header)
        self.current.seek(max(current_pos, len(header)))

    def _sync(self) -> None:
        if self.current is None:
            return

        self._write_header()
        self.current.flush()
        os.fsync(self.current.fileno())
        self.frames_since_sync = 0

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._watch_positive_session()
        offset = 0
        frame_bytes = self.sample_width
        total_frames = len(data) // frame_bytes
        while offset < len(data):
            if self.frames_written >= self.segment_frames or (self.current is None and not self.skipping):
                self.close()
                self.frames_written = 0
                self.skipping = not self._recording_allowed()
                if not self.skipping:
                    self._open_next()

            available_frames = self.segment_frames - self.frames_written
            take_frames = min(available_frames, total_frames - (offset // frame_bytes))
            take_bytes = take_frames * frame_bytes
            if self.current is not None:
                self.current.write(data[offset : offset + take_bytes])
                self.frames_since_sync += take_frames
            self.frames_written += take_frames
            offset += take_bytes
            if self.current is not None and self.frames_since_sync >= self.sync_frames:
                self._sync()

    def close(self) -> None:
        if self.current is not None:
            self._sync()
            self.current.close()
            self.current = None


class NullWriter:
    def write(self, data: bytes) -> None:
        return

    def close(self) -> None:
        return


def extract_channel0(raw: bytes, channels_in: int, sample_width: int) -> bytes:
    frame_size = channels_in * sample_width
    usable = len(raw) - (len(raw) % frame_size)
    if usable <= 0:
        return b""
    frames = memoryview(raw[:usable])
    return b"".join(frames[i : i + sample_width] for i in range(0, usable, frame_size))


def slug(value: object) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    text = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ_.-]+", "_", text)
    return text.strip("_") or "wake"


def write_mono_wav(path: Path, data: bytes, sample_rate: int, sample_width: int) -> None:
    data_size = len(data)
    byte_rate = sample_rate * sample_width
    block_align = sample_width
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,
        b"data",
        data_size,
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(header)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def dbfs_mono(data: bytes, sample_width: int) -> float:
    if not data or sample_width != 2:
        return -120.0
    usable = len(data) - (len(data) % sample_width)
    if usable <= 0:
        return -120.0
    samples = memoryview(data[:usable]).cast("h")
    if len(samples) == 0:
        return -120.0
    total = 0.0
    for value in samples:
        total += float(int(value) * int(value))
    rms = math.sqrt(total / len(samples))
    return 20.0 * math.log10(max(rms, 1.0) / 32768.0)


class PositiveSessionRecorder:
    def __init__(
        self,
        session_file: Path | None,
        positive_root: Path | None,
        sample_rate: int,
        sample_width: int,
        pre_roll_seconds: float,
        end_silence_seconds: float,
        min_seconds: float,
        max_seconds: float,
        start_margin_db: float,
        end_margin_db: float,
        min_start_dbfs: float,
    ) -> None:
        self.session_file = session_file
        self.positive_root = positive_root
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.pre_roll_frames = max(0, int(pre_roll_seconds * sample_rate))
        self.end_silence_frames = max(1, int(end_silence_seconds * sample_rate))
        self.min_frames = max(1, int(min_seconds * sample_rate))
        self.max_frames = max(self.min_frames, int(max_seconds * sample_rate))
        self.start_margin_db = start_margin_db
        self.end_margin_db = end_margin_db
        self.min_start_dbfs = min_start_dbfs
        self.active_session: dict | None = None
        self.session_mtime: float | None = None
        self.output_dir: Path | None = None
        self.clip_count = 0
        self.noise_floor_dbfs = -55.0
        self.pre_roll: list[bytes] = []
        self.pre_roll_frame_count = 0
        self.current_chunks: list[bytes] = []
        self.current_frames = 0
        self.current_level_max = -120.0
        self.silence_frames = 0
        self.recording = False

    def observe(self, data: bytes) -> None:
        if self.session_file is None or self.positive_root is None:
            return
        frames = len(data) // self.sample_width
        if frames <= 0:
            return

        level = dbfs_mono(data, self.sample_width)
        self._load_session_if_needed()
        if self.active_session is None:
            self._update_noise_floor(level)
            self._push_pre_roll(data, frames)
            return

        expected = int(self.active_session.get("expected_attempts") or 0)
        if expected > 0 and self.clip_count >= expected:
            self._update_noise_floor(level)
            self._push_pre_roll(data, frames)
            return

        start_threshold = max(self.noise_floor_dbfs + self.start_margin_db, self.min_start_dbfs)
        end_threshold = self.noise_floor_dbfs + self.end_margin_db
        if not self.recording:
            self._push_pre_roll(data, frames)
            if level >= start_threshold:
                self.recording = True
                self.current_chunks = list(self.pre_roll)
                self.current_frames = self.pre_roll_frame_count
                self.current_level_max = level
                self.silence_frames = 0
            else:
                self._update_noise_floor(level)
                return

        self.current_chunks.append(data)
        self.current_frames += frames
        self.current_level_max = max(self.current_level_max, level)
        if level <= end_threshold:
            self.silence_frames += frames
        else:
            self.silence_frames = 0

        complete_by_silence = self.current_frames >= self.min_frames and self.silence_frames >= self.end_silence_frames
        complete_by_length = self.current_frames >= self.max_frames
        if complete_by_silence:
            self._finish_clip(reason="silence")
        elif complete_by_length:
            self._discard_clip(reason="continued_past_max")

    def _load_session_if_needed(self) -> None:
        assert self.session_file is not None
        try:
            stat = self.session_file.stat()
        except FileNotFoundError:
            self._clear_session()
            return

        if self.session_mtime == stat.st_mtime and self.active_session is not None:
            return

        try:
            session = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if session.get("id") != (self.active_session or {}).get("id"):
            self._reset_recording()
            self.clip_count = 0

        self.active_session = session
        self.session_mtime = stat.st_mtime
        self.output_dir = self._output_dir(session)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.clip_count = max(self.clip_count, len(list(self.output_dir.glob("*.wav"))))

    def _clear_session(self) -> None:
        if self.active_session is not None:
            self._reset_recording()
        self.active_session = None
        self.session_mtime = None
        self.output_dir = None
        self.clip_count = 0

    def _output_dir(self, session: dict) -> Path:
        if session.get("output_name"):
            assert self.positive_root is not None
            return self.positive_root / slug(session["output_name"])
        if session.get("output_dir"):
            output_dir = Path(str(session["output_dir"]))
            parts = output_dir.parts
            if "real_user" in parts:
                assert self.positive_root is not None
                index = parts.index("real_user")
                if index + 1 < len(parts):
                    return self.positive_root / Path(*parts[index + 1 :])
            return output_dir
        assert self.positive_root is not None
        parts = [slug(session.get(key)) for key in ("phrase", "speaker", "style", "location") if session.get(key)]
        return self.positive_root / f"{session.get('id', 'session')}_{'_'.join(parts)}"

    def _push_pre_roll(self, data: bytes, frames: int) -> None:
        self.pre_roll.append(data)
        self.pre_roll_frame_count += frames
        while self.pre_roll and self.pre_roll_frame_count > self.pre_roll_frames:
            removed = self.pre_roll.pop(0)
            self.pre_roll_frame_count -= len(removed) // self.sample_width

    def _update_noise_floor(self, level: float) -> None:
        if level > self.noise_floor_dbfs + 12.0:
            return
        self.noise_floor_dbfs = (self.noise_floor_dbfs * 0.98) + (level * 0.02)

    def _reset_recording(self) -> None:
        self.recording = False
        self.current_chunks = []
        self.current_frames = 0
        self.current_level_max = -120.0
        self.silence_frames = 0

    def _finish_clip(self, reason: str) -> None:
        if self.active_session is None or self.output_dir is None:
            self._reset_recording()
            return
        data = b"".join(self.current_chunks)
        frames = len(data) // self.sample_width
        if frames < self.min_frames:
            self._reset_recording()
            return

        self.clip_count += 1
        session_id = slug(self.active_session.get("id", "session"))
        phrase = slug(self.active_session.get("phrase", "wake"))
        speaker = slug(self.active_session.get("speaker", "speaker"))
        style = slug(self.active_session.get("style", "style"))
        location = slug(self.active_session.get("location", "location"))
        path = self.output_dir / f"{session_id}_{self.clip_count:03d}_{phrase}_{speaker}_{style}_{location}.wav"
        write_mono_wav(path, data, self.sample_rate, self.sample_width)
        meta = {
            "session_id": self.active_session.get("id"),
            "phrase": self.active_session.get("phrase"),
            "speaker": self.active_session.get("speaker"),
            "style": self.active_session.get("style"),
            "location": self.active_session.get("location"),
            "index": self.clip_count,
            "path": str(path),
            "duration_seconds": round(frames / self.sample_rate, 3),
            "level_max_dbfs": round(self.current_level_max, 1),
            "noise_floor_dbfs": round(self.noise_floor_dbfs, 1),
            "finish_reason": reason,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "source": "respeaker_stream_vad",
            **self._doa_at_finish(),
        }
        path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[wakeword-positive] captured {path}", file=sys.stderr, flush=True)
        self._reset_recording()

    def _doa_at_finish(self) -> dict:
        """Direction the phrase came from, from the XVF-3000 reader (respeaker_tuning_service.py)."""
        if self.positive_root is None:
            return {}
        try:
            doa = json.loads((self.positive_root.parent.parent / "wakeword_doa.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        trail = [int(d) for d in doa.get("speech_trail_degrees") or []]
        if trail:
            s = sum(math.sin(math.radians(d)) for d in trail)
            c = sum(math.cos(math.radians(d)) for d in trail)
            return {"doa_degrees": round(math.degrees(math.atan2(s, c))) % 360, "doa_source": "xvf3000_speech_trail"}
        if doa.get("direction_degrees") is not None:
            return {"doa_degrees": int(doa["direction_degrees"]), "doa_source": "xvf3000_last"}
        return {}

    def _discard_clip(self, reason: str) -> None:
        duration = self.current_frames / self.sample_rate if self.sample_rate else 0.0
        print(
            f"[wakeword-positive] discarded {duration:.2f}s candidate: {reason}",
            file=sys.stderr,
            flush=True,
        )
        self._reset_recording()


class ArrayStatusWriter:
    def __init__(
        self,
        path: Path | None,
        sample_rate: int,
        channels_in: int,
        sample_width: int,
        interval_seconds: float,
    ) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.channels_in = channels_in
        self.sample_width = sample_width
        self.interval_seconds = max(0.1, interval_seconds)
        self.next_write_at = 0.0

    def observe(self, raw: bytes) -> None:
        if self.path is None:
            return
        now = time.monotonic()
        if now < self.next_write_at:
            return
        self.next_write_at = now + self.interval_seconds

        status = self._status_from_raw(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def _status_from_raw(self, raw: bytes) -> dict:
        frame_size = self.channels_in * self.sample_width
        usable = len(raw) - (len(raw) % frame_size)
        updated_at = dt.datetime.now(dt.UTC).isoformat()
        base = {
            "updated_at": updated_at,
            "sample_rate": self.sample_rate,
            "channels": self.channels_in,
            "source": "respeaker_6ch_energy",
        }
        if usable <= 0 or self.sample_width != 2:
            return {**base, "direction_degrees": None, "level_dbfs": None, "confidence": 0.0}

        samples = memoryview(raw[:usable]).cast("h")
        frames = len(samples) // self.channels_in
        if frames <= 0:
            return {**base, "direction_degrees": None, "level_dbfs": None, "confidence": 0.0}

        channel_sums = [0.0 for _ in range(self.channels_in)]
        channel_peaks = [0 for _ in range(self.channels_in)]
        for frame in range(frames):
            offset = frame * self.channels_in
            for channel in range(self.channels_in):
                value = int(samples[offset + channel])
                channel_sums[channel] += float(value * value)
                channel_peaks[channel] = max(channel_peaks[channel], abs(value))

        rms0 = math.sqrt(channel_sums[0] / frames) if channel_sums else 0.0
        level_dbfs = 20.0 * math.log10(max(rms0, 1.0) / 32768.0)

        # ReSpeaker UAC1 exposes ch0 as processed ASR audio and ch1-ch4 as
        # microphone elements. Use relative energy as a lightweight live DOA
        # hint; exact calibration can be tuned later without changing HA.
        mic_energies = channel_sums[1:5] if self.channels_in >= 5 else channel_sums[: min(4, self.channels_in)]
        direction = None
        confidence = 0.0
        if len(mic_energies) >= 4:
            min_energy = min(mic_energies)
            adjusted = [max(0.0, value - min_energy) for value in mic_energies]
            total = sum(adjusted)
            raw_total = sum(mic_energies)
            if raw_total > 0:
                confidence = max(0.0, min(1.0, (max(mic_energies) - min_energy) / raw_total * len(mic_energies)))
            if total > 0 and level_dbfs > -65.0 and confidence >= 0.03:
                angles = (0.0, 90.0, 180.0, 270.0)
                x = sum(value * math.cos(math.radians(angle)) for value, angle in zip(adjusted, angles, strict=True))
                y = sum(value * math.sin(math.radians(angle)) for value, angle in zip(adjusted, angles, strict=True))
                direction = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

        return {
            **base,
            "direction_degrees": None if direction is None else round(direction, 1),
            "level_dbfs": round(level_dbfs, 1),
            "confidence": round(confidence, 3),
            "channel_rms": [round(math.sqrt(value / frames), 1) for value in channel_sums],
            "channel_peaks": channel_peaks,
        }


_LAST_WARNING: dict[str, float] = {}


def best_effort(name: str, fn, *args) -> None:
    """Run a side output; on OSError warn at most once a minute and keep going."""
    try:
        fn(*args)
    except OSError as exc:
        now = time.monotonic()
        if now - _LAST_WARNING.get(name, float("-inf")) >= 60.0:
            _LAST_WARNING[name] = now
            print(f"[wakeword-tee] {name} failed, audio keeps flowing: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    args = parse_args()
    if not args.no_record and args.output_dir is None:
        raise SystemExit("--output-dir is required unless --no-record is set")

    frame_size = args.channels_in * args.sample_width
    read_size = args.frames_per_read * frame_size
    segment_frames = args.sample_rate * args.segment_seconds
    sync_frames = max(args.frames_per_read, args.sample_rate * args.sync_seconds)

    writer = (
        NullWriter()
        if args.no_record
        else SegmentWriter(
            args.output_dir,
            args.sample_rate,
            args.sample_width,
            segment_frames,
            sync_frames,
            session_file=args.session_file,
            record_always=args.record_always or args.session_file is None,
            min_free_bytes=int(args.min_free_gb * 1e9),
            positive_session_file=args.positive_session_file,
            positive_cooldown_seconds=args.positive_cooldown_seconds,
        )
    )
    status = ArrayStatusWriter(
        args.status_file,
        args.sample_rate,
        args.channels_in,
        args.sample_width,
        args.status_interval_seconds,
    )
    positive_recorder = PositiveSessionRecorder(
        args.positive_session_file,
        args.positive_root,
        args.sample_rate,
        args.sample_width,
        args.positive_pre_roll_seconds,
        args.positive_end_silence_seconds,
        args.positive_min_seconds,
        args.positive_max_seconds,
        args.positive_start_margin_db,
        args.positive_end_margin_db,
        args.positive_min_start_dbfs,
    )
    stdout = sys.stdout.buffer
    pending = b""

    try:
        while True:
            raw = sys.stdin.buffer.read(read_size)
            if not raw:
                break
            raw = pending + raw
            usable = len(raw) - (len(raw) % frame_size)
            pending = raw[usable:]
            usable_raw = raw[:usable]
            ch0 = extract_channel0(usable_raw, args.channels_in, args.sample_width)
            if ch0:
                # The satellite stream comes first: side outputs below may fail
                # (ENOSPC took capture down 609k times in Aug-Sep 2026) but must
                # never interrupt the audio the wake service is listening to.
                stdout.write(ch0)
                stdout.flush()
            best_effort("status file", status.observe, usable_raw)
            if not ch0:
                continue
            best_effort("positive recorder", positive_recorder.observe, ch0)
            best_effort("raw_live writer", writer.write, ch0)
    finally:
        best_effort("raw_live writer close", writer.close)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
