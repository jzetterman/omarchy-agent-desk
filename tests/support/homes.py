"""Build a fixture HOME with Claude homes, data dirs, and a fake default home."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "homes" / "claude"
FAKE_CLI = ROOT / "tests" / "support" / "fake_cli"
FAKE_SHELL = ROOT / "tests" / "support" / "fake_shell"

NOW = 1700000000.0


def copy_claude_home(dest: Path, case: str) -> Path:
    """Copy a named Claude fixture home into dest."""
    src = FIXTURES / case
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    identity = dest / ".claude.json"
    if identity.is_file():
        shutil.copy2(identity, dest.parent / ".claude.json")
    return dest


@contextmanager
def fixture_home(case: str = "signed-in"):
    """Temporary HOME containing a Claude fixture, data dirs, and test PATH."""
    tmp = tempfile.TemporaryDirectory(prefix="agent-desk-")
    home = Path(tmp.name)
    (home / ".config" / "omarchy" / "agent-desk").mkdir(parents=True)
    (home / ".local" / "state" / "omarchy" / "agent-desk").mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    copy_claude_home(home / ".claude", case)
    old = {
        "HOME": os.environ.get("HOME"),
        "SHELL": os.environ.get("SHELL"),
        "CLAUDE_CONFIG_DIR": os.environ.get("CLAUDE_CONFIG_DIR"),
        "AGENT_DESK_NOW": os.environ.get("AGENT_DESK_NOW"),
        "AGENT_DESK_CA_FILE": os.environ.get("AGENT_DESK_CA_FILE"),
    }
    os.environ["HOME"] = str(home)
    os.environ["SHELL"] = str(FAKE_SHELL)
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    try:
        yield home
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tmp.cleanup()


def config_dir(home: Path) -> Path:
    return home / ".config" / "omarchy" / "agent-desk"


def state_dir(home: Path) -> Path:
    return home / ".local" / "state" / "omarchy" / "agent-desk"
