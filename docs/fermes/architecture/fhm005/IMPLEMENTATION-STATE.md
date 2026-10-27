# FHM-005 implementation state

**Status: BLUEPRINT CANDIDATE — IMP-001/002 and IMP-003 source-only model merged; privileged trusted authority and Windows NOT qualified.**

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

## Completed implementation milestone — FHM005-IMP-001

- [PR #26](https://github.com/fredheathcote007/hermes-agent/pull/26) MERGED at `5dbb12ca030c022dbcfc14fa5be400ab4d979d69`: fail-closed versioned request/receipt data contract; independent Cursor no-P0/P1 source review; 77 focused host tests PASS, hosted CI PASS.
- [PR #31](https://github.com/fredheathcote007/hermes-agent/pull/31) MERGED at `d8d4884f61c0c8f9baec8f3a1ba7e97b0148fcd6`: pure monotonic attempt-state contract; independent Codex review found and verified fix of late-worker failure transition P1; 56 focused host tests PASS; exact-head CI #40438572424 PASS.
- [Issue #27](https://github.com/fredheathcote007/hermes-agent/issues/27) CLOSED completed.
- **Limitation:** no controller, authenticated IPC, protected service identity, durable one-use CAS, trusted effect readback, parent/UI integration or native Linux/Windows security qualification exists from these two contracts. Python object/status fields must never be treated as independent authority.

## IMP-002 source-only POSIX candidate merged — Windows release gate remains

- [PR #33](https://github.com/fredheathcote007/hermes-agent/pull/33) MERGED at `b5c3cf9ad2c5fd26747aac4582968fcef9e6d12d`: POSIX no-follow descriptor-based file identity, root binding and bounded SHA-256 observations; deliberately **not** used by Hermes completion paths.
- [FHM005-IMP-002 issue #35](https://github.com/fredheathcote007/hermes-agent/issues/35) tracks the source-only POSIX milestone.
- Project Coordinator: **82 focused tests PASS**, Ruff and compile PASS; exact-head hosted CI [#40443854739](https://github.com/fredheathcote007/hermes-agent/actions/runs/40443854739) PASS. Independent Cursor initial+follow-up review completed; all identified source-only P1 and test hardening resolved.
- **NOT qualified:** native Windows reparse/junction and volume/file identity, same-device bind mounts, restored TOCTOU, kernel/FUSE I/O hang, forgeable Python observations, or actual effects. Windows path explicitly returns `UNSUPPORTED`. DEC-005 still mandates both OSs for trusted release.

## IMP-003 source-only receipt transaction model merged — trusted authority still OPEN

- [PR #40](https://github.com/fredheathcote007/hermes-agent/pull/40) MERGED at `6fd54dc4c17831c0c7e0b5fb1627522f6c218384`: unprivileged candidate SQLite WAL/FULL receipt lifecycle, bounded BEGIN IMMEDIATE transactions, one-use CAS, foreign/expiry/replay fail-closed states and restart reconciliation primitives. It has **NO runtime wiring, protected access or effect authority**.
- **73 focused host tests PASS**, Ruff/compile PASS; independent Cursor original and recheck no remaining source-only P0/P1 (initial reported UNIQUE/correlation P1 disproved and tested). Exact-head hosted [CI #40446760100](https://github.com/fredheathcote007/hermes-agent/actions/runs/40446760100) PASS.
- [IMP-003 issue #36](https://github.com/fredheathcote007/hermes-agent/issues/36) remains OPEN P0 for protected store issuance, authenticated parent, mandatory restart reconciliation, native dual-platform qualification, integration and operational proof. Do not confuse candidate `consumed` with trusted `VERIFIED`.
- [Linux sandbox security issue #38](https://github.com/fredheathcote007/hermes-agent/issues/38) OPEN P0: Ubuntu 26.04 installed Bubblewrap 0.11.1-1ubuntu0.3 is not acceptable without qualifying its vulnerability applicability/mitigation. [Draft PR #39](https://github.com/fredheathcote007/hermes-agent/pull/39) records the required security gate; no host package changes.

## 27 October 2026 — additional source-only qualifications

- [PR #24](https://github.com/fredheathcote007/hermes-agent/pull/24) **MERGED** at `97c5a51eff68598bc209c0ab716c991f6fa19635`: false-success TUI/Desktop status projection; 52 focused host tests, exact-head CI #40448998036 and independent Cursor initial+refreshed review PASS. Other client surfaces and malformed non-dict legacy results still require comprehensive status-parity review.
- [PR #42](https://github.com/fredheathcote007/hermes-agent/pull/42) **MERGED** at `245b19dc8bd7e8c602b7612c3d70d001c8f12c4a`: unconnected receipt candidate startup barrier, explicit non-authoritative live-generation join, invalidated ambiguous commits and adversarial tests; 114 focused host tests, exact-head CI #40449660701, Cursor source-only PASS WITH CONDITIONS.
- The live-generation join is caller-controlled. It **can bypass** restart fencing unless a separately protected controller first authenticates the parent instance and its generation. Merged source tests *demonstrate this hazard* rather than authorising trusted completion. IMP-003 [#36](https://github.com/fredheathcote007/hermes-agent/issues/36) remains OPEN P0.
- New DR-02/DR-04 concrete security mechanism is being prepared as an **unapproved** owner decision candidate. DEC-007 separation principle is the only accepted architectural portion; option names retain owner-approved A=local protected controller, B=manual/external fallback.

## Next: resolve remaining security architecture approval gates

DR-02 concrete same-user-resistant parent identity and DR-04 protected receipt storage/issuance, including receipt state ownership and crash handling, remain **unapproved**. DR-03 and DR-05–07 must then be resolved before protected controller/service deployment. Source-only tests are not a native Linux/Windows trusted-verifier qualification. Retain manual/external fallback, no uncertain-effect replay and no FHM-007 writes.


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

## 27 October 2026 — source-only IMP-002 checkpoint

PR #33 merged source-only (see above), no privileged runtime service, keys, OS configuration, production deployment or FHM-007 writes. Current trusted-verifier status remains P0 OPEN; manual/external verification fallback preserved.
