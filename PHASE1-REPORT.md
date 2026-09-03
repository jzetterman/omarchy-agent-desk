# Phase 1 report — Agent Desk

Implementer worktree, branch `phase-1`. No commit. Live-shell install was not run.

## 1. Verify command output

### `python3 -m unittest discover -s tests -v`

```
test_3xx_failed_no_second_request (test_collector_claude.CollectorClaudeTests.test_3xx_failed_no_second_request) ... ok
test_401_expired_rejected (test_collector_claude.CollectorClaudeTests.test_401_expired_rejected) ... ok
test_429_rate_limited (test_collector_claude.CollectorClaudeTests.test_429_rate_limited) ... ok
test_5xx_failed (test_collector_claude.CollectorClaudeTests.test_5xx_failed) ... ok
test_api_key_only_is_not_signed_in (test_collector_claude.CollectorClaudeTests.test_api_key_only_is_not_signed_in) ... ok
test_clamp_above_100 (test_collector_claude.CollectorClaudeTests.test_clamp_above_100) ... ok
test_expired_default_home_opens_no_socket (test_collector_claude.CollectorClaudeTests.test_expired_default_home_opens_no_socket) ... ok
test_identity_from_default_claude_json (test_collector_claude.CollectorClaudeTests.test_identity_from_default_claude_json) ... ok
test_identity_mode_opens_no_socket (test_collector_claude.CollectorClaudeTests.test_identity_mode_opens_no_socket) ... ok
test_malformed_failed (test_collector_claude.CollectorClaudeTests.test_malformed_failed) ... ok
test_no_limits (test_collector_claude.CollectorClaudeTests.test_no_limits) ... ok
test_not_installed (test_collector_claude.CollectorClaudeTests.test_not_installed) ... ok
test_not_signed_in (test_collector_claude.CollectorClaudeTests.test_not_signed_in) ... ok
test_offline (test_collector_claude.CollectorClaudeTests.test_offline) ... ok
test_ok_and_scale_sniff_pairs (test_collector_claude.CollectorClaudeTests.test_ok_and_scale_sniff_pairs) ... ok
test_points_payload_all_below_one_reads_as_fraction (test_collector_claude.CollectorClaudeTests.test_points_payload_all_below_one_reads_as_fraction) ... ok
test_timeout_failed (test_collector_claude.CollectorClaudeTests.test_timeout_failed) ... ok
test_token_not_in_record (test_collector_claude.CollectorClaudeTests.test_token_not_in_record) ... ok
test_two_entries_uses_oauth_not_api_key (test_collector_claude.CollectorClaudeTests.test_two_entries_uses_oauth_not_api_key) ... ok
test_command_binary_must_match (test_descriptor.DescriptorTests.test_command_binary_must_match) ... ok
test_home_env_shape (test_descriptor.DescriptorTests.test_home_env_shape) ... ok
test_http_url_rejected (test_descriptor.DescriptorTests.test_http_url_rejected) ... ok
test_invalid_dir_reported (test_descriptor.DescriptorTests.test_invalid_dir_reported) ... ok
test_refresh_requires_format_and_client (test_descriptor.DescriptorTests.test_refresh_requires_format_and_client) ... ok
test_valid_loads (test_descriptor.DescriptorTests.test_valid_loads) ... ok
test_401_auth (test_http.HttpPolicyTests.test_401_auth) ... ok
test_429_rate_limited (test_http.HttpPolicyTests.test_429_rate_limited) ... ok
test_5xx_failed (test_http.HttpPolicyTests.test_5xx_failed) ... ok
test_https_assert (test_http.HttpPolicyTests.test_https_assert) ... ok
test_redirect_refused_no_second_request (test_http.HttpPolicyTests.test_redirect_refused_no_second_request) ... ok
test_tls_default_rejects_untrusted_cert (test_http.HttpPolicyTests.test_tls_default_rejects_untrusted_cert) ... ok
test_tls_with_cafile_succeeds (test_http.HttpPolicyTests.test_tls_with_cafile_succeeds) ... ok
test_active_scope_default (test_readout.ReadoutTests.test_active_scope_default) ... ok
test_all_scope_takes_highest (test_readout.ReadoutTests.test_all_scope_takes_highest) ... ok
test_disabled_provider_excluded (test_readout.ReadoutTests.test_disabled_provider_excluded) ... ok
test_empty_scope (test_readout.ReadoutTests.test_empty_scope) ... ok
test_threshold_749_normal_75_warning (test_readout.ReadoutTests.test_threshold_749_normal_75_warning) ... ok
test_ties_provider_then_card_then_kind (test_readout.ReadoutTests.test_ties_provider_then_card_then_kind) ... ok
test_drops_token_keys (test_record.AllowlistTests.test_drops_token_keys) ... ok
test_all_zero (test_record.BalanceUsedTests.test_all_zero) ... ok
test_never_nan_or_inf (test_record.BalanceUsedTests.test_never_nan_or_inf) ... ok
test_normalize_sets_balance_used (test_record.BalanceUsedTests.test_normalize_sets_balance_used) ... ok
test_remaining_only_above_zero (test_record.BalanceUsedTests.test_remaining_only_above_zero) ... ok
test_remaining_zero (test_record.BalanceUsedTests.test_remaining_zero) ... ok
test_spent_over_funded (test_record.BalanceUsedTests.test_spent_over_funded) ... ok
test_clamp_to_unit_interval (test_record.ClampTests.test_clamp_to_unit_interval) ... ok
test_non_finite_clamps_to_zero (test_record.ClampTests.test_non_finite_clamps_to_zero) ... ok
test_normalize_clamps_window_used (test_record.ClampTests.test_normalize_clamps_window_used) ... ok
test_empty_never_matches (test_record.EmailTests.test_empty_never_matches) ... ok
test_normalize_email_domain_and_local (test_record.EmailTests.test_normalize_email_domain_and_local) ... ok
test_kind_order_tuple (test_record.KindOrderTests.test_kind_order_tuple) ... ok
test_normalize_sorts_kind_then_label (test_record.KindOrderTests.test_normalize_sorts_kind_then_label) ... ok
test_unknown_kind_ranks_after_known (test_record.KindOrderTests.test_unknown_kind_ranks_after_known) ... ok
test_known_statuses (test_record.StatusEnumTests.test_known_statuses) ... ok
test_unknown_status_becomes_failed (test_record.StatusEnumTests.test_unknown_status_becomes_failed) ... ok
test_derived_id (test_record.WindowIdTests.test_derived_id) ... ok
test_supplied_id_kept (test_record.WindowIdTests.test_supplied_id_kept) ... ok
test_fallback_path_appends_local_bin_and_install_dirs (test_routing.ProbeParserTests.test_fallback_path_appends_local_bin_and_install_dirs) ... ok
test_probe_parses_between_sentinels (test_routing.ProbeParserTests.test_probe_parses_between_sentinels) ... ok
test_marked_only_is_not_installed (test_routing.RealBinaryTests.test_marked_only_is_not_installed) ... ok
test_real_binary_skips_marker (test_routing.RealBinaryTests.test_real_binary_skips_marker) ... ok
test_failed_keeps_last_known (test_scheduler.MergeRecordTests.test_failed_keeps_last_known) ... ok
test_backoff_ladder_and_clear_on_success (test_scheduler.SchedulerTests.test_backoff_ladder_and_clear_on_success) ... ok
test_manual_floor_skips (test_scheduler.SchedulerTests.test_manual_floor_skips) ... ok
test_runner_lock_refuses_second_instance (test_scheduler.SchedulerTests.test_runner_lock_refuses_second_instance) ... ok
test_single_flight (test_scheduler.SchedulerTests.test_single_flight) ... ok
test_timeout_kills_grandchild_and_sibling_completes (test_scheduler.SchedulerTests.test_timeout_kills_grandchild_and_sibling_completes) ... ok

----------------------------------------------------------------------
Ran 67 tests in 3.728s

OK
```

