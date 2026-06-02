#!/usr/bin/env bash
set -euo pipefail

LINE="*/15 * * * * cd /home/ultra/homeassistant && scripts/wakeword_noise_watchdog.py check >> /tmp/wakeword_noise_watchdog.log 2>&1"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

crontab -l 2>/dev/null | grep -v 'scripts/wakeword_noise_watchdog.py check' > "$TMP" || true
printf '%s\n' "$LINE" >> "$TMP"
crontab "$TMP"
crontab -l | grep 'scripts/wakeword_noise_watchdog.py check'
