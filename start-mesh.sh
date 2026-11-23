#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PIDS=()
cleanup() {
  pkill -9 -f "/app/servoshell" 2>/dev/null || true
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

for i in 0 1 2 3; do
  DISP=$((2 + i))
  VNC=$((5902 + i))
  WEB=$((6080 + i))

  if [ ! -S "/tmp/.X11-unix/X${DISP}" ]; then
    Xvfb ":${DISP}" -screen 0 1600x840x24 +extension GLX +render -noreset -nolisten tcp >/dev/null 2>&1 &
    PIDS+=($!)
    sleep 0.4
  fi

  DISPLAY=":${DISP}" setxkbmap us >/dev/null 2>&1 || true
  DISPLAY=":${DISP}" openbox --config-file "$PWD/openbox-rc.xml" >/dev/null 2>&1 &
  PIDS+=($!)

  x11vnc -display ":${DISP}" -listen 127.0.0.1 -rfbport "$VNC" -nopw -forever -shared -noxdamage -xkb -repeat >/dev/null 2>&1 &
  PIDS+=($!)

  websockify --web="$PWD/novnc" "127.0.0.1:${WEB}" "127.0.0.1:${VNC}" >/dev/null 2>&1 &
  PIDS+=($!)
done

./nym-socks5-client run --id mesh-nym >/tmp/nym.log 2>&1 &
PIDS+=($!)
python3 mesh-router.py >/tmp/mesh-router.log 2>&1 &
PIDS+=($!)
python3 mesh-scrubber.py >/dev/null 2>&1 &
PIDS+=($!)
python3 server.py &
PIDS+=($!)

for _ in $(seq 1 50); do
  (echo > /dev/tcp/127.0.0.1/8080) 2>/dev/null && break
  sleep 0.1
done

echo "Launching Mesh Browser..."
python3 "$PWD/mesh-app.py" &
MESH_PID=$!
wait "$MESH_PID"
