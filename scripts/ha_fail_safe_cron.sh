#!/bin/bash
# Wrapper for cron - runs check and auto-fixes if needed
LOG=/tmp/ha_check.log
if ! /home/ultra/homeassistant/scripts/ha_fail_safe.sh check >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Issues detected, running fix-all..." >> "$LOG"
    /home/ultra/homeassistant/scripts/ha_fail_safe.sh fix-all >> "$LOG" 2>&1
fi
