"""Descriptor loader: https-only URLs, homeEnv shape, invalid dirs reported."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdesk.descriptor import load_all  # noqa: E402


def _write_descriptor(dirpath: Path, doc: dict) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "descriptor.json").write_text(json.dumps(doc), encoding="utf-8")


VALID = {
    "schemaVersion": 1,
    "id": "claude",
    "name": "Claude Code",
    "mark": "mark.svg",
    "markLight": "mark-light.svg",
    "glyph": "x",
    "binary": "claude",
    "homeEnv": "CLAUDE_CONFIG_DIR",
    "defaultHome": "~/.claude",
    "commands": {
        "login": ["claude", "auth", "login"],
        "logout": ["claude", "auth", "logout"],
        "launch": ["claude"],
    },
    "credential": {
        "file": ".credentials.json",
        "currentEntry": "claudeAiOauth",
        "lockFile": None,
        "tempFiles": {"refresh": "r", "transaction": "t"},
    },
    "sharedEntries": [],
    "accountState": [],
    "scale": "sniff",
    "installDirs": [],
    "urls": {
        "usage": "https://api.anthropic.com/api/oauth/usage",
        "identity": None,
        "refresh": "https://platform.claude.com/v1/oauth/token",
        "refreshFormat": "json",
        "clientId": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        "clientIdKey": None,
    },
}


class DescriptorTests(unittest.TestCase):
    def test_valid_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_descriptor(Path(tmp) / "claude", VALID)
            loaded, errors = load_all(Path(tmp))
            self.assertEqual(errors, [])
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["id"], "claude")

    def test_http_url_rejected(self):
        doc = json.loads(json.dumps(VALID))
        doc["urls"]["usage"] = "http://api.anthropic.com/api/oauth/usage"
        with tempfile.TemporaryDirectory() as tmp:
            _write_descriptor(Path(tmp) / "claude", doc)
            loaded, errors = load_all(Path(tmp))
            self.assertEqual(loaded, [])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]["dir"], "claude")
            self.assertIn("https", errors[0]["message"].lower())

    def test_home_env_shape(self):
        doc = json.loads(json.dumps(VALID))
        doc["homeEnv"] = "claude-config-dir"
        with tempfile.TemporaryDirectory() as tmp:
            _write_descriptor(Path(tmp) / "claude", doc)
            loaded, errors = load_all(Path(tmp))
            self.assertEqual(loaded, [])
            self.assertTrue(any("homeEnv" in e["message"] for e in errors))

    def test_invalid_dir_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broken").mkdir()
            (Path(tmp) / "broken" / "descriptor.json").write_text("not json", encoding="utf-8")
            loaded, errors = load_all(Path(tmp))
            self.assertEqual(loaded, [])
            self.assertEqual(errors[0]["dir"], "broken")

    def test_refresh_requires_format_and_client(self):
        doc = json.loads(json.dumps(VALID))
        doc["urls"]["refreshFormat"] = None
        with tempfile.TemporaryDirectory() as tmp:
            _write_descriptor(Path(tmp) / "claude", doc)
            loaded, errors = load_all(Path(tmp))
            self.assertEqual(loaded, [])

    def test_command_binary_must_match(self):
        doc = json.loads(json.dumps(VALID))
        doc["commands"]["login"] = ["other", "auth", "login"]
        with tempfile.TemporaryDirectory() as tmp:
            _write_descriptor(Path(tmp) / "claude", doc)
            loaded, errors = load_all(Path(tmp))
            self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
