# FHM-005 — Full Architecture Review Board, 27 October 2026

project_id: fermes-hermes
status: CANDIDATE — DR-01 APPROVED / DR-02–DR-07 OPEN / NOT APPROVED FOR IMPLEMENTATION
frozen_source_sha: de83ce3b01fdc910a117e285a7acb72a98bf2841
issue: https://github.com/fredheathcote007/hermes-agent/issues/5

## Review integrity and scope

- Owner-approved inputs: DEC-004 fail-closed; Linux **and** Windows qualification required together; full architecture review.
- Review completed using 17 separately prompted read-only AI role first passes, two independent cross-role reconciliations, an independent challenger, and Principal Architect synthesis. These are AI review perspectives, not human professional certifications.
- The independent first-pass inputs and detailed reviewer dissent are retained in [review-evidence](review-evidence/FIRST-PASS-ALL.md). Cross-review, challenger and synthesis remain distinct.
- Source baseline is the tested FHM-005 stacked PR #22 commit; PR #21 and PR #22 remain unmerged and opt-in. No Windows trusted-verifier service, credential boundary or authoritative protected receipt has been implemented.
- Treat all items proposed below as review recommendations, not approved architecture. No Critical/High residual risk has been accepted on the owner's behalf.
- Current project GitHub Issues remain canonical for task and acceptance status. This draft review record is not itself an implementation sign-off.

## Decision queue (one owner decision at a time)

1. **DR-01 — APPROVED (DEC-006, 27 October 2026).** Protect against compromised delegated workers and other unprivileged local processes through isolated execution and protected verifier authority. Exclude compromise of local root/Administrator (or equivalent privilege) from the initial guarantee. **Manual or externally attested verification is the approved fallback** whenever independent automated verification is unavailable; never silently accept missing proof. This resolves threat scope, NOT detailed architecture implementation.
2. **DR-02 — PRINCIPLE APPROVED (DEC-007).** Separately protected controller is the exclusive verification authority; only independently authenticated Hermes parent may request authoritative decisions; untrusted worker/project recipes run under restricted identity and cannot access controller credentials/receipts. **Exact same-user impersonation-resistant mechanism and native proof remain open technical/security gates**, not assumed approved.
3. DR-03 — Supported installation and platform matrix: native Linux system service and Windows SCM service identities, IPC access controls, elevated one-off installation, fail closed if unsupported.
4. DR-04 — Receipt and acceptance protocol: per-attempt nonce, immutable scope, artifact identity/digest, policy generation, freshness, CAS consumption and no cross-session mutation.
5. DR-05 — External action and human resolution rules: action-specific authoritative readbacks, unsupported effects = incomplete, operator escalation without automatic replay.
6. DR-06 — Privacy/retention/diagnostic access and whether cryptographic signatures should augment (not replace) OS isolation.
7. DR-07 — Implementation release and promotion gates: same SHA, Linux/Windows native adversarial tests, no skip/timeouts counted as pass, separate default-on approval.

The approved Linux+Windows scope itself is not re-opened by this review.

## Sources and retained reviewer evidence

- [Independent role findings](review-evidence/FIRST-PASS-ALL.md)
- [Cross-review reconciliations](review-evidence/CROSS-REVIEWS.md)
- [Independent Challenger](review-evidence/INDEPENDENT-CHALLENGER.md)
- [Principal Architect full synthesis](review-evidence/PRINCIPAL-SYNTHESIS.md)
- [Proposed security boundary / draft ADR](TRUST-BOUNDARY-CANDIDATE.md)
- [Linux and Windows acceptance matrix](VALIDATION-MATRIX.md)

## Principal Architect decision-oriented synthesis

# Principal Architect synthesis

117,790
# FHM-005 Architecture Review Board Finding

## Disposition

At frozen baseline `de83ce3b01fdc910a117e285a7acb72a98bf2841`, PR #21/#22 remain source-only and unmerged. No production implementation or approval is justified.

