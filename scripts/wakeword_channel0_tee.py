#!/usr/bin/env python3
"""Tee ReSpeaker 6-channel raw PCM into channel-0 stdout and WAV segments.

The satellite still receives the same 16 kHz mono S16_LE stream on stdout.
In parallel, this writes the channel-0 stream into dated WAV files for real
home-noise wake word evaluation and hard-negative mining.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import wave
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels-in", type=int, default=6)
    parser.add_argument("--sample-width", type=int, default=2)
    parser.add_argument("--segment-seconds", type=int, default=600)
    parser.add_argument("--frames-per-read", type=int, default=1024)
    return parser.parse_args()


class SegmentWriter:
    def __init__(self, output_dir: Path, sample_rate: int, sample_width: int, segment_frames: int) -> None:
        self.output_dir = output_dir
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.segment_frames = segment_frames
        self.frames_written = 0
        self.current: wave.Wave_write | None = None

    def _open_next(self) -> None:
        now = dt.datetime.now()
        day_dir = self.output_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / f"{now.strftime('%H%M%S')}.wav"
        self.current = wave.open(str(path), "wb")
        self.current.setnchannels(1)
        self.current.setsampwidth(self.sample_width)
        self.current.setframerate(self.sample_rate)
        self.frames_written = 0
        print(f"[wakeword-recorder] writing {path}", file=sys.stderr, flush=True)

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
            self.current.writeframes(chunk)
            self.frames_written += take_frames
            offset += take_bytes

    def close(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None


def extract_channel0(raw: bytes, channels_in: int, sample_width: int) -> bytes:
    frame_size = channels_in * sample_width
    usable = len(raw) - (len(raw) % frame_size)
    if usable <= 0:
        return b""
    frames = memoryview(raw[:usable])
    return b"".join(frames[i : i + sample_width] for i in range(0, usable, frame_size))


def main() -> int:
    args = parse_args()
    frame_size = args.channels_in * args.sample_width
    read_size = args.frames_per_read * frame_size
    segment_frames = args.sample_rate * args.segment_seconds

    writer = SegmentWriter(args.output_dir, args.sample_rate, args.sample_width, segment_frames)
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
            ch0 = extract_channel0(raw[:usable], args.channels_in, args.sample_width)
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
