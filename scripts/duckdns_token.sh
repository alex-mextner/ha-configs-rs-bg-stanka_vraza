#!/usr/bin/env bash
# Store a regenerated DuckDNS token in .env and restart the updater; never echoes the token.
#
#   ssh -t root@home duckdns-token        # paste the token from duckdns.org (hidden), Enter
set -euo pipefail
cd /home/ultra/homeassistant
if [ -t 0 ]; then
  read -rsp "DuckDNS token (paste, Enter): " TOKEN; echo
else
  TOKEN="$(cat)"
fi
TOKEN="$(printf "%s" "$TOKEN" | tr -d "[:space:]")"
if ! printf "%s" "$TOKEN" | grep -qiE "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"; then
  echo "This does not look like a DuckDNS token (expected a UUID)." >&2
  exit 1
fi
export TOKEN
python3 - <<'PY'
import os, re
from pathlib import Path
env = Path(".env")
text = env.read_text()
line = "DUCKDNS_TOKEN=" + os.environ["TOKEN"]
text = re.sub(r"^DUCKDNS_TOKEN=.*$", lambda _: line, text, flags=re.M) if re.search(r"^DUCKDNS_TOKEN=", text, re.M) \
    else text.rstrip("\n") + "\n" + line + "\n"
env.write_text(text)
PY
chown ultra:ultra .env && chmod 600 .env
docker compose -f ha.docker-compose.yaml up -d --no-deps --force-recreate duckdns >/dev/null
for _ in $(seq 1 30); do
  sleep 2
  LOG="$(docker logs homeassistant-duckdns-1 2>&1 | tail -5)"
  if printf "%s" "$LOG" | grep -qx "OK"; then echo "DuckDNS: token accepted, stvrz.duckdns.org updated."; exit 0; fi
  if printf "%s" "$LOG" | grep -qx "KO"; then echo "DuckDNS answered KO: the token or subdomain is wrong." >&2; exit 1; fi
done
echo "No answer from DuckDNS yet; check: docker logs homeassistant-duckdns-1" >&2
exit 1
