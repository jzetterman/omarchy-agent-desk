"""Claude collector: every section-4 status from fixtures, plus scale sniff."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agentdesk.clock import Clock  # noqa: E402
from agentdesk.descriptor import load_all  # noqa: E402
from agentdesk.http import HttpResult  # noqa: E402
from support.fake_clock import FakeClock  # noqa: E402
from support.homes import NOW, fixture_home  # noqa: E402

COLLECTOR_PATH = ROOT / "providers" / "claude" / "collector.py"
PAYLOADS = ROOT / "tests" / "fixtures" / "payloads" / "claude"


def load_collector():
    import importlib.util

    spec = importlib.util.spec_from_file_location("claude_collector", COLLECTOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def descriptor():
    loaded, errors = load_all(ROOT / "providers")
    assert not errors, errors
    return loaded[0]


def payload(name: str) -> bytes:
    return (PAYLOADS / name).read_bytes()


class FakeHttp:
    def __init__(self, result: HttpResult):
        self.result = result
        self.calls = []

    def get(self, url, headers=None, timeout=10):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        return self.result

    def post(self, url, body=None, headers=None, timeout=10, cap=10):
        raise AssertionError("Claude default-home collector must not POST")


class CollectorClaudeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_collector()
        self.desc = descriptor()
        self.clock = FakeClock(now=NOW, monotonic=NOW)

    def run_full(self, home, http, binary="/usr/bin/claude", home_kind="default", home_env_set=False):
        return self.mod.collect(
            mode="full",
            home=str(home),
            home_kind=home_kind,
            home_env_set=home_env_set,
            binary=binary,
            deadline=NOW + 30,
            clock=self.clock,
            http=http,
            descriptor=self.desc,
        )

    def test_not_installed(self):
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", FakeHttp(HttpResult("ok", 200, b"{}")), binary="")
        self.assertEqual(rec["status"], "not-installed")
        self.assertIn("mise", rec["help"].lower())

    def test_not_signed_in(self):
        with fixture_home("not-signed-in") as home:
            rec = self.run_full(home / ".claude", FakeHttp(HttpResult("ok", 200, b"{}")))
        self.assertEqual(rec["status"], "not-signed-in")

    def test_api_key_only_is_not_signed_in(self):
        with fixture_home("api-key-only") as home:
            rec = self.run_full(home / ".claude", FakeHttp(HttpResult("ok", 200, b"{}")))
        self.assertEqual(rec["status"], "not-signed-in")

    def test_expired_default_home_opens_no_socket(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("expired-9min") as home:
            rec = self.run_full(home / ".claude", http, home_kind="default")
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["statusReason"], "default-home")
        self.assertEqual(http.calls, [])

    def test_401_expired_rejected(self):
        http = FakeHttp(HttpResult("auth", 401, b"nope"))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["statusReason"], "rejected")
        self.assertEqual(len(http.calls), 1)

    def test_429_rate_limited(self):
        http = FakeHttp(HttpResult("rate-limited", 429, b""))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "rate-limited")

    def test_offline(self):
        http = FakeHttp(HttpResult("offline", None, None))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "offline")

    def test_timeout_failed(self):
        http = FakeHttp(HttpResult("failed", None, None, error="timeout"))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "failed")

    def test_5xx_failed(self):
        http = FakeHttp(HttpResult("failed", 503, b"down"))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "failed")

    def test_3xx_failed_no_second_request(self):
        http = FakeHttp(HttpResult("failed", 302, b""))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "failed")
        self.assertEqual(len(http.calls), 1)

    def test_malformed_failed(self):
        http = FakeHttp(HttpResult("ok", 200, payload("malformed.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "failed")

    def test_no_limits(self):
        http = FakeHttp(HttpResult("ok", 200, payload("no-limits.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "no-limits")

    def test_ok_and_scale_sniff_pairs(self):
        frac_http = FakeHttp(HttpResult("ok", 200, payload("ok-fraction.json")))
        pts_http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("signed-in") as home:
            frac = self.run_full(home / ".claude", frac_http)
            pts = self.run_full(home / ".claude", pts_http)
        self.assertEqual(frac["status"], "ok")
        self.assertEqual(pts["status"], "ok")
        frac_used = {w["id"]: w["used"] for w in frac["windows"]}
        pts_used = {w["id"]: w["used"] for w in pts["windows"]}
        self.assertEqual(frac_used, pts_used)
        self.assertAlmostEqual(frac_used["session"], 0.05)
        self.assertAlmostEqual(frac_used["weekly"], 0.81)
        self.assertAlmostEqual(frac_used["model:claude-fable-5:weekly_scoped"], 0.02)
        self.assertAlmostEqual(frac_used["monthly:extra usage"], 0.25)
        kinds = [w["kind"] for w in frac["windows"]]
        self.assertEqual(kinds[:4], ["session", "weekly", "monthly", "model-scoped"])
        model = next(w for w in frac["windows"] if w["kind"] == "model-scoped")
        self.assertEqual(model["label"], "Fable · Weekly")
        extra = next(w for w in frac["windows"] if w["kind"] == "monthly")
        self.assertEqual(extra["label"], "Extra usage")

    def test_points_payload_all_below_one_reads_as_fraction(self):
        # Documented sniff edge: a points payload fresh after reset with every
        # value below 1 is read as a fraction (0.4 → 40%), then self-corrects
        # on the next fetch that has any value above 1.
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points-below-one.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        used = {w["kind"]: w["used"] for w in rec["windows"]}
        self.assertAlmostEqual(used["session"], 0.4)

    def test_clamp_above_100(self):
        http = FakeHttp(HttpResult("ok", 200, payload("clamp.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        session = next(w for w in rec["windows"] if w["kind"] == "session")
        self.assertEqual(session["used"], 1.0)

    def test_identity_from_default_claude_json(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http, home_env_set=False)
        self.assertEqual(rec["identity"]["email"], "John@Example.COM")
        self.assertEqual(rec["identity"]["org"], "Example Org")
        self.assertEqual(rec["identity"]["plan"], "Max 20x")

    def test_two_entries_uses_oauth_not_api_key(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("two-entries") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["identity"]["plan"], "Pro")

    def test_identity_mode_opens_no_socket(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("signed-in") as home:
            rec = self.mod.collect(
                mode="identity",
                home=str(home / ".claude"),
                home_kind="default",
                home_env_set=False,
                binary="/usr/bin/claude",
                deadline=NOW + 30,
                clock=self.clock,
                http=http,
                descriptor=self.desc,
            )
        self.assertEqual(http.calls, [])
        self.assertNotEqual(rec["status"], "not-signed-in")
        self.assertEqual(rec["identity"]["email"], "John@Example.COM")

    def test_token_not_in_record(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        dumped = json.dumps(rec)
        self.assertNotIn("sk-ant-fixture-token-DO-NOT-LEAK", dumped)
        self.assertNotIn("sk-ant-fixture-refresh-DO-NOT-LEAK", dumped)

    def test_authorization_header_equals_fixture_token(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-points.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(
            http.calls[0]["headers"]["Authorization"],
            "Bearer sk-ant-fixture-token-DO-NOT-LEAK",
        )

    def test_mixed_sniff_points_scale_on_session(self):
        http = FakeHttp(HttpResult("ok", 200, payload("ok-mixed-sniff.json")))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        used = {w["kind"]: w["used"] for w in rec["windows"]}
        self.assertAlmostEqual(used["session"], 0.004)
        self.assertAlmostEqual(used["weekly"], 0.81)

    def test_negative_utilization_clamped_not_dropped(self):
        body = json.dumps({
            "five_hour": {"utilization": -5, "resets_at": "2023-11-14T15:13:20Z"},
            "seven_day": {"utilization": 0.5, "resets_at": "2023-11-19T13:46:40Z"},
        }).encode()
        http = FakeHttp(HttpResult("ok", 200, body))
        with fixture_home("signed-in") as home:
            rec = self.run_full(home / ".claude", http)
        session = next(w for w in rec["windows"] if w["kind"] == "session")
        self.assertEqual(session["used"], 0.0)

    def test_read_json_fifo_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fifo.json"
            os.mkfifo(path)
            start = time.monotonic()
            rec = self.mod.read_json(path)
            elapsed = time.monotonic() - start
        self.assertIsNone(rec)
        self.assertLess(elapsed, 0.5)

    def test_build_http_and_clock_ignore_env_without_test(self):
        old_now = os.environ.get("AGENT_DESK_NOW")
        old_ca = os.environ.get("AGENT_DESK_CA_FILE")
        os.environ["AGENT_DESK_NOW"] = "123"
        os.environ["AGENT_DESK_CA_FILE"] = "/tmp/no-such-ca.pem"
        try:
            http = self.mod.build_http(False)
            clock = self.mod.build_clock(False)
            self.assertIsNone(http.cafile)
            self.assertIs(type(clock), Clock)
            self.assertGreater(clock.now(), 1.7e9)
        finally:
            if old_now is None:
                os.environ.pop("AGENT_DESK_NOW", None)
            else:
                os.environ["AGENT_DESK_NOW"] = old_now
            if old_ca is None:
                os.environ.pop("AGENT_DESK_CA_FILE", None)
            else:
                os.environ["AGENT_DESK_CA_FILE"] = old_ca


if __name__ == "__main__":
    unittest.main()
