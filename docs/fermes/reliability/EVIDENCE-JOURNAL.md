# FHM-004 implementation evidence journal

Date: 2026-10-26 UTC
Worktree: `fermes/fhm004-bounded-recovery-20261026`
Starting SHA: `1db86fb2c66ce6ee0625b159d39b850405fa060c`

## Source review

- Confirmed repository identity from `fork` remote, branch, and starting SHA after reading
  `docs/fermes/memory/MEMORY-INDEX.md`, `AGENT-EXECUTION-PROTOCOL.md`, `CONSTRAINTS.md`, and
  `PROJECT-STATE.md`.
- Read the historical Phase 1/2 implementation, tests, compatibility research, safe-orphan
  acceptance report, and implementation notes from the designated read-only reference worktree.
- Compared relevant methods with the current fork's canonical gateway contracts and handlers:
  `runtime.describe`, `session.resume`, `session.detach`, `session.interrupt`, `prompt.receipt`, and
  `session.events.since`. The current contracts include gateway profile/instance/epoch fencing,
  admission and execution-generation identity, and attachment subscriptions. Adapted the polling
  logic to detach every temporary subscription.
- GitHub Issue #4 was subsequently accessed and updated directly. It is the canonical
  P0 acceptance and evidence tracker, with PR #20 linked.

## Changes made

- Added `hermes_cli/fermes_reliability/`: one bounded supervisor, atomic/fsynced schema-v3
  checkpoint and append-only journal, exact gateway interruption/settlement, single-claim orphan
  scanner, and observation-only reconciliation. No prompt submission exists in recovery.
- Added `hermes gateway supervise`, `hermes gateway recover`, and `hermes gateway recover-orphans`.
  Orphan scanning defaults to preview; `--observe` is required to claim and attach.
- Added/ported Phase 1/2 contract tests under `tests/hermes_cli/test_fermes_*.py`, including
  checkpoint symlink refusal, scanner preview, symlink workspace refusal, and existing mismatch,
  unknown-outcome, single-claim, no-replay, and bounded-stop cases. Added a Linux process-group
  isolation test that verifies a TERM-ignoring child is gone after bounded cleanup.
- Added a user-facing maintenance guide. No timer/service template is included or installed.

## Verification state

| Gate | Result | Evidence |
|---|---|---|
| Repository/project identity | PASS | Fork remote, worktree branch, starting SHA inspected |
| Current RPC source/contract comparison | PASS (source review) | See README API section and current paths above |
| Historical reference preserved | PASS | Read-only source path only; no writes there |
| Local reliability unit suite | **PASS: 67 tests, 20 subtests** | Clean isolated locked Python 3.14 env, /tmp/fermes-fhm004-pr-clean-tests.log |
| Isolated real Linux process-tree cleanup | **PASS: 1 real ignoring-child test + shared-group safety guard** | tests/hermes_cli/test_fermes_process_group_isolation.py (included in 67) |
| Existing gateway/delegation regressions | **PASS: 22 tests** | /tmp/fermes-fhm004-native-regressions.log |
| Ruff source/test lint | **PASS** | Clean locked venv, /tmp/fermes-fhm004-lint-fix3.log; rechecked in test run |
| CLI parser and empty scanner preview | **PASS** | /tmp/fermes-fhm004-cli-help2.log; /tmp/fermes-fhm004-preview.log |
| Live gateway stop/crash | **PASS: 2 disposable real-gateway opt-in tests** | /tmp/fermes-fhm004-live-both-tests.log; GitHub Actions 40310182514 SUCCESS |
| Timer/service deployment | NOT DONE | No timer template, installation, or service change |
| Independent review | **PASS: no remaining P0/P1 code defects**; stale docs corrected | /tmp/fermes-fhm004-cursor-review-v2.log; /tmp/fermes-fhm004-cursor-live-final.log |

## Acceptance assessment

- **Completed:** bounded SIGTERM of a real in-flight admitted turn, supervisor SIGKILL,
  one-time manual recovery of the exact admission, preview/no-write scan, gateway
  restart epoch fencing, no replay/no duplicate durable submission, Linux
  process-group negative/positive cleanup, and fail-closed fast unverified turn.
