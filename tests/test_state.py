"""state.json validate, publish round-trip, generation, and file modes."""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdesk.state import (  # noqa: E402
    bump_and_publish,
    empty_state,
    load,
    publish,
    validate,
)

AID = "a" * 32


def valid_account(**overrides):
    acct = {
        "id": AID,
        "provider": "claude",
        "kind": "imported",
        "name": "default",
        "home": "/home/tester/.claude",
        "homeFromEnv": False,
        "createdAt": "2023-11-14T13:46:40Z",
        "generation": 1,
    }
    acct.update(overrides)
    return acct


class ValidateTests(unittest.TestCase):
    def test_rejects_garbage(self):
        self.assertIsNone(validate(None))
        self.assertIsNone(validate("nope"))
        self.assertIsNone(validate(["x"]))
        self.assertIsNone(validate({"schemaVersion": 2, "accounts": []}))
        self.assertIsNone(validate({"schemaVersion": 1, "accounts": "x"}))
        self.assertIsNone(validate({"schemaVersion": 1, "accounts": [{"id": "nope"}]}))

    def test_rejects_bad_account_generation(self):
        doc = empty_state()
        doc["accounts"] = [valid_account(generation="oops")]
        self.assertIsNone(validate(doc))

    def test_rejects_bad_top_generation(self):
        doc = empty_state()
        doc["generation"] = "oops"
        self.assertIsNone(validate(doc))

    def test_rejects_bad_provider_id(self):
        doc = empty_state()
        doc["accounts"] = [valid_account(provider="Claude")]
        self.assertIsNone(validate(doc))
        doc["accounts"] = [valid_account(provider="foo_bar")]
        self.assertIsNone(validate(doc))

    def test_rejects_bad_routing_types(self):
        doc = empty_state()
        doc["accounts"] = [valid_account()]
        doc["routing"] = {
            "installed": False,
            "partial": False,
            "shims": "claude",
            "shadowed": {},
            "rcFile": None,
            "rcCreated": False,
        }
        self.assertIsNone(validate(doc))
        doc["routing"] = {
            "installed": False,
            "partial": False,
            "shims": [],
            "shadowed": ["x"],
            "rcFile": None,
            "rcCreated": False,
        }
        self.assertIsNone(validate(doc))

    def test_round_trip(self):
        doc = empty_state()
        doc["accounts"] = [valid_account()]
        cleaned = validate(doc)
        self.assertIsNotNone(cleaned)
        again = validate(cleaned)
        self.assertEqual(again["accounts"][0]["id"], AID)
        self.assertEqual(again["accounts"][0]["provider"], "claude")
        self.assertEqual(again["active"]["claude"], AID)


class PublishTests(unittest.TestCase):
    def test_generation_monotonic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            doc = empty_state()
            d1 = bump_and_publish(path, doc)
            self.assertEqual(d1["generation"], 1)
            d2 = bump_and_publish(path, d1)
            self.assertEqual(d2["generation"], 2)
            loaded, err = load(path)
            self.assertIsNone(err)
            self.assertEqual(loaded["generation"], 2)

    def test_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-desk" / "state.json"
            doc = empty_state()
            publish(path, doc)
            st = path.stat()
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)
            dst = path.parent.stat()
            self.assertEqual(stat.S_IMODE(dst.st_mode), 0o700)

    def test_load_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            doc, err = load(path)
            self.assertIsNone(doc)
            self.assertEqual(err, "state-unreadable")


if __name__ == "__main__":
    unittest.main()
