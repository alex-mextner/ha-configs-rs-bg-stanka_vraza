#!/usr/bin/env bash
# safe_swapoff.sh — Safely disable a swap file with progress bar
# Usage: sudo ./scripts/safe_swapoff.sh [SWAP_FILE]
#   SWAP_FILE: path to swap file (default: /swap.img)
#
# SAFETY: Checks MemAvailable vs swap used before proceeding.
# If swap contains more data than 50% of available RAM, aborts.

set -euo pipefail

SWAP_FILE="${1:-/swap.img}"

echo "=== Safe Swap Off Script ==="
echo "Target swap file: $SWAP_FILE"

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root. Usage: sudo $0 $SWAP_FILE"
    exit 1
fi

# Check if swap file exists and is active
if ! swapon --show=NAME | grep -q "^$SWAP_FILE"; then
    echo "INFO: $SWAP_FILE is not active. Nothing to do."
    if [ -f "$SWAP_FILE" ]; then
        read -r -p "Remove inactive file $SWAP_FILE? [y/N] " confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            rm -f "$SWAP_FILE"
            sed -i "/$(basename $SWAP_FILE)/d" /etc/fstab
            echo "OK: File removed and fstab cleaned."
        fi
    fi
    exit 0
fi

# Get swap used in MB
SWAP_USED_KB=$(swapon --bytes --show=USED,NAME | awk -v f="$SWAP_FILE" '$2==f {print $1}')
SWAP_USED_MB=$((SWAP_USED_KB / 1024 / 1024))

# Get available RAM in MB
MEM_AVAILABLE_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
MEM_AVAILABLE_MB=$((MEM_AVAILABLE_KB / 1024))

echo ""
echo "Current status:"
echo "  Swap file:     $SWAP_FILE"
echo "  Swap used:     ${SWAP_USED_MB} MB"
echo "  RAM available: ${MEM_AVAILABLE_MB} MB"
echo ""

# Safety check: need at least 2× swap used as available RAM (very conservative)
SAFETY_MARGIN_MB=$((SWAP_USED_MB * 2))

if [ "$MEM_AVAILABLE_MB" -lt "$SAFETY_MARGIN_MB" ]; then
    echo "======================================================================"
    echo "ABORT: Not enough RAM to safely disable swap."
    echo "  Swap used:     ${SWAP_USED_MB} MB"
    echo "  RAM available: ${MEM_AVAILABLE_MB} MB"
    echo "  Required (2x): ${SAFETY_MARGIN_MB} MB"
    echo ""
    echo "Options:"
    echo "  1. Close some applications to free RAM, then re-run."
    echo "  2. Wait for system to idle (cache may drop)."
    echo "  3. Reboot — new swap will be active, old ignored."
    echo "======================================================================"
    exit 1
fi

echo "SAFETY CHECK PASSED: ${MEM_AVAILABLE_MB} MB available > ${SAFETY_MARGIN_MB} MB required."
echo ""
read -r -p "Proceed with swapoff and removal? [y/N] " confirm
if ! [[ "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Progress bar function
show_progress() {
    local target_swap="$1"
    local start_mb="$2"
    local pid="$3"
    local width=40

    echo ""
    echo "Disabling swap $target_swap (started with ${start_mb} MB)..."
    echo ""

    while kill -0 "$pid" 2>/dev/null; do
        local current_kb=$(swapon --bytes --show=USED,NAME 2>/dev/null | awk -v f="$target_swap" '$2==f {print $1}')
        if [ -z "$current_kb" ]; then
            current_kb=0
        fi
        local current_mb=$((current_kb / 1024 / 1024))
        local done_mb=$((start_mb - current_mb))

        if [ "$start_mb" -gt 0 ]; then
            local pct=$((done_mb * 100 / start_mb))
            if [ "$pct" -gt 100 ]; then pct=100; fi
        else
            local pct=100
        fi

        local filled=$((pct * width / 100))
        local empty=$((width - filled))
        local bar=""
        for ((i=0; i<filled; i++)); do bar="${bar}#"; done
        for ((i=0; i<empty; i++)); do bar="${bar}-"; done

        printf "\r[%s] %3d%%  %4d/%4d MB moved to RAM" "$bar" "$pct" "$done_mb" "$start_mb"
        sleep 0.5
    done

    # Final state
    printf "\r[%s] %3d%%  %4d/%4d MB moved to RAM\n" "$(printf '%*s' "$width" '' | tr ' ' '#')" 100 "$start_mb" "$start_mb"
    echo ""
}

# Run swapoff in background
swapoff "$SWAP_FILE" &
SO_PID=$!

# Show progress while swapoff runs
show_progress "$SWAP_FILE" "$SWAP_USED_MB" "$SO_PID"

# Wait for swapoff to complete (should already be done)
wait $SO_PID || true

# Verify
echo "Verifying..."
if swapon --show=NAME | grep -q "^$SWAP_FILE"; then
    echo "WARNING: $SWAP_FILE is still active (unexpected)."
    exit 1
fi

# Remove file and clean fstab
rm -f "$SWAP_FILE"
# Escape dots for sed
ESCAPED=$(basename "$SWAP_FILE" | sed 's/\./\\./g')
sed -i "/$ESCAPED/d" /etc/fstab
echo "OK: $SWAP_FILE disabled, removed, and fstab cleaned."

echo ""
echo "Final swap status:"
swapon --show=NAME,TYPE,SIZE,USED,PRIO
echo ""
free -h | grep -E "(Mem|Swap)"
