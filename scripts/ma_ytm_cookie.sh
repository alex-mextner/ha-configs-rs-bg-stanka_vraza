#!/usr/bin/env bash
# Set (or refresh) a YouTube Music cookie in Music Assistant; creates the account on first use.
#
#   ssh -t root@home ytm-cookie                        # household default account (as before)
#   ssh -t root@home ytm-cookie --person lena          # Lena's own account (aisis#17)
#   ssh -t root@home ytm-cookie --guest "Вася" --days 2
#   ssh root@home ytm-cookie --person lena --dry-run   # MA opens + aborts the setup flow
#   ... | ssh root@home ytm-cookie --person lena       # or pipe the cookie
#
# The cookie comes from the "YT Music -> Music Assistant" Chrome extension (one click copies the
# music.youtube.com Cookie header) in the browser where THAT person is signed in. It is sent to
# MA's own setup flow over the local API with the HA integration's MA token (Premium is checked
# there); MA stores setup data encrypted. Nothing is written to disk or printed here.
# Accounts, MA users and the person mapping: scripts/ma_accounts.py (music-accounts).
set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"
args=() dry=0 who=0
for a in "$@"; do
  case "$a" in --dry-run) dry=1 ;; --person|--guest|--default) who=1 ;; esac
  args+=("$a")
done
[ "$who" = 1 ] || args+=(--default)
MA_SECRET=""
if [ "$dry" = 0 ]; then
  if [ -t 0 ]; then read -rsp "YouTube Music cookie (paste, Enter): " MA_SECRET; echo; else MA_SECRET="$(cat)"; fi
  MA_SECRET="$(printf "%s" "$MA_SECRET" | tr -d "\r\n" | sed -E "s/^[Cc]ookie:[[:space:]]*//")"
  if [ "${#MA_SECRET}" -lt 100 ] || ! printf "%s" "$MA_SECRET" | grep -qE "(SAPISID|__Secure-3PAPISID)="; then
    echo "This does not look like a signed-in music.youtube.com cookie (no SAPISID)." >&2
    exit 1
  fi
fi
export MA_SECRET
exec "$here/ma_accounts.sh" add ytmusic "${args[@]}"
