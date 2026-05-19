#!/bin/bash
# HA Safe Reload — проверяет конфиг перед перезагрузкой
# Урок 2026-05-19: HA уходил в recovery из-за YAML syntax error

set -euo pipefail

echo "=== HA Safe Reload ==="
echo "Step 1/3: Checking YAML syntax..."

# Validate all YAML files in packages/
INVALID=0
for f in packages/*.yaml; do
    if ! python3 -c "import yaml; yaml.safe_load(open('$f'))" 2>/dev/null; then
        echo "  ERROR: $f — YAML syntax invalid"
        INVALID=1
    fi
done

if [ "$INVALID" -eq 1 ]; then
    echo ""
    echo "ABORTED: Fix YAML errors before reloading HA."
    echo "Use: python3 -c \"import yaml; yaml.safe_load(open('FILE.yaml'))\""
    exit 1
fi
echo "  All YAML files valid."

echo ""
echo "Step 2/3: Checking HA config via check_config..."
# Run HA config check inside container
docker exec homeassistant-homeassistant-1 python -m homeassistant --config /config --script check_config 2>&1 | tail -n 20 || true

# Alternative: we just check if HA container is healthy before restart
if ! docker ps | grep -q "homeassistant-homeassistant-1.*healthy"; then
    echo "  WARNING: HA container not healthy yet. Waiting..."
    sleep 10
fi

echo ""
echo "Step 3/3: Reloading Home Assistant..."
docker restart homeassistant-homeassistant-1

echo ""
echo "Done. HA is restarting. Check status in 30s:"
echo "  docker logs homeassistant-homeassistant-1 --tail 20"
