#!/bin/bash
# Escalate persistent HA/Dataplicity outages to a headless Codex recovery run.

set -u

REPO="${HA_CODEX_WATCHDOG_REPO:-/home/ultra/homeassistant}"
FAIL_SAFE="$REPO/scripts/ha_fail_safe.sh"
CODEX_BIN="${CODEX_BIN:-/home/linuxbrew/.linuxbrew/bin/codex}"
STATE_DIR="${HA_CODEX_WATCHDOG_STATE_DIR:-/tmp/ha_fail_safe/codex_watchdog}"
LOG="${HA_CODEX_WATCHDOG_LOG:-/tmp/ha_codex_watchdog.log}"
THRESHOLD_SEC="${HA_CODEX_WATCHDOG_THRESHOLD_SEC:-240}"
COOLDOWN_SEC="${HA_CODEX_WATCHDOG_COOLDOWN_SEC:-1800}"
DATAPLICITY_FIX_AFTER_SEC="${HA_CODEX_WATCHDOG_DATAPLICITY_FIX_AFTER_SEC:-60}"
DATAPLICITY_FIX_COOLDOWN_SEC="${HA_CODEX_WATCHDOG_DATAPLICITY_FIX_COOLDOWN_SEC:-600}"
CODEX_SANDBOX="${HA_CODEX_WATCHDOG_CODEX_SANDBOX:-danger-full-access}"
CODEX_APPROVAL="${HA_CODEX_WATCHDOG_CODEX_APPROVAL:-never}"

FAIL_SINCE="$STATE_DIR/fail_since"
LAST_CODEX="$STATE_DIR/last_codex"
LAST_DATAPLICITY_FIX="$STATE_DIR/last_dataplicity_fix"
RUN_LOCK="$STATE_DIR/codex_running"
CHECK_LOCK="$STATE_DIR/check_running"
STATUS_FILE="$STATE_DIR/last_status"

mkdir -p "$STATE_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

read_epoch_file() {
    local path="$1"
    if [ -f "$path" ]; then
        tr -dc '0-9' < "$path"
    fi
}

