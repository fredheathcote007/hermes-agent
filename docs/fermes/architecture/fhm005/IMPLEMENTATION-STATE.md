# FHM-005 implementation state

**Status: BLUEPRINT CANDIDATE — isolated nonprivileged FHM005-IMP-001 contract development begun; trusted architecture NOT approved.**

| Field | State |
| --- | --- |
| Project | `fermes-hermes` |
| Issue | FHM-005 / #5 |
| Worktree | `fermes/fhm005-detailed-design-20261027` |
| Baseline SHA | `120d7e3241621a72b66a5d09c25cb23d707f5ceb` |
| Current architecture | DEC-007 approved controller/parent/worker separation principle; detailed IPC/auth and DR-03–DR-07 still unapproved |
| Current runtime posture | Existing opt-in DEC-004 fail-closed/manual behavior remains the safe baseline |
| Native qualification | Not qualified for trusted verifier; existing evidence is Linux-only Phase 1 and explicitly excludes the trusted boundary |
| Default-on | Not authorized |
| FHM-007 | Preserved as a separate workstream; no dependency or edits |

## Baseline facts

The current source has durable opt-in pending markers and fail-closed finalization, but no separately
authorized controller, protected receipt store, native Linux/Windows service boundary, trusted
executor containment, or authoritative external-effect readback. The current SQLite ledger remains
diagnostic. The current recipe runner’s project-controlled shell path cannot be promoted into the
trusted authority. The TUI status projection still requires an explicit unresolved-state fix.

Authoritative context is retained in [ARB-REVIEW-20261027.md](ARB-REVIEW-20261027.md),
[FHM-005 Phase 1](../../memory/workstreams/reliability/FHM-005-PHASE-1.md),
[FHM-005 qualification evidence](../../memory/workstreams/reliability/FHM-005-E2E-QUALIFICATION.md),
and [DECISIONS.md](../../memory/DECISIONS.md). This candidate does not edit those records.

## Completed in this design task

* Identity gate passed against `docs/fermes/memory/MEMORY-INDEX.md`.
* Actual verification ledger, finalizer, delegated telemetry, runner, CLI/TUI/gateway seams, and CI
  conventions inspected.
* Candidate detailed design, DR-02–DR-07 candidate ADRs, granular implementation manifest, and
  native validation plan written under this directory.
* Challenger dissent and manual/external fallback retained explicitly.

## Next task

**FHM005-IMP-001 — complete and independently review the pure DTO/status/state-machine contract.**

Codex has started a pure receipt contract module on the separate branch `fermes/fhm005-verifier-protocol-20261027`; host tests and independent review are required before calling IMP-001 complete. Complete the monotonic state machine and interface constraints. Start with a pure contract module and behaviour tests. It must be independent of OS services,
process spawning, IPC, UI, and the legacy SQLite ledger. Prove DTO validation, legal transitions,
sticky `unknown_incomplete`, exact receipt binding fields, expiry, and one-use terminal behavior.
Do not create a trusted receipt, service, installer, default-on switch, or product behavior change in
this first task.

## Gates before each expansion

1. DR-02 separation principle approved (DEC-007); owner resolves the remaining authentication design plus DR-03–DR-07 choices relevant to the next capability.
2. The pure contract and its behavior tests pass with `scripts/run_tests.sh` when code work begins.
3. Native Linux and Windows implementations are developed and tested separately, then qualified on
   the same candidate SHA.
4. Any unsupported, ambiguous, crashed, stale, or unavailable path remains non-success and routes to
   manual/external resolution.
5. No task changes FHM-007 or reviewer/decision evidence.

## Safe rollback posture

Until all gates pass, retain the current opt-in fail-closed/manual path. If any later task fails,
disable the new trusted capability, fence its verifier generation, preserve affected attempts as
`unknown_incomplete`, and never replay uncertain external actions. A clean source diff or green unit
test is not architecture approval or native qualification.

## Design-review reconciliation (27 October 2026)

Independent Cursor review identified legacy receipt, delegate, request-client, module naming and task-dependency gaps. The candidate task graph now includes FHM005-IMP-015/016/017, aligns IMP-001 to `agent/trusted_verifier_contract.py`, adds protected legacy diagnostics fencing, fixes release-critical priority dependencies and preserves an explicit approval gate before any service or IPC installation. These are proposed tasks, not approved operational changes.

## Approved direction update (27 October 2026)

**DEC-007:** owner approved separate protected controller, authenticated Hermes parent, restricted worker execution. The exact Linux and Windows same-user impersonation-resistant mechanism remains unapproved/unproven; trusted service installation or success reporting must not proceed without it. PR #26 remains a non-authoritative contract-only implementation, not a protected verifier.
