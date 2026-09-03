# Phase 1 fix-1 report — Agent Desk

Implementer worktree, branch `phase-1`. No commit. Live-shell install was not run. `omarchy-shell` was not called.

## 1. Verify command output

### `python3 -m unittest discover -s tests -v`

```
Ran 104 tests in 6.822s

OK
```

All 104 tests passed. Named additions include scheduler snapshot dirty, unknown-provider no-spin, settings interval, PATH probe via fake_shell, grandchild pid kill, unreadable-state records, disabled-provider drop, import-on-tick, import-on-install, probe single-flight, state validate (`generation: "oops"`), mixed sniff, Authorization header, TLS `error == "tls"`, 301/307/308, readout funded/spent and no-numeric-used, symlink binary, quoted probe slots, and `tests/test_manifest.py`.

### `OMARCHY_PATH=/usr/share/omarchy bin/check`

```
qmllint: ok
validate: ok
```

Then the same 104 python tests (`Ran 104 tests in 6.828s` / `OK`), then:

```
********* Start testing of qmltestrunner *********
Config: Using QtTest library 6.11.2, Qt 6.11.2 (x86_64-little-endian-lp64 shared (dynamic) release build; by GCC 16.2.1 20260810), omarchy 4.0.0.r1849.g83881e9
PASS   : qmltestrunner::FormatTests::initTestCase()
PASS   : qmltestrunner::FormatTests::test_countdown_one_minute_floor()
PASS   : qmltestrunner::FormatTests::test_countdown_two_units()
PASS   : qmltestrunner::FormatTests::test_percent_half_up()
PASS   : qmltestrunner::FormatTests::test_plain_width_matches_plaintext_twin()
PASS   : qmltestrunner::FormatTests::test_tooltip_window()
PASS   : qmltestrunner::FormatTests::cleanupTestCase()
PASS   : qmltestrunner::KeysListMode::initTestCase()
PASS   : qmltestrunner::KeysListMode::test_activate_sets_active()
PASS   : qmltestrunner::KeysListMode::test_cards_filter_only_no_sort()
PASS   : qmltestrunner::KeysListMode::test_cursor_walk_and_wrap()
PASS   : qmltestrunner::KeysListMode::test_escape_closes()
PASS   : qmltestrunner::KeysListMode::test_move_and_focus_return_fresh_state()
PASS   : qmltestrunner::KeysListMode::test_r_refreshes()
PASS   : qmltestrunner::KeysListMode::test_section_jump()
PASS   : qmltestrunner::KeysListMode::cleanupTestCase()
Totals: 16 passed, 0 failed, 0 skipped, 0 blacklisted, 5ms
********* Finished testing of qmltestrunner *********
test_qml_plaintext: ok
```

`qmltestrunner` is required (exit 1 if missing). QML files for qmllint are discovered with the same `find` as the plaintext test.

### `git status --short`

```
 M AccountCard.qml
 M Format.js
 M Keys.js
 M Panel.qml
 M Service.qml
 M WindowRail.qml
 M agentdesk/clock.py
 M agentdesk/descriptor.py
 M agentdesk/record.py
 M agentdesk/routing.py
 M agentdesk/runner.py
 M agentdesk/state.py
 M bin/check
 M providers/claude/collector.py
 M providers/claude/descriptor.json
 M tests/qml/tst_format.qml
 M tests/qml/tst_keys.qml
 M tests/support/fake_clock.py
 M tests/support/fake_shell
 M tests/test_collector_claude.py
 M tests/test_http.py
 M tests/test_qml_plaintext.sh
 M tests/test_readout.py
 M tests/test_routing.py
 M tests/test_scheduler.py
?? tests/fixtures/payloads/claude/ok-mixed-sniff.json
?? tests/test_manifest.py
?? tests/test_state.py
?? PHASE1-FIX1-REPORT.md
```

No `docs/` edits. No live install.

## 2. Item-by-item

### Blockers

