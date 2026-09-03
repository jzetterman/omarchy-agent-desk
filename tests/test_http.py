"""HTTPS policy: redirects refused, TLS verified, http:// rejected."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agentdesk.http import Http  # noqa: E402
from support.fixture_server import CERT, FixtureServer  # noqa: E402


class HttpPolicyTests(unittest.TestCase):
    def test_https_assert(self):
        http = Http()
        result = http.get("http://127.0.0.1/usage")
        self.assertEqual(result.outcome, "failed")
        self.assertIsNone(result.body)

    def test_redirect_refused_no_second_request(self):
        routes = {
            ("GET", "/usage"): (302, {"Location": "https://example.invalid/next"}, b"", 0),
        }
        with FixtureServer(routes) as server:
            http = Http(cafile=str(CERT))
            result = http.get(server.origin + "/usage")
            self.assertEqual(result.outcome, "failed")
            self.assertEqual(len(server.requests), 1)
            self.assertEqual(server.requests[0]["path"], "/usage")

    def test_tls_default_rejects_untrusted_cert(self):
        routes = {("GET", "/usage"): (200, {"Content-Type": "application/json"}, b"{}", 0)}
        with FixtureServer(routes) as server:
            http = Http()
            result = http.get(server.origin + "/usage")
            self.assertEqual(result.outcome, "failed")

    def test_tls_with_cafile_succeeds(self):
        body = json.dumps({"ok": True}).encode()
        routes = {("GET", "/usage"): (200, {"Content-Type": "application/json"}, body, 0)}
        with FixtureServer(routes) as server:
            http = Http(cafile=str(CERT))
            result = http.get(server.origin + "/usage")
            self.assertEqual(result.outcome, "ok")
            self.assertEqual(result.status, 200)
            self.assertEqual(json.loads(result.body.decode()), {"ok": True})

    def test_429_rate_limited(self):
        routes = {("GET", "/usage"): (429, {}, b"slow down", 0)}
        with FixtureServer(routes) as server:
            http = Http(cafile=str(CERT))
            result = http.get(server.origin + "/usage")
            self.assertEqual(result.outcome, "rate-limited")

    def test_401_auth(self):
        routes = {("GET", "/usage"): (401, {}, b"nope", 0)}
        with FixtureServer(routes) as server:
            http = Http(cafile=str(CERT))
            result = http.get(server.origin + "/usage")
            self.assertEqual(result.outcome, "auth")

    def test_5xx_failed(self):
        routes = {("GET", "/usage"): (503, {}, b"down", 0)}
        with FixtureServer(routes) as server:
            http = Http(cafile=str(CERT))
            result = http.get(server.origin + "/usage")
            self.assertEqual(result.outcome, "failed")


if __name__ == "__main__":
    unittest.main()
