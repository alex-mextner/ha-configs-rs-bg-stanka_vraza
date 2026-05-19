#!/usr/bin/env bash
# increase_swap.sh — Add or expand swap file safely
# Usage: sudo ./scripts/increase_swap.sh [SIZE]
#   SIZE: swap size with unit, e.g. 16G, 32G, 8G (default: 16G)

set -euo pipefail

SIZE="${1:-16G}"
SWAP_FILE="/swap_new.img"
OLD_SWAP="/swap.img"

echo "=== Swap expansion script ==="
echo "Target new swap file: $SWAP_FILE"
echo "Target size: $SIZE"

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root or with sudo."
    echo "Usage: sudo $0 $SIZE"
    exit 1
fi

# Check current swap
echo ""
echo "Current swap status:"
swapon --show=NAME,TYPE,SIZE,USED,PRIO || true
free -h | grep -E "(Mem|Swap)"

# Check available disk space on /
AVAIL_GB=$(df -BG / | awk 'NR==2 {gsub(/G/,"",$4); print $4}')
echo ""
echo "Available disk space on /: ${AVAIL_GB}G"

# Extract numeric size for comparison
SIZE_NUM=$(echo "$SIZE" | sed 's/[GgMmKkBb]//')
SIZE_UNIT=$(echo "$SIZE" | sed 's/[0-9.]//g' | tr '[:lower:]' '[:upper:]')

if [ "$SIZE_UNIT" = "G" ] && [ "$SIZE_NUM" -ge "$AVAIL_GB" ]; then
    echo "WARNING: Requested swap size ${SIZE} is larger than available disk space ${AVAIL_GB}G."
    echo "Continuing anyway (may fail at fallocate)..."
fi

# Create swap file
echo ""
echo "Step 1/4: Creating swap file $SWAP_FILE (${SIZE})..."
if [ -f "$SWAP_FILE" ]; then
    echo "File $SWAP_FILE already exists. Checking if it's active..."
    if swapon --show=NAME | grep -q "^$SWAP_FILE"; then
        echo "WARNING: $SWAP_FILE is already active. Aborting to avoid duplicate."
        exit 1
    fi
    echo "Removing existing inactive file..."
    rm -f "$SWAP_FILE"
fi

fallocate -l "$SIZE" "$SWAP_FILE"
chmod 600 "$SWAP_FILE"
mkswap "$SWAP_FILE"
echo "  OK: Swap file created and formatted."

# Activate
echo ""
echo "Step 2/4: Activating swap..."
swapon "$SWAP_FILE"
echo "  OK: Swap activated."

# Verify
echo ""
echo "Step 3/4: Verifying..."
swapon --show=NAME,TYPE,SIZE,USED,PRIO
echo ""
free -h | grep -E "(Mem|Swap)"

# Update fstab
echo ""
echo "Step 4/4: Updating /etc/fstab..."
if grep -q "^$SWAP_FILE" /etc/fstab; then
    echo "  $SWAP_FILE already in fstab."
else
    echo "$SWAP_FILE    none    swap    sw    0    0" >> /etc/fstab
    echo "  OK: Added $SWAP_FILE to /etc/fstab."
fi

# Optionally disable old small swap
echo ""
if [ -f "$OLD_SWAP" ] && swapon --show=NAME | grep -q "^$OLD_SWAP"; then
    echo "Old swap $OLD_SWAP is still active."
    read -r -p "Disable and remove old $OLD_SWAP? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        swapoff "$OLD_SWAP"
        rm -f "$OLD_SWAP"
        sed -i "/swap.img/d" /etc/fstab
        echo "  OK: Old swap removed."
    else
        echo "  Kept old swap. You can remove it later with:"
        echo "    sudo swapoff $OLD_SWAP && sudo rm $OLD_SWAP"
    fi
fi

# Recommend zram
echo ""
echo "=== Done ==="
echo "New swap is active. Current status:"
free -h | grep Swap

echo ""
echo "TIP: Consider enabling zram for compressed RAM swap:"
echo "  sudo apt install zram-tools   # or configure manually"
echo "This speeds up swap operations when RAM is under pressure."