| Id | Status | Notes |
|---|---|---|
| B1 | done | `_dirty` set in `_handle_collector`, `_handle_probe`, and `detect_and_import` (on import). Serve emits when dirty, then clears. Tuple compare removed. Test: two collector results → two snapshots. |
| B2 | done | `_sync_schedule` skips providers without a descriptor. Early returns in `_spawn_collector` (no account / no desc / isolated-home fail) bump `nextDueMono`. Inflight/held still skip without bump. Test: provider `codex` with no descriptor → no entry, `next_timeout()` is `None` or `> 0`. |
| B3 | done | Deleted `Panel.qml` `onSettingsChanged` overwrite. `Service.qml` sends `settings` on `onSettingsChanged` while the process runs. `Scheduler.set_interval`: never-run (`lastStartMono is None`) becomes due now. Test: second settings command recomputes `nextDue`. |
| B4 | done | Probe interpolates `"${PATH-}" "${CLAUDE_CONFIG_DIR-}" …`. `fake_shell` does `set +u` before `eval`. Test: one home var unset, the other set, slots parse correctly. |
| B5 | done | (a) Timeout test records collector + grandchild pids and asserts `os.kill(pid, 0)` raises `ProcessLookupError` for both. (b) Removed `interactive_path` / `_path_injected`. SHELL is `tests/support/fake_shell` via `homes.py`. Tests: `pathProbe == "ok"` and PATH starts with `tests/support/fake_cli`; hanging SHELL + `probe_timeout_sec=0.2` → `fallback`. |

### Should-fix — runner and collector

| Id | Status | Notes |
|---|---|---|
| S1 | done | `real_binary` follows symlinks, requires `S_ISREG` on the target, checks marker on the resolved file. Symlink rejection stays in `paths.isolated_home`. Test: symlinked fake binary. |
| S2 | done | `_load_records` and `_sync_schedule` run in `start()` after `take_lock()`. `_load_records` returns early when `state_error` is set. Tests: unreadable state leaves records; second instance exits 75 and does not change the record mtime. |
| S3 | done | Disabled providers dropped in `_sync_schedule`; `"all"` refresh only walks remaining entries. Test added. |
| S4 | done | `tick()` calls `detect_and_import()` (a `stat` per descriptor via `real_binary`). Test: CLI that appears later is imported on the next tick. |
| S5 | done | Balance top includes `funded` and `spent`. |
| S6 | done | Snapshot accounts emitted in card order; `providers` in `providerOrder`. `cards_for` deleted. `Keys.cards` and `Panel.accountsFor` only filter by provider. Keys walks `snapshot.providers`. |
| S7 | done | `Keys.move` / `focusOnOpen` return fresh objects. Removed `keyState = keyState` nudge. Hover writes a new state object. |
| S8 | done | Deleted `warningThreshold` / `criticalThreshold` from AccountCard and WindowRail. Rails use a local `used >= 0.9` for meter colour only; readout colouring stays on the runner. |
| S9 | done | Collector `except Exception` writes `collector: <ExceptionName>` to stderr. Runner logs `collector <provider> <status> exit <code>`. |
| S10 | done | `_log` wrapped in `try/except OSError`, same idea as `_truncate_log`. |
| S11 | done | `RECORD_FIELDS` is the normalize allowlist. Removed `Scheduler.timeout_sec`/`grace_sec`, `note_start`'s `proc` argument, `job["proc"]`, and Service's no-op `next.error = null`. |
| S12 | done | One `twoUnits` helper in Format.js (dropped empty-parts branches). One `Runner._now_iso()`. |
| S13 | done | `snapshot_event` builds `providers` once and passes it to `first_provider_id`. |
| S14 | done | Probe, collectors, and terminal launch use `stdin=subprocess.DEVNULL`. |
| S15 | done | `validate` type-checks generation/shims/shadowed; any validation exception yields `state-unreadable`. Test: `"generation": "oops"`. |
| S16 | done | Collector `read_json` uses `os.open(O_RDONLY\|O_NOFOLLOW\|O_NOCTTY\|O_CLOEXEC)`, `fstat` must be `S_ISREG`, reads from the fd. |
| S17 | done | One inflight probe. `shutdown_workers` kills the inflight probe shell. Test added. |
| S18 | done | `bin/check` discovers QML with the same `find` as `test_qml_plaintext.sh`; exits 1 if `qmltestrunner` is missing. |
| S19 | done | Quote exemption only when the rest of the line has no `+` or `${`. |

