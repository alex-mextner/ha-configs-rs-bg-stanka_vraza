#!/bin/bash
# Wrapper for cron - runs check and auto-fixes if needed
# Anti-flap: skip restart if HA container started < 10 minutes ago
LOG=/tmp/ha_check.log
UPTIME_SEC=$(docker inspect --format='{{.State.StartedAt}}' homeassistant-homeassistant-1 2>/dev/null | xargs -I{} python3 -c "import datetime,sys; d=datetime.datetime.fromisoformat('{}'.replace('Z','+00:00')); print(int((datetime.datetime.now(datetime.timezone.utc)-d).total_seconds()))")
if [ -n "$UPTIME_SEC" ] && [ "$UPTIME_SEC" -lt 600 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] HA container up only ${UPTIME_SEC}s (< 10 min), skipping check to prevent restart loop" >> "$LOG"
    exit 0
fi

if ! /home/ultra/homeassistant/scripts/ha_fail_safe.sh check-ha >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Local HA check failed, running fix-all..." >> "$LOG"
    /home/ultra/homeassistant/scripts/ha_fail_safe.sh fix-all >> "$LOG" 2>&1
    exit $?
fi

if ! /home/ultra/homeassistant/scripts/ha_fail_safe.sh check-dataplicity >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dataplicity check failed while local HA is online; running dataplicity fix..." >> "$LOG"
    /home/ultra/homeassistant/scripts/ha_fail_safe.sh fix-dataplicity >> "$LOG" 2>&1
    exit $?
fi
