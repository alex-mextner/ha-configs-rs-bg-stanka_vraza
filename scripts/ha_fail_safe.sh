#!/bin/bash
# HA Fail-Safe Manager
# Usage: ./ha_fail_safe.sh [action]
# Actions: check, fix-orphaned, restart, status

set -e

LOG_DIR="/tmp/ha_fail_safe"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d_%H%M%S).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

DATAPLICITY_URL="${DATAPLICITY_URL:-https://spry-gazelle-4693.dataplicity.io/}"

check_ha() {
    local url="${HA_URL:-http://localhost:8123}"
    local response=$(curl -s --connect-timeout 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo "000")
    if [ "$response" = "200" ]; then
        log "✓ HA is accessible (HTTP $response)"
        return 0
    else
        log "✗ HA is NOT accessible (HTTP $response)"
        return 1
    fi
}

check_dataplicity() {
    local body=$(curl -s --connect-timeout 10 -m 15 "$DATAPLICITY_URL" 2>/dev/null || echo "")
    if [ -z "$body" ]; then
        log "✗ Dataplicity tunnel did not respond (empty body)"
        return 1
    fi
    if echo "$body" | grep -qi "device offline"; then
        log "✗ Dataplicity tunnel reports 'Device offline'"
        return 1
    fi
    if echo "$body" | grep -qi "wormhole"; then
        log "✗ Dataplicity tunnel shows wormhole page (not proxying to HA)"
        return 1
    fi
    if ! echo "$body" | grep -qi "home.assistant\|home-assistant"; then
        log "✗ Dataplicity tunnel response does not contain Home Assistant content"
        return 1
    fi
    log "✓ Dataplicity tunnel is proxying to HA correctly"
    return 0
}

fix_dataplicity() {
    log "Attempting to fix dataplicity tunnel (will restart HA container)..."
    restart_ha
    local result=$?
    if [ $result -eq 0 ]; then
        log "Waiting 30s for dataplicity m2m to reconnect..."
        sleep 30
        if check_dataplicity; then
            log "✓ Dataplicity tunnel recovered after restart"
            return 0
        else
            log "✗ Dataplicity tunnel still offline after restart"
            return 1
        fi
    fi
    return 1
}

fix_orphaned() {
    local registry="/home/ultra/homeassistant/.storage/core.entity_registry"
    local backup="$LOG_DIR/entity_registry.backup.$(date +%Y%m%d_%H%M%S)"

    if [ ! -f "$registry" ]; then
        log "Entity registry not found"
        return 1
    fi

    log "Creating backup: $backup"
    cp "$registry" "$backup"

    log "Finding orphaned TTS entities..."

    python3 << 'PYEOF'
import json
import sys

registry_path = "/home/ultra/homeassistant/.storage/core.entity_registry"
with open(registry_path, 'r') as f:
    data = json.load(f)

entities = data["data"]["entities"]
orphaned_tts = [e for e in entities if e.get("entity_id", "").startswith("tts.") and e.get("orphaned_timestamp")]

if orphaned_tts:
    print(f"Found {len(orphaned_tts)} orphaned TTS entities:")
    for e in orphaned_tts:
        print(f"  - {e['entity_id']} (unique_id: {e.get('unique_id')}, config_entry_id: {e.get('config_entry_id')})")

    # Remove orphaned entries that have no config_entry_id
    before = len(entities)
    entities = [e for e in entities if not (e.get("entity_id", "").startswith("tts.") and e.get("orphaned_timestamp") and not e.get("config_entry_id"))]
    after = len(entities)

    if before != after:
        data["data"]["entities"] = entities
        with open(registry_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Removed {before - after} orphaned TTS entities")
        print("SUCCESS")
    else:
        print("No orphaned entities to remove")
else:
    print("No orphaned TTS entities found")
PYEOF

    local result=$?
    if [ $result -eq 0 ]; then
        log "Orphaned entities cleaned successfully"
        return 0
    else
        log "Failed to clean orphaned entities"
        return 1
    fi
}

restart_ha() {
    local container="${HA_CONTAINER:-homeassistant-homeassistant-1}"

    log "Checking HA before restart..."
    check_ha || log "HA already down, proceeding with restart"

    log "Restarting container: $container"
    docker restart "$container" 2>&1 | tee -a "$LOG"

    log "Waiting for HA to come back (max 120s)..."
    local count=0
    while [ $count -lt 60 ]; do
        if check_ha; then
            log "✓ HA is back online after restart"
            return 0
        fi
        sleep 2
        count=$((count + 1))
        echo -n "."
    done

    log "✗ HA failed to come back after restart"
    return 1
}

status_report() {
    echo "=== HA Fail-Safe Status Report ==="
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    echo "HA Accessibility:"
    check_ha && echo "Status: ONLINE" || echo "Status: OFFLINE"
    echo ""

    echo "Dataplicity Tunnel:"
    check_dataplicity && echo "Status: ONLINE" || echo "Status: OFFLINE"
    echo ""

    echo "Orphaned Entities:"
    python3 << 'PYEOF'
import json
registry_path = "/home/ultra/homeassistant/.storage/core.entity_registry"
try:
    with open(registry_path, 'r') as f:
        data = json.load(f)
    entities = data["data"]["entities"]
    orphaned = [e for e in entities if e.get("orphaned_timestamp")]
    print(f"  Total orphaned: {len(orphaned)}")
    tts_orphaned = [e for e in orphaned if e.get("entity_id", "").startswith("tts.")]
    if tts_orphaned:
        print(f"  TTS orphaned: {len(tts_orphaned)}")
        for e in tts_orphaned:
            print(f"    - {e['entity_id']}")
except Exception as e:
    print(f"  Error: {e}")
PYEOF
    echo ""

    echo "TTS Pipeline Status:"
    python3 << 'PYEOF'
import json
pipeline_path = "/home/ultra/homeassistant/.storage/assist_pipeline.pipelines"
registry_path = "/home/ultra/homeassistant/.storage/core.entity_registry"

try:
    with open(pipeline_path, 'r') as f:
        pipelines = json.load(f)["data"]["items"]
    with open(registry_path, 'r') as f:
        registry = json.load(f)["data"]["entities"]

    for p in pipelines:
        tts = p.get("tts_engine")
        if tts:
            entity = next((e for e in registry if e["entity_id"] == tts), None)
            if entity:
                status = "✓ OK" if entity.get("config_entry_id") and not entity.get("orphaned_timestamp") else "✗ BROKEN"
                print(f"  {p['name']}: {tts} [{status}]")
            else:
                print(f"  {p['name']}: {tts} [✗ NOT FOUND]")
        else:
            print(f"  {p['name']}: (no TTS configured)")
except Exception as e:
    print(f"  Error: {e}")
PYEOF
    echo ""

    echo "Container Status:"
    docker ps --filter name=homeassistant-homeassistant --format "{{.Status}}"
}

case "${1:-status}" in
    check)
        check_ha
        check_dataplicity
        ;;
    fix-orphaned)
        fix_orphaned
        ;;
    fix-dataplicity)
        fix_dataplicity
        ;;
    fix-all)
        log "Running full fix cycle..."
        fix_orphaned || true
        if ! check_dataplicity; then
            fix_dataplicity || true
        fi
        ;;
    restart)
        restart_ha
        ;;
    status)
        status_report
        ;;
    *)
        echo "Usage: $0 {check|fix-orphaned|fix-dataplicity|fix-all|restart|status}"
        exit 1
        ;;
esac