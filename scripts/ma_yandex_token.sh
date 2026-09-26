#!/usr/bin/env bash
# Add (or refresh) a person's Yandex Music account in Music Assistant (aisis#17).
#
#   ssh -t root@home yandex-music-token --person lena --device    # code on ya.ru/device, no token
#   ssh -t root@home yandex-music-token --person lena             # paste a music token (hidden)
#   ssh -t root@home yandex-music-token --guest "Вася" --days 2 --device
#   ssh root@home yandex-music-token --person lena --dry-run      # MA opens + aborts the flow
#   ssh -t root@home yandex-music-token                           # household default account
#
# --device: MA's own Yandex Passport device login; the person opens the address shown and
# enters the code in THEIR Yandex account (MA keeps the session and refreshes it).
# Otherwise the token is read with hidden input, passed to MA's setup flow, never stored here.
set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"
args=() device=0 dry=0 who=0
for a in "$@"; do
  case "$a" in --device) device=1 ;; --dry-run) dry=1 ;; --person|--guest|--default) who=1 ;; esac
  args+=("$a")
done
[ "$who" = 1 ] || args+=(--default)
MA_SECRET=""
if [ "$device" = 0 ] && [ "$dry" = 0 ]; then
  if [ -t 0 ]; then read -rsp "Yandex Music token (paste, Enter): " MA_SECRET; echo; else MA_SECRET="$(cat)"; fi
  MA_SECRET="$(printf "%s" "$MA_SECRET" | tr -d " \r\n")"
  if [ "${#MA_SECRET}" -lt 20 ]; then
    echo "That does not look like a Yandex Music token (or use --device)." >&2; exit 1
  fi
fi
export MA_SECRET
exec "$here/ma_accounts.sh" add yandex_music "${args[@]}"
