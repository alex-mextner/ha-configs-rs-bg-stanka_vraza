#!/usr/bin/env bash
# Syncs the custom_components/<domain> directory for HACS-tracked submodule
# integrations from their submodule source, as a plain rsync copy (NOT a
# symlink). A symlink lets HACS's zip extractall() write straight through
# into the submodule's git working tree on every Update click, dirtying it
# outside git. Run this after every submodule git update, before the
# storage-sync and container-restart step in AGENTS.md.
set -euo pipefail

HA_ROOT="/home/ultra/homeassistant"
cd "$HA_ROOT"

# submodule_dir:custom_components_domain
MAP=(
  "xtend_tuya:xtend_tuya"
  "hass-mcp-server:mcp_server_http_transport"
  "YandexStation:yandex_station"
  "dataplicity:dataplicity"
  "home-generative-agent:home_generative_agent"
  "ha_washdata:ha_washdata"
  "ha_creality_ws:ha_creality_ws"
)

target="${1:-}"

sync_one() {
  local submodule="$1" domain="$2"
  local src="$HA_ROOT/submodules/$submodule/custom_components/$domain"
  local dst="$HA_ROOT/custom_components/$domain"
  if [ ! -d "$src" ]; then
    echo "SKIP $domain: source $src does not exist" >&2
    return 1
  fi
  mkdir -p "$dst"
  rsync -a --delete "$src/" "$dst/"
  echo "synced $domain <- submodules/$submodule"
}

if [ -n "$target" ]; then
  found=0
  for entry in "${MAP[@]}"; do
    submodule="${entry%%:*}"
    domain="${entry##*:}"
    if [ "$submodule" = "$target" ] || [ "$domain" = "$target" ]; then
      sync_one "$submodule" "$domain"
      found=1
    fi
  done
  if [ "$found" = 0 ]; then
    echo "unknown target: $target (not in MAP)" >&2
    exit 1
  fi
else
  for entry in "${MAP[@]}"; do
    submodule="${entry%%:*}"
    domain="${entry##*:}"
    sync_one "$submodule" "$domain"
  done
fi
