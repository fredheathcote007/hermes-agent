# FHM-005 validation plan

**Status: PROPOSED gate plan — not executed and not a PASS claim.**

The trusted verifier may be qualified only when the exact same candidate SHA passes the required
native Linux and native Windows lanes. The existing Phase 1 evidence is retained as evidence for
opt-in fail-closed parent/child behavior only; it does not qualify the controller, receipt, IPC,
executor, gateway, or external effects.

## 1. Rules for interpreting results

* `PASS` means the test ran on its required native host, completed within its bounded budget, and
  produced the expected fail-closed or verified contract result.
* `SKIP`, timeout, environment-blocked, simulated-host, emulated-host, missing artifact, or partial
  log is **NOT PASS**. The release gate is not qualified.
* Every security test records candidate SHA, host OS/version, service identity, protocol/policy
  generation, test fixture identity, start/end time, and raw evidence location. Secrets and personal
  data are redacted before retention.
* Negative tests must show `unknown_incomplete`, `failed`, or `verifier_unavailable` as appropriate;
  a test that merely raises an exception without checking the authoritative status is insufficient.
* Tests that claim OS-specific behavior run on that OS. Tests must use the repository runner
  (`scripts/run_tests.sh`) for Python suites; native service/installer tests may be driven by a
  bounded workflow wrapper that still records the exact command and artifacts.
* No test may write to a real user Hermes home or use production credentials. Use disposable profile,
  project, service state, and receipt directories.

## 2. Contract and state-machine gates

| ID | Scenario | Expected result |
| --- | --- | --- |
| VP-001 | Create attempt with missing nonce, authority, root, policy, scope, or protocol | Reject before dispatch; no receipt |
| VP-002 | Reuse nonce for another session, task, root, or effect | Reject as foreign/replay; original state unchanged |
| VP-003 | Unknown field, oversized DTO, protocol downgrade, malformed digest/time | Reject as unavailable or invalid; never success |
| VP-004 | Crash at every transition: arm, submit, authenticated, spawn, observe, validate, issue, consume | Durable `unknown_incomplete` or unconsumed exact receipt; no replay |
| VP-005 | Late child telemetry after finalization or restart | Cannot resurrect/retire a different attempt; unknown remains sticky |
| VP-006 | Concurrent evaluation and retirement with stale generation | Exactly one CAS wins; other path is rejected/non-success |
| VP-007 | Expired, future-skewed, or verifier-generation-mismatched receipt | Reject; do not refresh silently |
| VP-008 | Legacy SQLite row edited to `ok=True` or worker reports success | Diagnostic only; cannot yield `verified` |

## 3. Malicious worker and authority-boundary gates

Run these tests with a project-controlled recipe/manifest and a worker that returns exit code 0 while
attempting each action:

| ID | Attack | Expected result |
| --- | --- | --- |
| VP-101 | Write, truncate, replace, or delete protected receipt state | Access denied or isolated; no trusted receipt |
| VP-102 | Read controller credentials, profile secrets, service state, or unrelated personal files | Denied/redacted; no trusted receipt |
| VP-103 | Connect to Unix socket/named pipe; forge parent authority or `ok=True` | IPC authentication rejects; no trusted receipt |
| VP-104 | Replace controller binary, policy, protocol, or worker executable | Installation/generation check fails closed |
| VP-105 | Shell injection, environment expansion, executable shadowing, `PATH`/working-directory trick | Fixed policy rejects or executor remains untrusted; no controller execution |
| VP-106 | Write outside exported root, device/mount access, `/proc`/credential access, DNS/HTTP egress | Denied or classified unobservable; no trusted receipt |
| VP-107 | Spawn detached child, delayed writer, held pipe, grandchild server, or child that changes after exit | Containment/quiescence fails; `unknown_incomplete` |
| VP-108 | Return malformed/truncated/unpaired tool telemetry or omit the completion message | Missing evidence remains pending/unknown, never empty no-effect success |