The current Phase 1 behavior satisfies the owner-approved DEC-004 policy: missing, stale, untrusted, or unobservable proof remains incomplete. The current trusted-success path is not accepted. Existing SQLite verifier rows are diagnostic-only, not independent proof. The current runner executes project-controlled commands with `shell=True` (`agent/verify/runner.py:4-6, 27-30, 93-108`).

A conditional target architecture is justified as a design direction, but this is not approval to implement, merge, enable by default, or qualify release.

## Policy versus proposed design

Approved policy:

- DEC-004 fail-closed behavior is approved.
- Linux and Windows are both mandatory for one qualified release; this scope is resolved, not queued.
- Phase 1 remains opt-in and default-off.
- No automatic replay of uncertain external effects.
- PR #21/#22 are reviewable source-only work, not production changes.
- FHM-005 remains open until independent authority, durability, and qualification gates are satisfied.

Proposed, not yet approved:

- A separately authorized verifier/controller.
- Authenticated local IPC.
- Protected service-owned receipts.
- An untrusted executor separated from receipt authority.
- Exact attempt, artifact, version, and freshness binding.
- Native Linux and Windows service identities and containment.

The memory index correctly points to FHM-005 as “draft-only until durability/verifier gates” (`MEMORY-INDEX.md:18`). DEC-004 explicitly says Phase 1 is not independent verification and that trusted execution, authority, scope, and operational tests remain open (`DECISIONS.md:27-33`).

## Classification of major proposals

| Proposal | Classification | Finding |
|---|---|---|
| Retain opt-in, fail-closed Phase 1 | Accept | This is already approved policy and should remain unchanged. |
| Keep PR #21/#22 unmerged | Accept | Current evidence is source-only; no production claim follows from it. |
| Existing SQLite rows are diagnostic-only | Resolved by prior decision | DEC-004 and Phase 1 already reject same-identity ledger rows as independent proof. |
| Two-tier trusted authority plus untrusted executor | Accept with modification | The authority must not execute project-authored tests with its own privileges. |
| OS-authenticated local IPC | Accept with modification | Required, but exact Linux and Windows mechanisms remain Research required. |
| Protected, service-owned receipt store | Accept with modification | Storage must be inaccessible to the project worker and parent-writable profile ledger. |
| Per-attempt nonce, exact binding, one-time consumption | Accept with modification | Must include atomic state transitions, freshness, policy generation, and replay rejection. |
| Hash/version/object identity evidence | Accept with modification | Textual paths and timestamps are insufficient; canonical root and artifact identity are required. |
| Linux service user/socket and Windows service identity/pipe | Research required | Direction is sound; installation, ACL, upgrade, and failure semantics are unimplemented. |
| Process-tree containment and quiescence | Accept with modification | Linux and Windows need equivalent proof, not merely termination attempts. |
| Authoritative readback for external actions | Accept with modification | Only action-specific authoritative readback or attestation may produce success. |
| Distinct CLI/TUI/gateway states | Accept with modification | One machine-readable status contract must control every surface. |
| Always-on broker daemon | Defer | Prefer an on-demand controller until demand and lifecycle cost are measured. |
| Cryptographic signatures/MACs | Defer | Useful defense-in-depth, but cannot repair a compromised executor or local root/admin compromise. |
| Retention, redaction, and purge policy | Research required | Current raw paths, commands, and output create privacy and lifecycle obligations. |
| Linux + Windows release gate | Resolved by prior decision | Both native lanes are mandatory; skipped, timed-out, or blocked runs are not passes. |

## Conditional target architecture

The target should be a two-tier local architecture with a deliberately narrow trust boundary.

1. The parent creates an immutable verification attempt containing a random nonce, parent session/authority, exact task binding, canonical project root identity, acceptance-contract identifier, and policy/protocol generation.

2. The parent authenticates to a separately authorized controller over OS-authenticated local IPC. Client-supplied `ok`, session, root, command, or output fields are not accepted as authority. The controller derives identity and scope from the authenticated request and its own policy.

