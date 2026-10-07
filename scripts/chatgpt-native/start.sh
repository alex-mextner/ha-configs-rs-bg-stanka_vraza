#!/bin/bash
set -euo pipefail
base=${CHATGPT_NATIVE_BASE:-/home/ultra/.local/share/chatgpt-native-ha}
export LD_LIBRARY_PATH="$base/gui-runtime/root/usr/lib/x86_64-linux-gnu"
unset WAYLAND_DISPLAY
export XDG_SESSION_TYPE=x11
export DISPLAY=:109
export XDG_RUNTIME_DIR=/run/user/1000
export HOME=/home/ultra
"$base/gui-runtime/root/usr/bin/Xvfb" :109 -screen 0 1280x900x24 -nolisten tcp -auth "$base/gui-session/Xauthority" >"$base/gui-session/xvfb.log" 2>&1 &
xpid=$!
trap 'kill "$xpid" "${vpid:-}" "${bpid:-}" 2>/dev/null || true' EXIT
for i in {1..50}; do [ -S /tmp/.X11-unix/X109 ] && break; sleep .1; done
export XAUTHORITY="$base/gui-session/Xauthority"
"$base/gui-runtime/root/usr/bin/x11vnc" -display :109 -auth "$XAUTHORITY" -localhost -rfbport 5901 -forever -shared -nopw -quiet -noxdamage >"$base/gui-session/vnc.log" 2>&1 &
vpid=$!
/usr/bin/python3 "$base/gui-session/bridge.py" >"$base/gui-session/bridge.log" 2>&1 &
bpid=$!
/usr/bin/dbus-run-session -- "$base/gui-session/desktop-session.sh" >"$base/gui-session/chatgpt.log" 2>&1
