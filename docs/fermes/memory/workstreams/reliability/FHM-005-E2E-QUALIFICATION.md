# FHM-005 E2E qualification evidence

Status: **6/6 tests PASS on authorised host (3 real-process cases + 3 process-cleanup safeguards); gateway/async and trusted verifier remain UNQUALIFIED.**

## Scope

tests/hermes_cli/test_fermes_fhm005_qualification.py drives a real Hermes
one-shot AIAgent in a disposable child process. A deterministic
OpenAI-compatible FakeLLMServer is bound to 127.0.0.1 and is the only
synthetic boundary. The tests exercise:

- parent delegate_task dispatch to a real child;
- a real child terminal command that writes a disposable file;
- the parent model emitting an attempted success response while the runtime
  result is returned as completed=false, failed=true,
  turn_exit_reason=verification_unresolved, and
  verification_unresolved=true;
- the durable delegated_verification_pending SQLite row, including the
  unobservable effect disposition;
- a pure read_file child control that completes successfully and retires its
  exact marker;
- owner SIGKILL before child completion, followed by a resumed parent turn that
  rehydrates the pending row, does not replay the child, and remains incomplete.

The test is opt-in (HERMES_FHM005_LIVE=1, or
HERMES_E2E_STRICT_ACCEPTANCE=fhm005 when using the canonical runner),
Linux-only, loopback-only, and
owns every disposable process group it signals. It does not claim gateway
ingress/delivery qualification, trusted-verifier qualification, or detached
async late-completion qualification. Finite one-shot delegation joins its child
synchronously; the exact-binding late-telemetry behavior remains covered by
tests/tools/test_delegate_verification_outcome.py.

## Verification receipt — 27 October 2026 (Australia/Perth)

**Authorised host with actual Hermes subprocesses and loopback model stub:**

- **PASS (3/3)** — `HERMES_FHM005_LIVE=1` real-process test module, log
  `/tmp/fermes-fhm005-e2e-host-rerun2.log`; tested the isolated branch based on
  `5f68a2af69e52bf6e0b4c703637a71c15cf06c35` with test-only additions.
- **PASS** — a real delegated child executed a terminal command and created a
  disposable artefact, while child and parent outcome remained fail-closed:
  `completed=false`, `failed=true`, `verification_unresolved=true`,
  `turn_exit_reason=verification_unresolved`. The durable row stayed
  `state=failed, unobservable=1` (rather than a misleading completed receipt).
- **PASS** — a pure `read_file` child had an observable pre-completion
  `running` row, completed with a successful tool receipt, and retired its
  exact marker; final SQLite read fails if ledger is absent/unreadable.
- **PASS** — owner process killed before model released child tool call;
  fixture now unconditionally terminates the identity-checked owned
  process group even on failed preconditions, then waits for model-handler
  release and checks the group has exited. Pending state survived restart, the resumed
  parent returned incomplete, and the child action was not replayed. The
  model handler event itself is not claimed as child-process completion.
- **PASS** — after independent Codex review, crash-test teardown now
  unconditionally kills its fixture-owned process group even if readiness or
  SQLite polling fails. Host re-run: `/tmp/fermes-fhm005-e2e-host-cleanup.log`
  (3 passed), with Ruff and Python compilation PASS.
- **PASS** — follow-up safety review found the leader could exit while a
  descendant remained. Cleanup now checks `/proc` PGID, original session ID
  and start ticks before SIGKILL even after the leader has been reaped;
  refuses to signal foreign/reused groups. Two extra negative/positive
  fixture-cleanup tests pass. Authorised-host rerun: `5 passed` in
  `/tmp/fermes-fhm005-e2e-ownedgroup-host.log` (3 runtime + 2 cleanup).
- **PASS** — independent code review identified that Python `-O` would remove
  assert-based ownership checks. Changed both killpg authority gates to
  explicit `RuntimeError`, verified no signal to fake foreign/reused groups
  in an optimised Python process, and added a permanent `-O` subprocess
  regression. Authorised-host test log: `6 passed` in
  `/tmp/fermes-fhm005-e2e-optimized-regression.log` (3 runtime + 3 safety).
- **PASS** — initial focused source tests (43), Ruff, Python compilation,
  default skip policy and Git whitespace checks in the Codex sandbox. Host
  expanded regressions and independent review must be recorded separately.

**Earlier test harness failures retained as evidence, not product defects:**

- Restricted Codex sandbox could not write `/var/tmp` and could not bind even
  `127.0.0.1`: opt-in runtime testing there was **BLOCKED (environment)**.
- First host attempt failed before delegation with HTTP 401 from the fixture
  model's artificial API-key check. The fixture now accepts loopback requests
  without enforcing unrelated model authentication; it remains loopback-only.
- Second host attempt performed the real side effect and returned the correct
  failed-verification child status. The original test incorrectly expected
  `state=completed`; its assertion was corrected to require `state=failed`.
- After those test-only corrections, all three runtime tests passed.

**Limits:** this proves real **one-shot parent/child execution** with a stub
model and durable restart; it does **not** prove gateway ingress, detached
async late delivery, external system effects or separately trusted verifier
receipts. No default-on, production installation or live model was changed.

## Reproducible authorised-host command

Run only on an authorised Linux test host. This is the successful, bounded
host-side invocation, not the sandbox runner (which cannot bind loopback):

```sh
mkdir -p /home/fred/.cache/fermes-pytest-tmp
HERMES_FHM005_LIVE=1 TMPDIR=/home/fred/.cache/fermes-pytest-tmp \
timeout --signal=TERM --kill-after=10s 150s \
  /home/fred/.hermes/installs/68fc13a80951fcd6/test-environment/gen-e2914a30739c442cb49b28cbd98ff7b0/venv/bin/python \
  -m pytest -p no:cacheprovider -q --tb=short --maxfail=1 \
  --basetemp=/home/fred/.cache/fermes-pytest-tmp/fhm005-e2e-host \
  tests/hermes_cli/test_fermes_fhm005_qualification.py </dev/null
```

Retain the exact SHA, test output, and isolated-runtime logs with issue #5.
Do not treat any skipped, timed-out, or environment-blocked test as PASS.
