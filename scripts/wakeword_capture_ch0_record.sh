#!/usr/bin/env sh
set -eu

DEVICE="${WAKEWORD_DEVICE:-plughw:2,0}"
RATE="${WAKEWORD_RATE:-16000}"
CHANNELS="${WAKEWORD_CHANNELS:-6}"
RAW_DIR="${WAKEWORD_RAW_DIR:-/dataset/raw_live}"
SEGMENT_SECONDS="${WAKEWORD_SEGMENT_SECONDS:-60}"
SYNC_SECONDS="${WAKEWORD_SYNC_SECONDS:-5}"
RESTART_DELAY_SECONDS="${WAKEWORD_RESTART_DELAY_SECONDS:-2}"

mkdir -p "$RAW_DIR"

while :; do
    echo "[wakeword-recorder] starting arecord device=$DEVICE rate=$RATE channels=$CHANNELS segment=${SEGMENT_SECONDS}s" >&2
    arecord -D "$DEVICE" -r "$RATE" -c "$CHANNELS" -f S16_LE -t raw \
        | python3 /app/sounds/wakeword_channel0_tee.py \
            --output-dir "$RAW_DIR" \
            --sample-rate "$RATE" \
            --channels-in "$CHANNELS" \
            --segment-seconds "$SEGMENT_SECONDS" \
            --sync-seconds "$SYNC_SECONDS"
    status="$?"
    echo "[wakeword-recorder] capture pipeline exited status=$status; restarting in ${RESTART_DELAY_SECONDS}s" >&2
    sleep "$RESTART_DELAY_SECONDS"
done
