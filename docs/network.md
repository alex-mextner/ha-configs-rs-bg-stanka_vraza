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
Which TV / Chromecast player entity is which, and why the Samsung's DLNA player is hidden:
[media-players.md](media-players.md).

The whole stack starts at boot through `ha-compose.service` (`docker compose -f
ha.docker-compose.yaml up -d`), so whatever `ha.docker-compose.yaml` says is what runs after a reboot.

## Docker networks

| Network | Members | Purpose |
|---|---|---|
| `ha-net` (bridge, 172.20.0.0/16, host side 172.20.0.1) | homeassistant, esphome, go2rtc, ollama, ollama-embed, hga-postgres, wyoming-*, code-server, ssh-server, bgutil-pot, printer-proxy, u1-camera-proxy, openclaw, avahi-reflector | service-to-service by name; HA is also `homeassistant.local` inside it |
| `chatgpt-web` (bridge) | chatgpt-web, openclaw | the ChatGPT web bridge API is reachable only from OpenClaw |
| `lan` (macvlan on `enp3s0`, only 192.168.0.5) | avahi-reflector | the mDNS relay's LAN leg; nothing else may join it (see below) |
| host network | music-assistant, ma-local-audio (Sendspin player "Ноутбук") | players and phones must reach MA directly (streams, discovery) |

Home Assistant runs on `ha-net` only and is published on the host: `192.168.0.39:8123`.
Other containers reach it as `homeassistant:8123`; host-network services (MA) use `127.0.0.1:8123`.

### Why HA has no LAN leg (macvlan)

On 2026-09-25 HA got a second interface directly on the LAN (macvlan, 192.168.0.5) so that it
would see mDNS. That broke access to `192.168.0.39:8123` from the LAN: replies to LAN clients left
through the macvlan leg with the wrong source address and were dropped. HA's own zeroconf also
announced its 172.20.x address to the LAN. The leg was removed on 2026-09-26; do not add it back.
The only macvlan leg now belongs to the mDNS relay below; it has the same address, 192.168.0.5,
but serves no ports, so the asymmetric-routing problem cannot happen there.

## mDNS / discovery

- `homeassistant.local` and the `_home-assistant._tcp` service (-> 192.168.0.39:8123) are published
  on the LAN by `scripts/host/ha-mdns-publish.py`, a systemd *user* unit of `ultra`
  (`scripts/host/ha-mdns.service`, installed as `~/.config/systemd/user/ha-mdns.service`, linger on).
  It follows the host's primary IP.
- Music Assistant sees LAN mDNS itself (host network): Yandex stations, Chromecast, AirPlay, etc.
- HA on `ha-net` sees LAN mDNS through a filtered relay, the compose service `avahi-reflector`
  (live since 2026-09-26, approved by the owner). It is avahi in reflector mode with two legs:
  `ha-net` and the macvlan `lan` on `enp3s0` with the fixed address 192.168.0.5 (outside the DHCP
  pool). It publishes no ports. `REFLECTOR_REFLECT_FILTERS` limits it to `_yandexio._tcp`,
  `_googlecast._tcp` and `_esphomelib._tcp`; add a type there if another integration needs one.
  The host cannot talk to a macvlan child (by design), so 192.168.0.5 is unreachable from `home`
  itself; that is expected.
  - Verified from inside HA (python zeroconf): 3 Yandex stations (192.168.0.44, .22, .17),
    Chromecast-HD (192.168.0.24) and 2 ESPHome devices. Before the relay: 0.
  - Yandex stations run in local mode, with IPs from mDNS only: HA holds a websocket to
    `<station>:1961` for all three ("Станция Мини new", "Мини гостиная", "Станция Мини у Вовы"),
    and their `media_player` entities carry `alice_state`, which the integration sets only while
    the local connection is up. Its mDNS browser runs for HA's whole lifetime, so a new DHCP
    address is picked up without a restart.
  - From a LAN client (the Mac, `dns-sd -B _home-assistant._tcp`) there is exactly one
    "Home Assistant" service, 192.168.0.39. HA's own 172.20.0.2 announcement is not relayed.
  - Known and harmless: the filter applies to services, not to plain host-name lookups. HA's
    random `<uuid>.local` name resolves to 172.20.0.2 from the LAN if asked for directly, and the
    host's `home-2.local` also shows 172.20.0.1. Nothing on the LAN uses these names.
- Host names: the host's avahi-daemon runs as `home-2.local`. Music Assistant's AirPlay Receiver
  plugin runs `shairport-sync` with its built-in mDNS responder (tinysvcmdns) on the host network,
  and that responder answers for `home.local` with every host address (LAN, Wi-Fi, docker bridges,
  Tailscale), so avahi sees a name conflict at start-up and renames itself. `home.local` still
  resolves on the LAN (192.168.0.39 among others); for HA use `homeassistant.local` or
  192.168.0.39. The old standalone `avahi-reflector` container (host network, not in compose,
  created 2026-05-18, reflector disabled) was removed on 2026-09-26.

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
- HA's `external_url` is a Dataplicity tunnel (used by the mobile app away from home). It is run
  by the HA integration `custom_components/dataplicity` (the owner's fork), not by the host.
- The old host-level Dataplicity agent (`tuxtunnel` under supervisor, which once offered a remote
  root shell through the Dataplicity web UI) was removed on 2026-09-26: its program
  `/opt/dataplicity/agent/dataplicity` was already gone, so it sat in FATAL state. Its supervisor
  config is kept in `~/backups/tuxtunnel.conf.supervisor-2026-09-26`. The system user
  `dataplicity` (password locked; one sudoers line allowing `/sbin/reboot`) and `/home/dataplicity`
  (old pex caches only) are still there; nothing uses them.
- DuckDNS was removed on 2026-09-26: nothing used it (HA never pointed at it, its certificates had
  long expired). The old add-on files are in `~/backups/ssl-duckdns-addon-2026-09-26`.
