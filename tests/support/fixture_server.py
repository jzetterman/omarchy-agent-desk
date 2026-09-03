"""HTTPS fixture server on 127.0.0.1 with canned routes. No outbound network."""

from __future__ import annotations

import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CERT = ROOT / "tests" / "fixtures" / "tls" / "cert.pem"
KEY = ROOT / "tests" / "fixtures" / "tls" / "key.pem"


class FixtureServer:
    """Serve {(method, path): (status, headers, body, delay)} over HTTPS."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []
        self._httpd = None
        self._thread = None
        self.host = "127.0.0.1"
        self.port = 0

    def start(self):
        routes = self.routes
        recorded = self.requests
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                recorded.append({
                    "method": method,
                    "path": self.path,
                    "headers": {k: v for k, v in self.headers.items()},
                    "body": body,
                })
                key = (method, self.path.split("?", 1)[0])
                spec = routes.get(key) or routes.get((method, self.path))
                if spec is None:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"not found")
                    return
                status, headers, resp_body, delay = spec
                if delay:
                    import time
                    time.sleep(delay)
                if status in (301, 302, 303, 307, 308) and "Location" not in (headers or {}):
                    headers = dict(headers or {})
                    headers["Location"] = "https://example.invalid/redirected"
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                body_bytes = resp_body if isinstance(resp_body, bytes) else str(resp_body).encode()
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                if method != "HEAD":
                    self.wfile.write(body_bytes)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_HEAD(self):
                self._handle("HEAD")

        httpd = ThreadingHTTPServer((self.host, 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(CERT), str(KEY))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def origin(self):
        return f"https://{self.host}:{self.port}"

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