pid_is_running() {
    local pid="$1"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

release_run_lock() {
    rm -f "$RUN_LOCK/pid"
    rmdir "$RUN_LOCK" 2>/dev/null || true
}

acquire_run_lock() {
    local pid

    if mkdir "$RUN_LOCK" 2>/dev/null; then
        return 0
    fi

    pid="$(cat "$RUN_LOCK/pid" 2>/dev/null || true)"
    if pid_is_running "$pid"; then
        log "Codex recovery already running as PID $pid; skipping"
        return 1
    fi

    log "Removing stale Codex recovery lock"
    release_run_lock
    mkdir "$RUN_LOCK" 2>/dev/null
}

cleanup_check_lock() {
    rmdir "$CHECK_LOCK" 2>/dev/null || true
}

if ! mkdir "$CHECK_LOCK" 2>/dev/null; then
    log "Previous watchdog check still running; skipping"
    exit 0
fi
trap cleanup_check_lock EXIT

now="$(date +%s)"
ha_ok=0
dataplicity_ok=0

if "$FAIL_SAFE" check-ha >> "$LOG" 2>&1; then
    ha_ok=1
fi

if "$FAIL_SAFE" check-dataplicity >> "$LOG" 2>&1; then
    dataplicity_ok=1
fi

echo "time=$now ha_ok=$ha_ok dataplicity_ok=$dataplicity_ok" > "$STATUS_FILE"

if [ "$ha_ok" -eq 1 ] && [ "$dataplicity_ok" -eq 1 ]; then
    if [ -f "$FAIL_SINCE" ]; then
        log "HA and Dataplicity recovered; clearing outage timer"
        rm -f "$FAIL_SINCE"
    fi
    exit 0
fi

fail_since="$(read_epoch_file "$FAIL_SINCE")"
if [ -z "$fail_since" ]; then
    echo "$now" > "$FAIL_SINCE"
    fail_since="$now"
    log "Outage timer started: ha_ok=$ha_ok dataplicity_ok=$dataplicity_ok"
fi

age=$((now - fail_since))

if [ "$ha_ok" -eq 1 ] && [ "$dataplicity_ok" -eq 0 ] && [ "$age" -ge "$DATAPLICITY_FIX_AFTER_SEC" ]; then
    last_dataplicity_fix="$(read_epoch_file "$LAST_DATAPLICITY_FIX")"
    if [ -n "$last_dataplicity_fix" ] && [ $((now - last_dataplicity_fix)) -lt "$DATAPLICITY_FIX_COOLDOWN_SEC" ]; then
        log "Dataplicity down ${age}s, but soft-fix cooldown is active"
    else
        echo "$now" > "$LAST_DATAPLICITY_FIX"
        log "Dataplicity down ${age}s while local HA is healthy; running soft fix before Codex threshold"
        if "$FAIL_SAFE" fix-dataplicity >> "$LOG" 2>&1; then
            log "Dataplicity soft fix completed; rechecking tunnel"
            if "$FAIL_SAFE" check-dataplicity >> "$LOG" 2>&1; then
                dataplicity_ok=1
                echo "time=$(date +%s) ha_ok=$ha_ok dataplicity_ok=$dataplicity_ok" > "$STATUS_FILE"
                log "Dataplicity recovered after soft fix; clearing outage timer"
                rm -f "$FAIL_SINCE"
                exit 0
            fi
            log "Dataplicity still unhealthy after soft fix"
        else
            log "Dataplicity soft fix command failed"
        fi
    fi
fi

if [ "$age" -lt "$THRESHOLD_SEC" ]; then
    log "Outage age ${age}s below ${THRESHOLD_SEC}s threshold: ha_ok=$ha_ok dataplicity_ok=$dataplicity_ok"
    exit 0
fi

last_codex="$(read_epoch_file "$LAST_CODEX")"
if [ -n "$last_codex" ] && [ $((now - last_codex)) -lt "$COOLDOWN_SEC" ]; then
    log "Outage persisted ${age}s, but Codex cooldown is active"
    exit 0
fi

if [ ! -x "$CODEX_BIN" ]; then
    log "Codex binary is not executable at $CODEX_BIN"
    exit 1
fi

if ! acquire_run_lock; then
    exit 0
fi

echo "$now" > "$LAST_CODEX"
prompt_file="$STATE_DIR/prompt.$(date '+%Y%m%d_%H%M%S').txt"
codex_log="$STATE_DIR/codex.$(date '+%Y%m%d_%H%M%S').log"

cat > "$prompt_file" <<EOF
Home Assistant or Dataplicity has been continuously unhealthy for at least ${age}s.

Work autonomously in /home/ultra/homeassistant and restore service.

Current watchdog status:
- ha_ok=${ha_ok}
- dataplicity_ok=${dataplicity_ok}
- outage_started_epoch=${fail_since}
- last_status_file=${STATUS_FILE}

Follow the repo AGENTS.md safety rules exactly:
- Do not edit, delete, or overwrite .storage files directly.
- Do not touch runtime databases or backups.
- Do not use sudo/run0 unless strictly required.
- Prefer existing safe scripts: scripts/ha_fail_safe.sh status, check-ha, check-dataplicity, fix-dataplicity, fix-all.
- Use Docker commands as the current user when needed.
- If you change config/YAML/scripts, validate them and make an atomic git commit.
- Leave concise recovery notes in your final message and logs under /tmp/ha_fail_safe or /tmp/ha_codex_watchdog.log.

This is an unattended recovery task. Do not wait for human approval; diagnose, apply safe recovery steps, verify local HA and Dataplicity, and stop.
EOF

log "Launching Codex recovery after ${age}s outage; log=$codex_log"

(
    echo "${BASHPID:-$$}" > "$RUN_LOCK/pid"
    trap release_run_lock EXIT
    "$CODEX_BIN" exec -C "$REPO" -s "$CODEX_SANDBOX" -a "$CODEX_APPROVAL" \
        --output-last-message "$STATE_DIR/last_codex_message.txt" \
        - < "$prompt_file" >> "$codex_log" 2>&1
    rc=$?
    log "Codex recovery exited with status $rc"
) &

exit 0
