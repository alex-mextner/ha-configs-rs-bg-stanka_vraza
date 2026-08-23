#!/usr/bin/env python3
"""Print Transmission torrent errors as compact JSON for Home Assistant."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


RPC_URL = os.environ.get("TRANSMISSION_RPC_URL", "http://172.20.0.1:9091/transmission/rpc")
FIELDS = [
    "id",
    "name",
    "error",
    "errorString",
    "status",
    "percentDone",
    "downloadDir",
    "rateDownload",
    "rateUpload",
]


def rpc(method: str, arguments: dict | None = None) -> dict:
    payload = json.dumps({"method": method, "arguments": arguments or {}}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    for _ in range(2):
        request = urllib.request.Request(RPC_URL, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            session_id = exc.headers.get("X-Transmission-Session-Id")
            if exc.code == 409 and session_id:
                headers["X-Transmission-Session-Id"] = session_id
                continue
            raise
    raise RuntimeError("Transmission RPC session negotiation failed")


def main() -> int:
    try:
        data = rpc("torrent-get", {"fields": FIELDS})
        torrents = data.get("arguments", {}).get("torrents", [])
        normalized = []
        errors = []
        for torrent in torrents:
            item = {
                "id": torrent.get("id"),
                "name": torrent.get("name") or "",
                "error": int(torrent.get("error") or 0),
                "error_string": torrent.get("errorString") or "",
                "status": torrent.get("status"),
                "percent_done": round(float(torrent.get("percentDone") or 0) * 100, 2),
                "download_dir": torrent.get("downloadDir") or "",
                "rate_download": torrent.get("rateDownload") or 0,
                "rate_upload": torrent.get("rateUpload") or 0,
            }
            normalized.append(item)
            if item["error"] or item["error_string"]:
                errors.append(item)
        print(json.dumps({"count": len(errors), "errors": errors, "torrents": normalized}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - sensor should report probe failures as data.
        print(json.dumps({"count": 0, "errors": [], "torrents": [], "probe_error": repr(exc)}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
