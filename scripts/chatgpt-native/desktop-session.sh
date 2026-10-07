#!/bin/bash
# Run inside a dedicated dbus-run-session, never the physical GNOME bus.
set -euo pipefail
case "${1:-}" in
    ""|--controls-only) ;;
    *) echo 'Usage: desktop-session.sh [--controls-only]' >&2; exit 2 ;;
esac
base=${CHATGPT_NATIVE_BASE:-/home/ultra/.local/share/chatgpt-native-ha}
config=${CHATGPT_DESKTOP_CONFIG:-$base/gui-session/desktop}
root=${CHATGPT_DESKTOP_ROOT:-$base/desktop-runtime/root}
export PATH="$root/usr/bin:$config:$PATH"
export LD_LIBRARY_PATH="$root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export XDG_DATA_DIRS="$root/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export IMLIB2_LOADER_PATH="$root/usr/lib/x86_64-linux-gnu/imlib2/loaders"
export XDG_CURRENT_DESKTOP=Openbox
export GDK_BACKEND=x11
unset WAYLAND_DISPLAY SESSION_MANAGER
# Retain the user's existing runtime/keyring; do not create a second credential store.
# Application activation stays on this private D-Bus, keeping Files on this display.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
export CHATGPT_DESKTOP_APP_CONFIG_HOME="${XDG_CONFIG_HOME:-}"
openbox_config=${CHATGPT_DESKTOP_USER_CONFIG:-$base/gui-session/desktop-config}
mkdir -p "$openbox_config"
if [ ! -e "$openbox_config/openbox" ]; then
    ln -s "$config" "$openbox_config/openbox"
fi
for program in openbox tint2 xterm nautilus wmctrl; do
    command -v "$program" >/dev/null || { echo "Missing desktop dependency: $program" >&2; exit 1; }
done
# Update only this private D-Bus daemon; never use --systemd here.
dbus-update-activation-environment DISPLAY XAUTHORITY XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP GDK_BACKEND XDG_DATA_DIRS
cd "$config"
XDG_CONFIG_HOME="$openbox_config" openbox --config-file "$config/rc.xml" &
wmpid=$!
tint2 -c "$config/tint2rc" &
panelpid=$!
trap 'kill "$wmpid" "$panelpid" 2>/dev/null || true' EXIT
# Controls-only adds a desktop around an existing ChatGPT without restarting it.
if [ "${1:-}" = --controls-only ]; then
    wait "$wmpid" "$panelpid"
else
    # WM/panel termination does not terminate ChatGPT. Session ends when it exits.
    /usr/bin/chatgpt --user-data-dir="${CHATGPT_NATIVE_PROFILE:-/run/media/ultra/WD500/ultra-work/chatgpt-native}" --disable-gpu
fi