The test must demonstrate that the controller does not become a confused deputy. A separate service
identity is not enough if the worker inherits its authority.

## 4. Forged credential, provenance, session, and replay gates

| ID | Scenario | Linux native check | Windows native check |
| --- | --- | --- | --- |
| VP-201 | Wrong peer UID / group / socket owner | `SO_PEERCRED`, owner/mode, service generation reject | Token/service SID and pipe DACL reject |
| VP-202 | Same-user unprivileged process impersonates parent | Authority/profile binding rejects | Token impersonation and pipe-instance binding reject |
| VP-203 | Worker edits legacy ledger or injects a passed row | No effect on protected receipt | No effect on protected receipt |
| VP-204 | Replay old receipt for new attempt/session/root | Nonce/scope/generation/CAS reject | Same, including service restart |
| VP-205 | Receipt copied across profile/worktree/session | Parent authority and canonical root reject | Volume/file identity and authority reject |
| VP-206 | Change policy/check digest after dispatch | Digest mismatch, no receipt | Digest mismatch, no receipt |
| VP-207 | Consume same receipt concurrently or twice | One-use CAS; second rejected | One-use CAS; second rejected |

The exact cross-session corruption concern in the ARB evidence must remain visible: a direct finalizer
bypass is not claimed where same-session checks block it, but any cross-session mutation or future
ambiguity remains release-blocking.

## 5. Scope, symlink/junction/TOCTOU, and artifact identity gates

| ID | Scenario | Expected result |
| --- | --- | --- |
| VP-301 | Replace declared file with symlink or hardlink during check/readback | Object identity mismatch; unknown/incomplete |
| VP-302 | Linux mount/bind mount or Windows junction/reparse-point substitution | Scope mismatch or denied; no receipt |
| VP-303 | Rename path, case/volume change, delete/recreate, or directory swap | Canonical root/object identity mismatch |
| VP-304 | Mutate content after check but before digest/receipt | Post-worker SHA-256 mismatch |
| VP-305 | Concurrent session edits same path/root | Exact session/attempt/artifact scope prevents foreign retirement |
| VP-306 | Change file metadata/generation without content change | Approved generation/object rule decides; otherwise unknown |
| VP-307 | Worker reports a forged hash or path list | Controller re-reads/derives identity; worker field ignored as authority |
| VP-308 | Receipt read while a late mutation is still possible | No quiescence, no receipt |

Linux and Windows cases must be run natively because reparse-point, file-ID, locking, mount, and
rename semantics differ.

## 6. Crash, late child, containment, and expiry gates

Run each point on both native platforms and repeat across controller restart; Windows additionally
covers reboot/logoff and file-lock behavior:

1. Kill parent before controller submission.
2. Kill parent after durable arm but before executor spawn.
3. Kill parent/controller after spawn but before observation.
4. Kill controller after observation but before receipt issue.
5. Kill parent after receipt issue but before consume.
6. Kill parent during CAS consume and restart both sides.
7. Stop/restart service while a worker holds stdout, pipe, file lock, or network socket.
8. Spawn a descendant that survives the direct child; test PID reuse and delayed writes.
9. Advance/alter the freshness boundary and restart with an old verifier generation.
10. Interrupt/cancel a possible external effect after the remote side may have accepted it.

Expected result is a durable state that is either exactly consumed once or remains
`unknown_incomplete`/`verifier_unavailable`. There is no automatic replay, silent retirement, or
conversion of a crash into success.

## 7. External action and readback gates

For every initially supported effect class, test:

* success with matching authoritative readback, exact request/effect identity, scope, and freshness;
* authoritative failure;
* timeout before remote acceptance;
* timeout after remote acceptance;
* duplicate/ambiguous response and eventual consistency;
* stale readback from a prior attempt;
* readback unavailable, unauthorized, malformed, or outside declared scope.

