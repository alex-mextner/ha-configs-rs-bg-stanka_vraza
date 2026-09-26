#!/usr/bin/env bash
# music-accounts: Music Assistant accounts per person and guest (aisis#17).
#
#   ssh root@home music-accounts list
#   ssh root@home music-accounts assign --person lena --instance yandex_music--XXXXXXXX
#   ssh root@home music-accounts rename --person ultra Alex
#   ssh root@home music-accounts sync [--dry-run]
#   ssh root@home music-accounts expire            (hourly from /etc/cron.d/music-accounts)
#
# Adding / refreshing an account: ytm-cookie and yandex-music-token (same WHO options).
# The logic is scripts/ma_accounts.py, run inside the HA container with the HA integration's
# MA token. Commands that change MA hold /home/ultra/.ma-maintenance.lock (shared with other
# agents working on MA); a lock held by someone else makes us wait (cron: skip this run).
set -euo pipefail
LOCK=/home/ultra/.ma-maintenance.lock
CONTAINER=homeassistant-homeassistant-1

mutating=1
case "${1:-}" in list|"") mutating=0 ;; esac
for a in "$@"; do [ "$a" = "--dry-run" ] && mutating=0; done

if [ "$mutating" = 1 ]; then
  waited=0
  while ! ( set -C; printf 'owner=music-accounts pid=%s since=%s cmd=%s\n' "$$" "$(date -Is)" "$*" > "$LOCK" ) 2>/dev/null; do
    if [ "${MA_LOCK_SKIP:-}" = 1 ]; then
      echo "MA maintenance lock is held ($(cat "$LOCK" 2>/dev/null)); skipping this run." >&2
      exit 0
    fi
    if [ "$waited" -ge 600 ]; then
      echo "MA is still locked for maintenance ($(cat "$LOCK" 2>/dev/null)). Try again later." >&2
      exit 2
    fi
    [ "$waited" = 0 ] && echo "Music Assistant is being maintained ($(cat "$LOCK" 2>/dev/null)); waiting..." >&2
    sleep 20; waited=$((waited + 20))
  done
  trap 'rm -f "$LOCK"' EXIT
fi

MA_TOKEN="$(python3 -c 'import json; e=[e for e in json.load(open("/home/ultra/homeassistant/.storage/core.config_entries"))["data"]["entries"] if e["domain"]=="music_assistant"][0]; print(e["data"]["token"])')"
export MA_TOKEN MA_SECRET="${MA_SECRET:-}"
docker exec -i -e MA_TOKEN -e MA_SECRET "$CONTAINER" python3 /config/scripts/ma_accounts.py "$@"
