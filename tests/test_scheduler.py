"""Scheduler: A10 timeout/backoff, floor, single-flight, runner.lock."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agentdesk.runner import IMPORT_PLACEHOLDER_NAME, Runner, merge_record  # noqa: E402
from support.fake_clock import FakeClock  # noqa: E402
from support.homes import NOW, config_dir, fixture_home, state_dir  # noqa: E402

SLEEPING_COLLECTOR = r'''
import json, os, sys, time
from pathlib import Path
mode = "full"
home = ""
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--home" and i + 1 < len(args):
        home = args[i + 1]
        i += 2
        continue
    i += 1
slow = home.endswith("slow") or os.environ.get("AGENT_DESK_SLOW") == "1"
record = {
    "schemaVersion": 1,
    "provider": "claude",
    "mode": "full",
    "status": "ok",
    "statusReason": None,
    "help": "",
    "identity": {"email": "a@b.c", "org": "", "plan": ""},
    "windows": [{"id": "session", "kind": "session", "label": "Session", "used": 0.1, "resetsAt": None}],
    "balance": None,
    "collectedAt": "2023-11-14T13:46:40Z",
}
if slow:
    child = os.fork()
    if child == 0:
        time.sleep(30)
        os._exit(0)
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / "collector.pid").write_text(str(os.getpid()), encoding="utf-8")
    (Path(home) / "grandchild.pid").write_text(str(child), encoding="utf-8")
    time.sleep(30)
    record["status"] = "ok"
    print(json.dumps(record))
    sys.exit(0)
print(json.dumps(record))
'''

FAILING_COLLECTOR = r'''
import json, sys
print(json.dumps({
    "schemaVersion": 1,
    "provider": "claude",
    "mode": "full",
    "status": "failed",
    "statusReason": None,
    "help": "boom",
    "identity": None,
    "windows": [],
    "balance": None,
    "collectedAt": "2023-11-14T13:46:40Z",
}))
'''

OK_COLLECTOR = r'''
import json, sys
print(json.dumps({
    "schemaVersion": 1,
    "provider": "claude",
    "mode": "full",
    "status": "ok",
    "statusReason": None,
    "help": "",
    "identity": {"email": "a@b.c", "org": "", "plan": "Max"},
    "windows": [{"id": "session", "kind": "session", "label": "Session", "used": 0.2, "resetsAt": None}],
    "balance": None,
    "collectedAt": "2023-11-14T13:46:40Z",
}))
'''

OK_COLLECTOR_HIGH = r'''
import json, sys
print(json.dumps({
    "schemaVersion": 1,
    "provider": "claude",
    "mode": "full",
    "status": "ok",
    "statusReason": None,
    "help": "",
    "identity": {"email": "a@b.c", "org": "", "plan": "Max"},
    "windows": [{"id": "session", "kind": "session", "label": "Session", "used": 0.9, "resetsAt": None}],
    "balance": None,
    "collectedAt": "2023-11-14T13:46:40Z",
}))
'''

# Replaces a cache with not-installed if it runs; writes a spawn marker in --home.
SPAWNING_NOT_INSTALLED_COLLECTOR = r'''
import json, sys
from pathlib import Path
home = ""
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--home" and i + 1 < len(args):
        home = args[i + 1]
        i += 2
        continue
    i += 1
if home:
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / "collector-spawned").write_text("1", encoding="utf-8")
print(json.dumps({
    "schemaVersion": 1,
    "provider": "claude",
    "mode": "full",
    "status": "not-installed",
    "statusReason": None,
    "help": "CLI not found",
    "identity": None,
    "windows": [],
    "balance": None,
    "collectedAt": "2023-11-14T13:46:41Z",
}))
'''

DESCRIPTOR = {
    "schemaVersion": 1,
    "id": "claude",
    "name": "Claude Code",
    "mark": "mark.svg",
    "markLight": "mark-light.svg",
    "glyph": "x",
    "binary": "claude",
    "homeEnv": "CLAUDE_CONFIG_DIR",
    "defaultHome": "~/.claude",
    "commands": {
        "login": ["claude", "auth", "login"],
        "logout": ["claude", "auth", "logout"],
        "launch": ["claude"],
    },
    "credential": {
        "file": ".credentials.json",
        "currentEntry": "claudeAiOauth",
        "lockFile": None,
        "tempFiles": {"refresh": "r", "transaction": "t"},
    },
    "sharedEntries": [],
    "accountState": [],
    "scale": "sniff",
    "installDirs": ["~/.local/bin"],
    "urls": {
        "usage": "https://api.anthropic.com/api/oauth/usage",
        "identity": None,
        "refresh": None,
        "refreshFormat": None,
        "clientId": None,
        "clientIdKey": None,
    },
    "installHint": "Install Claude Code: mise use -g claude@latest",
}


def write_plugin(tmp: Path, collector_src: str) -> Path:
    plugin = tmp / "plugin"
    prov = plugin / "providers" / "claude"
    prov.mkdir(parents=True)
    (prov / "descriptor.json").write_text(json.dumps(DESCRIPTOR), encoding="utf-8")
    (prov / "mark.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (prov / "mark-light.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    coll = prov / "collector.py"
    coll.write_text(collector_src, encoding="utf-8")
    coll.chmod(coll.stat().st_mode | stat.S_IEXEC)
    (plugin / "bin").mkdir(parents=True)
    return plugin


def account(aid, home, generation=1, provider="claude"):
    return {
        "id": aid,
        "provider": provider,
        "kind": "imported",
        "name": "default",
        "home": home,
        "homeFromEnv": False,
        "createdAt": "2023-11-14T13:46:40Z",
        "generation": generation,
    }


def make_runner(plugin, clock=None, probe=None, **kwargs):
    """Build a Runner; `probe="ok"` stands in for a finished PATH probe so
    scheduling tests can tick without start() (E.1: nothing runs while pending)."""
    kw = dict(
        plugin_dir=plugin,
        clock=clock or FakeClock(now=NOW, monotonic=1000.0),
        collector_timeout_sec=0.2,
        probe_timeout_sec=0.2,
        grace_sec=0.2,
        floor_sec=0.05,
        interval_sec=1.0,
        test_mode=True,
    )
    kw.update(kwargs)
    runner = Runner(**kw)
    if probe:
        runner.path_probe = probe
    return runner


class MergeRecordTests(unittest.TestCase):
    def test_failed_keeps_last_known(self):
        old = {
            "status": "ok",
            "identity": {"email": "a@b.c"},
            "windows": [{"id": "session", "used": 0.4}],
            "balance": None,
            "fetchedAt": "old",
            "collectedAt": "old",
            "help": "",
        }
        new = {
            "status": "failed",
            "help": "timeout",
            "identity": None,
            "windows": [],
            "balance": None,
            "collectedAt": "new",
        }
        merged = merge_record(old, new)
        self.assertEqual(merged["status"], "failed")
        self.assertEqual(merged["windows"][0]["used"], 0.4)
        self.assertEqual(merged["fetchedAt"], "old")
        self.assertEqual(merged["collectedAt"], "new")
        self.assertEqual(merged["help"], "timeout")


class SchedulerTests(unittest.TestCase):
    def test_backoff_ladder_and_clear_on_success(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, FAILING_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(plugin, probe="ok", clock=clock, floor_sec=0.05, interval_sec=1.0)
            aid = "a" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            runner.scheduler.force(aid)
            runner.tick()
            self._wait_idle(runner)
            entry = runner.scheduler.entries[aid]
            self.assertEqual(entry["backoffMultiplier"], 2)
            first_due = entry["nextDueMono"]
            self.assertGreaterEqual(first_due, entry["lastStartMono"] + 2.0)
            clock.advance(2.0)
            runner.tick()
            self._wait_idle(runner)
            entry = runner.scheduler.entries[aid]
            self.assertEqual(entry["backoffMultiplier"], 4)
            clock.advance(4.0)
            runner.tick()
            self._wait_idle(runner)
            self.assertEqual(runner.scheduler.entries[aid]["backoffMultiplier"], 8)
            clock.advance(8.0)
            runner.tick()
            self._wait_idle(runner)
            self.assertEqual(runner.scheduler.entries[aid]["backoffMultiplier"], 8)
            (plugin / "providers" / "claude" / "collector.py").write_text(OK_COLLECTOR, encoding="utf-8")
            clock.advance(8.0)
            runner.tick()
            self._wait_idle(runner)
            self.assertEqual(runner.scheduler.entries[aid]["backoffMultiplier"], 1)
            rec = runner.records[aid]
            self.assertEqual(rec["status"], "ok")

    def test_manual_floor_skips(self):
        # R6: a manual refresh inside the 60 s floor is skipped; one at the
        # floor runs again.
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(
                plugin, probe="ok", clock=clock, floor_sec=60.0, interval_sec=900.0,
            )
            aid = "b" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            runner.handle_command({"cmd": "refresh", "accountId": "all", "manual": True})
            self._wait_idle(runner)
            first = runner.scheduler.entries[aid]["lastStartMono"]
            self.assertIsNotNone(first)
            self.assertEqual(runner.records[aid]["status"], "ok")
            clock.advance(59.0)
            runner.handle_command({"cmd": "refresh", "accountId": "all", "manual": True})
            self._wait_idle(runner)
            self.assertEqual(runner.scheduler.entries[aid]["lastStartMono"], first)
            clock.advance(1.0)
            runner.handle_command({"cmd": "refresh", "accountId": "all", "manual": True})
            self._wait_idle(runner)
            self.assertEqual(runner.scheduler.entries[aid]["lastStartMono"], first + 60.0)
            runner.shutdown_workers()

    def test_non_test_runner_strips_agent_desk_env_and_flag(self):
        # E.1: AGENT_DESK_* reaches a collector only under `serve --test`.
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            aid = "k" * 32
            with patch.dict(os.environ, {"AGENT_DESK_NOW": "123", "AGENT_DESK_CA_FILE": "/x/ca.pem"}):
                for test_mode in (False, True):
                    runner = make_runner(plugin, probe="ok", test_mode=test_mode)
                    runner.state["accounts"] = [account(aid, str(home / ".claude"))]
                    runner._sync_schedule()
                    jobs = []
                    with patch.object(runner, "_spawn_job", new=jobs.append):
                        runner.scheduler.force(aid)
                        runner.tick()
                    self.assertEqual(len(jobs), 1)
                    env = runner._minimal_env()
                    leaked = sorted(k for k in env if k.startswith("AGENT_DESK_"))
                    if test_mode:
                        self.assertEqual(leaked, ["AGENT_DESK_CA_FILE", "AGENT_DESK_NOW"])
                        self.assertIn("--test", jobs[0]["argv"])
                    else:
                        self.assertEqual(leaked, [])
                        self.assertEqual(sorted(env), ["HOME", "LANG", "PATH"])
                        self.assertNotIn("--test", jobs[0]["argv"])

    def test_launch_argv_for_imported_account(self):
        # E.3/E.5: an imported account launches the bare binary unless its
        # home came from the env var, then `env VAR=home <binary>`.
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            fake_cli = str(ROOT / "tests" / "support" / "fake_cli")
            with patch.dict(os.environ, {"PATH": fake_cli + os.pathsep + (os.environ.get("PATH") or "/usr/bin")}):
                runner = make_runner(plugin, probe="ok")
            self.assertEqual(runner.terminal_bin, os.path.join(fake_cli, "omarchy-launch-terminal"))
            binary = os.path.join(fake_cli, "claude")
            aid = "l" * 32
            claude_home = str(home / ".claude")
            acct = account(aid, claude_home)
            runner.state["accounts"] = [acct]
            events = runner.handle_command({"cmd": "launch", "accountId": aid})
            self.assertEqual(events[0]["event"], "snapshot")
            acct["homeFromEnv"] = True
            events = runner.handle_command({"cmd": "launch", "accountId": aid})
            self.assertEqual(events[0]["event"], "snapshot")
            log = home / ".launch.log"
            deadline = time.time() + 2.0
            recorded = []
            while time.time() < deadline:
                if log.is_file():
                    recorded = json.loads(log.read_text(encoding="utf-8"))
                    if len(recorded) == 2:
                        break
                time.sleep(0.02)
            self.assertEqual(recorded, [
                [binary],
                ["/usr/bin/env", f"CLAUDE_CONFIG_DIR={claude_home}", binary],
            ])

    def test_pinned_clock_pins_only_now(self):
        # `serve --test` with AGENT_DESK_NOW pins wall time; monotonic must
        # stay real so floors and intervals still elapse.
        from agentdesk.runner import PinnedClock
        clock = PinnedClock(NOW)
        self.assertEqual(clock.now(), NOW)
        self.assertAlmostEqual(clock.monotonic(), time.monotonic(), delta=1.0)

    def test_spawn_job_prunes_dead_threads(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin)
            job = {"type": "noop", "argv": [sys.executable, "-c", "pass"], "timeout": 2.0}
            runner._spawn_job(job)
            runner.threads[0].join(timeout=2.0)
            self.assertFalse(runner.threads[0].is_alive())
            runner._spawn_job(job)
            self.assertEqual(len(runner.threads), 1)
            runner.shutdown_workers()

    def test_load_records_unlinks_non_object_json(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            aid = "m" * 32
            rec_dir = state_dir(home) / "records" / "claude"
            rec_dir.mkdir(parents=True)
            rec_path = rec_dir / f"{aid}.json"
            rec_path.write_text("[1, 2]", encoding="utf-8")
            runner = make_runner(plugin)
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner._load_records()
            self.assertNotIn(aid, runner.records)
            self.assertFalse(rec_path.exists())

    def test_provider_order_drops_unknown_and_appends_unlisted(self):
        # C.6: unknown ids are dropped, unlisted ids appended in id order.
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin)
            runner.handle_command({"cmd": "settings", "providerOrder": ["nope", "claude", "claude"]})
            self.assertEqual(runner._ordered_provider_ids(), ["claude"])
            runner.handle_command({"cmd": "settings", "providerOrder": []})
            self.assertEqual(runner._ordered_provider_ids(), ["claude"])

    def test_single_flight(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, SLEEPING_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(
                plugin, probe="ok", clock=clock, collector_timeout_sec=2.0, floor_sec=0.0, interval_sec=900.0,
            )
            aid = "c" * 32
            slow_home = str(home / "slow")
            Path(slow_home).mkdir()
            runner.state["accounts"] = [account(aid, slow_home)]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            runner.scheduler.force(aid)
            runner.tick()
            self.assertTrue(runner.scheduler.entries[aid]["inflight"])
            spawned = runner.scheduler.entries[aid]["lastStartMono"]
            runner.tick()
            self.assertEqual(runner.scheduler.entries[aid]["lastStartMono"], spawned)
            runner.shutdown_workers()

    def test_timeout_kills_grandchild_and_sibling_completes(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, SLEEPING_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(
                plugin, probe="ok", clock=clock, collector_timeout_sec=0.2, grace_sec=0.2,
                floor_sec=0.0, interval_sec=1.0,
            )
            slow_id = "d" * 32
            fast_id = "e" * 32
            slow_home = str(home / "slow")
            Path(slow_home).mkdir()
            last_known = {
                "status": "ok",
                "identity": {"email": "old@example.com"},
                "windows": [{"id": "session", "kind": "session", "label": "Session", "used": 0.7}],
                "balance": None,
                "fetchedAt": "2023-11-14T13:00:00Z",
                "collectedAt": "2023-11-14T13:00:00Z",
                "help": "",
            }
            runner.state["accounts"] = [
                account(slow_id, slow_home),
                account(fast_id, str(home / ".claude")),
            ]
            runner.state["active"] = {"claude": fast_id}
            runner.records[slow_id] = last_known
            runner._sync_schedule()
            runner.scheduler.force(slow_id)
            runner.scheduler.force(fast_id)
            runner.tick()
            collector_pid, grandchild_pid = self._wait_pids(Path(slow_home))
            self._wait_idle(runner, timeout=2.0)
            self.assertEqual(runner.records[fast_id]["status"], "ok")
            self.assertEqual(runner.records[slow_id]["status"], "failed")
            self.assertEqual(runner.records[slow_id]["windows"][0]["used"], 0.7)
            self.assertEqual(runner.records[slow_id]["fetchedAt"], "2023-11-14T13:00:00Z")
            self.assertEqual(runner.scheduler.entries[slow_id]["backoffMultiplier"], 2)
            self.assertEqual(runner.scheduler.entries[fast_id]["backoffMultiplier"], 1)
            with self.assertRaises(ProcessLookupError):
                os.kill(collector_pid, 0)
            with self.assertRaises(ProcessLookupError):
                os.kill(grandchild_pid, 0)
            runner.shutdown_workers()

    def test_two_collector_results_produce_two_snapshots(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(plugin, probe="ok", clock=clock, floor_sec=0.0, interval_sec=1.0)
            aid = "f" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            snaps = []

            def emit_if_dirty():
                if getattr(runner, "_dirty", False):
                    snaps.append(runner.snapshot_event())
                    runner._dirty = False

            runner.scheduler.force(aid)
            runner.tick()
            self._wait_idle(runner)
            emit_if_dirty()
            (plugin / "providers" / "claude" / "collector.py").write_text(
                OK_COLLECTOR_HIGH, encoding="utf-8",
            )
            runner.scheduler.force(aid)
            runner.tick()
            self._wait_idle(runner)
            emit_if_dirty()
            self.assertEqual(len(snaps), 2)
            first = snaps[0]["records"][aid]["windows"][0]["used"]
            second = snaps[1]["records"][aid]["windows"][0]["used"]
            self.assertAlmostEqual(first, 0.2)
            self.assertAlmostEqual(second, 0.9)

    def test_unknown_provider_does_not_spin(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(plugin, clock=clock, interval_sec=900.0)
            aid = "c" * 32
            runner.state["accounts"] = [account(aid, str(home / ".codex"), provider="codex")]
            runner.state["active"] = {"codex": aid}
            runner._sync_schedule()
            self.assertNotIn(aid, runner.scheduler.entries)
            timeout = runner.scheduler.next_timeout()
            self.assertTrue(timeout is None or timeout > 0)
            runner.tick()
            timeout = runner.scheduler.next_timeout()
            self.assertTrue(timeout is None or timeout > 0)
            self.assertFalse(any(e.get("inflight") for e in runner.scheduler.entries.values()))

    def test_settings_interval_makes_never_run_due_now(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=0.0)
            runner = make_runner(plugin, clock=clock, interval_sec=900.0, floor_sec=0.0)
            aid = "g" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner._sync_schedule()
            entry = runner.scheduler.entries[aid]
            self.assertIsNone(entry["lastStartMono"])
            runner.handle_command({"cmd": "settings", "refreshIntervalSec": 120})
            self.assertEqual(runner.scheduler.entries[aid]["nextDueMono"], clock.monotonic())
            runner.scheduler.note_start(aid)
            runner.scheduler.note_result(aid, "ok", None)
            started = runner.scheduler.entries[aid]["lastStartMono"]
            runner.handle_command({"cmd": "settings", "refreshIntervalSec": 60})
            expected = started + 60.0 * runner.scheduler.entries[aid]["backoffMultiplier"]
            self.assertEqual(runner.scheduler.entries[aid]["nextDueMono"], expected)

    def test_path_probe_ok_uses_fake_shell(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin, probe_timeout_sec=2.0)
            self.assertEqual(runner.start(), 0)
            self._wait_probe(runner)
            self.assertEqual(runner.path_probe, "ok")
            fake_cli = str(ROOT / "tests" / "support" / "fake_cli")
            self.assertTrue(
                runner.path.startswith(fake_cli),
                f"path {runner.path!r} should start with {fake_cli}",
            )
            runner.shutdown_workers()

    def test_path_probe_timeout_falls_back(self):
        with fixture_home("signed-in") as home:
            hang = home / "hang_shell"
            hang.write_text("#!/bin/bash\nexec sleep 30\n", encoding="utf-8")
            hang.chmod(hang.stat().st_mode | stat.S_IEXEC)
            os.environ["SHELL"] = str(hang)
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin, probe_timeout_sec=0.2, grace_sec=0.2)
            self.assertEqual(runner.start(), 0)
            self._wait_probe(runner, timeout=3.0)
            self.assertEqual(runner.path_probe, "fallback")
            self.assertEqual(runner.path, runner.fallback)
            runner.shutdown_workers()

    def test_pending_probe_does_not_spawn_collectors(self):
        # G1a: a hanging SHELL must not collect on the fallback PATH; last-known
        # windows and identity stay until the first probe result.
        with fixture_home("signed-in") as home:
            hang = home / "hang_shell"
            hang.write_text("#!/bin/bash\nexec sleep 30\n", encoding="utf-8")
            hang.chmod(hang.stat().st_mode | stat.S_IEXEC)
            os.environ["SHELL"] = str(hang)
            plugin = write_plugin(home, SPAWNING_NOT_INSTALLED_COLLECTOR)
            aid = "d" * 32  # hex: state.validate rejects other ids
            claude_home = home / ".claude"
            rec = {
                "schemaVersion": 1,
                "provider": "claude",
                "mode": "full",
                "status": "ok",
                "statusReason": None,
                "help": "",
                "identity": {"email": "keep@example.com", "org": "Org", "plan": "Max"},
                "windows": [{
                    "id": "session", "kind": "session", "label": "Session",
                    "used": 0.42, "resetsAt": None,
                }],
                "balance": None,
                "collectedAt": "2023-11-14T13:46:40Z",
                "fetchedAt": "2023-11-14T13:46:40Z",
                "accountId": aid,
                "generation": 1,
                "installed": True,
            }
            rec_dir = state_dir(home) / "records" / "claude"
            rec_dir.mkdir(parents=True)
            (rec_dir / f"{aid}.json").write_text(json.dumps(rec), encoding="utf-8")
            (config_dir(home) / "state.json").write_text(json.dumps({
                "schemaVersion": 1,
                "generation": 1,
                "accounts": [account(aid, str(claude_home))],
                "active": {"claude": aid},
                "routing": {
                    "installed": False, "partial": False, "shims": [],
                    "shadowed": {}, "rcFile": None, "rcCreated": False,
                },
            }), encoding="utf-8")
            runner = make_runner(plugin, probe_timeout_sec=2.0, grace_sec=0.2, floor_sec=0.0)
            self.assertEqual(runner.start(), 0)
            self.assertEqual(runner.path_probe, "pending")
            self.assertEqual(runner.records[aid]["status"], "ok")
            deadline = time.time() + 0.3
            while time.time() < deadline:
                runner.tick()
                self.assertEqual(runner.path_probe, "pending")
                self.assertFalse(
                    any(e.get("inflight") for e in runner.scheduler.entries.values()),
                    "collector must not spawn while path_probe is pending",
                )
                time.sleep(0.02)
            self.assertFalse((claude_home / "collector-spawned").exists())
            cached = runner.records[aid]
            self.assertEqual(cached["status"], "ok")
            self.assertEqual(cached["identity"]["email"], "keep@example.com")
            self.assertEqual(cached["windows"][0]["used"], 0.42)
            runner.shutdown_workers()

    def test_failed_reprobe_keeps_successful_path(self):
        # G1b: a later failed/timed-out probe must not replace a good PATH.
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin)
            body = b"\n__AGENT_DESK__/interactive/bin:/usr/bin__AGENT_DESK__\n\n__AGENT_DESK____AGENT_DESK__\n"
            runner._handle_probe({"type": "probe", "timed_out": False, "code": 0, "stdout": body})
            self.assertEqual(runner.path_probe, "ok")
            self.assertTrue(runner.path.startswith("/interactive/bin"))
            good = runner.path
            runner._handle_probe({"type": "probe", "timed_out": True, "code": None, "stdout": b""})
            self.assertEqual(runner.path_probe, "ok")
            self.assertEqual(runner.path, good)
            log = (state_dir(home) / "runner.log").read_text(encoding="utf-8")
            self.assertIn("keeping previous PATH", log)
            self.assertEqual(log.count("keeping previous PATH"), 1)
            runner._handle_probe({"type": "probe", "timed_out": True, "code": 1, "stdout": b""})
            self.assertEqual(runner.path_probe, "ok")
            self.assertEqual(runner.path, good)
            log = (state_dir(home) / "runner.log").read_text(encoding="utf-8")
            self.assertEqual(log.count("keeping previous PATH"), 1)
            runner.shutdown_workers()

    def test_unreadable_state_leaves_records(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            cfg = config_dir(home)
            rec_dir = state_dir(home) / "records" / "claude"
            rec_dir.mkdir(parents=True)
            rec_path = rec_dir / ("a" * 32 + ".json")
            rec_path.write_text(json.dumps({"status": "ok", "provider": "claude"}), encoding="utf-8")
            (cfg / "state.json").write_text("{not json", encoding="utf-8")
            runner = make_runner(plugin)
            self.assertEqual(runner.start(), 0)
            self.assertEqual(runner.state_error, "state-unreadable")
            self.assertTrue(rec_path.is_file(), "unreadable state must not delete records")
            runner.shutdown_workers()

    def test_runner_lock_refuses_second_instance(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            rec_dir = state_dir(home) / "records" / "claude"
            rec_dir.mkdir(parents=True)
            rec_path = rec_dir / ("b" * 32 + ".json")
            rec_path.write_text("{}", encoding="utf-8")
            (config_dir(home) / "state.json").write_text("{not json", encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PYTHONPATH"] = str(ROOT)
            runner_py = ROOT / "bin" / "agent-desk-runner"
            proc1 = subprocess.Popen(
                [sys.executable, str(runner_py), "serve", "--test", "--plugin-dir", str(plugin)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            lock_path = config_dir(home) / "runner.lock"
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if lock_path.exists() and proc1.poll() is None:
                    break
                time.sleep(0.02)
            else:
                proc1.kill()
                self.fail("runner.lock did not appear")
            rec_mtime = rec_path.stat().st_mtime_ns
            proc2 = subprocess.Popen(
                [sys.executable, str(runner_py), "serve", "--test", "--plugin-dir", str(plugin)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            try:
                err = proc2.stderr.read()
                proc2.wait(timeout=2)
                self.assertEqual(proc2.returncode, 75)
                self.assertIn(b"another runner holds runner.lock", err)
                self.assertTrue(rec_path.is_file())
                self.assertEqual(rec_path.stat().st_mtime_ns, rec_mtime)
            finally:
                for stream in (proc1.stdin, proc1.stdout, proc1.stderr, proc2.stdin, proc2.stdout, proc2.stderr):
                    if stream:
                        stream.close()
                try:
                    proc1.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc1.kill()
                    proc1.wait(timeout=2)

    def test_disabled_provider_dropped_from_schedule_and_all_refresh(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin, floor_sec=0.0, interval_sec=900.0)
            aid = "h" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            self.assertIn(aid, runner.scheduler.entries)
            runner.handle_command({"cmd": "settings", "providerEnabled": {"claude": False}})
            self.assertNotIn(aid, runner.scheduler.entries)
            runner.handle_command({"cmd": "refresh", "accountId": "all", "manual": True})
            self.assertNotIn(aid, runner.scheduler.entries)
            self.assertFalse(any(e.get("inflight") for e in runner.scheduler.entries.values()))
            runner.shutdown_workers()

    def test_cli_appearing_later_imports_on_tick(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin)
            runner.path_probe = "ok"
            empty_bin = home / "empty-bin"
            empty_bin.mkdir()
            runner.path = str(empty_bin)
            runner.detect_and_import()
            self.assertEqual(runner.state["accounts"], [])
            cli_dir = home / "later-bin"
            cli_dir.mkdir()
            claude = cli_dir / "claude"
            claude.write_text("#!/bin/bash\necho claude\n", encoding="utf-8")
            claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
            runner.path = str(cli_dir)
            runner.tick()
            accounts = runner.state["accounts"]
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["provider"], "claude")
            self.assertEqual(accounts[0]["kind"], "imported")
            runner.shutdown_workers()

    def test_import_on_install_creates_imported_claude(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin, probe_timeout_sec=2.0)
            self.assertEqual(runner.state["accounts"], [])
            self.assertEqual(runner.start(), 0)
            self._wait_probe(runner)
            accounts = [a for a in runner.state["accounts"] if a.get("provider") == "claude"]
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["kind"], "imported")
            runner.shutdown_workers()

    def test_imported_account_is_named_by_email_in_snapshot(self):
        # R21: the import placeholder name "default" is shown as the email once
        # identity is known; an explicit name is never overridden.
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin, probe_timeout_sec=2.0)
            self.assertEqual(runner.start(), 0)
            self._wait_probe(runner)
            acct = [a for a in runner.state["accounts"] if a.get("provider") == "claude"][0]
            self.assertEqual(acct["name"], IMPORT_PLACEHOLDER_NAME)
            runner.records[acct["id"]] = {
                "identity": {"email": "me@example.com", "org": "Org"},
                "windows": [{
                    "id": "session", "kind": "session", "label": "Session",
                    "used": 0.4, "resetsAt": None,
                }],
                "fetchedAt": "2023-11-14T13:46:40Z",
            }
            snap = runner.snapshot_event()
            shown = [a for a in snap["state"]["accounts"] if a["id"] == acct["id"]][0]
            self.assertEqual(shown["name"], "me@example.com")
            self.assertEqual(snap["readout"]["top"]["accountName"], "me@example.com")
            acct["name"] = "work"
            shown = [a for a in runner.snapshot_event()["state"]["accounts"] if a["id"] == acct["id"]][0]
            self.assertEqual(shown["name"], "work")
            # sameAccountAs names the other account by its display name (email
            # for an imported placeholder), never the raw placeholder.
            acct["name"] = "default"
            twin = dict(acct, id="twin-id", name="default")
            runner.state["accounts"].append(twin)
            runner.records["twin-id"] = {"identity": {"email": "me@example.com", "org": "Org"}}
            recs = runner.snapshot_event()["records"]
            entry = recs[acct["id"]] if isinstance(recs, dict) else [r for r in recs if r.get("accountId") == acct["id"]][0]
            self.assertEqual(entry["sameAccountAs"]["name"], "me@example.com")
            runner.shutdown_workers()

    def test_sync_schedule_keeps_inflight_when_disabled(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, SLEEPING_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = make_runner(
                plugin, probe="ok", clock=clock, collector_timeout_sec=2.0, floor_sec=0.0, interval_sec=900.0,
            )
            aid = "i" * 32
            slow_home = str(home / "slow")
            Path(slow_home).mkdir()
            runner.state["accounts"] = [account(aid, slow_home)]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            runner.scheduler.force(aid)
            runner.tick()
            self.assertTrue(runner.scheduler.entries[aid]["inflight"])
            deadline = time.time() + 1.0
            proc = None
            while time.time() < deadline:
                proc = runner.scheduler.entries[aid].get("proc")
                if proc is not None:
                    break
                time.sleep(0.02)
            self.assertIsNotNone(proc)
            runner.handle_command({"cmd": "settings", "providerEnabled": {"claude": False}})
            self.assertIn(aid, runner.scheduler.entries)
            self.assertTrue(runner.scheduler.entries[aid]["inflight"])
            self.assertIs(runner.scheduler.entries[aid]["proc"], proc)
            starts = runner.scheduler.entries[aid]["lastStartMono"]
            runner.handle_command({"cmd": "settings", "providerEnabled": {"claude": True}})
            self.assertEqual(runner.scheduler.entries[aid]["lastStartMono"], starts)
            self.assertTrue(runner.scheduler.entries[aid]["inflight"])
            runner.shutdown_workers()
            self.assertIsNotNone(proc.poll())

    def test_probe_unchanged_does_not_mark_dirty(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin)
            runner.path = "/same/path"
            runner.path_probe = "ok"
            runner.probe_envs = {"CLAUDE_CONFIG_DIR": ""}
            runner._dirty = False
            body = b"\n__AGENT_DESK__/same/path__AGENT_DESK__\n\n__AGENT_DESK____AGENT_DESK__\n"
            runner._handle_probe({"type": "probe", "timed_out": False, "code": 0, "stdout": body})
            self.assertFalse(runner._dirty)
            runner.path = "/old/path"
            runner._handle_probe({"type": "probe", "timed_out": False, "code": 0, "stdout": body})
            self.assertTrue(runner._dirty)
            runner.shutdown_workers()

    def test_write_and_publish_oserror_keeps_serving(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin)
            aid = "j" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            rec = {"status": "ok", "provider": "claude", "help": ""}
            real_open = os.open

            def deny_record(path, flags, *args):
                text = str(path)
                if text.endswith(".json") or text.endswith(".json.tmp"):
                    raise OSError("denied")
                return real_open(path, flags, *args)

            with patch("os.open", deny_record):
                runner._write_record(aid, rec)
            snap = runner.snapshot_event()
            self.assertEqual(snap["error"], "record-write-failed")
            log = (state_dir(home) / "runner.log").read_text(encoding="utf-8")
            self.assertIn("record write failed", log)
            self.assertNotIn(str(state_dir(home)), log)
            self.assertNotIn(str(home / ".claude"), log)
            with patch("agentdesk.state.os.open", side_effect=OSError("denied")):
                runner._publish()
            snap = runner.snapshot_event()
            self.assertEqual(snap["error"], "state-write-failed")
            events = runner.handle_command({"cmd": "snapshot"})
            self.assertEqual(events[0]["event"], "snapshot")
            runner.shutdown_workers()

    def test_start_creates_state_and_records_dirs(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            sd = state_dir(home)
            shutil.rmtree(sd)
            self.assertFalse(sd.exists())
            runner = make_runner(plugin)
            self.assertEqual(runner.start(), 0)
            rec = sd / "records"
            self.assertTrue(sd.is_dir())
            self.assertTrue(rec.is_dir())
            self.assertEqual(stat.S_IMODE(sd.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(rec.stat().st_mode), 0o700)
            runner.shutdown_workers()

    def test_probe_single_flight(self):
        with fixture_home("signed-in") as home:
            hang = home / "hang_shell"
            hang.write_text("#!/bin/bash\nexec sleep 30\n", encoding="utf-8")
            hang.chmod(hang.stat().st_mode | stat.S_IEXEC)
            os.environ["SHELL"] = str(hang)
            plugin = write_plugin(home, OK_COLLECTOR)
            runner = make_runner(plugin, probe_timeout_sec=2.0, grace_sec=0.2)
            runner._submit_probe()
            runner._submit_probe()
            runner._submit_probe()
            self.assertEqual(getattr(runner, "_probe_inflight", None), True)
            probe_threads = [t for t in runner.threads if t.is_alive()]
            self.assertEqual(len(probe_threads), 1)
            runner.shutdown_workers()
            proc = getattr(runner, "_probe_proc", None)
            if proc is not None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
                self.assertIsNotNone(proc.poll())

    def _wait_pids(self, slow_home: Path, timeout=1.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            cpath = slow_home / "collector.pid"
            gpath = slow_home / "grandchild.pid"
            if cpath.is_file() and gpath.is_file():
                return int(cpath.read_text()), int(gpath.read_text())
            time.sleep(0.02)
        self.fail("collector/grandchild pid files did not appear")

    def _wait_probe(self, runner, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            runner.tick()
            if runner.path_probe != "pending":
                return
            time.sleep(0.02)
        self.fail("path probe still pending after %.1fs" % timeout)

    def _wait_idle(self, runner, timeout=1.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            runner.tick()
            if not any(e.get("inflight") for e in runner.scheduler.entries.values()):
                return
            time.sleep(0.02)
        runner.tick()
        self.fail("workers still inflight after %.1fs" % timeout)


if __name__ == "__main__":
    unittest.main()
