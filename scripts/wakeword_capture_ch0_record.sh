#!/usr/bin/env sh
set -eu

DEVICE="${WAKEWORD_DEVICE:-plughw:2,0}"
RATE="${WAKEWORD_RATE:-16000}"
CHANNELS="${WAKEWORD_CHANNELS:-6}"
RAW_DIR="${WAKEWORD_RAW_DIR:-/dataset/raw_live}"
SEGMENT_SECONDS="${WAKEWORD_SEGMENT_SECONDS:-600}"

mkdir -p "$RAW_DIR"

arecord -D "$DEVICE" -r "$RATE" -c "$CHANNELS" -f S16_LE -t raw \
    | python3 /app/sounds/wakeword_channel0_tee.py \
        --output-dir "$RAW_DIR" \
        --sample-rate "$RATE" \
        --channels-in "$CHANNELS" \
        --segment-seconds "$SEGMENT_SECONDS"
