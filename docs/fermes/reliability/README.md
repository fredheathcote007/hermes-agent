# Fermes gateway reliability tools

This package adds an explicit, opt-in supervisor for one local `hermes chat` attempt. It owns a
private retained workspace and durable checkpoint, tracks the exact gateway profile/instance/epoch,
session, execution generation, admission, and Linux supervisor process identity, and never resubmits
the prompt during recovery. Checkpoints and journals contain identifiers and status only; prompts,
model output, credentials, and environment values are not persisted there.

The runner stops the exact `session.interrupt` generation after a deadline or stop signal, waits for
an identity-matched idle `session.resume` snapshot, and then confirms its own CLI process has exited.
The CLI process runs in a new Linux process group; cleanup sends bounded TERM then KILL to the group
so surviving descendants do not outlive the supervisor. A missing, mismatched, or ambiguous gateway
receipt leaves the attempt blocked for an operator. A nonzero CLI exit is recorded `SETTLED_UNKNOWN`,
not successful completion. `TERMINAL` means the matching admission has a terminal owner receipt; it
does not certify that external side effects succeeded. Inspect the receipt outcome and original
workspace before deciding the task is complete.

## Commands

Use an existing absolute private parent directory for retained workspaces. The default is the
platform temporary directory; each created workspace is mode-restricted by `mkdtemp`.

```sh
hermes gateway supervise --deadline 900 --workspace-parent /tmp --query-file - <<'TASK'
<your task>
TASK
hermes gateway recover-orphans --workspace-parent /tmp
hermes gateway recover-orphans --workspace-parent /tmp --observe
hermes gateway recover --checkpoint /tmp/hermes-supervised-<id>/phase2-checkpoint.json
```

`--query-file` keeps prompt text out of the supervisor command line and checkpoint. `recover-orphans`
previews by default. `--observe` explicitly permits one durable scanner claim and one reconciliation
attachment to the same gateway attempt. The current `session.resume` path may allow Hermes's own
already-admitted continuation to proceed; this tool never submits another prompt. It does not replay
unknown external effects. Do not delete a `BLOCKED` checkpoint until the session owner has reconciled
the original workspace and side effects.

The scanner accepts only an absolute, existing, canonical, non-symlink parent other than `/` or the
user home. It inspects direct child directories with the supervisor prefix, caps work at 100
entries, skips live owners using PID + `/proc` birth tick + boot ID, uses a single nonblocking
per-attempt claim lock, and stops on malformed/mismatched identities. Reports are atomic JSON.

## Gateway API compatibility

The implementation was checked against the current fork's v0.22.5 source contracts rather than
copying the historical interface assumptions:

- `runtime.describe` exposes `instance_id`, `profile_id`, and `authority_epoch` in
  `gateway/session_controls.py` and `tui_gateway/contracts/canonical.py`.
- `session.resume` returns the session ID, authority epoch, execution generation, running state,
  pending admission rows, replay cursor, and a subscription ID in `gateway/session_controls.py`.
- `session.interrupt` takes the exact execution generation and returns the current session handle;
  `session.detach` confirms the exact session/subscription pair.
- `session.status` is human-readable presentation, not a structured state query. It cannot replace
  `session.resume` when recovery needs trusted session, epoch, generation, running, pending-admission,
  or subscription fields.
- `prompt.receipt` reports the durable admission identity/status, and `session.events.since` is used
  only with the recorded event epoch/cursor. Both use canonical contracts in
  `tui_gateway/contracts/canonical.py`.
- Settlement polling reuses the supervisor's current subscription (the authority reuses an existing
  subscriber for the same authenticated transport) and the supervisor detaches it exactly once at
  shutdown. Standalone polls detach subscriptions they create. This follows the current
  explicit-subscription API and prevents both leaked and prematurely detached subscriptions.

The gateway client is Hermes-owned (`hermes_cli.gateway_client`) and follows the active profile's
`HERMES_HOME`; no Project Coordinator service, timer, environment file, or external coordinator is
required. The supervisor and `/proc` owner scanner currently support Linux only. The code does not
install or enable a timer. The gateway client's normal local ensure path may start the current
profile's gateway when supervision or explicit recovery is invoked while no owner is ready.

## Qualification status and limitations

An opt-in Linux live integration qualification now lives at
`tests/hermes_cli/test_fermes_live_recovery.py`. It starts the real local gateway and supervisor in
disposable `HOME`/`HERMES_HOME` directories, uses a deterministic blockable OpenAI-compatible HTTP
stub bound to `127.0.0.1`, checks a bounded SIGTERM stop, kills a second supervisor with SIGKILL
during an active request, proves the orphan scan preview leaves the checkpoint and journal byte
identical, then permits exactly one read-only recovery attachment. It verifies the same admission,
profile, instance, authority epoch, session, and generation remain bound and that the model sees each
submitted marker once. Gateway and process-group termination is guarded by PID, process start time,
process group, and command identity.

Run it only on an authorized Linux host with the repository's isolated test environment:

```sh
HERMES_FHM004_LIVE=1 scripts/run_tests.sh tests/hermes_cli/test_fermes_live_recovery.py
```

The test is skipped unless explicitly enabled. It needs the installed test dependencies available to
that runner, Linux `/proc`, loopback TCP, and time for two local model turns. It does not contact a
public provider, install a service, or start a timer. The current worktree has not run this test;
adding it is not live qualification evidence.

The historical Phase 1/2 source, tests, and evidence under
`/srv/project-coordinator/projects/hermes-v0225-phase2-20261025` informed this port and remain
untouched. Those historical VM results do not qualify this fork revision. New copied/ported tests
are present under `tests/hermes_cli/test_fermes_*.py`; the host supervisor ran them in a clean
isolated locked Python 3.14 test environment (67 tests and 20 subtests PASS) and
also ran 22 existing Hermes gateway/delegation regressions (PASS). No live gateway, deliberate process kill, timer, or production
service was used for this implementation; the opt-in live test above remains an unrun acceptance gate.

Before calling FHM-004 accepted, require an independent review and complete the missing
real-world gateway/supervisor interruption gates. Then run the opt-in test above on the authorized
host and review its actual result: it must demonstrate the exact original admission is stopped or
observed once, descendants are gone, and no second prompt is submitted. Independent verification of
delegated work and stop outcomes belongs to FHM-005 and remains a separate gate; this code does not
claim delegated side effects are proven by a parent process exit.


## Live disposable regression

A real gateway plus local loopback model is exercised by two **opt-in** tests
without external tools, persistent deployment or production profiles. Use only
an authorised Linux development host with an isolated test temp directory:

```sh
HERMES_FHM004_LIVE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/hermes_cli/test_fermes_live_recovery.py \
  tests/hermes_cli/test_fermes_gateway_epoch_restart.py
```

The first test covers real bounded interruption, supervisor SIGKILL, immutable
admission identity, preview-only scanning, one observation, a second skipped
observation and no duplicate model call/admission. The second kills and restarts
the disposable gateway and proves the stale epoch/instance remains BLOCKED,
without replay. Fixture cleanup checks birth ticks and process group ownership
before stopping only processes it started. Ordinary pytest runs skip these tests
unless `HERMES_FHM004_LIVE=1` is set.

A fast successful CLI response with an unverified admission now returns 125
(`SETTLED_UNKNOWN`), not 0; it is not a verified task completion. Even a
TERMINAL matched gateway receipt is not independent verification of external
side effects (FHM-005).
