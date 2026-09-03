"""Scheduler, command loop, snapshot builder, and runner.lock."""

from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from collections import deque
from pathlib import Path

from agentdesk.clock import Clock, iso
from agentdesk.descriptor import load_all
from agentdesk.paths import config_dir, ensure_dir, isolated_home, state_dir
from agentdesk.record import KIND_ORDER, kind_rank, normalize, normalize_email
from agentdesk.routing import fallback_path, parse_probe_output, probe_command, real_binary
from agentdesk.state import bump_and_publish, empty_state, load as load_state

KEEP_ON_FAILURE = ("identity", "windows", "balance", "fetchedAt")
REPLACE_STATUSES = {"ok", "no-limits", "not-signed-in", "not-installed"}
BACKOFF_STATUSES = {"rate-limited", "offline", "failed"}
OPEN_NOFOLLOW = os.O_NOFOLLOW | os.O_CLOEXEC
IMPORT_PLACEHOLDER_NAME = "default"


def merge_record(old: dict | None, new: dict) -> dict:
    """Replace cache on success statuses; keep last-known values on failure."""
    incoming = dict(new)
    if incoming.get("status") in REPLACE_STATUSES:
        incoming["fetchedAt"] = incoming.get("collectedAt")
        return incoming
    if old:
        merged = dict(incoming)
        for key in KEEP_ON_FAILURE:
            if key in old:
                merged[key] = old[key]
        return merged
    return incoming


def compute_readout(accounts, records, active, providers, provider_order, scope, warning, critical):
    """Highest used in scope, with ties by provider order, card order, kind order."""
    enabled = {p["id"]: p.get("enabled", True) for p in providers}
    names = {p["id"]: p.get("name") or p["id"] for p in providers}
    order = list(provider_order)
    for pid in sorted(enabled):
        if pid not in order:
            order.append(pid)
    p_rank = {pid: i for i, pid in enumerate(order)}
    card_index = {}
    candidates = []
    for acct in accounts:
        pid = acct.get("provider")
        if not enabled.get(pid, True):
            continue
        if scope == "active" and active.get(pid) != acct["id"]:
            continue
        c_index = card_index.get(pid, 0)
        card_index[pid] = c_index + 1
        rec = records.get(acct["id"]) or {}
        windows = rec.get("windows") or []
        for window in windows:
            used = window.get("used")
            if used is None:
                continue
            candidates.append((
                float(used), p_rank.get(pid, len(order)), c_index, kind_rank(window.get("kind") or ""),
                str(window.get("label") or ""),
                {
                    "provider": pid,
                    "providerName": names.get(pid, pid),
                    "accountId": acct["id"],
                    "accountName": acct.get("name") or "",
                    "kind": "window",
                    "label": window.get("label") or "",
                    "used": float(used),
                    "resetsAt": window.get("resetsAt"),
                    "remaining": None,
                    "unit": None,
                    "precision": None,
                    "fetchedAt": rec.get("fetchedAt"),
                },
            ))
        bal = rec.get("balance")
        if isinstance(bal, dict) and bal.get("used") is not None:
            used = float(bal["used"])
            candidates.append((
                used, p_rank.get(pid, len(order)), c_index, len(KIND_ORDER) + 1, "",
                {
                    "provider": pid,
                    "providerName": names.get(pid, pid),
                    "accountId": acct["id"],
                    "accountName": acct.get("name") or "",
                    "kind": "balance",
                    "label": "",
                    "used": used,
                    "resetsAt": None,
                    "remaining": bal.get("remaining"),
                    "funded": bal.get("funded"),
                    "spent": bal.get("spent"),
                    "unit": bal.get("unit"),
                    "precision": bal.get("precision"),
                    "fetchedAt": rec.get("fetchedAt"),
                },
            ))
    if not candidates:
        return {"used": None, "level": "none", "top": None}
    candidates.sort(key=lambda c: (-c[0], c[1], c[2], c[3], c[4]))
    top = candidates[0][5]
    used = top["used"]
    if used >= critical:
        level = "critical"
    elif used >= warning:
        level = "warning"
    else:
        level = "normal"
    return {"used": used, "level": level, "top": top}


