"""Scheduler: A10 timeout/backoff, floor, single-flight, runner.lock."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agentdesk.clock import FakeClock  # noqa: E402
from agentdesk.runner import Runner, merge_record  # noqa: E402
from support.homes import NOW, fixture_home  # noqa: E402

SLEEPING_COLLECTOR = r'''
import json, os, sys, time
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
    if os.fork() == 0:
        time.sleep(30)
        os._exit(0)
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
    "installHint": "Install Claude Code: `mise use -g claude@latest`",
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


def account(aid, home, generation=1):
    return {
        "id": aid,
        "provider": "claude",
        "kind": "imported",
        "name": "default",
        "home": home,
        "homeFromEnv": False,
        "createdAt": "2023-11-14T13:46:40Z",
        "generation": generation,
    }


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
            runner = Runner(
                plugin_dir=plugin,
                clock=clock,
                collector_timeout_sec=0.2,
                probe_timeout_sec=0.2,
                grace_sec=0.2,
                floor_sec=0.05,
                interval_sec=1.0,
                test_mode=True,
                interactive_path=str(ROOT / "tests" / "support" / "fake_cli"),
            )
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
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = Runner(
                plugin_dir=plugin,
                clock=clock,
                collector_timeout_sec=0.2,
                probe_timeout_sec=0.2,
                grace_sec=0.2,
                floor_sec=60.0,
                interval_sec=900.0,
                test_mode=True,
                interactive_path=str(ROOT / "tests" / "support" / "fake_cli"),
            )
            aid = "b" * 32
            runner.state["accounts"] = [account(aid, str(home / ".claude"))]
            runner.state["active"] = {"claude": aid}
            runner._sync_schedule()
            runner.handle_command({"cmd": "refresh", "accountId": "all", "manual": True})
            self._wait_idle(runner)
            starts = runner.scheduler.entries[aid]["lastStartMono"]
            runner.handle_command({"cmd": "refresh", "accountId": "all", "manual": True})
            self.assertEqual(runner.scheduler.entries[aid]["lastStartMono"], starts)
            self.assertFalse(runner.scheduler.entries[aid]["inflight"])

    def test_single_flight(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, SLEEPING_COLLECTOR)
            clock = FakeClock(now=NOW, monotonic=1000.0)
            runner = Runner(
                plugin_dir=plugin,
                clock=clock,
                collector_timeout_sec=2.0,
                probe_timeout_sec=0.2,
                grace_sec=0.2,
                floor_sec=0.0,
                interval_sec=900.0,
                test_mode=True,
                interactive_path=str(ROOT / "tests" / "support" / "fake_cli"),
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
            runner = Runner(
                plugin_dir=plugin,
                clock=clock,
                collector_timeout_sec=0.2,
                probe_timeout_sec=0.2,
                grace_sec=0.2,
                floor_sec=0.0,
                interval_sec=1.0,
                test_mode=True,
                interactive_path=str(ROOT / "tests" / "support" / "fake_cli"),
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
            self._wait_idle(runner, timeout=2.0)
            self.assertEqual(runner.records[fast_id]["status"], "ok")
            self.assertEqual(runner.records[slow_id]["status"], "failed")
            self.assertEqual(runner.records[slow_id]["windows"][0]["used"], 0.7)
            self.assertEqual(runner.records[slow_id]["fetchedAt"], "2023-11-14T13:00:00Z")
            self.assertEqual(runner.scheduler.entries[slow_id]["backoffMultiplier"], 2)
            self.assertEqual(runner.scheduler.entries[fast_id]["backoffMultiplier"], 1)
            runner.shutdown_workers()

    def test_runner_lock_refuses_second_instance(self):
        with fixture_home("signed-in") as home:
            plugin = write_plugin(home, OK_COLLECTOR)
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
            time.sleep(0.3)
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
            finally:
                for stream in (proc1.stdin, proc1.stdout, proc1.stderr, proc2.stdin, proc2.stdout, proc2.stderr):
                    if stream:
                        stream.close()
                try:
                    proc1.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc1.kill()
                    proc1.wait(timeout=2)

    def _wait_idle(self, runner, timeout=1.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            runner.tick()
            if not any(e.get("inflight") for e in runner.scheduler.entries.values()):
                return
            time.sleep(0.02)
        runner.tick()


if __name__ == "__main__":
    unittest.main()
