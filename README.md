# Mesh Browser

A sandboxed, hybrid **I2P + Nym Mixnet** desktop browser built around a custom toolbar-free **Servo** (`servoshell`) engine, **Bubblewrap (`bwrap`)** per-tab isolation, **Xvfb + noVNC** display separation, and automatic **`mat2`** metadata scrubbing.

---

## Architecture

- **Desktop App Shell (`mesh-app.py`)**
  Native GTK3 + WebKit2 (`4.1`) window that hosts the browser UI (`ui.html`) on `127.0.0.1:8080` or run ./start-mesh.sh then an tauri app opens simple use.
- **Control Server (`server.py`)**
  Locked to `127.0.0.1:8080` with strict origin checks and URL sanitization. Manages per-tab sandboxes, security levels, privacy toggles, route resets, and identity wipes.
- **Hybrid Fail-Closed Proxy (`mesh-router.py`)**
  Listens on `127.0.0.1:4446`:
  - `*.i2p` domains → forwarded to **`i2pd`** (`127.0.0.1:4444`)
  - Clearnet (`http://` / `https://`) → forwarded to **`nym-socks5-client`** (`127.0.0.1:1080`) using SOCKS5 remote DNS (`ATYP=0x03`)
  - Blocks localhost / private LAN addresses and **fails closed** (never falls back to your real IP) if Nym is offline.
- **Per-Tab Sandbox (`mesh-run.sh`)**
  Launches `servoshell` inside `bwrap` with:
  - `--cap-drop ALL`, `--unshare-net`, `--unshare-pid`, `--unshare-uts`, `--unshare-cgroup`, `--clearenv`
  - Host-side Unix socket bridge (`socat`) into the sandbox (no direct network interfaces inside)
  - Isolated `Xvfb` display (`:2`–`:5`) + borderless `openbox` + `x11vnc` + `websockify`/`novnc` (`6080`–`6083`)
- **Metadata Vault (`mesh-scrubber.py`)**
  Watches `~/Mesh-Share`, strips EXIF/GPS/author metadata with `mat2`, zeroes timestamps, and mounts cleaned files read-only inside sandboxes at `/home/mesh/Share` (unsupported file types are blocked).

---

## Security Levels & Privacy Controls

Configured live from the UI (`Standard` / `Safer` / `Safest`):

- **Standard:** `mesh-prefs.json` baseline (WebRTC, WebGPU, WebXR, Geolocation, Bluetooth, Gamepad, Notifications, Permissions, OffscreenCanvas disabled) + `userscripts/01-mesh-rfp.js` fingerprint normalization.
- **Safer:** Disables JS JITs (`js_disable_jit`, `js_ion_enabled=false`, `js_offthread_compilation_enabled=false`), WASM JITs (`js_wasm_baseline_enabled=false`, `js_wasm_ion_enabled=false`), WebGL2, Web Fonts (`dom_fontface_enabled=false`), ServiceWorkers, SharedWorkers, and Worklets.
- **Safest:** Adds `js_baseline_interpreter_enabled=false`, disables IndexedDB, CookieStore, StorageManager, CredentialManagement, WakeLock, Async Clipboard, Canvas text/capture, and hides `<video>`/`<audio>` via `safest.css`.
- **Block Trackers:** Enables Servo's `--host-file=/app/blocklist.hosts` to sinkhole tracker domains at the network layer.
- **New Route:** Terminates and respawns the active tab's `bwrap` + `servoshell` sandbox cleanly.
- **New Identity:** Kills all running tab sandboxes, removes stale socket directories, and opens a fresh session.

---

## Prerequisites

- `i2pd` running on `127.0.0.1:4444` (`sudo systemctl enable --now i2pd`)
- Initialized Nym client profile (`mesh-nym` in `~/.nym/socks5-clients/mesh-nym/`)
- System tools: `bwrap`, `socat`, `xvfb`, `openbox`, `x11vnc`, `websockify`, `xdotool`, `mat2`, `python3-gi`, `gir1.2-webkit2-4.1`

---

## Usage & Installation
- git clone https://github.com/bisheshnaharki9-sketch/mesh-browser.git
- cd mesh-browser
# Download servoshell-runtime-linux-x86_64.tar.gz and nym-socks5-client from the latest Release, then:
- tar -xzvf servoshell-runtime-linux-x86_64.tar.gz
- chmod +x servoshell nym-socks5-client start-mesh.sh mesh-run.sh
- ./start-mesh.sh
- Start the full Mesh Browser stack 

