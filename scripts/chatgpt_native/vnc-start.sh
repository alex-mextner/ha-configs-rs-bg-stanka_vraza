#!/bin/bash
unset WAYLAND_DISPLAY
export XDG_SESSION_TYPE=x11
export LD_LIBRARY_PATH=/home/ultra/.local/share/chatgpt-native-ha/gui-runtime/root/usr/lib/x86_64-linux-gnu
exec /home/ultra/.local/share/chatgpt-native-ha/gui-runtime/root/usr/bin/x11vnc -display :109 -auth /home/ultra/.local/share/chatgpt-native-ha/gui-session/Xauthority -localhost -rfbport 5901 -forever -shared -nopw -quiet -noxdamage
