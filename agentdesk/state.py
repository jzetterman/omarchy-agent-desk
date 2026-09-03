"""state.json schema, validation, and atomic publish."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def empty_state() -> dict:
    return {
        "schemaVersion": 1,
        "generation": 0,
        "accounts": [],
        "active": {},
        "routing": {
            "installed": False,
            "partial": False,
            "shims": [],
            "shadowed": {},
            "rcFile": None,
            "rcCreated": False,
        },
    }


def _valid_imported_home(home: str) -> bool:
    if not isinstance(home, str) or not home.startswith("/"):
        return False
    parts = [p for p in home.split("/") if p]
    return "." not in parts and ".." not in parts


def validate(doc) -> dict | None:
    """Return a cleaned state dict, or None if the file is structurally invalid."""
    if not isinstance(doc, dict):
        return None
    if doc.get("schemaVersion") != 1:
        return None
    accounts = doc.get("accounts")
    if not isinstance(accounts, list):
        return None
    cleaned_accounts = []
    for acct in accounts:
        if not isinstance(acct, dict):
            return None
        aid = acct.get("id")
        if not isinstance(aid, str) or not ACCOUNT_ID_RE.fullmatch(aid):
            return None
        kind = acct.get("kind")
        if kind not in ("imported", "isolated"):
            return None
        if kind == "imported":
            if not _valid_imported_home(acct.get("home")):
                return None
        elif acct.get("home") is not None:
            return None
        cleaned_accounts.append({
            "id": aid,
            "provider": str(acct.get("provider") or ""),
            "kind": kind,
            "name": str(acct.get("name") or ""),
            "home": acct.get("home") if kind == "imported" else None,
            "homeFromEnv": bool(acct.get("homeFromEnv")) if kind == "imported" else False,
            "createdAt": str(acct.get("createdAt") or ""),
            "generation": int(acct.get("generation") or 1),
        })
    active_in = doc.get("active") if isinstance(doc.get("active"), dict) else {}
    active = {}
    by_provider = {}
    for acct in cleaned_accounts:
        by_provider.setdefault(acct["provider"], []).append(acct)
    for provider, group in by_provider.items():
        named = active_in.get(provider)
        if any(a["id"] == named and a["provider"] == provider for a in group):
            active[provider] = named
        else:
            imported = next((a for a in group if a["kind"] == "imported"), group[0])
            active[provider] = imported["id"]
    routing = doc.get("routing") if isinstance(doc.get("routing"), dict) else {}
    out = empty_state()
    try:
        out["generation"] = int(doc.get("generation") or 0)
    except (TypeError, ValueError):
        out["generation"] = 0
    out["accounts"] = cleaned_accounts
    out["active"] = active
    out["routing"] = {
        "installed": bool(routing.get("installed")),
        "partial": bool(routing.get("partial")),
        "shims": list(routing.get("shims") or []),
        "shadowed": dict(routing.get("shadowed") or {}),
        "rcFile": routing.get("rcFile"),
        "rcCreated": bool(routing.get("rcCreated")),
    }
    return out


def load(path: Path) -> tuple[dict | None, str | None]:
    """Load state.json. Missing file → empty state. Unreadable → (None, reason)."""
    if not path.exists():
        return empty_state(), None
    try:
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None, "state-unreadable"
    cleaned = validate(doc)
    if cleaned is None:
        return None, "state-unreadable"
    return cleaned, None


def publish(path: Path, doc: dict) -> None:
    """Write tmp (0600), fsync, rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    payload = (json.dumps(doc, indent=2, sort_keys=False) + "\n").encode()
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    doc["generation"] = int(doc.get("generation") or 0)


def bump_and_publish(path: Path, doc: dict) -> dict:
    doc = dict(doc)
    doc["generation"] = int(doc.get("generation") or 0) + 1
    publish(path, doc)
    return doc
