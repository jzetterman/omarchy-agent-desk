# Agent Desk — design notes (mechanism moved out of the spec)

Seed for the implementation plan's design section. Extracted from spec v11 on 2026-09-02 (US Eastern) with the Fable pass's fixes applied. Every paragraph here serves an invariant in spec v12; the spec's acceptance criteria pin the behavior, this file says how. Edit here, not in the spec.

## D1. Isolated-home token refresh (serves R5, A3, A3b)

Applies only to isolated homes. Sequence per collector run:
1. Skip unless the token has been expired for at least 10 minutes (a live CLI in that home refreshes at expiry, so a long-expired token implies no session there). Skipped → `expired`/`deferred`, keep last-known, no backoff.
2. Take the per-home lock, and the CLI's own credential lock file where the descriptor names one. Hold both from inspection through replacement. Exclusion between collectors, replacement, removal, and startup recovery is by these locks only; no process ids are persisted or signaled.
3. If the descriptor-named refresh temp file exists: if it parses as a complete credential file and its 0600 sidecar `<temp>.base` holds the sha256 of the credential file as it is now, commit it by rename (a prior run answered but failed to commit and nothing rewrote the file since); otherwise delete both. Either way abort this run as `expired`/`deferred`. An incomplete temp file cannot distinguish "killed before the request" from "killed mid-write"; the next attempt discovers an invalidated grant on its own, so this path never reports `grant-rejected`.
4. Create the temp file with exclusive create (`O_CREAT|O_EXCL`) at 0600 and write the step-6 base hash into `<temp>.base` at 0600. Create failure → `deferred`.
5. Require at least 2 s of the collector timeout remaining; else `deferred`.
6. Snapshot a cryptographic hash of the credential file at run start; re-read under the lock immediately before the request; if the hash differs, `deferred` (a CLI wrote in the meantime).
7. Send the grant to the descriptor's constant refresh URL with the descriptor's public client id. Never follow any redirect (any 3xx is `failed`, no second connection). TLS verification never disabled.
8. On 401/403/`invalid_grant` → `expired`/`grant-rejected`, file untouched. Unreachable → `offline`. 429 → `rate-limited`. Timeout, 5xx, malformed → `failed`. All enter backoff.
9. On success, rewrite only the current interactive entry (R4) into the temp file, preserving every other entry; fsync; rename over the credential file (0600). If write, fsync, or rename fails after the provider answered, leave the complete fsynced temp as the recovery file for step 3.
10. Remove any temp file this run created on every controlled exit; only a kill can leave one.
Tokens are read from the file (or a 0600 fd) and never exported to env or argv. README residuals: a CLI session racing in the same home; a kill between request and commit.

## D2. Collector runner (serves R6, A10)

- One collector process per (account, run), in its own process group so the hard timeout (30 s) can terminate the group, escalating to kill after 2 s. Grandchildren die with the group. No group ids persist across runner restarts; exclusion is the D1 lock.
- Single-flight per account. Each run carries the account's generation token; replacement and removal advance it, and a result with a stale token is discarded before it touches cache or state.
- Backoff: scheduled runs only, per account; starts at 2× interval, doubles, caps at 8×; cleared by any successful run or non-backoff status. Manual triggers (right click, `r`, IPC refresh, panel open, past-reset queue) ignore backoff and obey the 60 s per-account floor.
- The clock and the floor are injectable in tests (R34); no acceptance test waits on wall-clock.

## D3. Startup cleanup and login ownership (serves R7a, R10, R11, A6c)

- Cleanup runs only after plugin state loads and validates. It lists `homes/<provider>/` once, considering only canonical, non-symlink direct children, and deletes trees that are not saved accounts. It takes each tree's D1 lock first; a tree whose lock is held is skipped this pass.
- Agent Desk owns the login process: the CLI (or a thin wrapper that records its own pid and start time into the staging tree) is spawned as a direct child of a terminal invocation Agent Desk controls. Success and cancellation are judged on that process, never on the terminal launcher's exit (single-instance terminals return immediately). A recorded login process is signaled only if the leader's start time from `/proc` matches the recorded value; otherwise it is treated as gone.
- If a live login cannot be verified gone, the tree is renamed to a quarantined pending-cleanup name rather than deleted.
- Completion of a login is a usable identity from the collector's `identity` mode, polled every 1 s; failure is the owned process exiting with identity still unusable.

