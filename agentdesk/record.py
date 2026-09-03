"""Record schema, status mapping, window order, balance.used, and email match."""

from __future__ import annotations

import math
import re
from typing import Any

STATUSES = (
    "ok",
    "not-installed",
    "not-signed-in",
    "expired",
    "rate-limited",
    "offline",
    "failed",
    "no-limits",
)
STATUS_REASONS = (
    "default-home",
    "deferred",
    "grant-rejected",
    "rejected",
    "unsupported-refresh",
)
KIND_ORDER = (
    "session",
    "weekly",
    "monthly",
    "billing-period",
    "model-scoped",
)
SECRET_KEY = re.compile(r"token|key|authorization|secret", re.I)
RECORD_FIELDS = (
    "schemaVersion",
    "provider",
    "mode",
    "status",
    "statusReason",
    "help",
    "identity",
    "windows",
    "balance",
    "collectedAt",
    "fetchedAt",
    "accountId",
    "generation",
    "installed",
    "sharedHealth",
    "sameAccountAs",
)


def kind_rank(kind: str) -> int:
    try:
        return KIND_ORDER.index(kind)
    except ValueError:
        return len(KIND_ORDER)


def clamp_used(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(n):
        return 0.0
    if n < 0:
        return 0.0
    if n > 1:
        return 1.0
    return n


def balance_used(balance: dict | None) -> float:
    """used as spent/funded when both known and funded > 0, else 0 if remaining > 0 else 1."""
    if not isinstance(balance, dict):
        return 0.0
    remaining = _num(balance.get("remaining"))
    funded = balance.get("funded")
    spent = balance.get("spent")
    if funded is not None and spent is not None:
        funded_n = _num(funded)
        spent_n = _num(spent)
        if funded_n > 0:
            return clamp_used(spent_n / funded_n)
    if remaining > 0:
        return 0.0
    return 1.0


def _num(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(n):
        return 0.0
    return n


def window_id(window: dict) -> str:
    supplied = window.get("id")
    if isinstance(supplied, str) and supplied:
        return supplied
    kind = str(window.get("kind") or "unknown")
    label = str(window.get("label") or "").lower()
    return f"{kind}:{label}"


def normalize_email(email: str | None) -> str:
    if not email:
        return ""
    text = str(email).strip()
    if not text or "@" not in text:
        return text.lower() if text else ""
    local, _, domain = text.partition("@")
    local = local.strip().lower()
    domain = domain.strip().lower()
    if not local or not domain:
        return ""
    return f"{local}@{domain}"


def _drop_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _drop_secrets(v)
            for k, v in value.items()
            if not (isinstance(k, str) and SECRET_KEY.search(k))
        }
    if isinstance(value, list):
        return [_drop_secrets(v) for v in value]
    return value


def normalize(raw: dict | None) -> dict:
    """Allowlist fields, clamp used, sort windows, drop secret keys."""
    src = raw if isinstance(raw, dict) else {}
    src = _drop_secrets(src)
    status = src.get("status")
    if status not in STATUSES:
        status = "failed"
    reason = src.get("statusReason")
    if status != "expired" or reason not in STATUS_REASONS:
        reason = None
    identity = src.get("identity")
    if isinstance(identity, dict):
        identity = {
            "email": str(identity.get("email") or ""),
            "org": str(identity.get("org") or ""),
            "plan": str(identity.get("plan") or ""),
        }
    else:
        identity = None
    windows_in = src.get("windows") if isinstance(src.get("windows"), list) else []
    windows = []
    for item in windows_in:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "unknown")
        label = str(item.get("label") or kind)
        windows.append({
            "id": window_id({"id": item.get("id"), "kind": kind, "label": label}),
            "kind": kind,
            "label": label,
            "used": clamp_used(item.get("used")),
            "resetsAt": item.get("resetsAt") or None,
            "periodStart": item.get("periodStart") or None,
            "note": item.get("note") or None,
        })
    windows.sort(key=lambda w: (kind_rank(w["kind"]), w["label"].lower(), w["id"]))
    balance = src.get("balance")
    if isinstance(balance, dict):
        remaining = _num(balance.get("remaining"))
        unit = str(balance.get("unit") or "credits")
        precision = balance.get("precision")
        try:
            precision = int(precision)
        except (TypeError, ValueError):
            precision = 0
        cleaned = {
            "remaining": remaining,
            "funded": None if balance.get("funded") is None else _num(balance.get("funded")),
            "spent": None if balance.get("spent") is None else _num(balance.get("spent")),
            "unit": unit,
            "precision": precision,
        }
        cleaned["used"] = balance_used(cleaned)
        balance = cleaned
    else:
        balance = None
    out = {
        "schemaVersion": 1,
        "provider": str(src.get("provider") or ""),
        "mode": str(src.get("mode") or "full"),
        "status": status,
        "statusReason": reason,
        "help": str(src.get("help") or ""),
        "identity": identity,
        "windows": windows,
        "balance": balance,
        "collectedAt": src.get("collectedAt"),
        "fetchedAt": src.get("fetchedAt"),
        "accountId": src.get("accountId"),
        "generation": src.get("generation"),
        "installed": src.get("installed"),
    }
    if src.get("sharedHealth") is not None:
        out["sharedHealth"] = src["sharedHealth"]
    if src.get("sameAccountAs") is not None:
        out["sameAccountAs"] = src["sameAccountAs"]
    return out
