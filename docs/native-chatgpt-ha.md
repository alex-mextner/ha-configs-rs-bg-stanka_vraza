# Separate native GUI through HA

A dedicated `ultra:ultra`, mode 0700 directory exists at `/run/media/ultra/WD500/ultra-work` on `/dev/sdc1` (ext4). Only that new directory was created; the disk was not reformatted and other data was not modified.

The user service `chatgpt-native-ha` launches `/usr/bin/chatgpt` (26.930.51102) on Xvfb :109 as ultra, with a separate profile under the new directory. It uses Xauthority and launches without `--no-sandbox`. The service has MemoryMax=2G, MemorySwapMax=512M, CPUQuota=150%. GUI dependencies were downloaded from Ubuntu's configured official repositories and extracted into `~/.local/share/chatgpt-native-ha/gui-runtime/root`, without installing system packages.

The existing Chrome/noVNC container e0f400053f33 remains untouched and healthy. The new VNC listener is 127.0.0.1/[::1]:5901. The HTTP/WebSocket bridge binds only the private Docker gateway 172.20.0.1:6081 and rejects peers except HA at 172.20.0.5. No new listener on LAN/public interfaces, Docker published port, or router port was added.

The `chatgpt_native` integration registers the sidebar at `/chatgpt-native`. It exchanges an existing authenticated HA Ingress session for an HttpOnly, SameSite=Strict cookie scoped to `/api/chatgpt_native`. Each asset/WebSocket request resolves the current HA user and requires is_active and is_admin. Open WebSockets recheck every 30 seconds. It creates no users/passwords or independent credentials. The panel also requires admin, but access control is enforced in the backend.

Validation: configuration check and `ha_safe_reload.sh`; HA healthy; ruff format/check; authorization regression checks for missing/expired sessions, deleted/inactive/non-admin users, and role revocation; live anonymous HTML and WebSocket rejection (401), non-HA backend peer rejection (403), existing admin initialization and HTML (200), live RFB handshake and a 1280x900 raw framebuffer obtained through the authenticated HA WebSocket. Screenshot/report retained privately, not committed.

## Material limits

The installed package is branded ChatGPT, but its captured default screen says Codex. This proves the installed native binary works, not that the ChatGPT conversation view was visually verified. Browser automation is unavailable in the delegated execution environment (`Browser is not available: iab`), so rendering of the HA sidebar iframe and interactive keyboard/mouse were not browser-tested. Actual non-admin HA credentials were not created or used; those role cases were tested with current-user mocks.

The bridge pins the current HA container IP. If Docker assigns another IP, it fails closed until that allowlist is updated. At boot the service starts only if WD500 is already mounted at its expected path. If the mount arrives later, run `systemctl --user start chatgpt-native-ha`. Do not redirect the profile onto the root disk.

The implementation source is installed in the active HA checkout. This branch contains the identical new integration/package/service sources for review. No Crypto/Conloca production project was touched.

## Operations

- Open the existing authenticated HA URL with `/chatgpt-native` appended, or choose ChatGPT Native in the admin sidebar.
- Service: `systemctl --user status chatgpt-native-ha`.
- Stop only the new GUI: `systemctl --user stop chatgpt-native-ha`.
- Rollback HA: remove only `packages/chatgpt_native.yaml` and the new `custom_components/chatgpt_native/` directory, then use `scripts/ha_safe_reload.sh`. Keep the WD500 directory/profile unless explicitly requested otherwise.
