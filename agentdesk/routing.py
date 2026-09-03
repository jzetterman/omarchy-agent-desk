"""E.6 real-binary rule, sentinel PATH-probe parser, and fallback PATH."""

from __future__ import annotations

import os
import re
import stat

MARKER = "# agent-desk routing shim v1"
SENTINEL_RE = re.compile(r"\n__AGENT_DESK__(.*?)__AGENT_DESK__\n", re.DOTALL)


def real_binary(name: str, path: str) -> str | None:
    """First unmarked executable regular file of `name` on path, or None."""
    for entry in path.split(":"):
        directory = entry if entry else "."
        candidate = os.path.join(directory, name)
        try:
            st = os.lstat(candidate)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            continue
        if not os.access(candidate, os.X_OK):
            continue
        try:
            with open(candidate, "rb") as fh:
                head = fh.read(512)
        except OSError:
            continue
        if MARKER.encode() in head:
            continue
        return os.path.abspath(candidate)
    return None


def parse_probe_output(text: str) -> list[str]:
    """Take only sentinel-wrapped values, ignoring rc banners such as fastfetch."""
    return SENTINEL_RE.findall(text)


def probe_command(shell: str, home_envs: list[str]) -> list[str]:
    variables = ["$PATH"] + [f"${name}" for name in home_envs]
    fmt = r'printf "\n__AGENT_DESK__%s__AGENT_DESK__\n" ' + " ".join(variables)
    return [shell, "-lic", fmt]


def fallback_path(runner_path: str, install_dirs: list[str], home: str) -> str:
    """Runner PATH plus ~/.local/bin plus every descriptor installDirs."""
    parts = [p for p in runner_path.split(":") if p]
    extras = [os.path.join(home, ".local", "bin")]
    for raw in install_dirs:
        extras.append(os.path.expanduser(raw.replace("~", home, 1) if raw.startswith("~") else raw))
    seen = set(parts)
    for extra in extras:
        if extra not in seen:
            parts.append(extra)
            seen.add(extra)
    return ":".join(parts)
