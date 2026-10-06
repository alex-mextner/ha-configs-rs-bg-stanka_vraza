# Separate native GUI through HA

A dedicated `ultra:ultra`, mode 0700 directory exists at `/run/media/ultra/WD500/ultra-work` on `/dev/sdc1` (ext4). Only that new directory was created; the disk was not reformatted and other data was not modified.

The user service `chatgpt-native-ha` launches `/usr/bin/chatgpt` (26.930.51102) on Xvfb :109 as ultra, with a separate profile under the new directory. It uses Xauthority and launches without `--no-sandbox`. The service has MemoryMax=2G, MemorySwapMax=512M, CPUQuota=150%. GUI dependencies were downloaded from Ubuntu's configured official repositories and extracted into `~/.local/share/chatgpt-native-ha/gui-runtime/root`, without installing system packages.

The existing Chrome/noVNC container e0f400053f33 remains untouched and healthy. The new VNC listener is 127.0.0.1/[::1]:5901. The HTTP/WebSocket bridge binds only the private Docker gateway 172.20.0.1:6081 and rejects peers except HA at 172.20.0.5. No new listener on LAN/public interfaces, Docker published port, or router port was added.

The `chatgpt_native` integration registers the sidebar at `/chatgpt-native`. It exchanges an existing authenticated HA Ingress session for an HttpOnly, SameSite=Strict cookie scoped to `/api/chatgpt_native`. Each asset/WebSocket request resolves the current HA user and requires is_active and is_admin. Open WebSockets recheck every 30 seconds. It creates no users/passwords or independent credentials. The panel also requires admin, but access control is enforced in the backend.

Validation: configuration check and `ha_safe_reload.sh`; HA healthy; ruff format/check; authorization regression checks for missing/expired sessions, deleted/inactive/non-admin users, and role revocation; live anonymous HTML and WebSocket rejection (401), non-HA backend peer rejection (403), existing admin initialization and HTML (200), live RFB handshake and a 1280x900 raw framebuffer obtained through the authenticated HA WebSocket. Screenshot/report retained privately, not committed.

## Material limits

The official launcher is `/usr/bin/chatgpt` (`Exec=chatgpt %U` in the installed ChatGPT desktop entry). This app has a native product dropdown with ChatGPT and Codex. The separate GUI was switched via that dropdown to ChatGPT, and its Chat tab and Ask ChatGPT composer were visually verified inside the real HA iframe. Existing HA credentials were reused only temporarily for the local browser smoke; no account/login/password was created, and temporary browser token state was cleared and the browser closed afterward.

Browser smoke caught and fixed a relative WebSocket path bug. The panel now uses the absolute `/api/chatgpt_native/websockify` path. The final visual check required actual 1280x900 framebuffer pixels, not merely HTTP or a canvas element. Real non-admin HA credentials were not created or used; non-admin/inactive/deleted/revoked-role cases were tested with current-user mocks, and anonymous HTTP/WebSocket denials and real existing-admin access were tested live.

The dedicated browser profile/cache is `/run/media/ultra/WD500/ultra-work/chatgpt-native`; runtime/Xauthority/service logs are under `~/.local/share/chatgpt-native-ha`. Existing account and agent data remain in the user's existing `~/.codex` / `~/.config/Codex`; this is a separate GUI/profile, not a separate account or migration of all user data to WD500.

The bridge pins the current HA container IP. If Docker assigns another IP, it fails closed until that allowlist is updated. At boot the service starts only if WD500 is already mounted at its expected path. If the mount arrives later, run `systemctl --user start chatgpt-native-ha`. Do not redirect the profile onto the root disk.

The implementation source is installed in the active HA checkout. This branch contains the identical new integration/package/service sources for review. No Crypto/Conloca production project was touched.

## Operations

- Open the existing authenticated HA URL with `/chatgpt-native` appended, or choose ChatGPT Native in the admin sidebar.
- Service: `systemctl --user status chatgpt-native-ha`.
- Stop only the new GUI: `systemctl --user stop chatgpt-native-ha`.
- Rollback HA: remove only `packages/chatgpt_native.yaml` and the new `custom_components/chatgpt_native/` directory, then use `scripts/ha_safe_reload.sh`. Keep the WD500 directory/profile unless explicitly requested otherwise.

## Proposed shared Ubuntu Desktop (draft, not deployed)