## D4. Isolated-home path validation (serves R8)

Before any read, write, refresh, login, replacement, launch, or deletion: derive the path solely from provider id and account id; require it to be a canonical, non-symlink direct child of `homes/<provider>/`; require the credential and account-state paths to be absent or regular non-symlink files, existence being required only by operations that consume them. Anything else fails closed and reports. Shared-entry relink moves the diverged copy to `<entry>.diverged.<UTC timestamp>` (suffix `-2`, `-3` on collision, never overwrite) and recreates the link to the recorded default-home target.

## D5. Credential replacement transaction (serves R10, R11, A6, A6b, A6e)

Under both homes' D1 locks in a fixed order plus the CLI lock where present: revalidate the target's credential hash under the lock; write only the descriptor-selected interactive entry into a 0600 exclusive transaction temp in the target home, preserving the target's other entries; merge the descriptor-declared identity keys of account-state entries from staging while preserving configuration keys; fsync; atomic rename; only then delete the staging tree. On any failure the target is untouched. Removal publishes one atomic state update (account removed, imported account active) before deleting the tree, so a crash leaves an orphan for D3.

## D6. Routing shim (serves R13, R30, A5, M4)

- One shim per currently installed launch-provider binary at `~/.local/bin/<binary>`, mode 0755, carrying a marker line. Install preflights every target; if any target exists without the marker (even with identical bytes) install refuses as a whole and writes nothing; otherwise each file is written atomically and a failure rolls back that install. No backups: install never replaces a non-marked file, so removal simply deletes marked shims and the marked PATH fragment and leaves anything unmarked untouched, reported.
- Runtime, at every invocation: resolve the real CLI as the next binary of the same name on `PATH` after removing the shim's own directory and any entry whose file carries the marker; never exec a marked file; no recorded path. If none exists, exit non-zero with a short message. If the descriptor's home variable is already set in the environment, exec the real CLI unchanged (explicit wins). Read plugin state; canonicalize both sides (state path; recorded imported home; real path of `homes/<provider>/<id>`), resolving `~`, `.`, `..`, symlinks, trailing slashes; apply the home only on an exact canonical match with that provider's imported home or the isolated home of the saved account id, by exec of the real CLI with the home variable set in the child environment; for the imported account, only when the variable selected the default home at import (recorded as homeFromEnv), since setting it to the CLI's own default relocates state files such as Claude's `.claude.json`. Missing, unreadable, or malformed state, or any other path → exec unchanged. Valid state naming a saved account whose directory is missing → exit non-zero (never silently the default home). These are the only fail-closed cases.
- PATH precedence is a plan decision, not a mise assumption. On this machine `~/.grok/bin` is PATH entry 1, mise tool dirs are 7–13, and `~/.local/bin` is 24, so a mise `conf.d` fragment cannot win. Install must verify, per provider, that a new interactive login shell resolves the plain command to the shim, and report any shadowed provider with the shadowing PATH entry; routing is then "partial", not on. Candidates: an rc-file prepend, mise `[env]`/shims ordering, or relocating the shim; decide in the plan.

## D7. Scale normalization (serves R3, A1)

Scale is a per-collector decision from the provider contract. Claude's payload varies (0..1 or 0..100), so the Claude collector sniffs the whole payload (any utilization > 1 → points). Grok always reports points. Codex reports what its RPC declares. Clamp to 0..1 after conversion.

## D8. Network policy (serves R29)

Every usage, identity, and refresh URL is an `https://` constant in the descriptor. Collectors never disable TLS verification and never follow redirects. Credentials travel only in headers or bodies to those constants.
