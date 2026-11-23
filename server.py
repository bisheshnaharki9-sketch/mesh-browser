import http.server, socketserver, subprocess, os, re, signal, time, json, glob, shutil
from urllib.parse import urlparse, parse_qs, quote

HOST = "127.0.0.1"
PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
ALLOWED_ORIGINS = {
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
}

active_tabs = {}   # tab_circuit -> {"proc": Popen, "url": str, "disp": str}
tab_counter = 0
tab_to_win = {}

config = {
    "level": "standard",
    "trackers": True,
    "fingerprint": True,
    "isolate": True,
    "erase": True,
    "route": True,
}

def cleanup_stale_socks():
    for d in glob.glob("/tmp/mesh-sock.*"):
        shutil.rmtree(d, ignore_errors=True)

def kill_tab(tab_name):
    info = active_tabs.pop(tab_name, None)
    if not info:
        return False
    p = info["proc"]
    if p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            return True
        except (ProcessLookupError, PermissionError):
            pass
    return False

def kill_all_browsers():
    killed = 0
    for info in list(active_tabs.values()):
        p = info["proc"]
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass
    time.sleep(0.5)
    for info in list(active_tabs.values()):
        p = info["proc"]
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    active_tabs.clear()
    for pattern in ["bwrap.*servoshell", "/app/servoshell"]:
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    cleanup_stale_socks()
    return killed

def sanitize_url(raw):
    u = (raw or "").strip()
    if not u:
        return "http://notbob.i2p/"
    if u.startswith("search:"):
        return "https://duckduckgo.com/?q=" + quote(u[7:])
    u = re.sub(r"^https://([^/]+\.i2p(?:/|$))", r"http://\1", u, flags=re.I)
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or u.startswith("-"):
        return None
    return u

def launch_tab(url, tab, disp=None):
    kill_tab(tab)
    if disp is None:
        try:
            tab_num = int(tab.split("_")[1])
        except (IndexError, ValueError):
            global tab_counter
            tab_counter += 1
            tab_num = tab_counter
        disp = str(2 + ((tab_num - 1) % 4))

    env = os.environ.copy()
    env["MESH_LEVEL"] = config["level"]
    env["MESH_TRACKERS"] = "1" if config["trackers"] else "0"
    env["MESH_FINGERPRINT"] = "1" if config["fingerprint"] else "0"
    env["MESH_ERASE"] = "1" if config["erase"] else "0"

    p = subprocess.Popen(
        ["./mesh-run.sh", url, tab, disp],
        cwd=DIRECTORY,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    active_tabs[tab] = {"proc": p, "url": url, "disp": disp}
    return p

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _cors_origin(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return None
        return origin if origin in ALLOWED_ORIGINS else False

    def _send_json(self, code, payload, origin=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_OPTIONS(self):
        origin = self._cors_origin()
        if origin is False:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        origin = self._cors_origin()
        if origin is False:
            self._send_json(403, {"error": "forbidden origin"})
            return

        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api(parsed, origin)
            return

        if parsed.path == "/":
            self.path = "/ui.html"

        return super().do_GET()

    def handle_api(self, parsed, origin):
        params = parse_qs(parsed.query)

        if parsed.path in ("/api/navigate", "/api/open"):
            url = sanitize_url(params.get("url", ["http://notbob.i2p/"])[0])
            if not url:
                self._send_json(400, {"status": "error", "error": "invalid url"}, origin)
                return

            tab = params.get("tab", ["tab_1"])[0]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", tab):
                tab = "tab_1"

            p = launch_tab(url, tab)
            self._send_json(200, {"status": "ok", "tab": tab, "url": url, "pid": p.pid, "level": config["level"]}, origin)

        elif parsed.path == "/api/newroute":
            old_tab = params.get("old_tab", [""])[0]
            new_tab = params.get("tab", ["tab_1"])[0]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", new_tab):
                new_tab = "tab_1"
            raw_url = params.get("url", [""])[0]
            if old_tab:
                kill_tab(old_tab)
            kill_tab(new_tab)
            restarted = False
            if raw_url:
                url = sanitize_url(raw_url)
                if url:
                    launch_tab(url, new_tab)
                    restarted = True
            self._send_json(200, {"status": "ok", "tab": new_tab, "restarted": restarted}, origin)

        elif parsed.path == "/api/config":
            changed = False
            level = params.get("level", [None])[0]
            if level in ("standard", "safer", "safest") and config["level"] != level:
                config["level"] = level
                changed = True

            pref = params.get("pref", [None])[0]
            val = params.get("val", [None])[0]
            if pref in config and pref != "level" and val in ("0", "1", "true", "false"):
                new_val = val in ("1", "true")
                if config[pref] != new_val:
                    config[pref] = new_val
                    changed = True

            if changed:
                for tab, info in list(active_tabs.items()):
                    if info["proc"].poll() is None:
                        launch_tab(info["url"], tab, info["disp"])

            self._send_json(200, {"status": "ok", "config": config, "reloaded": changed}, origin)

        elif parsed.path == "/api/focus":
            tab = params.get("tab", [""])[0]
            win = tab_to_win.get(tab)
            if win:
                subprocess.run(["xdotool", "windowraise", win], capture_output=True)
            self._send_json(200, {"status": "ok"}, origin)

        elif parsed.path == "/api/close":
            tab = params.get("tab", [""])[0]
            closed = kill_tab(tab)
            self._send_json(200, {"status": "closed", "closed": closed}, origin)

        elif parsed.path == "/api/ident":
            killed = kill_all_browsers()
            self._send_json(200, {"status": "ok", "killed": killed}, origin)

        elif parsed.path == "/api/status":
            self._send_json(200, {"tabs": list(active_tabs.keys()), "config": config, "i2p": True}, origin)

        else:
            self._send_json(404, {"error": "not found"}, origin)

    def log_message(self, format, *args):
        pass

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    cleanup_stale_socks()
    print(f"Mesh Server locked to http://{HOST}:{PORT}")
    with ReusableTCPServer((HOST, PORT), Handler) as httpd:
        httpd.serve_forever()
