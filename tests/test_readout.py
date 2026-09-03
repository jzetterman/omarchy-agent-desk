"""A7: readout scope, thresholds, ties, and empty scope."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdesk.runner import compute_readout  # noqa: E402


def acct(aid, provider, kind="imported", created="2023-11-14T13:46:40Z", name=None):
    return {
        "id": aid,
        "provider": provider,
        "kind": kind,
        "name": name or aid[:6],
        "home": "/home/x/.claude" if kind == "imported" else None,
        "homeFromEnv": False,
        "createdAt": created,
        "generation": 1,
    }


def rec(used, label="Weekly", kind="weekly", fetched="2023-11-14T13:46:40Z"):
    return {
        "status": "ok",
        "identity": {"email": "a@b.c", "org": "", "plan": ""},
        "windows": [{
            "id": kind,
            "kind": kind,
            "label": label,
            "used": used,
            "resetsAt": "2023-11-19T13:46:40Z",
        }],
        "balance": None,
        "fetchedAt": fetched,
        "collectedAt": fetched,
    }


PROVIDERS = [
    {"id": "claude", "name": "Claude Code", "enabled": True, "installed": True},
    {"id": "codex", "name": "Codex", "enabled": True, "installed": True},
]


class ReadoutTests(unittest.TestCase):
    def test_active_scope_default(self):
        accounts = [
            acct("c1" + "0" * 30, "claude", name="personal"),
            acct("c2" + "0" * 30, "claude", kind="isolated", name="work"),
        ]
        records = {
            accounts[0]["id"]: rec(0.4),
            accounts[1]["id"]: rec(0.9),
        }
        active = {"claude": accounts[0]["id"]}
        out = compute_readout(
            accounts, records, active, PROVIDERS, ["claude", "codex"],
            scope="active", warning=0.75, critical=0.90,
        )
        self.assertAlmostEqual(out["used"], 0.4)
        self.assertEqual(out["level"], "normal")
        self.assertEqual(out["top"]["accountName"], "personal")

    def test_all_scope_takes_highest(self):
        accounts = [
            acct("c1" + "0" * 30, "claude", name="personal"),
            acct("c2" + "0" * 30, "claude", kind="isolated", name="work"),
        ]
        records = {
            accounts[0]["id"]: rec(0.4),
            accounts[1]["id"]: rec(0.9),
        }
        active = {"claude": accounts[0]["id"]}
        out = compute_readout(
            accounts, records, active, PROVIDERS, ["claude", "codex"],
            scope="all", warning=0.75, critical=0.90,
        )
        self.assertAlmostEqual(out["used"], 0.9)
        self.assertEqual(out["level"], "critical")
        self.assertEqual(out["top"]["accountName"], "work")

    def test_threshold_749_normal_75_warning(self):
        accounts = [acct("c1" + "0" * 30, "claude", name="personal")]
        active = {"claude": accounts[0]["id"]}
        low = compute_readout(
            accounts, {accounts[0]["id"]: rec(0.749)}, active, PROVIDERS, ["claude"],
            scope="active", warning=0.75, critical=0.90,
        )
        self.assertEqual(low["level"], "normal")
        self.assertAlmostEqual(low["used"], 0.749)
        high = compute_readout(
            accounts, {accounts[0]["id"]: rec(0.75)}, active, PROVIDERS, ["claude"],
            scope="active", warning=0.75, critical=0.90,
        )
        self.assertEqual(high["level"], "warning")

    def test_empty_scope(self):
        out = compute_readout([], {}, {}, PROVIDERS, ["claude"], "active", 0.75, 0.90)
        self.assertEqual(out, {"used": None, "level": "none", "top": None})

    def test_ties_provider_then_card_then_kind(self):
        accounts = [
            acct("c1" + "0" * 30, "claude", name="claude-a"),
            acct("x1" + "0" * 30, "codex", name="codex-a"),
        ]
        records = {
            accounts[0]["id"]: rec(0.5, label="Weekly", kind="weekly"),
            accounts[1]["id"]: rec(0.5, label="Weekly", kind="weekly"),
        }
        active = {"claude": accounts[0]["id"], "codex": accounts[1]["id"]}
        out = compute_readout(
            accounts, records, active, PROVIDERS, ["claude", "codex"],
            scope="all", warning=0.75, critical=0.90,
        )
        self.assertEqual(out["top"]["provider"], "claude")

        one = acct("c1" + "0" * 30, "claude", name="one")
        records = {
            one["id"]: {
                "status": "ok",
                "identity": {},
                "windows": [
                    {"id": "weekly", "kind": "weekly", "label": "Weekly", "used": 0.5, "resetsAt": None},
                    {"id": "session", "kind": "session", "label": "Session", "used": 0.5, "resetsAt": None},
                ],
                "balance": None,
                "fetchedAt": "t",
                "collectedAt": "t",
            }
        }
        out = compute_readout(
            [one], records, {"claude": one["id"]}, PROVIDERS, ["claude"],
            scope="active", warning=0.75, critical=0.90,
        )
        self.assertEqual(out["top"]["label"], "Session")

    def test_disabled_provider_excluded(self):
        accounts = [acct("c1" + "0" * 30, "claude", name="personal")]
        providers = [{"id": "claude", "name": "Claude Code", "enabled": False, "installed": True}]
        out = compute_readout(
            accounts, {accounts[0]["id"]: rec(0.9)}, {"claude": accounts[0]["id"]},
            providers, ["claude"], "all", 0.75, 0.90,
        )
        self.assertEqual(out["used"], None)
        self.assertEqual(out["level"], "none")

    def test_balance_top_includes_funded_and_spent(self):
        accounts = [acct("c1" + "0" * 30, "claude", name="personal")]
        records = {
            accounts[0]["id"]: {
                "status": "ok",
                "identity": {},
                "windows": [],
                "balance": {
                    "remaining": 6,
                    "funded": 10,
                    "spent": 4,
                    "unit": "USD",
                    "precision": 2,
                    "used": 0.4,
                },
                "fetchedAt": "t",
                "collectedAt": "t",
            }
        }
        out = compute_readout(
            accounts, records, {"claude": accounts[0]["id"]},
            PROVIDERS, ["claude"], "active", 0.75, 0.90,
        )
        self.assertEqual(out["top"]["kind"], "balance")
        self.assertEqual(out["top"]["funded"], 10)
        self.assertEqual(out["top"]["spent"], 4)
        self.assertEqual(out["top"]["remaining"], 6)

    def test_accounts_present_but_no_numeric_used(self):
        accounts = [acct("c1" + "0" * 30, "claude", name="personal")]
        records = {
            accounts[0]["id"]: {
                "status": "ok",
                "identity": {"email": "a@b.c"},
                "windows": [{"id": "session", "kind": "session", "label": "Session", "used": None}],
                "balance": None,
                "fetchedAt": "t",
                "collectedAt": "t",
            }
        }
        out = compute_readout(
            accounts, records, {"claude": accounts[0]["id"]},
            PROVIDERS, ["claude"], "active", 0.75, 0.90,
        )
        self.assertEqual(out, {"used": None, "level": "none", "top": None})


if __name__ == "__main__":
    unittest.main()