class Scheduler:
    """Per-account due times, single-flight, backoff, and collector spawn.

    A hold flag arrives with Phase 4 (login/removal). Until then an inflight
    entry is the only thing that blocks a new spawn.
    """

    def __init__(self, clock: Clock, interval_sec: float, floor_sec: float):
        self.clock = clock
        self.interval_sec = interval_sec
        self.floor_sec = floor_sec
        self.entries = {}

    def ensure(self, account_id: str, generation: int) -> dict:
        entry = self.entries.get(account_id)
        if entry is None:
            now = self.clock.monotonic()
            entry = {
                "nextDueMono": now,
                "lastStartMono": None,
                "backoffMultiplier": 1,
                "inflight": False,
                "generation": generation,
                "proc": None,
            }
            self.entries[account_id] = entry
        else:
            entry["generation"] = generation
        return entry

    def drop(self, account_id: str) -> None:
        self.entries.pop(account_id, None)

    def force(self, account_id: str) -> None:
        entry = self.entries.get(account_id)
        if not entry:
            return
        entry["nextDueMono"] = self.clock.monotonic()
        entry["backoffMultiplier"] = 1

    def set_interval(self, interval_sec: float) -> None:
        self.interval_sec = interval_sec
        now = self.clock.monotonic()
        for entry in self.entries.values():
            if entry["lastStartMono"] is None:
                entry["nextDueMono"] = now
                continue
            entry["nextDueMono"] = entry["lastStartMono"] + interval_sec * entry["backoffMultiplier"]
            if entry["nextDueMono"] < now:
                entry["nextDueMono"] = now

    def due_ids(self, manual_ids=None) -> list[str]:
        now = self.clock.monotonic()
        due = []
        for aid, entry in self.entries.items():
            if entry["inflight"]:
                continue
            if manual_ids is not None:
                if aid not in manual_ids:
                    continue
                if entry["lastStartMono"] is not None and now - entry["lastStartMono"] < self.floor_sec:
                    continue
                due.append(aid)
            elif now >= entry["nextDueMono"]:
                due.append(aid)
        return due

    def next_timeout(self) -> float | None:
        now = self.clock.monotonic()
        waits = []
        for entry in self.entries.values():
            if entry["inflight"]:
                continue
            waits.append(max(0.0, entry["nextDueMono"] - now))
        if not waits:
            return None
        return min(waits)

    def note_start(self, account_id: str) -> int:
        entry = self.entries[account_id]
        entry["inflight"] = True
        entry["lastStartMono"] = self.clock.monotonic()
        return entry["generation"]

    def note_result(self, account_id: str, status: str, reason: str | None) -> None:
        entry = self.entries.get(account_id)
        if not entry:
            return
        entry["inflight"] = False
        entry["proc"] = None
        if status in BACKOFF_STATUSES or (status == "expired" and reason == "grant-rejected"):
            entry["backoffMultiplier"] = min(8, 2 * entry["backoffMultiplier"])
        else:
            entry["backoffMultiplier"] = 1
        entry["nextDueMono"] = entry["lastStartMono"] + self.interval_sec * entry["backoffMultiplier"]


