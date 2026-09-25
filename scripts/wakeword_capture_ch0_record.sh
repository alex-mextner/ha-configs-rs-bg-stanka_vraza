#!/usr/bin/env sh
# ReSpeaker capture for wyoming-satellite: ch0 goes to the satellite on stdout,
# and wakeword_channel0_tee.py records 60 s segments to raw_live/ only while a
# noise session is active in $SESSION_FILE (start/stop it with
# scripts/wakeword_noise_watchdog.py start|stop, no container restart needed).
set -eu

DEVICE="${WAKEWORD_DEVICE:-plughw:CARD=ArrayUAC10,DEV=0}"
RATE="${WAKEWORD_RATE:-16000}"
CHANNELS="${WAKEWORD_CHANNELS:-6}"
RAW_DIR="${WAKEWORD_RAW_DIR:-/dataset/raw_live}"
SESSION_FILE="${WAKEWORD_SESSION_FILE:-/dataset/raw_live_session.json}"
STATUS_FILE="${WAKEWORD_STATUS_FILE:-/dataset/wakeword_array_status.json}"
POSITIVE_SESSION_FILE="${WAKEWORD_POSITIVE_SESSION_FILE:-/dataset/positive_sessions/current.json}"
POSITIVE_ROOT="${WAKEWORD_POSITIVE_ROOT:-/dataset/positives/real_user}"
SEGMENT_SECONDS="${WAKEWORD_SEGMENT_SECONDS:-60}"
SYNC_SECONDS="${WAKEWORD_SYNC_SECONDS:-5}"
MIN_FREE_GB="${WAKEWORD_MIN_FREE_GB:-30}"
RESTART_DELAY_SECONDS="${WAKEWORD_RESTART_DELAY_SECONDS:-2}"
RECORD_ALWAYS=""
if [ "${WAKEWORD_RECORD_AFTER_COMPLETE:-0}" = "1" ]; then
    RECORD_ALWAYS="--record-always"
fi

mkdir -p "$RAW_DIR"

while :; do
    echo "[wakeword-recorder] starting arecord device=$DEVICE rate=$RATE channels=$CHANNELS segment=${SEGMENT_SECONDS}s session=$SESSION_FILE" >&2
    arecord -D "$DEVICE" -r "$RATE" -c "$CHANNELS" -f S16_LE -t raw \
        | python3 /app/sounds/wakeword_channel0_tee.py \
            --output-dir "$RAW_DIR" \
            --session-file "$SESSION_FILE" \
            $RECORD_ALWAYS \
            --min-free-gb "$MIN_FREE_GB" \
            --status-file "$STATUS_FILE" \
            --positive-session-file "$POSITIVE_SESSION_FILE" \
            --positive-root "$POSITIVE_ROOT" \
            --sample-rate "$RATE" \
            --channels-in "$CHANNELS" \
            --segment-seconds "$SEGMENT_SECONDS" \
            --sync-seconds "$SYNC_SECONDS"
    status="$?"
    echo "[wakeword-recorder] capture pipeline exited status=$status; restarting in ${RESTART_DELAY_SECONDS}s" >&2
    sleep "$RESTART_DELAY_SECONDS"
done
