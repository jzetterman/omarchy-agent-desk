"""E.6 real-binary rule and sentinel PATH-probe parser."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdesk.routing import (  # noqa: E402
    fallback_path,
    parse_probe_output,
    real_binary,
)

MARKER = "# agent-desk routing shim v1"


class RealBinaryTests(unittest.TestCase):
    def test_real_binary_skips_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim_dir = Path(tmp) / "shim"
            real_dir = Path(tmp) / "real"
            shim_dir.mkdir()
            real_dir.mkdir()
            shim = shim_dir / "claude"
            real = real_dir / "claude"
            shim.write_text(f"#!/bin/bash\n{MARKER}\necho shim\n")
            real.write_text("#!/bin/bash\necho real\n")
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            real.chmod(real.stat().st_mode | stat.S_IEXEC)
            path = f"{shim_dir}:{real_dir}"
            found = real_binary("claude", path)
            self.assertEqual(found, str(real.resolve()))

    def test_marked_only_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim_dir = Path(tmp) / "shim"
            shim_dir.mkdir()
            shim = shim_dir / "claude"
            shim.write_text(f"#!/bin/bash\n{MARKER}\n")
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            self.assertIsNone(real_binary("claude", str(shim_dir)))


class ProbeParserTests(unittest.TestCase):
    def test_probe_parses_between_sentinels(self):
        banner = "fastfetch banner\nmore noise\n"
        body = (
            banner
            + "\n__AGENT_DESK__/tmp/fake-cli:/usr/bin__AGENT_DESK__\n"
            + "\n__AGENT_DESK____AGENT_DESK__\n"
        )
        values = parse_probe_output(body)
        self.assertEqual(values, ["/tmp/fake-cli:/usr/bin", ""])

    def test_fallback_path_appends_local_bin_and_install_dirs(self):
        home = "/home/tester"
        path = fallback_path(
            "/usr/bin",
            ["~/.local/share/mise/shims", "~/.local/bin"],
            home,
        )
        self.assertIn("/usr/bin", path)
        self.assertIn(f"{home}/.local/bin", path)
        self.assertIn(f"{home}/.local/share/mise/shims", path)


if __name__ == "__main__":
    unittest.main()