class Runner:
    """Single writer of state.json and records. Speaks the C.4 JSON-line protocol."""

    def __init__(
        self,
        plugin_dir: Path,
        clock: Clock | None = None,
        collector_timeout_sec: float = 30.0,
        probe_timeout_sec: float = 5.0,
        grace_sec: float = 2.0,
        floor_sec: float = 60.0,
        interval_sec: float = 900.0,
        test_mode: bool = False,
        home: str | None = None,
    ):
        self.plugin_dir = Path(plugin_dir)
        self.clock = clock or Clock()
        self.test_mode = test_mode
        if home:
            self.home = Path(home)
        else:
            self.home = Path(os.environ.get("HOME") or Path.home())
        self.config_dir = config_dir(str(self.home))
        self.state_dir = state_dir(str(self.home))
        self.collector_timeout_sec = collector_timeout_sec
        self.probe_timeout_sec = probe_timeout_sec
        self.grace_sec = grace_sec
        self.floor_sec = floor_sec
        self.interval_sec = interval_sec
        self.warning = 0.75
        self.critical = 0.90
        self.readout_scope = "active"
        self.provider_order = ["claude", "codex", "grok"]
        self.provider_enabled = {}
        self.descriptors, self.load_errors = load_all(self.plugin_dir / "providers")
        self.desc_by_id = {d["id"]: d for d in self.descriptors}
        install_dirs = []
        for d in self.descriptors:
            install_dirs.extend(d.get("installDirs") or [])
        self.fallback = fallback_path(os.environ.get("PATH") or "/usr/bin", install_dirs, str(self.home))
        self.path = self.fallback
        self.path_probe = "pending"
        self.probe_envs = {}
        self.state, err = load_state(self.config_dir / "state.json")
        self.state_error = err
        if self.state is None:
            self.state = empty_state()
        self.records = {}
        self.scheduler = Scheduler(self.clock, interval_sec, floor_sec)
        self.results = deque()
        self.threads = []
        self.wake_r, self.wake_w = os.pipe()
        os.set_blocking(self.wake_r, False)
        os.set_blocking(self.wake_w, False)
        if hasattr(self.clock, "wake_fd"):
            self.clock.wake_fd = self.wake_w
        self.lock_fd = None
        self._stop = False
        self.manual_queue = set()
        self.provider_errors = list(self.load_errors)
        self._dirty = False
        self._probe_inflight = False
        self._probe_proc = None
        self.persist_error = None
        self.python_bin = shutil.which("python3") or sys.executable
        self.terminal_bin = shutil.which("omarchy-launch-terminal")

    def _now_iso(self) -> str:
        return iso(self.clock.now())

    def _display_name(self, acct: dict) -> str:
        """Imported placeholder name yields the identity email when known."""
        name = str(acct.get("name") or "")
        if acct.get("kind") == "imported" and name == IMPORT_PLACEHOLDER_NAME:
            rec = self.records.get(acct["id"]) or {}
            email = str(((rec.get("identity") or {}).get("email")) or "")
            if email:
                return email
        return name

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _sync_schedule(self) -> None:
        live = set()
        for acct in self.state.get("accounts") or []:
            if not self._provider_enabled(acct["provider"]):
                continue
            if acct["provider"] not in self.desc_by_id:
                continue
            live.add(acct["id"])
            self.scheduler.ensure(acct["id"], acct.get("generation") or 1)
        for aid in list(self.scheduler.entries):
            if aid in live:
                continue
            entry = self.scheduler.entries[aid]
            if entry.get("inflight"):
                continue
            self.scheduler.drop(aid)

    def _provider_enabled(self, pid: str) -> bool:
        value = self.provider_enabled.get(pid)
        return True if value is None else bool(value)

    def _load_records(self) -> None:
        if self.state_error:
            return
        root = self.state_dir / "records"
        saved = {(a["provider"], a["id"]) for a in self.state.get("accounts") or []}
        if root.is_dir():
            for path in root.glob("*/*.json"):
                provider = path.parent.name
                aid = path.stem
                if (provider, aid) not in saved:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    continue
                try:
                    rec = normalize(json.loads(path.read_text(encoding="utf-8")))
                    self.records[aid] = rec
                except (OSError, json.JSONDecodeError, TypeError):
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def _write_record(self, account_id: str, rec: dict) -> None:
        acct = self._account(account_id)
        if not acct:
            return
        path = self.state_dir / "records" / acct["provider"] / f"{account_id}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._log("record write failed")
            self.persist_error = "record-write-failed"
            return
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        payload = (json.dumps(rec) + "\n").encode()
        tmp = path.with_name(path.name + ".tmp")
        try:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | OPEN_NOFOLLOW, 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, path)
            if self.persist_error == "record-write-failed":
                self.persist_error = None
        except OSError:
            self._log("record write failed")
            self.persist_error = "record-write-failed"

    def _account(self, account_id: str):
        for acct in self.state.get("accounts") or []:
            if acct["id"] == account_id:
                return acct
        return None

    def _log(self, message: str) -> None:
        try:
            ensure_dir(self.state_dir)
            path = self.state_dir / "runner.log"
            line = (message.replace("\n", " ") + "\n").encode()
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND | OPEN_NOFOLLOW, 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError:
            pass

    def _truncate_log(self) -> None:
        path = self.state_dir / "runner.log"
        try:
            if path.is_file() and path.stat().st_size > 1_000_000:
                fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC | OPEN_NOFOLLOW, 0o600)
                try:
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)
        except OSError:
            pass

    def take_lock(self) -> int:
        ensure_dir(self.config_dir)
        path = self.config_dir / "runner.lock"
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_RDWR | OPEN_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
        except OSError:
            sys.stderr.write("agent-desk-runner: cannot open runner.lock\n")
            return 75
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            sys.stderr.write("agent-desk-runner: another runner holds runner.lock\n")
            return 75
        self.lock_fd = fd
        return 0

    def start(self) -> int:
        code = self.take_lock()
        if code:
            return code
        ensure_dir(self.state_dir)
        ensure_dir(self.state_dir / "records")
        self._truncate_log()
        if self.state_error:
            return 0
        self._load_records()
        self._sync_schedule()
        if self.path_probe == "pending":
            self._submit_probe()
        else:
            self.detect_and_import()
        return 0

    def _home_envs(self) -> list[str]:
        return [d["homeEnv"] for d in sorted(self.descriptors, key=lambda d: d["id"])]

    def _submit_probe(self) -> None:
        if self._probe_inflight:
            return
        self._probe_inflight = True
        shell = os.environ.get("SHELL") or "/bin/bash"
        argv = probe_command(shell, self._home_envs())
        self._spawn_job({"type": "probe", "argv": argv, "timeout": self.probe_timeout_sec, "env": dict(os.environ)})

    def detect_and_import(self) -> None:
        if self.state_error:
            return
        changed = False
        self.provider_errors = list(self.load_errors)
        for desc in self.descriptors:
            binary = real_binary(desc["binary"], self.path)
            has_account = any(a["provider"] == desc["id"] for a in self.state["accounts"])
            if self.path_probe != "ok" and not has_account:
                continue
            if self.path_probe == "ok" and binary and not has_account:
                if self._import_default(desc):
                    changed = True
        if changed:
            self._publish()
            self._mark_dirty()
        self._sync_schedule()

    def _import_default(self, desc: dict) -> bool:
        env_val = (self.probe_envs.get(desc["homeEnv"]) or "").strip()
        home_from_env = bool(env_val)
        raw = env_val or desc.get("defaultHome") or ""
        home = os.path.abspath(os.path.expanduser(raw))
        parts = [p for p in home.split("/") if p]
        if not home.startswith("/") or "." in parts or ".." in parts:
            self.provider_errors.append({
                "dir": desc["id"],
                "message": f"default home is not a plain absolute path: {raw}",
            })
            return False
        aid = uuid.uuid4().hex
        now = self._now_iso()
        self.state["accounts"].append({
            "id": aid,
            "provider": desc["id"],
            "kind": "imported",
            "name": IMPORT_PLACEHOLDER_NAME,
            "home": home,
            "homeFromEnv": home_from_env,
            "createdAt": now,
            "generation": 1,
        })
        self.state["active"][desc["id"]] = aid
        self.scheduler.ensure(aid, 1)
        self.scheduler.force(aid)
        return True

    def _publish(self) -> None:
        if self.state_error:
            return
        try:
            self.state = bump_and_publish(self.config_dir / "state.json", self.state)
            if self.persist_error == "state-write-failed":
                self.persist_error = None
        except OSError:
            self._log("state write failed")
            self.persist_error = "state-write-failed"

    def _minimal_env(self) -> dict:
        env = {
            "PATH": self.path,
            "HOME": str(self.home),
            "LANG": os.environ.get("LANG") or "C",
        }
        if self.test_mode:
            env["AGENT_DESK_NOW"] = str(self.clock.now())
            ca = os.environ.get("AGENT_DESK_CA_FILE")
            if ca:
                env["AGENT_DESK_CA_FILE"] = ca
        return env

    def _spawn_job(self, job: dict) -> None:
        thread = threading.Thread(target=self._job_worker, args=(job,), daemon=True)
        self.threads.append(thread)
        thread.start()

    def _job_worker(self, job: dict) -> None:
        timeout = job.get("timeout", self.collector_timeout_sec)
        env = job.get("env") or self._minimal_env()
        argv = job["argv"]
        proc = None
        stdout = b""
        timed_out = False
        try:
            proc = subprocess.Popen(
                argv,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            if job.get("type") == "probe":
                self._probe_proc = proc
            if job.get("type") == "collector":
                entry = self.scheduler.entries.get(job["accountId"])
                if entry is not None:
                    entry["proc"] = proc
            try:
                stdout, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_group(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=self.grace_sec)
                except subprocess.TimeoutExpired:
                    self._kill_group(proc.pid, signal.SIGKILL)
                    try:
                        proc.wait(timeout=self.grace_sec)
                    except subprocess.TimeoutExpired:
                        pass
                stdout = b""
            if proc.stdout:
                proc.stdout.close()
        except Exception as exc:
            self.results.append({"type": job.get("type"), "error": exc.__class__.__name__, "job": job, "stdout": b"", "timed_out": False, "code": 1})
            self._wake()
            return
        code = proc.returncode if proc is not None else 1
        self.results.append({
            "type": job.get("type"),
            "job": job,
            "stdout": stdout,
            "timed_out": timed_out,
            "code": code,
        })
        self._wake()

    def _kill_group(self, pid: int, sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass

    def _wake(self) -> None:
        try:
            os.write(self.wake_w, b"\0")
        except OSError:
            pass

    def tick(self) -> None:
        self._reap()
        if self.state_error:
            return
        self.detect_and_import()
        if self.manual_queue:
            if "all" in self.manual_queue:
                manual = set(self.scheduler.entries)
            else:
                manual = set(self.manual_queue)
            self.manual_queue.clear()
            due = self.scheduler.due_ids(manual_ids=manual)
        else:
            due = self.scheduler.due_ids()
        for aid in due:
            self._spawn_collector(aid)

    def _bump_due(self, account_id: str) -> None:
        entry = self.scheduler.entries.get(account_id)
        if not entry:
            return
        entry["nextDueMono"] = self.clock.monotonic() + self.scheduler.interval_sec * entry["backoffMultiplier"]

    def _spawn_collector(self, account_id: str) -> None:
        entry = self.scheduler.entries.get(account_id)
        if entry is None or entry["inflight"]:
            return
        acct = self._account(account_id)
        if not acct:
            self._bump_due(account_id)
            return
        desc = self.desc_by_id.get(acct["provider"])
        if not desc:
            self._bump_due(account_id)
            return
        collector = self.plugin_dir / "providers" / desc["id"] / "collector.py"
        binary = real_binary(desc["binary"], self.path) or ""
        if acct["kind"] == "imported":
            home = acct["home"]
            kind = "default"
            home_env_set = bool(acct.get("homeFromEnv"))
        else:
            try:
                home = str(isolated_home(acct["provider"], acct["id"], home=str(self.home)))
            except Exception:
                self._bump_due(account_id)
                return
            kind = "isolated"
            home_env_set = True
        deadline = self.clock.now() + self.collector_timeout_sec
        argv = [
            self.python_bin, str(collector),
            "--mode", "full",
            "--home", home,
            "--home-kind", kind,
            "--binary", binary,
            "--deadline", str(deadline),
        ]
        if home_env_set:
            argv.append("--home-env-set")
        if self.test_mode:
            argv.append("--test")
        self.scheduler.note_start(account_id)
        self._spawn_job({
            "type": "collector",
            "accountId": account_id,
            "generation": acct.get("generation") or 1,
            "argv": argv,
            "timeout": self.collector_timeout_sec,
        })

    def _reap(self) -> None:
        while self.results:
            item = self.results.popleft()
            if item.get("type") == "probe":
                self._handle_probe(item)
            elif item.get("type") == "collector":
                self._handle_collector(item)

    def _probe_changed(self, old_path, old_probe, old_envs) -> bool:
        return self.path != old_path or self.path_probe != old_probe or self.probe_envs != old_envs

    def _handle_probe(self, item: dict) -> None:
        self._probe_inflight = False
        self._probe_proc = None
        old_path = self.path
        old_probe = self.path_probe
        old_envs = dict(self.probe_envs)
        if item.get("timed_out") or item.get("code") not in (0, None):
            self.path_probe = "fallback"
            self.path = self.fallback
            self._log("probe fallback")
            if self._probe_changed(old_path, old_probe, old_envs):
                self._mark_dirty()
            self.detect_and_import()
            return
        text = (item.get("stdout") or b"").decode("utf-8", errors="replace")
        values = parse_probe_output(text)
        if not values:
            self.path_probe = "fallback"
            self.path = self.fallback
            if self._probe_changed(old_path, old_probe, old_envs):
                self._mark_dirty()
            self.detect_and_import()
            return
        self.path = values[0] or self.fallback
        envs = self._home_envs()
        self.probe_envs = {}
        for i, name in enumerate(envs):
            self.probe_envs[name] = values[i + 1] if i + 1 < len(values) else ""
        self.path_probe = "ok"
        if self._probe_changed(old_path, old_probe, old_envs):
            self._mark_dirty()
        self.detect_and_import()

    def _handle_collector(self, item: dict) -> None:
        job = item.get("job") or {}
        account_id = job.get("accountId")
        generation = job.get("generation")
        acct = self._account(account_id)
        entry = self.scheduler.entries.get(account_id)
        if not acct or not entry or generation != acct.get("generation"):
            if entry:
                entry["inflight"] = False
                entry["proc"] = None
            return
        if item.get("timed_out"):
            new = {
                "schemaVersion": 1,
                "provider": acct["provider"],
                "mode": "full",
                "status": "failed",
                "statusReason": None,
                "help": "Collector timed out",
                "identity": None,
                "windows": [],
                "balance": None,
                "collectedAt": self._now_iso(),
            }
        else:
            try:
                new = json.loads((item.get("stdout") or b"").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                new = {
                    "status": "failed",
                    "help": "Collector output was not JSON",
                    "provider": acct["provider"],
                    "collectedAt": self._now_iso(),
                }
            if item.get("code") not in (0, None) and (not isinstance(new, dict) or new.get("status") not in REPLACE_STATUSES):
                new = {
                    "status": "failed",
                    "help": "Collector exited with an error",
                    "provider": acct["provider"],
                    "collectedAt": self._now_iso(),
                }
        new = normalize(new if isinstance(new, dict) else {"status": "failed", "provider": acct["provider"]})
        new["accountId"] = account_id
        new["generation"] = generation
        new["installed"] = bool(real_binary((self.desc_by_id.get(acct["provider"]) or {}).get("binary") or "", self.path))
        merged = merge_record(self.records.get(account_id), new)
        self.records[account_id] = merged
        self._write_record(account_id, merged)
        self.scheduler.note_result(account_id, merged.get("status"), merged.get("statusReason"))
        self._log(f"collector {acct['provider']} {merged.get('status')} exit {item.get('code')}")
        self._mark_dirty()

    def handle_command(self, cmd: dict) -> list[dict]:
        name = cmd.get("cmd")
        if name == "settings":
            return self._cmd_settings(cmd)
        if name == "refresh":
            return self._cmd_refresh(cmd)
        if name == "snapshot":
            return [self.snapshot_event()]
        if name == "set-active":
            return self._cmd_set_active(cmd.get("accountId"))
        if name == "next":
            return self._cmd_next()
        if name == "launch":
            return self._cmd_launch(cmd.get("accountId"))
        return [{"event": "caption", "text": f"unknown command {name}"}]

    def handle_line(self, line: str) -> list[dict]:
        line = line.strip()
        if not line:
            return []
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            return [{"event": "caption", "text": "malformed command"}]
        if not isinstance(cmd, dict):
            return [{"event": "caption", "text": "malformed command"}]
        return self.handle_command(cmd)

    def _cmd_settings(self, cmd: dict) -> list[dict]:
        interval = cmd.get("refreshIntervalSec", self.interval_sec)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = 900.0
        if interval < 60:
            interval = 60.0
        if interval != self.interval_sec:
            self.interval_sec = interval
            self.scheduler.set_interval(interval)
        order = cmd.get("providerOrder")
        if isinstance(order, list) and all(isinstance(x, str) for x in order):
            self.provider_order = order
        enabled = cmd.get("providerEnabled")
        if isinstance(enabled, dict):
            self.provider_enabled = {k: bool(v) for k, v in enabled.items() if isinstance(v, bool)}
        for key, attr, default in (
            ("warningThreshold", "warning", 0.75),
            ("criticalThreshold", "critical", 0.90),
        ):
            value = cmd.get(key, getattr(self, attr))
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = default
            if value < 0:
                value = 0.0
            if value > 1:
                value = 1.0
            setattr(self, attr, value)
        if self.warning > self.critical:
            self.warning = self.critical
        scope = cmd.get("readoutScope", self.readout_scope)
        if scope not in ("active", "all"):
            scope = "active"
        self.readout_scope = scope
        self._sync_schedule()
        return [self.snapshot_event()]

    def _cmd_refresh(self, cmd: dict) -> list[dict]:
        account_id = cmd.get("accountId") or "all"
        self.manual_queue.add(account_id)
        if self.path_probe != "ok" or cmd.get("manual"):
            self._submit_probe()
        self.tick()
        return [self.snapshot_event()]

    def _cmd_set_active(self, account_id: str) -> list[dict]:
        acct = self._account(account_id)
        if not acct:
            return [{"event": "caption", "text": "unknown account"}]
        self.state.setdefault("active", {})[acct["provider"]] = account_id
        self._publish()
        return [self.snapshot_event()]

    def first_provider_id(self, providers=None) -> str | None:
        views = providers
        if views is None:
            views = []
            for pid in self._ordered_provider_ids():
                desc = self.desc_by_id.get(pid)
                if desc:
                    views.append(self._provider_view(desc))
        for prov in views:
            if prov.get("enabled") and prov.get("installed"):
                return prov["id"]
        return None

    def _cmd_next(self) -> list[dict]:
        pid = self.first_provider_id()
        if not pid:
            return [self.snapshot_event()]
        cards = self._cards(pid)
        if not cards:
            return [self.snapshot_event()]
        ids = [a["id"] for a in cards]
        current = self.state.get("active", {}).get(pid)
        if current in ids:
            nxt = ids[(ids.index(current) + 1) % len(ids)]
        else:
            nxt = ids[0]
        self.state.setdefault("active", {})[pid] = nxt
        self._publish()
        return [self.snapshot_event()]

    def _cmd_launch(self, account_id: str) -> list[dict]:
        acct = self._account(account_id)
        if not acct:
            return [{"event": "caption", "text": "unknown account"}]
        desc = self.desc_by_id.get(acct["provider"])
        if not desc:
            return [{"event": "caption", "text": "unknown provider"}]
        if not self.terminal_bin:
            return [{"event": "caption", "text": "omarchy-launch-terminal is not on PATH"}]
        binary = real_binary(desc["binary"], self.path)
        if not binary:
            return [{"event": "caption", "text": "CLI is not installed"}]
        launch = list((desc.get("commands") or {}).get("launch") or [desc["binary"]])
        args = launch[1:]
        if acct["kind"] == "isolated":
            try:
                home = str(isolated_home(acct["provider"], acct["id"], home=str(self.home)))
            except Exception as exc:
                return [{"event": "caption", "text": str(exc)}]
            argv = [self.terminal_bin, "/usr/bin/env", f"{desc['homeEnv']}={home}", binary, *args]
        elif acct.get("homeFromEnv"):
            argv = [self.terminal_bin, "/usr/bin/env", f"{desc['homeEnv']}={acct['home']}", binary, *args]
        else:
            argv = [self.terminal_bin, binary, *args]
        try:
            subprocess.Popen(
                argv,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
            )
        except OSError as exc:
            return [{"event": "caption", "text": f"launch failed: {exc.__class__.__name__}"}]
        return [self.snapshot_event()]

    def _cards(self, provider: str) -> list[dict]:
        group = [a for a in self.state.get("accounts") or [] if a.get("provider") == provider]
        imported = [a for a in group if a.get("kind") == "imported"]
        isolated = sorted(
            [a for a in group if a.get("kind") == "isolated"],
            key=lambda a: a.get("createdAt") or "",
        )
        return imported + isolated

    def _ordered_accounts(self) -> list[dict]:
        out = []
        seen = set()
        for pid in self._ordered_provider_ids():
            for acct in self._cards(pid):
                out.append(acct)
                seen.add(acct["id"])
        for acct in self.state.get("accounts") or []:
            if acct["id"] not in seen:
                out.append(acct)
        return out

    def _ordered_provider_ids(self) -> list[str]:
        ids = [d["id"] for d in self.descriptors]
        out = []
        seen = set()
        for pid in self.provider_order:
            if pid in ids and pid not in seen:
                out.append(pid)
                seen.add(pid)
        for pid in sorted(ids):
            if pid not in seen:
                out.append(pid)
        return out

    def _provider_view(self, desc: dict) -> dict:
        has_account = any(a["provider"] == desc["id"] for a in self.state.get("accounts") or [])
        binary_path = real_binary(desc["binary"], self.path)
        installed = binary_path is not None
        hint = desc.get("installHint") or f"Install {desc.get('name') or desc['id']}"
        if self.path_probe != "ok" and not has_account:
            installed = False
            hint = "Checking PATH…" if self.path_probe == "pending" else "PATH probe timed out · refresh to retry"
            binary_path = None
        enabled = self._provider_enabled(desc["id"])
        mark = str(self.plugin_dir / "providers" / desc["id"] / desc.get("mark", "mark.svg"))
        mark_light = str(self.plugin_dir / "providers" / desc["id"] / desc.get("markLight", "mark-light.svg"))
        return {
            "id": desc["id"],
            "name": desc.get("name") or desc["id"],
            "markPath": mark,
            "markLightPath": mark_light,
            "glyph": desc.get("glyph") or "",
            "installed": installed,
            "installHint": hint,
            "enabled": enabled,
            "binaryPath": binary_path,
        }

    def snapshot_event(self) -> dict:
        providers = []
        for pid in self._ordered_provider_ids():
            desc = self.desc_by_id.get(pid)
            if desc:
                providers.append(self._provider_view(desc))
        accounts_src = self._ordered_accounts()
        accounts_out = []
        for acct in accounts_src:
            item = dict(acct)
            item["name"] = self._display_name(acct)
            if acct.get("kind") == "isolated":
                try:
                    item["homePath"] = str(isolated_home(acct["provider"], acct["id"], home=str(self.home)))
                except Exception:
                    item["homePath"] = ""
            else:
                item["homePath"] = acct.get("home")
            accounts_out.append(item)
        records_out = {}
        for aid, rec in self.records.items():
            acct = self._account(aid)
            item = dict(rec)
            item["sameAccountAs"] = self._same_account_as(acct, rec) if acct else None
            records_out[aid] = item
        state_out = dict(self.state)
        state_out["accounts"] = accounts_out
        readout = compute_readout(
            accounts_out,
            self.records,
            self.state.get("active") or {},
            providers,
            self._ordered_provider_ids(),
            self.readout_scope,
            self.warning,
            self.critical,
        )
        return {
            "event": "snapshot",
            "state": state_out,
            "records": records_out,
            "providers": providers,
            "firstProviderId": self.first_provider_id(providers),
            "readout": readout,
            "pathProbe": self.path_probe,
            "login": None,
            "providerErrors": self.provider_errors,
            "error": self.state_error or self.persist_error,
            "generation": self.state.get("generation") or 0,
        }

    def _same_account_as(self, acct: dict, rec: dict):
        email = normalize_email(((rec.get("identity") or {}) if rec else {}).get("email"))
        if not email:
            return None
        for other in self.state.get("accounts") or []:
            if other["id"] == acct["id"] or other.get("provider") != acct.get("provider"):
                continue
            other_rec = self.records.get(other["id"]) or {}
            other_email = normalize_email((other_rec.get("identity") or {}).get("email"))
            if other_email and other_email == email:
                return {"id": other["id"], "name": self._display_name(other)}
        return None

    def shutdown_workers(self) -> None:
        self._stop = True
        probe = self._probe_proc
        if probe is not None and probe.poll() is None:
            self._kill_group(probe.pid, signal.SIGKILL)
        for entry in self.scheduler.entries.values():
            proc = entry.get("proc")
            if proc is not None and proc.poll() is None:
                self._kill_group(proc.pid, signal.SIGKILL)
        for thread in list(self.threads):
            thread.join(timeout=0.5)

    def serve(self, stdin, stdout) -> int:
        code = self.start()
        if code:
            return code
        stdout.write(json.dumps(self.snapshot_event()) + "\n")
        stdout.flush()
        stdin_fd = stdin.fileno()
        buf = b""
        while not self._stop:
            timeout = self.scheduler.next_timeout()
            try:
                ready, _, _ = select.select([stdin_fd, self.wake_r], [], [], timeout)
            except (ValueError, OSError):
                break
            if stdin_fd in ready:
                try:
                    chunk = os.read(stdin_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    for event in self.handle_line(line.decode("utf-8", errors="replace")):
                        stdout.write(json.dumps(event) + "\n")
                        stdout.flush()
                        if event.get("event") == "snapshot":
                            self._dirty = False
            if self.wake_r in ready:
                try:
                    os.read(self.wake_r, 4096)
                except OSError:
                    pass
            self.tick()
            if self._dirty:
                stdout.write(json.dumps(self.snapshot_event()) + "\n")
                stdout.flush()
                self._dirty = False
        self.shutdown_workers()
        return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "serve":
        sys.stderr.write("usage: agent-desk-runner serve [--test] [--plugin-dir DIR]\n")
        return 2
    test_mode = "--test" in argv
    plugin_dir = Path(__file__).resolve().parents[1]
    if "--plugin-dir" in argv:
        if not test_mode:
            sys.stderr.write("agent-desk-runner: --plugin-dir requires --test\n")
            return 2
        idx = argv.index("--plugin-dir")
        if idx + 1 < len(argv):
            plugin_dir = Path(argv[idx + 1])
    clock = Clock()
    if test_mode and os.environ.get("AGENT_DESK_NOW"):
        now = float(os.environ["AGENT_DESK_NOW"])

        class _EnvClock(Clock):
            def now(self) -> float:
                return now

            def monotonic(self) -> float:
                return now

        clock = _EnvClock()
    runner = Runner(plugin_dir=plugin_dir, clock=clock, test_mode=test_mode)
    try:
        return runner.serve(sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        runner.shutdown_workers()
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
