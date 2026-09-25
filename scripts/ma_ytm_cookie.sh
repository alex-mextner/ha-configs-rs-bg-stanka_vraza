#!/usr/bin/env bash
# Set (or refresh) the Music Assistant YouTube Music cookie; creates the provider on first use.
#
#   ssh -t root@home ytm-cookie        # paste the cookie (hidden), Enter
#   ... | ssh root@home ytm-cookie     # or pipe it
#
# The cookie comes from the "YT Music -> Music Assistant" Chrome extension (one click copies the
# music.youtube.com Cookie header). It is sent to MA's own setup flow over the local API with the
# HA integration's MA token; MA stores setup data encrypted. Nothing is written to disk here.
set -euo pipefail
if [ -t 0 ]; then
  read -rsp "YouTube Music cookie (paste, Enter): " YTM_COOKIE; echo
else
  YTM_COOKIE="$(cat)"
fi
YTM_COOKIE="$(printf "%s" "$YTM_COOKIE" | tr -d "\r\n" | sed -E "s/^[Cc]ookie:[[:space:]]*//")"
if [ "${#YTM_COOKIE}" -lt 100 ] || ! printf "%s" "$YTM_COOKIE" | grep -qE "(SAPISID|__Secure-3PAPISID)="; then
  echo "This does not look like a signed-in music.youtube.com cookie (no SAPISID)." >&2
  exit 1
fi
MA_TOKEN="$(python3 -c 'import json; e=[e for e in json.load(open("/home/ultra/homeassistant/.storage/core.config_entries"))["data"]["entries"] if e["domain"]=="music_assistant"][0]; print(e["data"]["token"])')"
export MA_TOKEN YTM_COOKIE
docker exec -i -e MA_TOKEN -e YTM_COOKIE -e YTM_DRY_RUN="${YTM_DRY_RUN:-}" homeassistant-homeassistant-1 python3 - <<'PY'
import asyncio, os
import aiohttp
from music_assistant_client import MusicAssistantClient

def as_dict(obj):
    if isinstance(obj, dict):
        return obj
    return obj.to_dict() if hasattr(obj, "to_dict") else vars(obj)

async def main() -> int:
    values = {"username": "default", "cookie": os.environ["YTM_COOKIE"], "po_token_server_url": "http://127.0.0.1:4416"}
    async with aiohttp.ClientSession() as session:
        client = MusicAssistantClient("http://172.20.0.1:8095", session, token=os.environ["MA_TOKEN"])
        await client.connect()
        try:
            configs = [as_dict(c) for c in await client.send_command("config/providers")]
            existing = next((c for c in configs if c.get("domain") == "ytmusic"), None)
            if existing:
                step = as_dict(await client.send_command("config/providers/reconfigure", instance_id=existing["instance_id"]))
                action = "updated"
            else:
                step = as_dict(await client.send_command("config/providers/setup", provider_domain="ytmusic"))
                action = "created"
            flow_id = step.get("flow_id")
            if step.get("type") != "form" or not flow_id:
                print("unexpected flow step:", step.get("type"), step.get("reason")); return 1
            if os.environ.get("YTM_DRY_RUN"):
                await client.send_command("config/flows/abort", flow_id=flow_id)
                print("dry run: flow opened and aborted (", action, ")"); return 0
            step = as_dict(await client.send_command("config/flows/submit", flow_id=flow_id, values=values))
            for _ in range(30):
                if step.get("type") != "progress":
                    break
                await asyncio.sleep(2)
                step = as_dict(await client.send_command("config/flows/get", flow_id=flow_id))
            if step.get("type") == "finish":
                print(f"YouTube Music provider {action}: cookie accepted (Premium check passed)."); return 0
            print("MA refused the cookie:", step.get("errors") or step.get("reason") or step.get("type"))
            try:
                await client.send_command("config/flows/abort", flow_id=flow_id)
            except Exception:
                pass
            return 1
        finally:
            await client.disconnect()

raise SystemExit(asyncio.run(main()))
PY
