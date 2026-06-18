#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${HA_CONTAINER:-homeassistant-homeassistant-1}"

usage() {
    cat <<'EOF'
Usage: scripts/ha_validate_lovelace.sh [FILE ...]

Validate Lovelace YAML dashboards and local custom-card resources.

With files, validates only staged/changed dashboard-related files passed by the
pre-commit hook. With no files, validates all YAML dashboards declared in
configuration.yaml.

Set HA_CONTAINER to override the container name.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "ERROR: HA container '$CONTAINER' is not available" >&2
    exit 2
fi

docker exec "$CONTAINER" python3 /config/scripts/ha_validate_lovelace.py "$@"
