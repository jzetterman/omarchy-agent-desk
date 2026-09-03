"""Record schema, status enum, kind order, clamp, and A1b balance.used."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdesk.record import (  # noqa: E402
    KIND_ORDER,
    STATUSES,
    balance_used,
    clamp_used,
    kind_rank,
    normalize,
    normalize_email,
    window_id,
)


class StatusEnumTests(unittest.TestCase):
    def test_known_statuses(self):
        expected = {
            "ok",
            "not-installed",
            "not-signed-in",
            "expired",
            "rate-limited",
            "offline",
            "failed",
            "no-limits",
        }
        self.assertEqual(set(STATUSES), expected)

    def test_unknown_status_becomes_failed(self):
        rec = normalize({"status": "bogus", "provider": "claude"})
        self.assertEqual(rec["status"], "failed")


class KindOrderTests(unittest.TestCase):
    def test_kind_order_tuple(self):
        self.assertEqual(
            list(KIND_ORDER),
            ["session", "weekly", "monthly", "billing-period", "model-scoped"],
        )

    def test_normalize_sorts_kind_then_label(self):
        rec = normalize({
            "status": "ok",
            "provider": "claude",
            "windows": [
                {"kind": "weekly", "label": "Zebra", "used": 0.1},
                {"kind": "session", "label": "Session", "used": 0.2},
                {"kind": "weekly", "label": "Alpha", "used": 0.3},
                {"kind": "model-scoped", "label": "Fable · Weekly", "used": 0.4},
                {"kind": "mystery", "label": "Other", "used": 0.5},
                {"kind": "monthly", "label": "Extra usage", "used": 0.25},
                {"kind": "billing-period", "label": "Credits", "used": 0.6},
            ],
        })
        kinds_labels = [(w["kind"], w["label"]) for w in rec["windows"]]
        self.assertEqual(
            kinds_labels,
            [
                ("session", "Session"),
                ("weekly", "Alpha"),
                ("weekly", "Zebra"),
                ("monthly", "Extra usage"),
                ("billing-period", "Credits"),
                ("model-scoped", "Fable · Weekly"),
                ("mystery", "Other"),
            ],
        )

    def test_unknown_kind_ranks_after_known(self):
        self.assertGreater(kind_rank("mystery"), kind_rank("model-scoped"))


class ClampTests(unittest.TestCase):
    def test_clamp_to_unit_interval(self):
        self.assertEqual(clamp_used(1.5), 1.0)
        self.assertEqual(clamp_used(-0.1), 0.0)
        self.assertEqual(clamp_used(0.4), 0.4)

    def test_non_finite_clamps_to_zero(self):
        self.assertEqual(clamp_used(float("nan")), 0.0)
        self.assertEqual(clamp_used(float("inf")), 1.0)

    def test_normalize_clamps_window_used(self):
        rec = normalize({
            "status": "ok",
            "provider": "claude",
            "windows": [{"kind": "session", "label": "Session", "used": 150}],
        })
        self.assertEqual(rec["windows"][0]["used"], 1.0)


class BalanceUsedTests(unittest.TestCase):
    def test_remaining_only_above_zero(self):
        self.assertEqual(balance_used({"remaining": 5}), 0.0)

    def test_remaining_zero(self):
        self.assertEqual(balance_used({"remaining": 0}), 1.0)

    def test_spent_over_funded(self):
        self.assertEqual(
            balance_used({"remaining": 6, "funded": 10, "spent": 4}),
            0.4,
        )

    def test_all_zero(self):
        self.assertEqual(
            balance_used({"remaining": 0, "funded": 0, "spent": 0}),
            1.0,
        )

    def test_never_nan_or_inf(self):
        used = balance_used({"remaining": 1, "funded": 0, "spent": 4})
        self.assertTrue(math.isfinite(used))
        self.assertGreaterEqual(used, 0.0)
        self.assertLessEqual(used, 1.0)

    def test_normalize_sets_balance_used(self):
        rec = normalize({
            "status": "ok",
            "provider": "grok",
            "balance": {"remaining": 6, "funded": 10, "spent": 4, "unit": "USD", "precision": 2},
        })
        self.assertEqual(rec["balance"]["used"], 0.4)


class WindowIdTests(unittest.TestCase):
    def test_supplied_id_kept(self):
        self.assertEqual(
            window_id({"id": "model:x:weekly", "kind": "model-scoped", "label": "X"}),
            "model:x:weekly",
        )

    def test_derived_id(self):
        self.assertEqual(
            window_id({"kind": "weekly", "label": "Weekly"}),
            "weekly:weekly",
        )


class EmailTests(unittest.TestCase):
    def test_normalize_email_domain_and_local(self):
        self.assertEqual(normalize_email(" John+tag@Example.COM "), "john+tag@example.com")

    def test_empty_never_matches(self):
        self.assertEqual(normalize_email(""), "")
        self.assertEqual(normalize_email("   "), "")


class AllowlistTests(unittest.TestCase):
    def test_drops_token_keys(self):
        rec = normalize({
            "status": "ok",
            "provider": "claude",
            "accessToken": "secret",
            "identity": {"email": "a@b.c", "token": "nope", "org": "Org", "plan": "Max"},
            "windows": [{"kind": "session", "label": "Session", "used": 0.1, "authorization": "x"}],
        })
        dumped = str(rec)
        self.assertNotIn("secret", dumped)
        self.assertNotIn("nope", dumped)
        self.assertNotIn("accessToken", dumped)
        self.assertEqual(rec["identity"]["email"], "a@b.c")


if __name__ == "__main__":
    unittest.main()
