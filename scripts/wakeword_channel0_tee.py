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
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels-in", type=int, default=6)
    parser.add_argument("--sample-width", type=int, default=2)
    parser.add_argument("--segment-seconds", type=int, default=600)
    parser.add_argument("--frames-per-read", type=int, default=1024)
    parser.add_argument("--sync-seconds", type=int, default=5)
    return parser.parse_args()


class SegmentWriter:
    def __init__(
        self,
        output_dir: Path,
        sample_rate: int,
        sample_width: int,
        segment_frames: int,
        sync_frames: int,
    ) -> None:
        self.output_dir = output_dir
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.segment_frames = segment_frames
        self.sync_frames = sync_frames
        self.frames_written = 0
        self.frames_since_sync = 0
        self.current = None

    def _open_next(self) -> None:
        now = dt.datetime.now()
        day_dir = self.output_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / f"{now.strftime('%H%M%S_%f')}.wav"
        self.current = path.open("w+b")
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
        offset = 0
        frame_bytes = self.sample_width
        total_frames = len(data) // frame_bytes
        while offset < len(data):
            if self.current is None or self.frames_written >= self.segment_frames:
                self.close()
                self._open_next()

            available_frames = self.segment_frames - self.frames_written
            take_frames = min(available_frames, total_frames - (offset // frame_bytes))
            take_bytes = take_frames * frame_bytes
            chunk = data[offset : offset + take_bytes]
            self.current.write(chunk)
            self.frames_written += take_frames
            self.frames_since_sync += take_frames
            offset += take_bytes
            if self.frames_since_sync >= self.sync_frames:
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
        else SegmentWriter(args.output_dir, args.sample_rate, args.sample_width, segment_frames, sync_frames)
    )
    status = ArrayStatusWriter(
        args.status_file,
        args.sample_rate,
        args.channels_in,
        args.sample_width,
        args.status_interval_seconds,
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
            status.observe(usable_raw)
            ch0 = extract_channel0(usable_raw, args.channels_in, args.sample_width)
            if not ch0:
                continue
            stdout.write(ch0)
            stdout.flush()
            writer.write(ch0)
    finally:
        writer.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
