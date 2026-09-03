"""Pinned data directories, mode enforcement, and isolated-home validation."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

PROVIDER_RE = re.compile(r"^[a-z0-9-]+$")
ACCOUNT_RE = re.compile(r"^[0-9a-f]{32}$")


class PathError(Exception):
    """Isolated home failed D4 validation."""


def home_dir(home: str | None = None) -> Path:
    return Path(home or os.environ.get("HOME") or Path.home())


def config_dir(home: str | None = None) -> Path:
    """$HOME/.config/omarchy/agent-desk/ — XDG_CONFIG_HOME is ignored on purpose."""
    return home_dir(home) / ".config" / "omarchy" / "agent-desk"


def state_dir(home: str | None = None) -> Path:
    """$HOME/.local/state/omarchy/agent-desk/ — XDG_STATE_HOME is ignored on purpose."""
    return home_dir(home) / ".local" / "state" / "omarchy" / "agent-desk"


def ensure_dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def isolated_home(provider: str, account_id: str, *, need=(), home: str | None = None) -> Path:
    """Derive homes/<provider>/<id> from ids alone and fail closed on anything else."""
    if not PROVIDER_RE.fullmatch(provider):
        raise PathError("invalid provider id")
    if not ACCOUNT_RE.fullmatch(account_id):
        raise PathError("invalid account id")
    root = config_dir(home) / "homes" / provider
    path = root / account_id
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise PathError("isolated home missing") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PathError("isolated home is not a plain directory")
    if path.name != account_id or path.parent != root:
        raise PathError("isolated home is not a direct child of homes/<provider>")
    if st.st_uid != os.getuid():
        raise PathError("isolated home not owned by this user")
    if stat.S_IMODE(st.st_mode) != 0o700:
        raise PathError("isolated home mode is not 0700")
    for name in need:
        child = path / name
        try:
            cst = os.lstat(child)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(cst.st_mode) or not stat.S_ISREG(cst.st_mode):
            raise PathError(f"{name} is not a regular file")
    return path