Only the first case may become `verified`. The remaining cases are `failed` or
`unknown_incomplete`/`verifier_unavailable` according to the contract. Browser/UI, connector, deploy,
email, SaaS, and remote API actions remain manual/external unless their issuer and readback contract
is explicitly implemented and qualified.

## 8. CLI, TUI, gateway, desktop, and ACP gates

Use one fixture for each authoritative state and drive every surface:

| Fixture | Required surface behavior |
| --- | --- |
| `verified` | Success only after exact receipt consumption; show bounded scope/effect summary |
| `failed` | Non-success; show check failure and inspect action |
| `unknown_incomplete` | Never `completed=true`, “settled”, or green success; show inspect/resolve, no auto-retry |
| `verifier_unavailable` | Never success; show manual/external fallback and installation/controller reason |
| `cancelled_interrupted` | Preserve cancellation and possible-effect state; no automatic replay |
| malformed/late/foreign status | Reject or render unavailable/incomplete; never infer from prose |

Specific regressions include the existing TUI `_result_status()` contradiction, gateway projection of
`completed`/`turn_exit_reason`, ACP cancellation, desktop status rendering, CLI one-shot/REPL exit
codes, and gateway reconnect/resume. The machine DTO is the assertion target; snapshots alone are not
enough.

## 9. Native CI and release gates

The implementation should add explicit FHM-005 Linux and Windows jobs following repository CI
conventions (`scripts/run_tests.sh`, native `platforms()` markers, bounded workflow timeouts, and
artifacts attached to the exact SHA). The job must fail or report not-qualified when required native
tests are not selected. A workflow-level green result with a skipped security matrix is not a pass.

Required native lanes:

* Linux: service installation/identity, Unix socket peer auth, protected state, executor isolation,
  cgroup/process ownership, symlink/hardlink/mount races, crash/restart, receipt CAS, expiry, UI,
  privacy, and external-effect fixtures.
* Windows: SCM/service SID, named-pipe DACL/token/impersonation, protected state, Job Objects,
  reparse/junction/locking races, crash/restart/reboot/logoff, receipt CAS, expiry, UI, privacy, and
  external-effect fixtures.
* Both: same source SHA, same contract vectors, malicious worker, forged credential, cross-session,
  replay, late child, unsupported install, upgrade/rollback, and no-default-on assertion.

Existing Windows live process-topology patterns in `windows-venv-e2e.yml` may inform harness design,
but they do not by themselves qualify the verifier. No simulated platform test substitutes for a
native lane.

## 10. Evidence package and expiry

Each qualification package contains:

* exact source SHA and dependency/environment identifiers;
* native host/OS and service identity evidence;
* complete test selection, including proof that required cases were not skipped;
* bounded logs, receipt/state exports, artifact hashes, and redaction report;
* workflow/job URLs and artifact retention metadata;
* failures, blocked cases, timeouts, and manual resolutions called out separately;
* expiry date for the qualification based on policy/protocol/verifier generation and supported OS
  changes;
* rollback result: trusted mode disabled, receipts fenced, unknown preserved, no replay.

Qualification expires when the source SHA, verifier generation, policy/protocol, OS support, service
identity/ACL, executor boundary, or receipt schema changes materially. Expiry is `verifier_unavailable`,
not an automatic waiver. A later candidate needs a new native package on the same SHA for its release
decision.

## 11. Manual and external fallback validation

Test that an unavailable controller, unsupported OS, failed native gate, missing readback, or expired
qualification produces a clear manual/external path:

1. preserve the exact attempt and scope as `unknown_incomplete`;
2. display observed evidence without secrets/raw output by default;
3. allow an operator or approved external attestor to record identity, scope, method, and time;
4. never mint a local automated trusted receipt from a worker claim;
5. never replay the uncertain operation automatically;
6. propagate the resolution consistently to CLI, TUI, gateway, desktop, and ACP.

The fallback is a safety behavior, not a trusted-verifier PASS and not a reason to weaken DEC-004.
