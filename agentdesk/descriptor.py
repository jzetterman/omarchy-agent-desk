"""Load and validate provider descriptors. Reject non-https URLs."""

from __future__ import annotations

import json
import re
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9-]+$")
HOME_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
BINARY_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
URL_KEYS = ("usage", "identity", "refresh")


def load_all(providers_dir: Path) -> tuple[list[dict], list[dict]]:
    """Return (descriptors, providerErrors). Invalid dirs are skipped, not raised."""
    loaded = []
    errors = []
    if not providers_dir.is_dir():
        return loaded, errors
    for child in sorted(providers_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.is_symlink():
            continue
        path = child / "descriptor.json"
        try:
            loaded.append(load_one(path, child.name))
        except Exception as exc:
            errors.append({"dir": child.name, "message": str(exc)})
    return loaded, errors


def load_one(path: Path, dirname: str | None = None) -> dict:
    """Parse and validate one descriptor.json."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"descriptor is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("descriptor must be an object")
    if doc.get("schemaVersion") != 1:
        raise ValueError("unsupported schemaVersion")
    ident = doc.get("id")
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
        raise ValueError("id must match ^[a-z0-9-]+$")
    if dirname and ident != dirname:
        raise ValueError(f"id {ident!r} does not match directory {dirname!r}")
    home_env = doc.get("homeEnv")
    if not isinstance(home_env, str) or not HOME_ENV_RE.fullmatch(home_env):
        raise ValueError("homeEnv must match ^[A-Z_][A-Z0-9_]*$")
    binary = doc.get("binary")
    if not isinstance(binary, str) or not BINARY_RE.fullmatch(binary):
        raise ValueError("binary must match ^[A-Za-z0-9._+-]+$")
    commands = doc.get("commands")
    if not isinstance(commands, dict):
        raise ValueError("commands must be an object")
    for key in ("login", "logout", "launch"):
        value = commands.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
            raise ValueError(f"commands.{key} must be a string list")
        if value[0] != binary:
            raise ValueError(f"commands.{key}[0] must equal binary")
    urls = doc.get("urls")
    if not isinstance(urls, dict):
        raise ValueError("urls must be an object")
    for key in URL_KEYS:
        value = urls.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.startswith("https://"):
            raise ValueError(f"urls.{key} must be an https:// URL")
    refresh = urls.get("refresh")
    if refresh:
        fmt = urls.get("refreshFormat")
        if fmt not in ("json", "form"):
            raise ValueError("urls.refresh requires refreshFormat json|form")
        has_id = bool(urls.get("clientId"))
        has_key = bool(urls.get("clientIdKey"))
        if has_id == has_key:
            raise ValueError("urls.refresh requires exactly one of clientId / clientIdKey")
    cred = doc.get("credential")
    if not isinstance(cred, dict):
        raise ValueError("missing credential")
    lock = cred.get("lockFile")
    if isinstance(lock, dict):
        if lock.get("kind") != "pidfile":
            raise ValueError('credential.lockFile.kind must be "pidfile"')
    for required in ("name", "mark", "defaultHome", "scale"):
        if required not in doc:
            raise ValueError(f"missing {required}")
    return doc
