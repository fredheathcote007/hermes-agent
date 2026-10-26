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
- Live GitHub Issue #4 was unavailable through the browser fetch in this environment. The user
  supplied issue requirements and remains the acceptance source for this task.

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
| Isolated real Linux process-tree cleanup | **PASS: 1 real ignoring-child test + shared-group safety guard** | tests/hermes_cli/test_fermes_process_group_isolation.py (included in 65) |
| Existing gateway/delegation regressions | **PASS: 22 tests** | /tmp/fermes-fhm004-native-regressions.log |
| Ruff source/test lint | **PASS** | Clean locked venv, /tmp/fermes-fhm004-lint-fix3.log; rechecked in test run |
| CLI parser and empty scanner preview | **PASS** | /tmp/fermes-fhm004-cli-help2.log; /tmp/fermes-fhm004-preview.log |
| Live gateway stop/crash | NOT RUN | No live runtime or destructive fault injection authorized here |
| Timer/service deployment | NOT DONE | No timer template, installation, or service change |
| Independent review | Initial Cursor found P0/P1, **remediated and second review in progress** | /tmp/fermes-fhm004-cursor-review.log; /tmp/fermes-fhm004-cursor-review-v2.log |

## Remaining acceptance gates

1. On the authorized host, prepare the repository's separate test environment and run only:
   `scripts/run_tests.sh tests/hermes_cli/test_fermes_bounded_supervisor.py`
   `scripts/run_tests.sh tests/hermes_cli/test_fermes_supervise_chat.py`
   `scripts/run_tests.sh tests/hermes_cli/test_fermes_recovery.py`
   `scripts/run_tests.sh tests/hermes_cli/test_fermes_recover_orphans.py`
   `scripts/run_tests.sh tests/hermes_cli/test_fermes_process_group_isolation.py`
2. Run the applicable repository lint/check gate and resolve every failure; record the exact SHA,
   interpreter/tool versions, commands, and results. Do not label this source review as a runtime
   PASS.
3. Obtain independent source review, then schedule an owner-authorized disposable live qualification
   covering timeout/explicit stop, a descendant process, admission receipt reconciliation, reboot or
   changed-owner identities, and no replay after an unknown outcome. Preserve full provenance and
   keep production gateway/timer state unchanged.
4. Close remaining delegated-worker proof requirements under FHM-005 only after that issue's own
   independent evidence gate is satisfied.

## Test interpretation / outstanding gates

- Source reference code from historical closed VM qualification passed **55 tests and 20 subtests** before port (/tmp/fermes-fhm004-historical-tests.log), but this does not validate the new fork.
- Source port tests initially failed due fake-process PID omissions, old auto-observe assumptions and absent terminal receipt fixtures; the production contract was strengthened rather than weakened. New synthetic tests now pass.
- A negative test confirmed the original unsafe shared-group signal path was present. Source was corrected to check live `getpgid(pid) == pid` and never signal the caller's shared process group. Both shared-group refusal and isolated descendant cleanup tests pass.
- A recovery case with missing admission ID previously attempted to certify TERMINAL after matching an event; it is now fail-closed BLOCKED, requiring operator inspection instead of implying success.
- Standalone recovery now uses compare-and-swap even without explicit caller-provided expected values, preventing overwrite of a concurrently updated checkpoint.
- **NOT YET QUALIFIED:** genuinely interrupted live gateway after supervisor death, gateway-side effects from `session.resume`, independent verification of external tool mutations, cold resume after reboot, and any production timer. The first two require a separately authorised isolated fault-injection environment. FHM-005 remains open.

- 2026-10-26 final host source suite: **67 passed, 20 subtests passed**, Ruff clean. /tmp/fermes-fhm004-final-test.log. Additional negative tests enforce operator BLOCKED checkpoint refusal and lost process-group-leader group-signal refusal. Independent second Cursor review permitted **draft PR only** and explicitly left live gateway crash/reattach effects unresolved.