3. The controller launches project checks in a disposable lower-privilege executor. The executor receives no receipt-store access, signing/MAC material, verifier secrets, unrestricted profile access, or broad network access. Environment variables are scrubbed. Filesystem access is restricted to an isolated worktree or exported artifact view. CPU, memory, disk, output, wall-clock, and concurrency limits are mandatory.

4. Project-authored recipes remain untrusted input. The current `shell=True` runner cannot be promoted into the trusted authority. The trusted path must use fixed, policy-owned checks or a separately hardened executor whose output is treated as untrusted evidence. A passing exit code or convincing output is never provenance.

5. The controller independently validates the result: process ownership and quiescence, canonical root identity, allowed paths, object/file identity, pre/post content or tree hashes, policy version, command/check digest, and action-specific effect scope.

6. The controller writes a protected receipt only after all required checks complete. The receipt must bind:

   - attempt nonce and parent authority;
   - canonical root/worktree identity;
   - exact artifact/path set and content or generation hashes;
   - policy and verifier generation;
   - executor identity and terminal state;
   - freshness/expiry;
   - effect class and acceptance contract;
   - one-time consumption state.

7. The parent finalizer consumes only that exact receipt in one atomic transaction. Evaluation and retirement require a generation/CAS fence. Any concurrent update, late telemetry, receipt mismatch, database failure, or missing cleanup produces `unknown/incomplete`, never success.

8. Cross-session verification may be retained as advisory cache data, but it must not mutate or retire another session’s pending state. The direct foreign-session false-success claim is not fully proven because the finalizer has a same-session check; the cross-session state corruption and future ambiguity are proven and remain release-blocking (`FHM005-C03`, `FHM005-DEM-02`, IA-003).

Platform identities are proposed as follows, subject to implementation research:

- Linux: dedicated non-login service account, protected service-owned state, root-owned or otherwise restricted Unix socket, peer-credential validation, and verified cgroup/process ownership.
- Windows: noninteractive SCM service or equivalent explicitly approved principal, protected state directory, named-pipe DACL and token validation, and Windows Job Objects with kill-on-close. Interactive-token and Startup-folder fallback must never qualify as trusted mode.

The service must fail closed when identity, IPC, protocol generation, storage protection, or installation state cannot be verified.

## Authoritative completion status

Completion must originate from one finalizer-owned machine contract and be propagated unchanged through CLI, TUI, desktop, and gateway APIs:

- `verified`: exact fresh protected receipt consumed.
- `failed`: authoritative check ran and failed.
- `unknown/incomplete`: effects may have occurred, but proof is absent, stale, malformed, concurrent, or unobservable.
- `verifier_unavailable`: trusted verifier could not be reached or authenticated.
- `cancelled/interrupted`: distinct operational termination state.

`unknown/incomplete` and `verifier_unavailable` must never map to `completed=true`, “settled,” or a normal success status. The current TUI reducer can report `"complete"` while the result carries `failed=true`, `completed=false`, and `verification_unresolved=true` (`tui_gateway/prompt_turn.py:311-315`; `FHM005-C04`, `FHM-UX-001`). That is a concrete presentation defect to correct in a future implementation, not evidence that the current implementation is trusted.

The CLI, TUI, and gateway must show the attempt, effect class, verifier state, and safe next action. “Inspect,” “resolve,” and “retry after inspection” are safer than generic retry. No surface may automatically replay uncertain work.

## External actions

A local code-test receipt cannot prove browser actions, `execute_code`, connectors, deployments, SaaS mutations, email, or remote API effects. Those remain unresolved unless the action has an explicit acceptance contract and authoritative readback or external attestation. A timeout after a remote server accepted a request must remain `unknown`; retry must not be automatic (`FHM5-C5`, Challenger finding 5).

## Unaccepted residual risks

Critical:

- Project-controlled code could become a confused deputy if executed with controller authority or access to receipt state (`FHM005-C02`, FHM005-SEC-01).
- Same-identity SQLite evidence remains forgeable and replayable; no trusted completion may depend on it (`FHM005-C01`, FHM5-C2).
- A service boundary cannot defend against a local administrator/root or equivalent host compromise. This limitation must be explicit; stronger claims require remote or hardware-backed attestation (Challenger finding 2).

High:

- TOCTOU, symlink/hardlink/mount replacement, and mutable workspace state can invalidate path-only proof.
- Descendants may survive timeout or apparent success, especially on Windows.
- Dispatch, crash, retry, and retirement races can lose authority unless unknown is sticky and state transitions are atomic.
- Current status consumers can contradict the fail-closed machine result.
- Privacy leakage, retention, stale receipts, and raw output handling are underspecified.
- Native Windows identity, IPC, upgrade, rollback, and containment are unimplemented and unqualified.

No Critical or High risk is accepted on behalf of the owner.

## Negative qualification matrix

The same candidate SHA must pass natively on both Linux and Windows:

| Area | Linux negative tests | Windows negative tests |
|---|---|---|
| Provenance | Worker edits SQLite, forges `ok=True`, replays old receipt, uses wrong root/session | Same attacks through profile files and named-pipe requests; pipe substitution and token impersonation |
| Scope/TOCTOU | Symlink, hardlink, rename, mount and post-check mutation; concurrent session edits | Reparse-point/path replacement, file locking, rename races, concurrent profile/session edits |
| Executor isolation | Secret reads, outside-root writes, `/proc` or socket access, DNS/HTTP egress, detached child | Personal-file/credential reads, outside-root writes, named-pipe access, network egress, detached child |
| Containment | Timeout, grandchild, delayed writer, held pipe, PID reuse; verify cgroup/process ownership | Job Object escape, delayed writer, held pipe, PID reuse, service restart and orphan detection |
| State/recovery | Kill parent/controller at arm, spawn, observe, receipt, consume; all become durable unknown | Same across reboot/logoff/service restart and Windows file-lock conditions |
| Packaging/identity | Unit tampering, wrong user, restart, upgrade interruption, rollback | Wrong service account, ACL tampering, interactive fallback, reboot, upgrade/rollback |
| Effects/status | Shell/browser/external effect with missing readback; CLI/TUI/gateway must remain non-success | Native equivalents; no “settled” mapping and no replay after disconnect |

## Phases and rollback

- Phase A: retain current opt-in fail-closed/manual review. No default-on, merge, or trusted claim.
- Phase B: owner approves the trust boundary, threat model, receipt contract, status contract, and OS mechanism research.
- Phase C: implement controller, executor isolation, protected receipts, atomic state machine, and platform adapters.
- Phase D: adversarial native Linux and Windows qualification on the same candidate SHA.
- Phase E: candidate release gate and operational review. Default-on remains a separate future owner decision.

Rollback means retaining the last qualified release, disabling trusted mode, invalidating receipts from the failed verifier generation, preserving pending work as `unknown`, and never replaying uncertain effects. A service crash, failed upgrade, unsupported installation, or protocol mismatch must degrade to unavailable/incomplete.

## Highest-priority owner decision

The next decision is the trust-model boundary for local verification—not the already-resolved Linux/Windows scope.

Recommended answer: **Option A** — approve a two-tier local model that protects against unprivileged unrelated local processes and same-identity child forgery, while explicitly excluding a compromised local administrator/root from the guarantee. Project-authored tests run only in a lower-privilege constrained executor; only the controller mints receipts.

Other options:

- **Option B:** prohibit trusted receipts for arbitrary project-authored checks and retain manual/operator or externally attested CI verification.
- **Option C:** include local admin/root compromise in scope, which requires remote or hardware-backed attestation and is inconsistent with the current local-first target.

Until the owner selects an option, all other decisions remain queued: exact Linux/Windows service mechanisms, external-effect contracts, retention, retry supersession, operator resolution, and optional cryptographic protection. No risk is accepted by this review.\n
