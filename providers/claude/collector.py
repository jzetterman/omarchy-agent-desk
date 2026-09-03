#!/usr/bin/env python3
"""Claude Code collector: identity from local files, usage over HTTPS."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from agentdesk.clock import Clock, FakeClock
from agentdesk.descriptor import load_one
from agentdesk.http import Http
from agentdesk.record import normalize

INSTALL_HINT = "Install Claude Code: `mise use -g claude@latest`"
USAGE_HEADERS_EXTRA = {
    "anthropic-beta": "oauth-2025-04-20",
    "Accept": "application/json",
}


# UTC timestamp for collectedAt, from the injectable clock.
def iso_from_clock(clock: Clock) -> str:
    return datetime.fromtimestamp(clock.now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Display plan from rateLimitTier (Max Nx) or subscriptionType.
def plan_label(tier: str, subscription: str) -> str:
    if tier:
        match = re.search(r"max_(\d+x)", tier, re.IGNORECASE)
        if match:
            return "Max " + match.group(1)
    if subscription:
        return subscription[0].upper() + subscription[1:]
    return ""


# Read a regular non-symlink JSON file, or None if missing/invalid.
def read_json(path: Path) -> dict | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    import stat as statmod
    if statmod.S_ISLNK(st.st_mode) or not statmod.S_ISREG(st.st_mode):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# R4: the claudeAiOauth entry, ignored when it has no accessToken (API-key-only).
def select_oauth(doc: dict | None) -> dict | None:
    if not isinstance(doc, dict):
        return None
    entry = doc.get("claudeAiOauth")
    if not isinstance(entry, dict):
        return None
    if not entry.get("accessToken"):
        return None
    return entry


# .claude.json under home when the env var selected it, else ~/.claude.json.
def identity_path(home: Path, home_env_set: bool, descriptor: dict) -> Path:
    entries = descriptor.get("accountState") or []
    name = ".claude.json"
    default_path = "~/.claude.json"
    if entries and isinstance(entries[0], dict):
        name = str(entries[0].get("name") or name)
        default_path = str(entries[0].get("defaultPath") or default_path)
    if home_env_set:
        return home / name
    return Path(os.path.expanduser(default_path))


# Email/org from the identity file, plan from the credential entry.
def load_identity(home: Path, home_env_set: bool, descriptor: dict, entry: dict | None) -> dict:
    ident = {"email": "", "org": "", "plan": ""}
    doc = read_json(identity_path(home, home_env_set, descriptor)) or {}
    oauth = doc.get("oauthAccount") if isinstance(doc, dict) else None
    if isinstance(oauth, dict):
        ident["email"] = str(oauth.get("emailAddress") or "")
        ident["org"] = str(oauth.get("organizationName") or "")
    if entry:
        ident["plan"] = plan_label(str(entry.get("rateLimitTier") or ""), str(entry.get("subscriptionType") or ""))
    return ident


def parse_utilization(value) -> float:
    try:
        return float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return float("nan")


# True when any utilization/percent in the payload is > 1 (D7 sniff).
def sniff_points(payload: dict) -> bool:
    raw = []
    for key in ("five_hour", "seven_day_oauth_apps", "seven_day"):
        bucket = payload.get(key)
        if isinstance(bucket, dict):
            raw.append(bucket.get("utilization"))
    limits = payload.get("limits")
    if isinstance(limits, list):
        for entry in limits:
            if isinstance(entry, dict):
                raw.append(entry.get("percent"))
    return any(parse_utilization(v) > 1 for v in raw)


def as_fraction(value, points: bool) -> float | None:
    n = parse_utilization(value)
    if not (n >= 0):
        return None
    if points or n > 1:
        n = n / 100.0
    if n < 0:
        return 0.0
    if n > 1:
        return 1.0
    return n


def window_word(kind: str) -> str:
    text = kind.lower()
    if "month" in text:
        return "Monthly"
    if "week" in text or "day" in text:
        return "Weekly"
    if "hour" in text or "session" in text:
        return "Session"
    return ""


def normalize_reset_at(value) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        ts = int(raw)
        if ts < 1e12:
            ts *= 1000
        try:
            return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return raw
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return raw


# Map the usage payload to session/weekly/monthly/model-scoped windows.
def parse_windows(payload: dict) -> list[dict]:
    points = sniff_points(payload)
    windows = []
    session = payload.get("five_hour") if isinstance(payload.get("five_hour"), dict) else None
    if session is not None:
        used = as_fraction(session.get("utilization"), points)
        if used is not None:
            windows.append({
                "id": "session",
                "kind": "session",
                "label": "Session",
                "used": used,
                "resetsAt": normalize_reset_at(session.get("resets_at")),
            })
    weekly = payload.get("seven_day_oauth_apps")
    if not isinstance(weekly, dict):
        weekly = payload.get("seven_day") if isinstance(payload.get("seven_day"), dict) else None
    if isinstance(weekly, dict):
        used = as_fraction(weekly.get("utilization"), points)
        if used is not None:
            windows.append({
                "id": "weekly",
                "kind": "weekly",
                "label": "Weekly",
                "used": used,
                "resetsAt": normalize_reset_at(weekly.get("resets_at")),
            })
    extra = payload.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled"):
        limit = extra.get("monthly_limit")
        used_credits = extra.get("used_credits")
        try:
            limit_n = float(limit)
            used_n = float(used_credits)
        except (TypeError, ValueError):
            limit_n = 0.0
            used_n = 0.0
        if limit_n > 0:
            windows.append({
                "id": "monthly:extra usage",
                "kind": "monthly",
                "label": "Extra usage",
                "used": min(1.0, max(0.0, used_n / limit_n)),
                "resetsAt": None,
            })
    limits = payload.get("limits")
    if isinstance(limits, list):
        seen = set()
        for entry in limits:
            if not isinstance(entry, dict):
                continue
            scope = entry.get("scope")
            model = scope.get("model") if isinstance(scope, dict) else None
            if not isinstance(model, dict):
                continue
            display = str(model.get("display_name") or model.get("id") or "").strip()
            kind = str(entry.get("kind") or "").strip()
            model_id = str(model.get("id") or display)
            key = (model_id, kind)
            if not display or key in seen:
                continue
            used = as_fraction(entry.get("percent"), points)
            if used is None:
                continue
            seen.add(key)
            word = window_word(kind)
            label = f"{display} · {word}" if word else display
            windows.append({
                "id": f"model:{model_id}:{kind}",
                "kind": "model-scoped",
                "label": label,
                "used": used,
                "resetsAt": normalize_reset_at(entry.get("resets_at")),
            })
    return windows


# One normalized record with collectedAt from the clock.
def base_record(clock: Clock, status: str, help_text: str, **extra) -> dict:
    rec = {
        "schemaVersion": 1,
        "provider": "claude",
        "mode": extra.get("mode", "full"),
        "status": status,
        "statusReason": extra.get("statusReason"),
        "help": help_text,
        "identity": extra.get("identity"),
        "windows": extra.get("windows") or [],
        "balance": None,
        "collectedAt": iso_from_clock(clock),
    }
    return normalize(rec)


def collect(mode, home, home_kind, home_env_set, binary, deadline, clock, http, descriptor) -> dict:
    """Return one normalized record. identity mode never opens a socket."""
    home_path = Path(home)
    hint = descriptor.get("installHint") or INSTALL_HINT
    if not binary:
        return base_record(clock, "not-installed", hint, mode=mode)
    cred = read_json(home_path / (descriptor.get("credential") or {}).get("file", ".credentials.json"))
    entry = select_oauth(cred)
    identity = load_identity(home_path, home_env_set, descriptor, entry)
    if entry is None:
        return base_record(
            clock, "not-signed-in", "Run `claude auth login`",
            identity=identity, mode=mode,
        )
    if mode == "identity":
        return base_record(clock, "ok", "", identity=identity, mode="identity")
    expires_at_ms = 0
    try:
        expires_at_ms = int(entry.get("expiresAt") or 0)
    except (TypeError, ValueError):
        expires_at_ms = 0
    if expires_at_ms > 0 and expires_at_ms / 1000.0 <= clock.now():
        if home_kind == "default":
            return base_record(
                clock, "expired", "Sign-in expired · run `claude auth login`",
                statusReason="default-home", identity=identity, mode=mode,
            )
        return base_record(
            clock, "expired", "Token expired · refresh deferred",
            statusReason="deferred", identity=identity, mode=mode,
        )
    url = (descriptor.get("urls") or {}).get("usage")
    timeout = 10.0
    if deadline is not None:
        timeout = max(0.1, min(10.0, float(deadline) - clock.now()))
    result = http.get(
        url,
        headers={"Authorization": "Bearer " + str(entry.get("accessToken") or ""), **USAGE_HEADERS_EXTRA},
        timeout=timeout,
    )
    if result.outcome == "auth":
        return base_record(
            clock, "expired", "Usage request rejected",
            statusReason="rejected", identity=identity, mode=mode,
        )
    if result.outcome == "rate-limited":
        return base_record(clock, "rate-limited", "Usage endpoint rate-limited", identity=identity, mode=mode)
    if result.outcome == "offline":
        return base_record(clock, "offline", "Couldn't reach the usage endpoint", identity=identity, mode=mode)
    if result.outcome != "ok" or not result.body:
        return base_record(clock, "failed", "Usage request failed", identity=identity, mode=mode)
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return base_record(clock, "failed", "Usage payload was malformed", identity=identity, mode=mode)
    if not isinstance(payload, dict):
        return base_record(clock, "failed", "Usage payload was malformed", identity=identity, mode=mode)
    windows = parse_windows(payload)
    if not windows:
        return base_record(
            clock, "no-limits", "No rate limits on this plan",
            identity=identity, mode=mode,
        )
    return base_record(clock, "ok", "", identity=identity, windows=windows, mode=mode)


def build_clock(test: bool) -> Clock:
    if test:
        raw = os.environ.get("AGENT_DESK_NOW")
        if raw:
            return FakeClock(now=float(raw), monotonic=float(raw))
    return Clock()


def build_http(test: bool) -> Http:
    cafile = os.environ.get("AGENT_DESK_CA_FILE") if test else None
    return Http(cafile=cafile or None)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="collector")
    parser.add_argument("--mode", choices=("full", "identity"), required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--home-kind", choices=("default", "isolated"), required=True)
    parser.add_argument("--home-env-set", action="store_true")
    parser.add_argument("--binary", default="")
    parser.add_argument("--deadline", type=float, default=None)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args(argv)
    try:
        descriptor = load_one(Path(__file__).resolve().parent / "descriptor.json", "claude")
        record = collect(
            mode=args.mode,
            home=args.home,
            home_kind=args.home_kind,
            home_env_set=args.home_env_set,
            binary=args.binary,
            deadline=args.deadline,
            clock=build_clock(args.test),
            http=build_http(args.test),
            descriptor=descriptor,
        )
        sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
