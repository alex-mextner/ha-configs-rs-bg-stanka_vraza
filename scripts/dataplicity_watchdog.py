#!/usr/bin/env python3
"""End-to-end check of HA's external URL (Dataplicity tunnel), every 5 min from cron.

Logs every probe to ~/dataplicity-watchdog/probes.jsonl. After 2 failed probes in a row it reloads
the Dataplicity config entry once per outage and raises an HA notification; on recovery it
dismisses it and logs the outage length. Cron (ultra):
  */5 * * * * /home/ultra/homeassistant/scripts/dataplicity_watchdog.py >> /tmp/dataplicity_watchdog.log 2>&1
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

HA = "http://127.0.0.1:8123"
CONFIG = Path("/home/ultra/homeassistant/.storage")
STATE_DIR = Path.home() / "dataplicity-watchdog"
NID = "dataplicity_watchdog"


def ha_token() -> str:
    for line in (Path.home() / ".env").read_text().splitlines():
        if line.startswith("HA_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("HA_TOKEN missing in ~/.env")


def ha(service: str, payload: dict) -> None:
    req = urllib.request.Request(f"{HA}/api/services/{service}", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {ha_token()}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()


def probe(url: str) -> tuple[bool, str, float]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/manifest.json", timeout=20) as resp:
            ok = resp.status == 200 and b"Home Assistant" in resp.read(4096)
            return ok, str(resp.status), time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return False, str(exc.code), time.monotonic() - started
    except Exception as exc:
        return False, type(exc).__name__, time.monotonic() - started


def main() -> None:
    url = json.loads((CONFIG / "core.config").read_text())["data"].get("external_url")
    entry = next(e["entry_id"] for e in json.loads((CONFIG / "core.config_entries").read_text())["data"]["entries"]
                 if e["domain"] == "dataplicity")
    STATE_DIR.mkdir(exist_ok=True)
    state_file = STATE_DIR / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"fails": 0}
    ok, code, seconds = probe(url)
    now = time.time()
    record = {"ts": int(now), "ok": ok, "code": code, "seconds": round(seconds, 2)}
    if ok:
        if state.get("down_since"):
            record["outage_minutes"] = round((now - state["down_since"]) / 60, 1)
            try:
                ha("persistent_notification/dismiss", {"notification_id": NID})
            except Exception:
                pass
        state = {"fails": 0}
    else:
        state["fails"] = state.get("fails", 0) + 1
        state.setdefault("down_since", now)
        if state["fails"] >= 2 and not state.get("reloaded"):
            try:
                ha("homeassistant/reload_config_entry", {"entry_id": entry})
                ha("persistent_notification/create", {
                    "notification_id": NID, "title": "Внешний доступ к HA пропал",
                    "message": f"Dataplicity ({url}) не отвечает: {code}. Интеграция перезапущена автоматически."})
                record["action"] = "reloaded"
            except Exception as exc:
                record["action"] = f"reload failed: {exc}"
            state["reloaded"] = True
    with open(STATE_DIR / "probes.jsonl", "a") as log:
        log.write(json.dumps(record) + "\n")
    state_file.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
