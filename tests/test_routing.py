"""E.6 real-binary rule and sentinel PATH-probe parser."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdesk.routing import (  # noqa: E402
    fallback_path,
    parse_probe_output,
    probe_command,
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

    def test_real_binary_follows_symlink_to_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real"
            link_dir = Path(tmp) / "link"
            real_dir.mkdir()
            link_dir.mkdir()
            real = real_dir / "claude"
            real.write_text("#!/bin/bash\necho real\n")
            real.chmod(real.stat().st_mode | stat.S_IEXEC)
            link = link_dir / "claude"
            link.symlink_to(real)
            found = real_binary("claude", str(link_dir))
            self.assertEqual(found, os.path.abspath(str(link)))
            self.assertTrue(os.path.samefile(found, real))


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

    def test_probe_command_quotes_unset_vars(self):
        argv = probe_command("/bin/bash", ["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        self.assertEqual(argv[0], "/bin/bash")
        self.assertEqual(argv[1], "-lic")
        fmt = argv[2]
        self.assertIn('"${PATH-}"', fmt)
        self.assertIn('"${CLAUDE_CONFIG_DIR-}"', fmt)
        self.assertIn('"${CODEX_HOME-}"', fmt)

    def test_probe_unset_var_parses_into_right_slots(self):
        argv = probe_command("/bin/bash", ["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        env = os.environ.copy()
        env.pop("CLAUDE_CONFIG_DIR", None)
        env["CODEX_HOME"] = "/tmp/codex-home-slot"
        env["PATH"] = "/tmp/fake-cli:/usr/bin"
        result = subprocess.run(
            ["/bin/bash", "-c", argv[2]],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = parse_probe_output(result.stdout)
        self.assertGreaterEqual(len(values), 3)
        self.assertEqual(values[0], "/tmp/fake-cli:/usr/bin")
        self.assertEqual(values[1], "")
        self.assertEqual(values[2], "/tmp/codex-home-slot")


if __name__ == "__main__":
    unittest.main()