### Should-fix — UX

| Id | Status | Notes |
|---|---|---|
| U1 | done | `readonly property bool vertical: bar ? bar.vertical : false`. Readout uses `root.vertical`. |
| U2 | done | Icon and readout both use `root.barForeground`; urgent (and urgent-tint) for warning/critical. |
| U3 | done | Title mark uses `Color.popups.background` via `popupMarkSource()`. |
| U4 | done | Status strip maps enum → labels; rate-limited/offline/failed append ` · ` + `Format.ago`. Raw enum never shown. |
| U5 | done | Not-installed hint: `Style.normalFillFor`, `Border.controlSpec("normal", …)`, `Style.cornerRadius`. |
| U6 | done | Card `MouseArea.cursorShape: Qt.PointingHandCursor`. |
| U7 | done | `Style.space(6)` between meta block and rails (`topPadding: Style.space(5)` plus column spacing). Rails use `space(4)` inside. Label is `body`, percent is `caption`. |
| U8 | done | `providerIds` / `accountIdsByProvider` / `railIds` only reassigned when the id list changes, so delegates update in place. |
| U9 | done | After `Keys.move`, `scrollCursorIntoView` maps the focused card into `panelFlick` and clamps `contentY`. |

### Nits

| Id | Status | Notes |
|---|---|---|
| N1 | done | `--plugin-dir` requires `--test`. |
| N2 | done | Negative utilization clamps to 0 and keeps the window. |
| N3 | done | Removed post-replace generation write; backoff `min(8, 2*prev)`; dropped list-comp around `_cards`; dropped redundant `or {}`; dropped unreachable `or not home`; descriptor credential read once; `fallback_path` no longer double-`expanduser`. |
| N4 | done | `implicitWidth: Style.space(200)`; `NETWORK_CAP_SEC`; `import stat` at collector module top; explicit `math.isnan`. |
| N5 | done | FakeClock lives in `tests/support/fake_clock.py`. `agentdesk/clock.py` is `Clock` only. Runner `main` uses a tiny `_EnvClock` when `AGENT_DESK_NOW` is set under `--test`. Collector `build_clock(False)` ignores env. |
| N6 | done | Marks `Style.space(14)` / `space(12)`; skeleton mirrors rail geometry; section header row is full width and elides the plan; backticks dropped from collector/descriptor help; ages read `"20 min ago"`. |
| N7 | done | Lock test polls for `runner.lock`; HTTP 301/307/308 + TLS `error == "tls"`; `percent(0.745)==75` and `percent(0.005)==1`; `_wait_idle` fails on timeout; `tests/test_state.py`; mixed sniff fixture; import-on-install; Authorization header; `build_http(False).cafile is None` and `build_clock(False)` is a real `Clock` with both env vars set; readout with no numeric used; golden tooltip `"resets in 5d 2h"` and `"stale · 20 min ago"`. |
| N8 | done | Provider ids `^[a-z0-9-]+$`; `omarchy-launch-terminal` and `python3` resolved once with `shutil.which` (caption when the terminal is missing); `runner.log`, `runner.lock`, `state.json.tmp`, and record `.tmp` opened with `O_NOFOLLOW` and 0600 at creation. |
| N9 | done | `tests/test_manifest.py` mirrors `omarchy-plugin-validate:41-115` in stdlib. |

## 3. Deviations

- Never-run scheduler entries use `lastStartMono is None` rather than `0.0`, so a FakeClock that starts at monotonic 0 can still tell “never run” from “started at t=0”.
- After deleting threshold plumbing from the rails, WindowRail still tints the meter at `used >= 0.9`. That is local visual only; readout colouring stays on the runner.
- `take_lock` returns 75 if `runner.lock` cannot be opened (`O_NOFOLLOW` / `ELOOP` / permissions), not only on `BlockingIOError`.
- Keys walks `snapshot.providers` (already in `providerOrder` from the runner). Panel still applies `validated.providerOrder` so a settings change can paint before the settings snapshot returns.

## 4. Open questions

- Imported account name remains `"default"` (owner decision pending).
- Caption bold/tracking treatment left as-is (owner decision pending).
