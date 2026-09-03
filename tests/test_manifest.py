"""Mirror omarchy-plugin-validate:41-115 against this repo's manifest.json."""

from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "manifest.json"

KIND_ENTRY_POINTS = {
    "bar": "bar",
    "bar-widget": "barWidget",
    "menu": "menu",
    "overlay": "overlay",
    "panel": "panel",
    "service": "service",
}

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_schema_version_is_1(self):
        self.assertEqual(self.doc.get("schemaVersion"), 1)

    def test_required_fields(self):
        for field in ("id", "name", "version", "kinds", "entryPoints"):
            self.assertIn(field, self.doc, f"manifest missing required field '{field}'")

    def test_id_shape(self):
        ident = self.doc.get("id") or ""
        self.assertTrue(ident, "manifest 'id' is empty")
        self.assertRegex(ident, ID_RE)
        self.assertNotIn("..", ident)
        self.assertFalse(ident.startswith("omarchy."))

    def test_kinds_non_empty_array(self):
        kinds = self.doc.get("kinds")
        self.assertIsInstance(kinds, list)
        self.assertGreater(len(kinds), 0)

    def test_entry_points_object(self):
        self.assertIsInstance(self.doc.get("entryPoints"), dict)

    def test_bar_widget_default_section(self):
        bar = self.doc.get("barWidget")
        if not isinstance(bar, dict) or "defaultSection" not in bar:
            return
        section = bar["defaultSection"]
        self.assertIsInstance(section, str)
        self.assertIn(section, ("left", "center", "right"))

    def test_entry_point_paths(self):
        for value in self.doc["entryPoints"].values():
            self.assertIsInstance(value, str)
            self.assertTrue(value, "entry point path is empty")
            self.assertNotIn("\n", value)
            self.assertFalse(value.startswith("/"), f"entry point must be a relative path: '{value}'")
            self.assertNotIn("..", value)
            self.assertTrue((ROOT / value).is_file(), f"entry point file not found: '{value}'")

    def test_kind_requires_matching_entry_point(self):
        kinds = self.doc.get("kinds") or []
        entry_points = self.doc.get("entryPoints") or {}
        for kind, key in KIND_ENTRY_POINTS.items():
            if kind not in kinds:
                continue
            self.assertIn(key, entry_points, f"kind '{kind}' requires an 'entryPoints.{key}' to load")

    def test_no_symlinks_inside_plugin(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            if ".git" in Path(dirpath).parts:
                continue
            if ".git" in dirnames:
                dirnames.remove(".git")
            for name in dirnames + filenames:
                path = Path(dirpath) / name
                self.assertFalse(path.is_symlink(), f"symlinks are not allowed inside a plugin folder: {path}")


if __name__ == "__main__":
    unittest.main()