- **Source and CI:** 89 combined source/gateway tests plus 20 unittest subtests;
  two opt-in real Hermes gateway tests passed locally and in the hosted CI run
  [40310182514](https://github.com/fredheathcote007/hermes-agent/actions/runs/40310182514).
  The final documentation-only commit is subject to its own CI check.
- **Independent reviewer:** Cursor found no outstanding P0/P1 code defect; documentation
  contradictions identified by the reviewer were subsequently reconciled.
- **Not in this delivery:** deployment, background timers, non-Linux hosting,
  crash during an irreversible external tool action, or independent verification
  of delegated task success. Those are separate acceptance decisions, principally
  FHM-005. Gateway `TERMINAL` is never evidence of successful external effects.

## Test interpretation / outstanding gates

- Source reference code from historical closed VM qualification passed **55 tests and 20 subtests** before port (/tmp/fermes-fhm004-historical-tests.log), but this does not validate the new fork.
- Source port tests initially failed due fake-process PID omissions, old auto-observe assumptions and absent terminal receipt fixtures; the production contract was strengthened rather than weakened. New synthetic tests now pass.
- A negative test confirmed the original unsafe shared-group signal path was present. Source was corrected to check live `getpgid(pid) == pid` and never signal the caller's shared process group. Both shared-group refusal and isolated descendant cleanup tests pass.
- A recovery case with missing admission ID previously attempted to certify TERMINAL after matching an event; it is now fail-closed BLOCKED, requiring operator inspection instead of implying success.
- Standalone recovery now uses compare-and-swap even without explicit caller-provided expected values, preventing overwrite of a concurrently updated checkpoint.
- **Historical interim boundary (superseded by the next section):** the
  original source port initially lacked a fresh live gateway SIGKILL/restart
  qualification; it was intentionally kept Draft and FHM-005 remained open.
  A subsequent host-run, disposable real-gateway test campaign resolved the
  FHM-004 stop/orphan/restart gates below; it did **not** verify external tool
  effects, delegation or any production timer.
- **Original source acceptance:** 67 unit tests and 20 subtests passed; a
  subsequent combined run with existing gateway/stop/delegation suites passed
  **89 tests plus 20 subtests**. Source-level reviewer confirmed no P0 after
  the live test additions and red/green fast-turn failure correction.

## 2026-10-26 — Real disposable gateway qualification

- **Live SIGTERM during in-flight model response:** PASS. Actual Hermes gateway captured session, authority epoch, generation and admission ID; supervisor signal caused a fail-closed BLOCKED/exit-125 result, with one and only one task model request. Evidence: `/tmp/fermes-fhm004-interrupt-live.log`.
- **Live SIGKILL same-authority recovery:** PASS. Supervisor killed while original admission running, preview made no checkpoint/journal mutation, explicit scanner observation claimed once and returned TERMINAL for the exact admission, second scan skipped, no duplicate model request or durable admission. Evidence: `/tmp/fermes-fhm004-crash-live-isolated.log`.
- **Live gateway restart with different authority:** PASS. Old supervisor killed mid-turn and original gateway restarted from same disposable state; instance ID/authority epoch changed, scanner observed once and returned BLOCKED, second scan required manual review, only one user-task inference and exactly one original durable admission. Catalogue metadata probes were counted separately. Evidence: `/tmp/fermes-fhm004-restart-live.log`.
- **Reproducible opt-in pytest gate:** PASS — two real-gateway tests, `HERMES_FHM004_LIVE=1`, 2 passed in 16.11s (`/tmp/fermes-fhm004-live-both-tests.log`). It is not a simulation of the Hermes gateway: real gateway/CLI subprocesses are launched under disposable HERMES_HOME and loopback model. No external tool side effects.
- **Adjacent/source regression:** PASS — 89 tests and 20 unittest subtests on the FHM-004 branch (`/tmp/fermes-fhm004-final-combined-regressions.log`). The environment received the optional test-only `aiohttp` dependency; no production or shared package change.
- **False-success negative case:** Before fix, a fast answer-only gateway run returned status 0 with checkpoint `SETTLED_UNKNOWN` and no exact admission receipt (real model-stub evidence `/tmp/fermes-fhm004-live-probe.log`); focused unit RED (`/tmp/fermes-fhm004-false-success-red.log`). Corrected `supervise_chat` so fast unknown returns 125; focused regression GREEN (`/tmp/fermes-fhm004-false-success-green.log`).
- **Test harness safety:** Existing autouse system guard rejects destructive signals to foreign process groups. Live tests require both explicit opt-in and `live_system_guard_bypass` marker; they verify disposable PID birth ticks, process group and command identity before signals. A controller environment mismatch in an earlier manual probe attached the wrong default profile; the inadvertently launched idle gateway was identified, confirmed to have no admissions and stopped by exact PID/start identity. Corrected scanner calls launch under explicit ephemeral profile. Only the corrected isolated evidence qualifies.
- **API note:** `session.status` returns formatted human-readable text only in this version; it cannot prove exact generation/admission/authority identity and is not a drop-in substitute for `session.resume`.
- **FHM-005 boundary:** TERMINAL is gateway admission lifecycle evidence, not independent verification of external tools, delegated work or side effects. The test model has no external tools; FHM-005 remains open P0.
