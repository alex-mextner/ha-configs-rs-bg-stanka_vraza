# Network layout of the `home` box

This is how Home Assistant and its neighbours are wired on the always-on laptop `home`, and why.
It describes the working state as of 2026-09-26; update it with every network change.

## Host

| Interface | Address | Notes |
|---|---|---|
| `enp3s0` (cable) | 192.168.0.39/24, DHCP | default route (metric 100); the address to use from the LAN |
| `wlo1` (Wi-Fi) | 192.168.0.11/24, DHCP | backup route (metric 600) |
| `tailscale0` | Tailscale | remote administration (`ssh root@home`) |

Router: the ISP modem/router at 192.168.0.1 (DHCP pool .10-.254, few static reservations).
Speakers, TV and other devices have plain DHCP addresses, so nothing may hardcode their IPs.

The whole stack starts at boot through `ha-compose.service` (`docker compose -f
ha.docker-compose.yaml up -d`), so whatever `ha.docker-compose.yaml` says is what runs after a reboot.

## Docker networks

| Network | Members | Purpose |
|---|---|---|
| `ha-net` (bridge, 172.20.0.0/16, host side 172.20.0.1) | homeassistant, esphome, go2rtc, ollama, ollama-embed, hga-postgres, wyoming-*, code-server, ssh-server, bgutil-pot, printer-proxy, u1-camera-proxy, openclaw, avahi-reflector | service-to-service by name; HA is also `homeassistant.local` inside it |
| `chatgpt-web` (bridge) | chatgpt-web, openclaw | the ChatGPT web bridge API is reachable only from OpenClaw |
| host network | music-assistant, ma-local-audio (Sendspin player "Ноутбук") | players and phones must reach MA directly (streams, discovery) |

Home Assistant runs on `ha-net` only and is published on the host: `192.168.0.39:8123`.
Other containers reach it as `homeassistant:8123`; host-network services (MA) use `127.0.0.1:8123`.

### Why HA has no LAN leg (macvlan)

On 2026-09-25 HA got a second interface directly on the LAN (macvlan, 192.168.0.5) so that it
would see mDNS. That broke access to `192.168.0.39:8123` from the LAN: replies to LAN clients left
through the macvlan leg with the wrong source address and were dropped. HA's own zeroconf also
announced its 172.20.x address to the LAN. The leg was removed on 2026-09-26; do not add it back.

## mDNS / discovery

- `homeassistant.local` and the `_home-assistant._tcp` service (-> 192.168.0.39:8123) are published
  on the LAN by `scripts/host/ha-mdns-publish.py`, a systemd *user* unit of `ultra`
  (`scripts/host/ha-mdns.service`, installed as `~/.config/systemd/user/ha-mdns.service`, linger on).
  It follows the host's primary IP.
- Music Assistant sees LAN mDNS itself (host network): Yandex stations, Chromecast, AirPlay, etc.
- **Open problem:** HA on `ha-net` does not see LAN mDNS (verified: 0 `_yandexio`, `_googlecast`,
  `_esphomelib` services from inside HA, all of them visible from the host). Yandex stations
  therefore run without their local mode (cloud only).
  The intended fix is a filtered mDNS relay: the existing `avahi-reflector` service with a small
  macvlan leg on the LAN (it serves no ports, unlike HA) plus `ha-net`, relaying only
  `_yandexio._tcp`, `_googlecast._tcp` and `_esphomelib._tcp`. It is waiting for the owner's approval.
- Leftovers to clean up: the compose `avahi-reflector` currently runs with the reflector disabled
  (no effect), and a standalone `avahi-reflector` container on the host network (not in compose,
  created 2026-05-18) also has the reflector disabled and makes the host's avahi rename itself to
  `home-2.local`.

## Ports on the host

| Port | Bind | Service |
|---|---|---|
| 8123 | all | Home Assistant |
| 8095 / 8097 / 8927 | all | Music Assistant (UI+API / streams / Sendspin); 8928 Sendspin player |
| 6052 | all | ESPHome dashboard |
| 1984, 8554, 8555 | all | go2rtc |
| 10400 | all | wyoming-openwakeword |
| 2222 | all | ssh-server container |
| 8443 | all | code-server (no auth, intentional) |
| 9091, 51413 | all | transmission (host service) |
| 61208 | all | glances |
| 18789 | 127.0.0.1 | OpenClaw gateway |
| 6080 | 127.0.0.1 | chatgpt-web noVNC (use `ssh -L`) |
| 4416 | 127.0.0.1 | bgutil PO-token server for YouTube Music |

## Access from outside

- Administration: Tailscale only.
- HA's `external_url` is a Dataplicity tunnel (used by the mobile app away from home). The host's
  Dataplicity agent (`tuxtunnel` under supervisor) is in FATAL state; being investigated.
- DuckDNS was removed on 2026-09-26: nothing used it (HA never pointed at it, its certificates had
  long expired). The old add-on files are in `~/backups/ssl-duckdns-addon-2026-09-26`.