### `bin/check`

```
qmllint: ok
validate: ok
```

Then the same 67 python tests (`Ran 67 tests in 3.728s` / `OK`), then:

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
PASS   : qmltestrunner::KeysListMode::test_cursor_walk_and_wrap()
PASS   : qmltestrunner::KeysListMode::test_escape_closes()
PASS   : qmltestrunner::KeysListMode::test_r_refreshes()
PASS   : qmltestrunner::KeysListMode::test_section_jump()
PASS   : qmltestrunner::KeysListMode::cleanupTestCase()
Totals: 14 passed, 0 failed, 0 skipped, 0 blacklisted, 5ms
********* Finished testing of qmltestrunner *********
test_qml_plaintext: ok
```

### `bash tests/test_qml_plaintext.sh`

```
test_qml_plaintext: ok
```

## 2. File list

```
AccountCard.qml
Format.js
Keys.js
Panel.qml
PHASE1-REPORT.md
Service.qml
WindowRail.qml
agentdesk/__init__.py
agentdesk/clock.py
agentdesk/descriptor.py
agentdesk/http.py
agentdesk/paths.py
agentdesk/record.py
agentdesk/routing.py
agentdesk/runner.py
agentdesk/state.py
assets/agent-desk-light.svg
assets/agent-desk.svg
bin/agent-desk-runner
bin/check
bin/dev-sync
manifest.json
providers/claude/collector.py
providers/claude/descriptor.json
providers/claude/mark-light.svg
providers/claude/mark.svg
tests/fixtures/homes/claude/api-key-only/.credentials.json
tests/fixtures/homes/claude/expired-10min/.claude.json
tests/fixtures/homes/claude/expired-10min/.credentials.json
tests/fixtures/homes/claude/expired-9min/.claude.json
tests/fixtures/homes/claude/expired-9min/.credentials.json
tests/fixtures/homes/claude/not-signed-in/.credentials.json
tests/fixtures/homes/claude/signed-in/.claude.json
tests/fixtures/homes/claude/signed-in/.credentials.json
tests/fixtures/homes/claude/two-entries/.claude.json
tests/fixtures/homes/claude/two-entries/.credentials.json
tests/fixtures/payloads/claude/clamp.json
tests/fixtures/payloads/claude/malformed.json
tests/fixtures/payloads/claude/no-limits.json
tests/fixtures/payloads/claude/ok-fraction.json
tests/fixtures/payloads/claude/ok-points-below-one.json
tests/fixtures/payloads/claude/ok-points.json
tests/fixtures/tls/cert.pem
tests/fixtures/tls/key.pem
tests/qml/tst_format.qml
tests/qml/tst_keys.qml
tests/support/__init__.py
tests/support/fake_cli/claude
tests/support/fake_cli/codex
tests/support/fake_cli/grok
tests/support/fake_cli/omarchy-launch-terminal
tests/support/fake_clock.py
tests/support/fake_shell
tests/support/fixture_server.py
tests/support/homes.py
tests/test_collector_claude.py
tests/test_descriptor.py
tests/test_http.py
tests/test_qml_plaintext.sh
tests/test_readout.py
tests/test_record.py
tests/test_routing.py
tests/test_scheduler.py
```

## 3. Deviations from the plan

- Isolated expired tokens in `full` mode return `expired`/`deferred` and open no socket. `credfile.py` / E.2 is Phase 5; Phase 1 only implements the default-home short-circuit.
- Bar readout is a sibling `Text` next to `BarIconButton`, not the WidgetButton text slot. `BarIconButton` sets `labelVisible: false` and a fixed slot width, so the text slot cannot sit beside the icon.
- Card pencil, chevron, and per-card terminal button are omitted. R22/R24 are later phases. Header "Open terminal" (R19) is implemented and sends `launch`.
- "+ Add account" is omitted (R23, Phase 3). Routing install/remove UI is omitted (R13, Phase 8).
- Past-reset queue is omitted (Phase 6). `Format.countdown` of a past reset returns `"resetting"` and does not queue a refresh.
- `launch` lives in `runner.py`, not `accounts.py` (`accounts.py` is not a Phase 1 file).
- Imported accounts are named `"default"`. The first collector identity does not rename them.
- `bin/check` uses `/usr/lib/qt6/bin/qmllint` and `/usr/lib/qt6/bin/qmltestrunner`. `/usr/bin/qmllint` and `/usr/bin/qmltestrunner` are Qt 5 and cannot load these files.
- `qmllint -I /usr/share/omarchy/shell` warns that `qs.Ui` / `qs.Commons` cannot be imported (there is no `qs/` directory). First-party panels warn the same way. Exit code is 0. `bin/check` keeps that log on failure only.
- `Format.plain` is also applied to own `Text` live bindings. The A14 grep cannot tell kit props from own `text:` properties.
- Test-only `--plugin-dir` on `agent-desk-runner serve` so scheduler tests can swap in a fake collector.
- `tests/support/fake_cli/omarchy-launch-terminal` and `tests/support/__init__.py` were added under `tests/support/*`.
- `installHint` is stored on the Claude descriptor as an extra key the loader keeps. C.1 does not name that field; D.claude does name the string.

## 4. For Phase 2

- The runner already loads every valid `providers/<id>/descriptor.json` and spawns `providers/<id>/collector.py`. A Codex or Grok directory with a valid descriptor appears in the snapshot with no QML change.
- `compute_readout` already walks every enabled provider and both windows and balances.
- Fake CLIs for `codex` and `grok` already live under `tests/support/fake_cli/`. They only implement the stubs Phase 1 needed.
- `agentdesk/http.py` is shared. Codex should not use it (CLI RPC). Grok will.
- Identity-mode collector contract is implemented for Claude and is what login polling will call later.
- PATH probe home-env list is built from every loaded descriptor's `homeEnv`, in id order after `PATH`. Adding Codex/Grok descriptors extends the probe automatically.
- Do not add network calls to identity mode.

## 5. Open questions

- Should an imported account's `name` become the email once identity arrives, or stay `"default"` with email on the meta line?
- Should header "Open terminal" close the panel? The stock agents launcher does; R19 does not say to.
- How should local `qmllint` resolve `qs.Ui` without a `qs/` directory? Warnings match first-party panels; not blocking.
- Isolated-home `full` mode in Phase 1 reports `expired`/`deferred` and never refreshes. Confirm that is the intended bridge until Phase 5.
