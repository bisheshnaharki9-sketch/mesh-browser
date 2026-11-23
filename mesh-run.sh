#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://notbob.i2p/}"
TAB="${2:-tab1}"
DISP="${3:-2}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

LEVEL="${MESH_LEVEL:-standard}"
TRACKERS="${MESH_TRACKERS:-1}"
FINGERPRINT="${MESH_FINGERPRINT:-1}"
ERASE="${MESH_ERASE:-1}"

case "$URL" in
  http://*|https://*) ;;
  *) echo "Blocked invalid URL scheme: $URL"; exit 1 ;;
esac

XPID=""
if [ ! -S "/tmp/.X11-unix/X${DISP}" ]; then
    Xvfb ":${DISP}" -screen 0 1600x840x24 +extension GLX +render -noreset -nolisten tcp 2>/dev/null &
    XPID=$!
    sleep 0.5
    [ -S "/tmp/.X11-unix/X${DISP}" ] || { echo "Failed to start Xvfb :${DISP}"; exit 1; }
fi
(echo > /dev/tcp/127.0.0.1/4444) 2>/dev/null || { echo "i2pd is not running on port 4444"; exit 1; }

SOCK_DIR="$(mktemp -d /tmp/mesh-sock.XXXXXX)"
chmod 700 "$SOCK_DIR"
cleanup() { kill "${SOCAT_PID:-}" 2>/dev/null || true; rm -rf "$SOCK_DIR"; [ -n "$XPID" ] && kill "$XPID" 2>/dev/null || true; }
trap cleanup EXIT

TARGET_PORT=4444
(echo > /dev/tcp/127.0.0.1/4446) 2>/dev/null && TARGET_PORT=4446
socat UNIX-LISTEN:"$SOCK_DIR/i2p.sock",fork,mode=600 "TCP:127.0.0.1:${TARGET_PORT}" &
SOCAT_PID=$!

EXTRA_ARGS=()
[ "$ERASE" = "1" ] && EXTRA_ARGS+=(--temporary-storage)
[ "$TRACKERS" = "1" ] && [ -f "$APP_DIR/blocklist.hosts" ] && EXTRA_ARGS+=(--host-file=/app/blocklist.hosts)

if [ "$FINGERPRINT" = "1" ]; then
  EXTRA_ARGS+=(
    --userscripts=/app/userscripts
    "--pref=user_agent=Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0"
  )
fi

if [ "$LEVEL" = "safer" ] || [ "$LEVEL" = "safest" ]; then
  EXTRA_ARGS+=(
    "--pref=js_disable_jit=true"
    "--pref=js_ion_enabled=false"
    "--pref=js_offthread_compilation_enabled=false"
    "--pref=dom_webgl2_enabled=false"
    "--pref=dom_fontface_enabled=false"
    "--pref=dom_serviceworker_enabled=false"
    "--pref=dom_sharedworker_enabled=false"
    "--pref=dom_worklet_enabled=false"
  )
fi

if [ "$LEVEL" = "safest" ]; then
  EXTRA_ARGS+=(
    "--pref=js_baseline_interpreter_enabled=false"
    "--pref=dom_indexeddb_enabled=false"
    "--pref=dom_cookiestore_enabled=false"
    "--pref=dom_storage_manager_api_enabled=false"
    "--pref=dom_credential_management_enabled=false"
    "--pref=dom_wakelock_enabled=false"
    "--pref=dom_async_clipboard_enabled=false"
    "--pref=dom_canvas_text_enabled=false"
    "--pref=dom_canvas_capture_enabled=false"
    "--pref=dom_allow_scripts_to_close_windows=false"
  )
  [ -f "$APP_DIR/safest.css" ] && EXTRA_ARGS+=(--user-stylesheet=/app/safest.css)
fi

bwrap \
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 \
  --ro-bind "$APP_DIR/fonts" /usr/share/fonts \
  --ro-bind "$APP_DIR/fonts" /usr/local/share/fonts \
  --ro-bind-try /bin /bin \
  --ro-bind /etc/ssl /etc/ssl --ro-bind /etc/ca-certificates /etc/ca-certificates \
  --ro-bind /etc/ld.so.cache /etc/ld.so.cache \
  --dir /app \
  --ro-bind "$APP_DIR/servoshell" /app/servoshell \
  --ro-bind "$APP_DIR/mesh-prefs.json" /app/mesh-prefs.json \
  --ro-bind "$APP_DIR/fonts.conf" /app/fonts.conf \
  --ro-bind "$APP_DIR/fonts" /app/fonts \
  --ro-bind "$APP_DIR/userscripts" /app/userscripts \
  --ro-bind-try "$APP_DIR/resources" /app/resources \
  --ro-bind-try "$APP_DIR/blocklist.hosts" /app/blocklist.hosts \
  --ro-bind-try "$APP_DIR/safest.css" /app/safest.css \
  --dev /dev --proc /proc --tmpfs /dev/shm --tmpfs /tmp --tmpfs /home/mesh \
  --dir /home/mesh/Share --ro-bind "$APP_DIR/.clean-share" /home/mesh/Share --dir /tmp/xdg \
  --bind "/tmp/.X11-unix/X${DISP}" "/tmp/.X11-unix/X${DISP}" \
  --bind "$SOCK_DIR" /tmp/mesh-sock \
  --cap-drop ALL \
  --unshare-net --unshare-pid --unshare-uts --unshare-cgroup \
  --die-with-parent --new-session --clearenv \
  --setenv FONTCONFIG_FILE /app/fonts.conf \
  --setenv PATH /usr/bin:/bin --setenv HOME /home/mesh \
  --setenv XDG_RUNTIME_DIR /tmp/xdg --setenv DISPLAY ":${DISP}" \
  --setenv TZ UTC --setenv LANG en_US.UTF-8 \
  --chdir /app \
  /bin/sh -c '
    socat TCP-LISTEN:4444,bind=127.0.0.1,fork,reuseaddr UNIX-CONNECT:/tmp/mesh-sock/i2p.sock &
    exec /app/servoshell -b "$@"
  ' -- \
  --prefs-file=/app/mesh-prefs.json \
  --pref="network_http_proxy_uri=http://127.0.0.1:4444" \
  --pref="network_https_proxy_uri=http://127.0.0.1:4444" \
  --pref="network_http_cache_disabled=true" \
  --pref="network_use_webpki_roots=true" \
  --screen-size=1600x840 --window-size=1600x840 --device-pixel-ratio=1.0 \
  "${EXTRA_ARGS[@]}" \
  "$URL"
