import ipaddress
import socket
import socketserver
import struct
import threading
from urllib.parse import urlsplit

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 4446
I2P_HOST, I2P_PORT = "127.0.0.1", 4444
NYM_HOST, NYM_PORT = "127.0.0.1", 1080

STRIP_REQ_HEADERS = {
    b"proxy-connection",
    b"connection",
    b"if-none-match",
    b"if-modified-since",
    b"dnt",
    b"accept-language",
    b"referer",
}

def is_i2p(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    return h == "i2p" or h.endswith(".i2p")

def is_private_ip(host: str) -> bool:
    h = (host or "").strip("[]").lower()
    if h in ("localhost", "localhost.localdomain"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    except ValueError:
        return False

def scrub_http_request(lines, target_host, new_req_line=None):
    out = [new_req_line if new_req_line else lines[0]]
    for ln in lines[1:]:
        name = ln.split(b":", 1)[0].strip().lower()
        if name == b"referer":
            # Keep only same-host referer; strip all cross-site referers
            ref_val = ln.split(b":", 1)[1].strip().decode("latin1", "ignore")
            try:
                if urlsplit(ref_val).hostname and urlsplit(ref_val).hostname.lower() == target_host.lower():
                    out.append(ln)
            except Exception:
                pass
            continue
        if name in STRIP_REQ_HEADERS:
            continue
        out.append(ln)
    out.append(b"Accept-Language: en-US,en;q=0.5")
    out.append(b"Connection: close")
    return out

def socks5_connect(host: str, port: int, timeout: float = 25.0) -> socket.socket:
    host_b = host.encode("idna")
    if len(host_b) > 255:
        raise ValueError("hostname too long")
    s = socket.create_connection((NYM_HOST, NYM_PORT), timeout=timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        resp = s.recv(2)
        if len(resp) != 2 or resp != b"\x05\x00":
            raise ConnectionError("SOCKS5 auth failed")

        req = b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack("!H", port)
        s.sendall(req)

        hdr = b""
        while len(hdr) < 4:
            chunk = s.recv(4 - len(hdr))
            if not chunk:
                raise ConnectionError("SOCKS5 EOF")
            hdr += chunk
        if hdr[1] != 0:
            raise ConnectionError(f"SOCKS5 error code {hdr[1]}")

        atyp = hdr[3]
        if atyp == 1:
            s.recv(6)
        elif atyp == 4:
            s.recv(18)
        elif atyp == 3:
            ln = s.recv(1)
            if ln:
                s.recv(ln[0] + 2)
        s.settimeout(300.0)
        return s
    except Exception:
        s.close()
        raise

def relay(a: socket.socket, b: socket.socket):
    def pump(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass

    t1 = threading.Thread(target=pump, args=(a, b), daemon=True)
    t2 = threading.Thread(target=pump, args=(b, a), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

def send_err(client: socket.socket, code: int, msg: str):
    body = msg.encode("utf-8", "replace")
    hdr = (
        f"HTTP/1.1 {code} Bad Gateway\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    try:
        client.sendall(hdr + body)
    except Exception:
        pass

class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(30.0)
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                return
            buf += chunk

        sep = buf.find(b"\r\n\r\n")
        if sep == -1:
            return
        head_bytes = buf[:sep]
        rest = buf[sep + 4:]
        lines = head_bytes.split(b"\r\n")
        parts = lines[0].decode("latin1").split(" ")
        if len(parts) < 3:
            return
        method, target, version = parts[0].upper(), parts[1], parts[2]
        client.settimeout(300.0)

        if method == "CONNECT":
            if target.startswith("["):
                hp = target[1:].split("]:", 1)
                host, port = hp[0], int(hp[1]) if len(hp) > 1 else 443
            elif ":" in target:
                host, pstr = target.rsplit(":", 1)
                port = int(pstr)
            else:
                host, port = target, 443

            if is_i2p(host):
                try:
                    up = socket.create_connection((I2P_HOST, I2P_PORT), timeout=30.0)
                    up.settimeout(300.0)
                    up.sendall(buf)
                    relay(client, up)
                    up.close()
                except Exception as e:
                    send_err(client, 502, f"I2P proxy error: {e}\n")
                return

            if is_private_ip(host):
                send_err(client, 403, "Blocked local/private address\n")
                return

            try:
                up = socks5_connect(host, port)
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    up.sendall(rest)
                relay(client, up)
                up.close()
            except Exception as e:
                send_err(client, 502, f"Nym Mixnet unavailable (fail-closed): {e}\n")
            return

        # Plain HTTP request
        parsed = urlsplit(target)
        host = parsed.hostname or ""
        if not host:
            for ln in lines[1:]:
                if ln.lower().startswith(b"host:"):
                    hval = ln.split(b":", 1)[1].strip().decode("latin1")
                    host = hval.split(":")[0]
                    break
        port = parsed.port or 80

        if is_i2p(host):
            scrubbed = b"\r\n".join(scrub_http_request(lines, host)) + b"\r\n\r\n" + rest
            try:
                up = socket.create_connection((I2P_HOST, I2P_PORT), timeout=30.0)
                up.settimeout(300.0)
                up.sendall(scrubbed)
                relay(client, up)
                up.close()
            except Exception as e:
                send_err(client, 502, f"I2P proxy error: {e}\n")
            return

        if not host or is_private_ip(host):
            send_err(client, 403, "Blocked local/private address\n")
            return

        path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        req_line = f"{method} {path} {version}".encode("latin1")
        payload = b"\r\n".join(scrub_http_request(lines, host, req_line)) + b"\r\n\r\n" + rest

        try:
            up = socks5_connect(host, port)
            up.sendall(payload)
            relay(client, up)
            up.close()
        except Exception as e:
            send_err(client, 502, f"Nym Mixnet unavailable (fail-closed): {e}\n")

class ThreadedProxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    print(f"Mesh Hybrid Router (.i2p->4444, clearnet->1080) on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    with ThreadedProxy((LISTEN_HOST, LISTEN_PORT), ProxyHandler) as srv:
        srv.serve_forever()