The desktop extension adds an administrator-only sidebar entry at `/ubuntu-desktop` and retains `/chatgpt-native`. Both use the exact same `/api/chatgpt_native` session/assets/WebSocket proxy and the same :109 framebuffer. The Desktop panel explicitly says that window switching is visible in both panels. ChatGPT is retained as an application/window, rather than replaced. This is a virtual application desktop for ultra, not a mirror of the physical GNOME/Wayland screen.

Openbox manages and moves/maximizes windows. A 48-pixel tint2 taskbar provides Terminal, Files and ChatGPT launchers and a window switcher. Terminal runs xterm in `/home/ultra`; Files uses existing Nautilus. ChatGPT's launcher focuses the existing `Chatgpt` window with wmctrl, without opening another app/profile. Additional installed applications can be launched from the terminal. Alt+Tab changes windows; Super+Return opens Terminal, Super+E opens Files, Super+Space opens the desktop menu. The noVNC controls provide keyboard/modifier input on mobile.

`desktop-session.sh` runs inside a private `dbus-run-session`, so activating Files stays on the virtual screen rather than the physical GNOME application's bus. The original user runtime/keyring and application configuration are retained; only Openbox gets a separate XDG config directory. `desktop-launch` restores the original application XDG config for programs launched through Openbox's menu/shortcuts. No second keyring, login, credentials, SSH or ACL rules are created.

Desktop packages come from the host's configured Ubuntu repositories and are extracted into `~/.local/share/chatgpt-native-ha/desktop-runtime/root`, alongside the existing gui-runtime. Additional packages used here: openbox, tint2, xterm, wmctrl, libobrender32, libobt2, libimlib2t64, libutempter0, xbitmaps. All libraries already present on this Ubuntu host are reused. Imlib2's loader directory and XDG data directory point at the extracted root so tint2 can load icons. No third-party binaries are committed to this repository. No new system package installation, service, network listener or external port is introduced.

### Review and deployment boundary

Only isolated :119 testing has been performed for this desktop extension. It is not deployed to HA or :109 and has not been tested through the new live HA panel or an actual phone. Existing authentication code/network bindings are unchanged. Local backend and panel tests supplement the original live ChatGPT/Ingress proof; they do not prove the complete new phone flow.

After explicit acceptance of the draft PR and private screenshot/report evidence:

1. Back up the installed `gui-session/start.sh` and existing `custom_components/chatgpt_native` sources to a new dated backup. Preserve the WD500 profile, runtime Xauthority and bridge. Do not remove the existing package/integration or ChatGPT panel.
2. Download the additional official packages with `apt-get download` into a separate `desktop-runtime/debs` folder and extract each with `dpkg-deb -x` into `desktop-runtime/root`. This does not require sudo or system installation. Confirm `ldd` has no missing dependencies; do not work around a permission failure.
3. Copy `desktop-session.sh` and the `desktop/` configuration subtree into `gui-session/`. The configuration contains the launcher executable, three desktop entries, Openbox rc/menu and tint2 configuration. Keep the existing bridge and VNC listeners unchanged.
4. **Do not restart `chatgpt-native-ha` to activate controls.** Use the existing :109/Xauthority and start only the controls in a separate foreground terminal:

   ```bash
   base=/home/ultra/.local/share/chatgpt-native-ha
   DISPLAY=:109 XAUTHORITY="$base/gui-session/Xauthority" \
     /usr/bin/dbus-run-session -- "$base/gui-session/desktop-session.sh" --controls-only
   ```

   This command has an explicit lifetime: keep that terminal/process running until controls are intentionally stopped or the native GUI next restarts. It does not launch, terminate or restart ChatGPT. The PID and ChatGPT window must remain unchanged. No new supervisor/service is installed. For unattended persistence after acceptance, copy the reviewed `start.sh` for the next natural service start; it launches desktop controls and ChatGPT together. Do not run both control owners on the same screen.
5. Deploy only the reviewed HA integration changes, validate the configuration and use the repository's safe reload procedure. This HA reload is separate from the native ChatGPT user service. Reload the browser to register the second web component, then test admin access, anonymous denial, role revocation and the new panel on the phone. Stop if a new credential prompt appears; never enter or change a password to bypass it.

### Desktop-only rollback

Stop the controls-only command (Ctrl+C in its owning terminal) to remove Openbox/tint2/private application bus, leaving ChatGPT and VNC in place. Restore the backed-up start script and HA integration files from before this desktop change, and safely reload HA to remove only `/ubuntu-desktop`. Preserve `/chatgpt-native`, its profile, Xauthority, bridge and service. For controls launched on a future service start, rollback requires scheduling the native GUI restart with the user; it is not silently performed during the current session.
