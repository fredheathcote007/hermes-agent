# FHM-005 Architecture Review Board: independent first-pass evidence

Status: REVIEW EVIDENCE ONLY, not user-approved target architecture.
Frozen source baseline: de83ce3b01fdc910a117e285a7acb72a98bf2841, issue #5; PRs #21/#22 unmerged.

# Independent first pass: product

87,704
## Product Owner findings

### PO-001 — Critical
**Type:** Security boundary / truthful completion

**Evidence:** `agent/verify/runner.py:4-6,28-30,93-108`; `agent/verify/recipes.py:50-76`. Verification executes project-authored shell commands with `shell=True`, including user-editable manifests.

**Why:** A separate service identity is insufficient if that privileged service runs untrusted project tests. Malicious tests could use the verifier’s privileges or produce misleading results.

**Recommendation:** The MVP must separate trusted orchestration from untrusted checks: low-privilege/sandboxed execution, deterministic allowlisted checks, bounded resources, and no privileged filesystem/network authority in project tests.

**Decision Required:** Reject any “trusted verifier” claim until this boundary is explicitly approved.

**Validation test:** A test command attempts to modify a protected sentinel, access outside the worktree, or create an external side effect; verification must fail closed and the privileged identity must remain unaffected.

### PO-002 — Critical
**Type:** Provenance / receipt integrity

**Evidence:** `agent/verification_evidence.py:487-505,509-547`; `agent/verification_evidence.py:587-604`; `tests/agent/test_verification_evidence.py:350-363`.

**Why:** `kind="verify"` is a writable profile-local SQLite event. `record_verify_run()` accepts caller-supplied session data, while a newest full pass can clear another session’s stale state. This is not independent evidence and permits same-identity forgery or cross-session clearing.

**Recommendation:** Do not let the service write the existing ledger as proof. Use protected receipts minted only after verifier exit, containing service identity, nonce, child attempt, exact root, artifact hashes/versions, scope, freshness, and one-time consumption state. Parent IPC authentication must be mandatory.

**Decision Required:** Confirm that existing SQLite entries are diagnostics only and cannot satisfy trusted completion.

**Validation test:** Worker code directly inserts or replays a `verify` row; parent completion must remain unresolved. A receipt from another session/root or after a file mutation must be rejected.

### PO-003 — High
**Type:** Release acceptance / platform scope

**Evidence:** `FHM-005-E2E-QUALIFICATION.md:3,25-32,87-90`; `FHM-005-PHASE-1.md:45-54`.

**Why:** Current qualification is Linux-only and explicitly leaves trusted verifier, gateway/async, and detached completion unqualified. Simulated Windows parsing tests do not qualify Windows behavior.

**Recommendation:** Define one release gate covering real Linux and Windows processes: authenticated IPC, crash/restart, cancellation, process cleanup, stale/replayed receipts, and conservative shell/browser effects. Skips, timeouts, and environment-blocked runs cannot count as passes.

**Decision Required:** Hold default-on or “qualified release” status until both operating systems pass the same acceptance matrix.

**Validation test:** Authorised-host Linux and Windows runs exercise real parent/child/service processes and retain exact SHA, logs, and machine-readable receipts.

### PO-004 — Medium
**Type:** UX / default-off policy

**Evidence:** `agent/verification_stop.py:52-78`; `agent/turn_verification_finalize.py:63-77`; `FHM-005-PHASE-1.md:40-43,58-63`.

**Why:** Default-off is currently preserved, but the user-facing contract must distinguish “completed,” “incomplete,” and “verification unavailable.” IPC failure, missing proof, or service absence must never silently degrade to success when opt-in is enabled.

**Recommendation:** Keep installation and activation default-off. Provide explicit opt-in status and a visible unresolved explanation; preserve existing compatibility when disabled.

**Decision Required:** Approve the exact UX/state contract before implementation.

**Validation test:** Unset config/env on both platforms and verify no service or ledger is activated; with opt-in enabled, kill or disconnect the verifier and assert `completed=false`, `failed=true`, and an actionable reason.

## Top recommendation

Keep the source-only work reviewable but unmerged for P0 completion claims. First approve and qualify the protected receipt boundary, including untrusted-test isolation and Linux/Windows evidence.

**Credible alternative:** Avoid a privileged service for MVP; provide only conservative fail-closed status (`verified`, `unresolved`, `not run`) using operator-run checks, postponing trusted completion until the boundary is ready.

**Uncertainties:** No verifier service implementation exists in this baseline, so its IPC, identity, isolation, and receipt protections cannot be confirmed. No live Windows qualification evidence was found.


# Independent first pass: business

93,215
Independent Business Analyst review — 5 material findings

BA-001 — Critical
Type: Trust boundary / actor identity
Evidence: `agent/verification_evidence.py:487-505`; `agent/verification_stop.py:116-145`; FHM-005-PHASE-1, “same local execution rights.”
Why: `kind=verify` receipts are writable by the same profile identity as the worker/project tests. A forged or replayed full-pass row can appear to satisfy completion, violating DEC-004.
Recommendation: Separate trusted verifier identity, authenticated local IPC, deterministic command selection, scoped post-child evidence, protected non-replayable receipts bound to attempt/root/artifact version.
Decision Required: ARB approval of this boundary before any trusted-success claim.
Validation test: A child writes/replays a fake verify receipt; completion must remain blocked. Only a valid trusted receipt may clear it.

BA-002 — High
Type: Cross-session state isolation
Evidence: `agent/verification_evidence.py:535-543`, `587-604`, `607-649`.
Why: A full pass for one session updates other sessions’ workspace state and shared status can report `passed`. The finalizer’s session check may still reject completion, creating contradictory operator-visible states and potentially clearing another session’s dirty-path record.
Recommendation: Never mutate another session’s state. Treat cross-session verification as non-authoritative unless explicitly bound to the same session, attempt, and artifact version.
Decision Required: Choose and document workspace-level versus session-level proof semantics; current DEC-004 favors session/attempt binding.
Validation test: Session A edits; Session B verifies; A must retain stale/dirty state and remain deterministically unresolved.

BA-003 — High
Type: Retry / attempt lifecycle
Evidence: `tools/delegate_tool.py:687-693`; `agent/verification_evidence.py:767-805`.
Why: Each retry gets a new attempt, but old `running/failed/unknown/unobservable` rows remain. Pending evaluation considers all rows, while cleanup only removes completed observable rows. A legitimate retry therefore cannot recover without an unimplemented operator resolution path.
Recommendation: Add immutable attempt history plus explicit `supersedes` and operator-resolved states. No automatic replay or silent clearing.
Decision Required: Define who may resolve an abandoned attempt and whether a retry can supersede it.
Validation test: Crash attempt A, retry as B, pass B; result remains blocked until explicit resolution of A, with no child replay.

BA-004 — High
Type: Release qualification / platform workflow
Evidence: FHM-005-E2E-QUALIFICATION, Scope and Limits: qualification is Linux-only; gateway/async and trusted verifier remain unqualified.
Why: Approved release scope requires both Linux and Windows. Current evidence cannot support one qualified cross-platform release or establish equivalent restart/cleanup semantics on Windows.
Recommendation: Require authorized Windows real-process qualification covering side effect, restart, persistence, cleanup, and no-replay cases.
Decision Required: Block promotion until Windows evidence is independently recorded.
Validation test: Run the equivalent bounded Windows suite without faking platform identity.

BA-005 — Medium
Type: Operator workflow / effect disposition
Evidence: `tools/delegate_verification.py:21-35`; `agent/turn_verification_finalize.py:63-78`; FHM-005-PHASE-1 conservative shell/browser policy.
Why: Read-only children may retire markers, while shell, `execute_code`, and browser-console work remain unresolved—even when apparently harmless. The user receives only a generic incomplete message, with no clear attempt, effect class, paths, or resolution action. This encourages unsafe retry decisions.
Recommendation: Surface structured status: attempt, tool/effect disposition, paths, verifier availability, and explicit “inspect/resolve/retry” guidance; preserve no-replay behavior.
Decision Required: Approve the operator resolution UX and authority model.

Top recommendation: approve and qualify the separate trusted verifier boundary before enabling any trusted-success path.

Credible alternative: retain Phase 1 as permanently fail-closed, with manual operator inspection and no automated completion claims.

Uncertainties: I did not perform live Linux/Windows execution; exact Windows parity and the practical exploit path for direct ledger forgery remain untested, though the same-identity forgeability is explicitly documented.


# Independent first pass: enterprise

109,348
Enterprise Architect review at frozen SHA `de83ce3b01fdc910a117e285a7acb72a98bf2841`. Source-only review; no edits or production activity.

Top recommendation: reuse Hermes profile scoping, service-manager abstractions, and local configuration, but build only a minimal separate verifier service boundary. Keep the current ledger as untrusted audit state, never as proof. Do not run project-authored tests with verifier privileges.

### EA-001 — Critical

- Type: Security architecture / trust boundary
- Evidence: `agent/verification_evidence.py:139-154,487-505,537-543,607-613`; `agent/turn_verification_finalize.py:33-60`; DEC-004; `FHM-005-PHASE-1.md`
- Why: `hermes verify` writes directly to a profile-local SQLite ledger, and finalization accepts same-identity evidence. A child or parent sharing local rights can forge rows, alter timestamps, inject a passing `kind=verify` entry, or exploit cross-session full-pass clearing. This is explicitly acknowledged as non-independent.
- Recommendation: separate verifier security identity, authenticated local IPC, protected receipt storage, exact session/attempt/root binding, artifact hashes or versions, freshness, and replay rejection.
- Decision Required: approve the OS-level identity, IPC mechanism, receipt authority, and behavior when the verifier is unavailable.
- Validation test: an untrusted child edits/injects/replays a passing ledger entry; Linux and Windows must remain `verification_unresolved=true`.

### EA-002 — Critical

- Type: Privilege separation / execution safety
- Evidence: `agent/verify/runner.py:4-7,27-30,93-100,168-181`; `agent/verify/environment.py:3-5`; `agent/verify/recipes.py:27-39`
- Why: the proposed verifier cannot safely execute arbitrary project-authored recipes under its own trusted identity. Commands use `shell=True`, may bootstrap dependencies, build, start servers, access the network, mutate files, and spawn descendants. A dedicated identity alone is insufficient if it runs hostile or compromised project tests with elevated rights.
- Recommendation: trusted checks must be deterministic and narrowly allowlisted. Run project tests only in an untrusted worker/snapshot. The trusted verifier should independently inspect scoped post-child evidence and protected artifact state, without inheriting project secrets or broad filesystem/network access.
- Decision Required: define which checks are trusted versus merely advisory.
- Validation test: a recipe attempts to modify files outside the project, access protected verifier state, spawn a detached descendant, or exfiltrate data while returning exit 0; no trusted receipt may be minted.

### EA-003 — High

- Type: Cross-platform installation and operations
- Evidence: `hermes_cli/service_manager.py:14-78,182-209`; `FHM-005-E2E-QUALIFICATION.md:25-30`; `tests/hermes_cli/test_fermes_fhm005_qualification.py:46-52`
- Why: Hermes has reusable Linux/macOS/Windows service-management concepts, but no verifier-specific installation, identity, ACL, upgrade, uninstall, or recovery model. Current FHM-005 qualification is Linux-only; it does not qualify Windows process, IPC, or identity behavior. One qualified release requires both platforms.
- Recommendation: extend existing service abstractions with verifier-specific backends and explicit installation/repair flows. Define fail-closed behavior when no supported service backend exists.
- Decision Required: supported Windows service mechanism and minimum privileges; whether unsupported installations remain permanently incomplete.
- Validation test: clean Linux and Windows install/upgrade/uninstall/restart tests verify identity, IPC ACLs, receipt protection, and profile isolation.

### EA-004 — High

- Type: Release qualification / lifecycle coverage
- Evidence: `FHM-005-E2E-QUALIFICATION.md:7-30,38-58`; `.github/workflows/fermes-pr-checks.yml:127-142`
- Why: current evidence covers real one-shot parent/child execution and restart on Linux, but explicitly excludes gateway ingress, detached async completion, trusted verifier receipts, and Windows. It cannot support a cross-platform qualified release or default-on policy.
- Recommendation: add a release matrix covering both OSes, service restart, late completion, cancellation, receipt replay, profile switching, and verifier failure.
- Decision Required: keep phase one opt-in/manual-review until that matrix passes.
- Validation test: require independent receipts from real Linux and Windows service processes before any completion claim.

Uncertainties: I confirmed the current source and documented limitations; I did not inspect an unimplemented verifier design or validate host-specific service behavior. Credible alternative: retain fail-closed/manual review indefinitely, avoiding a new privileged boundary until its operational cost is justified.


# Independent first pass: solution

96,429
Independent Solution Architect review of frozen SHA `de83ce3b`.

Top recommendation: do not promote a privileged verifier until the trust model explicitly prevents untrusted project code from running with verifier authority. Use a trusted broker/verifier that owns receipts, while project checks run with strictly lower privileges and cannot access verifier credentials or storage.

1. **SA-001 — High — Trust-boundary design**

- **Evidence:** `agent/verify/runner.py:4-7,27-30,93-100`; `agent/verify/environment.py:1-6`; `FHM-005-PHASE-1.md` architecture review gate.
- **Why:** Verification executes project-authored shell commands with `shell=True`; manifests are user-editable. A service identity executing hostile tests grants those tests the service’s privileges. Service identity alone is therefore insufficient.
- **Recommendation:** Separate trusted orchestration/evidence minting from untrusted test execution. The verifier must observe and validate results independently; project code must not receive verifier credentials or receipt-write access.
- **Decision Required:** Is malicious project/test code inside the threat model, or only accidental effects?
- **Validation test:** A test attempts to read a service-only secret, write a protected receipt, invoke verifier IPC, and leave a privileged descendant on both Linux and Windows.

2. **SA-002 — High — Receipt authenticity and IPC**

- **Evidence:** `agent/verification_evidence.py:139-169,477-506,509-547`; `hermes_cli/verify_cmd.py:83-103`.
- **Why:** Same-identity processes can write the profile SQLite ledger or call `record_verify_run` directly. `HERMES_SESSION_ID` is environment-derived, and a caller can submit arbitrary root/session/full-pass data. The ledger has no cryptographic authenticity or protected writer.
- **Recommendation:** Make the receipt store service-owned and inaccessible to project identity. Use authenticated local IPC with OS peer authentication, per-request nonce/attempt ID, strict request schema, and service-only MAC/signature minting. Never accept client-supplied “passed” as authoritative.
- **Decision Required:** Must the parent accept only service-signed receipts?
- **Validation test:** Project code forges, edits, truncates, replays, and cross-binds receipts; every case must remain unresolved.

3. **SA-003 — High — Scope, freshness, and replay**

- **Evidence:** `agent/verification_evidence.py:587-649`; `_insert_evidence` cross-session update at `535-543`; `agent/verification_stop.py:116-145`.
- **Why:** Evidence is primarily keyed to workspace root and timestamps, not an immutable artifact/tree state or delegated attempt. A full pass can clear another session’s state, and the verifier does not prove that the exact post-child state was checked.
- **Recommendation:** Bind receipts to canonical root identity, exact artifact/tree hashes, changed-path set, verifier-policy version, parent attempt ID, and a service-issued freshness nonce. Accept only a post-child receipt; reject replay and intervening mutation.
- **Decision Required:** Is qualification for the whole working tree, exact changed artifacts, or a commit snapshot?
- **Validation test:** Mutate outside/inside the reported path set, reuse an old receipt, race two sessions, and alter clock time.

4. **SA-004 — High — Cross-platform process containment**

- **Evidence:** `agent/verify/runner.py:127-166,168-186`; `FHM-005-E2E-QUALIFICATION.md` explicitly limits qualification to Linux and excludes trusted verifier qualification.
- **Why:** Phase commands use `subprocess.run` without descendant ownership. Start cleanup uses POSIX process groups but only direct-child termination on Windows. A passing process can leave descendants or external effects running.
- **Recommendation:** Share one lifecycle/state-machine contract; use platform adapters: Linux process groups plus cgroup/namespace policy, Windows Job Objects with kill-on-close. Receipt minting requires verified quiescence or unresolved status.
- **Decision Required:** Are network, external services, and detached descendants in scope?
- **Validation test:** Timeout/exit with daemonized descendants, PID reuse, and cleanup races on both operating systems.

5. **SA-005 — Medium — Bootstrap and crash recovery**

- **Evidence:** `hermes_cli/verify_cmd.py:19-52,83-105`; `agent/verify/environment.py:24-51`.
- **Why:** Project-controlled recipe bootstrap is not authenticated, and evidence recording is fail-silent after the CLI result is produced. A crash between process exit and receipt minting has no explicit terminal state.
- **Recommendation:** Use durable `requested → running → observed → receipt-minted` state owned by the verifier; crashes recover to unresolved. Define explicit recipe trust/bootstrap policy.
- **Decision Required:** Are project manifests trusted configuration or untrusted input?
- **Validation test:** Kill verifier at every transition and confirm no success is emitted without a durable trusted receipt.

Credible alternative: retain phase-one fail-closed behavior and require operator-run verification under the same identity. This preserves local-first architecture but provides no strong independence guarantee.

Uncertainties: no trusted verifier implementation exists in this baseline; the intended service lifetime, OS account/service model, and malicious-test threat boundary remain unspecified.


# Independent first pass: security

86,115
Security Architect review at frozen SHA `de83ce3b01fdc910a117e285a7acb72a98bf2841`.

Assessment: fail-closed behavior is demonstrated, but no trusted-verifier boundary is qualified. PR #21/#22 should remain unmerged for this scope.

**SA-01 — High — Forgeable verification provenance**

- **Evidence:** `agent/verification_evidence.py:487-506,509-545`; `agent/verification_stop.py:99-122`.
- **Why:** Any same-identity code can call `record_verify_run()` or modify the profile SQLite database. A `kind=verify`, `status=passed`, `scope=full` row is accepted without authentication, integrity protection, signer identity, or protected storage.
- **Recommendation:** Only a separately authorized verifier may mint receipts. Use authenticated local IPC, OS-protected receipt storage, nonce/session/root binding, recipe identity, post-child snapshot/hash, freshness, and replay rejection. Parent code must not accept direct ledger writes.
- **Decision Required:** Approve this trust-boundary architecture before calling evidence trusted.
- **Validation test:** Same-identity child attempts API insertion, SQLite mutation, receipt replay, wrong-session receipt, and cross-profile receipt; all must be rejected on Linux and Windows.

**SA-02 — High — Cross-session verification clears state**

- **Evidence:** `agent/verification_evidence.py:535-543,587-604,607-649`; explicitly encoded by `tests/agent/test_verification_evidence.py:350-364`.
- **Why:** A full pass by one session updates and clears every other session’s state for the same root. This permits a pass unrelated to the delegated child’s exact post-effect state to satisfy the completion gate.
- **Recommendation:** Bind evidence to the exact parent session/attempt, changed-path set, and post-child workspace snapshot. Do not clear another session’s pending state. If workspace-wide evidence is intentional, require a global mutation lock plus immutable pre/post snapshot.
- **Decision Required:** Choose session-scoped evidence, as DEC-004 implies, or formally approve workspace-scoped semantics.
- **Validation test:** Two sessions edit different files; one runs a full pass. The other must remain unresolved until its own scoped post-child evidence exists.

**SA-03 — Critical — Untrusted recipe execution under verifier authority**

- **Evidence:** `agent/verify/environment.py:3-5,25-33`; `agent/verify/recipes.py:40-45`; `agent/verify/runner.py:27-30,93-108,168-186`.
- **Why:** User-editable manifests and project-detected commands execute with `shell=True`, including install, build, test, and start phases. A malicious project can read inherited secrets, modify files outside the root, access network/services, persist descendants, or forge conditions. A dedicated service identity is insufficient if it runs hostile project code with that identity’s privileges.
- **Recommendation:** Keep project tests untrusted and minimally privileged. Trusted receipts should cover only deterministic Hermes-owned checks or execution inside a hardened sandbox with no secrets, restricted filesystem/network, sealed argv recipes, and root confinement. Never treat project-controlled output as provenance.
- **Decision Required:** Explicitly reject privileged execution of untrusted project tests unless a cross-platform sandbox is approved.
- **Validation test:** Malicious `environment.json`, package scripts, and test code attempt secret reads, outside-root writes, network access, shell injection, and environment mutation on Linux and Windows.

**SA-04 — High — Windows process containment and late effects are unqualified**

- **Evidence:** `agent/verify/runner.py:127-149,168-186`; `FHM-005-E2E-QUALIFICATION.md` (Linux-only; Windows and trusted verifier explicitly unqualified).
- **Why:** Teardown documents direct-child termination on Windows, without Job Object/process-tree containment. A detached descendant can modify the workspace after a passing test and before receipt minting.
- **Recommendation:** Use Windows Job Objects with kill-on-close and Linux cgroup/pidfd-equivalent containment; snapshot/hash after quiescence; reject receipts if descendants or late mutations remain.
- **Decision Required:** Windows must remain release-blocked until adversarial E2E qualification passes.
- **Validation test:** Project code spawns a detached descendant that writes after parent exit; receipt must be rejected and no process may survive.

Top recommendation: establish the authenticated, least-privilege verifier/broker boundary and exact scoped receipt contract before implementation promotion.

Credible alternative: retain phase-one fail-closed behavior and require manual external verification; this avoids introducing a privileged boundary but leaves automated completion unresolved.

Uncertainties: I did not run live or Windows tests; filesystem permissions, deployment ACLs, and any future IPC implementation were not available for review.


# Independent first pass: data

85,950
## Data and Knowledge Architect review

Top recommendation: replace profile-local SQLite verdicts with receipts minted by a separately authorized verifier service over authenticated local IPC. The verifier must bind each result to an attempt nonce, approved command digest, workspace/root hash, artifact hashes, and post-child version. A dedicated identity alone is insufficient if it executes untrusted project tests with its own privileges; execution must be isolated and command scope constrained.

1. **FHM-005-DKA-01 — High — Forgeable verifier provenance**

   **Evidence:** `agent/verification_evidence.py:487-506`; `hermes_cli/verify_cmd.py:83-105`; `agent/verification_stop.py:116-145`.

   **Why:** `record_verify_run()` accepts caller-supplied `ok`, `root`, `scope`, command, and session identity, then writes a normal SQLite row. The CLI obtains the session ID from an environment variable and silently ignores receipt-write failures. `kind="verify"` is therefore metadata, not independent provenance. A same-profile process can mint a passing receipt without proving what actually ran.

   **Recommendation:** only the trusted verifier may mint receipts; reject caller-provided verdicts and require authenticated IPC plus verifier-generated terminal evidence.

   **Decision Required:** approve the verifier trust boundary and whether uncommitted receipt publication must make `hermes verify` fail.

   **Validation test:** untrusted worker attempts to submit `ok=True`; no admissible receipt is created, and finalization remains incomplete.

2. **FHM-005-DKA-02 — High — Replayable and destructively consumable attempt state**

   **Evidence:** `agent/verification_evidence.py:686-696`, `:721-742`, `:794-807`.

   **Why:** Pending IDs are deterministic (`session:attempt:task:authority`), with no nonce, sequence number, signature/MAC, or child-process identity. A replayed `completed` update can delete an empty marker at lines 734-735. Successful rows and completed pending rows are later deleted, eliminating evidence of what was consumed. The tests prove late telemetry after retirement is rejected, but not replay before retirement or database tampering.

   **Recommendation:** use random per-attempt nonces, monotonic event sequencing, authenticated receipts, append-only event history, and explicit one-time consumption records.

   **Decision Required:** whether receipt history must remain auditable after successful finalization.

   **Validation test:** replay an old completion against a live marker and verify rejection; replay after restart and verify no state change.

3. **FHM-005-DKA-03 — High — No artifact/root-hash binding**

   **Evidence:** schema `agent/verification_evidence.py:62-104`; path propagation `tools/delegate_verification.py:53-80`; verification lookup `agent/verification_evidence.py:587-649`.

   **Why:** Evidence binds only textual `root`, timestamps, and a bounded list of path strings. There is no repository/tree/version hash, artifact digest, command digest, or immutable changed-file manifest. Child-provided paths are stored without a trusted under-root validation. A later pass for the same resolved root can therefore be associated with a different workspace state.

   **Recommendation:** verifier receipts must include canonical root identity, workspace version/root hash, scoped artifact hashes, and exact attempt linkage; reject paths outside the approved root.

   **Validation test:** mutate or replace a changed file after child completion but before verification; receipt must fail freshness/hash validation.

4. **FHM-005-DKA-04 — Medium — Retention and atomicity undermine durable evidence**

   **Evidence:** pruning/deletion `agent/verification_evidence.py:389-421`; receipt retirement `:794-807`; CLI fail-silent recording `hermes_cli/verify_cmd.py:83-105`.

   **Why:** The ledger deletes events after 30 days, per-root/session caps, and successful pending rows. This is not immutable or append-only retention. Separately, a successful verify command can return success even when receipt persistence fails; the failure is swallowed.

   **Recommendation:** retain immutable receipt envelopes according to an explicit policy, record retirement/tombstone events rather than delete, and make receipt publication atomic with the reported success.

   **Validation test:** force SQLite commit failure and confirm the command is not qualified as a durable pass.

5. **FHM-005-DKA-05 — Medium — Windows qualification gap**

   **Evidence:** `docs/fermes/memory/workstreams/reliability/FHM-005-E2E-QUALIFICATION.md` states the qualification is Linux-only and explicitly excludes trusted verifier qualification.

   **Why:** Both Linux and Windows are in scope for one qualified release, but current evidence does not establish SQLite durability, path canonicalization, restart recovery, or receipt atomicity on Windows.

   **Recommendation:** require equivalent Windows real-process qualification before release approval.

**Uncertainties:** I confirmed the source-level gaps above; I did not assume a dedicated verifier identity would solve them, and no trusted service implementation is present to assess.


# Independent first pass: ai

111,203
## AI Systems Architect review — FHM-005

### FHM005-A1

- **Severity:** High
- **Type:** Trust boundary / provenance
- **Evidence:** `agent/verification_evidence.py:487-506`, `:515-545`, `:587-604`; `FHM-005-PHASE-1.md:61-63`
- **Why:** Same-profile callers can supply `root`, `session_id`, `ok`, and output to `record_verify_run`; the receipt is plain SQLite. A full verify also rewrites other sessions’ state (`:537-543`). The finalizer’s same-session check reduces one false-success path, but does not make the receipt trusted or tamper-resistant.
- **Recommendation:** Only a separately authorised verifier may mint receipts. Protect the ledger from worker/test identity, authenticate IPC, bind receipts to verifier identity, root/tree digest, attempt, authority, freshness, and nonce. Prevent replay and cross-session state rewriting.
- **Decision Required:** Approve this as a release-blocking architecture gate; do not promote same-profile `kind=verify` entries.
- **Validation test:** Same-identity child/test attempts to mint a passing receipt, edit SQLite, or submit a cross-session full pass; parent must remain unresolved and pending state must remain intact.

### FHM005-A2

- **Severity:** High
- **Type:** Verifier execution / prompt-injection resistance
- **Evidence:** `agent/verify/runner.py:4-6`, `:28-30`, `:93-108`; `hermes_cli/verify_cmd.py:19-52`; `FHM-005-PHASE-1.md:45-54`
- **Why:** Verification executes project-controlled recipes and manifests using `shell=True`. Untrusted tests can modify the checkout, access local resources, contact the verifier, or emit convincing output. A dedicated service identity alone is insufficient if it runs these tests with meaningful privileges.
- **Recommendation:** Run untrusted project checks in a restricted disposable sandbox: no verifier secrets/socket, constrained filesystem/network, bounded descendants, immutable verifier policy, and pre/post tree measurement. Treat all test output as untrusted data.
- **Decision Required:** Choose sandbox/isolation requirements before implementing a privileged verifier boundary.
- **Validation test:** Malicious recipe/test attempts outside-root writes, IPC access, source mutation after checks, and descendant persistence; no trusted receipt is minted.

### FHM005-A3

- **Severity:** High
- **Type:** Failure handling / tool-trace completeness
- **Evidence:** `tools/delegate_tool_child_run.py:563-596`; `tools/delegate_verification.py:19-35`, `:46-50`; `agent/verification_evidence.py:734-740`
- **Why:** A non-list or missing child `messages` becomes an empty trace. If `completed=True` is also present, no failed/unobservable tool is detected and the pending row may be deleted. Partial or malformed transcript data is therefore interpreted as “no effects,” contrary to fail-closed policy.
- **Recommendation:** Require runtime-issued, complete call/result receipts with sequence, pairing, exit status, and termination proof. Missing, malformed, or truncated telemetry must remain `unknown`; never retire from the model-facing `completed` flag.
- **Decision Required:** Treat telemetry completeness as a mandatory invariant, not a best-effort diagnostic.
- **Validation test:** Feed completed child results with absent messages, unmatched calls, truncated tool results, and late delivery; every case remains pending/unresolved.

### FHM005-A4

- **Severity:** Medium
- **Type:** Acceptance semantics / scope
- **Evidence:** `agent/verification_stop.py:116-145`; `agent/verification_evidence.py:487-506`; `DECISIONS.md DEC-004`; `FHM-005-PHASE-1.md:47-52`
- **Why:** A workspace-wide full `hermes verify` pass is not bound to the delegated task’s acceptance criteria, exact changed paths, artifact hashes, or external effects. It cannot prove browser, shell, connector, deployment, or other unsupported actions.
- **Recommendation:** Use action-specific deterministic checks and scoped post-child evidence. Report unsupported external effects as unresolved; never generalize a code-test receipt.
- **Decision Required:** Define per-action acceptance contracts before any default-on policy.
- **Validation test:** Change file A while verifying B, or perform an external side effect with a green code suite; completion must remain false.

### FHM005-A5

- **Severity:** Medium
- **Type:** Cross-platform qualification
- **Evidence:** `FHM-005-E2E-QUALIFICATION.md:3`, `:25-32`, `:87-90`; `agent/verify/runner.py:127-165`
- **Why:** Current qualification is Linux-only. Windows uses direct-child cleanup rather than verified process-group ownership, and no native Windows E2E proves cleanup, SQLite locking, or future IPC behavior.
- **Recommendation:** Require native Linux and Windows qualification before one release is called qualified.
- **Decision Required:** Keep FHM-005 open until both platform matrices pass.
- **Validation test:** Native Windows real-process tests for timeout, descendants, restart, receipt tampering, IPC authentication, and no replay.

**Top recommendation:** retain opt-in fail-closed behavior and implement no privileged boundary until A1–A3 are resolved.

**Credible alternative:** keep verification permanently non-authoritative; require operator review for unresolved delegated work.

**Uncertainties:** Normal child execution may always provide a complete message list, but that contract is not enforced here. Gateway, detached async, trusted-verifier, and Windows behavior remain unqualified.


# Independent first pass: software

72,013
Independent Software Architect review of baseline `de83ce3b` only. I did not inspect other reviewers’ reports or run host qualification.

Confirmed: the current ledger is same-identity, mutable SQLite state; phase one is not an independent verifier. Assumed for threat analysis: delegated project processes can write through the same profile identity or call the public ledger APIs.

### FHM005-ARCH-01

- Severity: Critical
- Type: Trust boundary / provenance
- Evidence: `agent/verification_evidence.py:487-506`; `hermes_cli/verify_cmd.py:83-105`
- Why: Any process with the profile identity can call `record_verify_run()` or forge `HERMES_SESSION_ID`; `kind=verify` is therefore not authenticated evidence. A dedicated service identity is not sufficient if that service executes untrusted project tests with its own privileges.
- Recommendation: Preserve the existing ledger as legacy diagnostic state. Add a narrowly scoped verifier service reached through authenticated local IPC. The service should mint receipts only after deterministic checks, while test execution occurs in a separately restricted worker/sandbox identity. Receipts must bind project root, child-attempt set, artifact hashes/generation, verifier policy version, and expiry.
- Decision Required: Approve the split between receipt authority and untrusted test execution before implementing the boundary.
- Validation test: Same-identity forged `record_verify_run()` and forged IPC payloads must never produce an accepted receipt; verifier-service compromise must not grant project-write authority.

### FHM005-ARCH-02

- Severity: High
- Type: Atomicity / race
- Evidence: `agent/turn_verification_finalize.py:33-52`; `agent/verification_evidence.py:794-809`
- Why: Finalization reads pending rows and workspace evidence in separate operations, then deletes all completed rows for the authority. A late child can arrive between the read and delete and be retired without being included in the evaluated snapshot. `_DB_LOCK` is process-local and does not protect detached processes.
- Recommendation: Introduce one transactional `evaluate_and_retire()` operation using a parent fence/generation. Read the exact row IDs and evidence generation under `BEGIN IMMEDIATE`; validate; delete only those IDs if the fence is unchanged. Any concurrent update causes unresolved status.
- Decision Required: Choose transaction/fence semantics as the compatibility contract for detached completion.
- Validation test: Concurrent late completion during finalization must remain pending and force `verification_unresolved=true`.

### FHM005-ARCH-03

- Severity: High
- Type: State machine / dispatch race
- Evidence: `agent/verification_evidence.py:702-745`, `:748-764`; `tools/delegate_tool.py:511-533`
- Why: `update_delegated_verification()` accepts arbitrary state changes without expected-version or monotonic transition checks. `disarm_delegated_verification()` unconditionally deletes a marker after setup failure; a child that crosses the spawn boundary can then report telemetry against no marker, while the parent may treat the absence as safe.
- Recommendation: Define explicit states and CAS transitions: `armed → started → terminal`; never delete after ambiguous dispatch. Disarm only before spawn reservation, or convert ambiguity to permanent `unknown`. Add an immutable dispatch nonce and attempt generation.
- Decision Required: Approve “unknown is sticky” semantics for every post-reservation failure.
- Validation test: Inject failure between spawn and marker deletion; parent restart must remain blocked and child telemetry must not resurrect or clear state.

### FHM005-ARCH-04

- Severity: High
- Type: SQL ledger compatibility / versioning
- Evidence: `agent/verification_evidence.py:29`, `:54-110`, `:163-169`
- Why: `_VERIFY_SCHEMA_VERSION` is stamped with `INSERT OR REPLACE`, but there is no migration or unsupported-version handling. `CREATE TABLE IF NOT EXISTS` leaves older schemas unchanged. A future receipt schema can silently operate against incompatible columns or semantics.
- Recommendation: Add explicit schema migration steps, supported-version checks, and fail-closed read behavior. Keep a compatibility adapter for existing `verification_events`, `verification_state`, and `delegated_verification_pending`; do not reinterpret legacy rows as trusted receipts.
- Decision Required: Define upgrade/downgrade policy, especially for existing profile databases and Windows file-lock failures.
- Validation test: Open v1, partially migrated, newer, corrupt, and concurrently upgraded ledgers; only the fully supported schema may permit completion.

### FHM005-ARCH-05

- Severity: Medium
- Type: Cross-session state isolation
- Evidence: `agent/verification_evidence.py:535-543`, `:587-604`
- Why: A full verify event from one session rewrites and clears `verification_state` rows for every other session sharing the root. This can erase pending edit attribution even though final acceptance requires same-session evidence.
- Recommendation: Track workspace generation independently from session state. Cross-session verification may be an input candidate, but must not mutate or clear another session’s pending state unless an authenticated receipt explicitly names that parent binding.
- Decision Required: Confirm whether cross-session verification is intended to satisfy acceptance or only provide advisory evidence.
- Validation test: Session A edits; session B verifies; A must retain its pending generation and remain unresolved until an authorized receipt covers A.

Uncertainty remains around detached async behavior and Windows filesystem locking; these require dedicated race and restart tests.


# Independent first pass: platform

141,195
Review status: baseline confirmed at `de83ce3b`; read-only review only. No FHM-007 activity.

### FHM-005-DEVOPS-01

Severity: Critical
Type: Trust boundary / provenance

Evidence: `agent/verification_evidence.py:151-168, 487-543, 587-604, 635-649`; `hermes_cli/verify_cmd.py:47-52, 83-105`; `DEC-004`.

Why: The profile-local SQLite ledger is writable by the same identity that runs delegated/project code. `record_verify_run()` accepts caller-supplied `ok`, `session_id`, root, and command metadata. A full pass is intentionally reused across sessions and can clear other session edit state. This is not independent evidence and permits forged or replayed success.

Recommendation: Move acceptance to a protected verifier service. Receipts must be minted only by that service, bind exact request nonce, child attempt, root/worktree identity, artifact hashes, verifier generation, and post-child evidence. Store/sign receipts outside the project/profile-writable tree.

Decision Required: Approve the receipt schema, signing/key-protection mechanism, and explicit prohibition on SQLite rows serving as trusted receipts.

Validation test: Same-user child edits the project and directly forges/injects a `kind=verify` row; finalization must remain incomplete. A receipt from another session, generation, or prior request must be rejected.

### FHM-005-DEVOPS-02

Severity: Critical
Type: Privilege separation

Evidence: `hermes_cli/verify_cmd.py:47-52`; `FHM-005-PHASE-1.md:45-54, 61-63`.

Why: A dedicated service identity is insufficient if that service executes untrusted project tests with its own privileged access. Test code could modify verifier inputs, IPC endpoints, receipt stores, keys, or the installed verifier.

Recommendation: Separate trusted controller from untrusted executor. The controller performs deterministic command selection and receipt issuance; a lower-privilege worker executes project tests in a disposable copy/namespace with no write access to controller state, IPC credentials, or signing keys.

Decision Required: Decide whether Linux and Windows qualify only with this two-tier model, rather than a single privileged verifier process.

Validation test: Malicious test code attempts to alter the verifier executable, receipt directory, IPC endpoint, environment, and worktree after launch; the controller must detect/reject the run.

### FHM-005-DEVOPS-03

Severity: High
Type: Windows service identity / ACL

Evidence: `hermes_cli/gateway_windows.py:513-535, 570-601`; `:604-615`; `:394-400, 434-446`.

Why: The current Windows launcher uses `InteractiveToken` and `LeastPrivilege`, normally under the current user, with a Startup-folder fallback. That is suitable for gateway persistence, not trusted verification. The fallback has no independently verifiable service identity.

Recommendation: Use a dedicated SCM service or noninteractive Task Scheduler principal with explicit service-account SID, named-pipe DACL, protected receipt/key directory, and no Startup fallback for trusted mode. Fail closed if effective XML/account cannot be verified.

Decision Required: Choose SCM versus Task Scheduler and define service-account provisioning/upgrades.

Validation test: Windows standard-user, elevated-admin, logoff, reboot, and ACL-tampering scenarios; verify the effective principal and reject fallback/interactive execution.

### FHM-005-DEVOPS-04

Severity: High
Type: Linux systemd packaging / ACL

Evidence: `hermes_cli/gateway.py:3211-3240, 3270-3288`; `gateway_runtime_service_identity.py:170-205`.

Why: Existing systemd support is gateway-oriented. User services run as the user; system services merely select `User=` and expose the target home. No verifier-specific `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `StateDirectory`, or protected IPC boundary exists.

Recommendation: Ship a dedicated system service with a fixed non-login account, root-owned unit, `/run` socket ACL, private state/key directories, and a disposable worker workspace. User-service mode must never claim trusted verification.

Decision Required: Approve the Linux account, directories, socket group, and root-required installer behavior.

Validation test: Verify service/user/project ACL matrix, unit tampering, restart, reboot, and rollback on both user and system scopes.

### FHM-005-DEVOPS-05

Severity: High
Type: Packaging / upgrade / rollback

Evidence: `hermes_cli/gateway.py:3613-3623`; `gateway_windows.py:570-598`; package-management docs `:36-51, 88-95, 122-125`.

Why: Current updates replace service definitions and Windows tasks, while old/new interpreters can coexist. No verifier protocol version, receipt-key rotation, generation fence, or rollback invalidation is defined. Stale receipts could outlive the verifier that created them.

Recommendation: Package verifier generations side-by-side, atomically select one, handshake protocol/generation, drain old instances, and invalidate receipts on downgrade or verifier identity change. Preserve unresolved pending work across interruption.

Decision Required: Define upgrade/rollback compatibility and receipt invalidation policy.

Validation test: Kill during install, service restart, receipt issuance, and rollback on Linux and Windows; old receipts must never authorize new code.

Top recommendation: retain Phase 1 fail-closed behavior until a two-tier verifier, authenticated IPC, protected receipts, and cross-platform upgrade tests are qualified.

Credible alternative: defer trusted automation and require operator-run verification/manual acceptance; this preserves local-first operation without pretending the current ledger is independent.

Uncertainties: installer-specific service-account provisioning, key storage, and systemd/Windows hardening requirements are not yet specified.


# Independent first pass: sre

167,003
Top recommendation: do not qualify FHM-005 as trusted until a separate verifier service has authenticated IPC, protected signed receipts, scoped worktree/commit binding, and sandboxed execution of untrusted project tests. A dedicated identity alone is insufficient if it executes hostile tests with elevated rights.

1. **FHM-005-SRE-01 — Critical**
   **Type:** Trusted-boundary failure
   **Evidence:** `agent/verify/environment.py:3-6,25-33`; `agent/verify/runner.py:4-6`; `hermes_cli/verify_cmd.py:83-105`; `agent/verification_evidence.py:487-505`.
   **Why:** The project-editable manifest controls `shell=True` commands, while the same identity records a successful receipt into a local SQLite ledger. A project test can alter the manifest, workspace, ledger, or verifier inputs. This is confirmation of the documented limitation, not an assumption.
   **Recommendation:** Separate verifier identity/service, authenticated local IPC, signed receipts bound to immutable workspace/commit and verifier policy. Execute project code in a sandbox or reduced-privilege worker; never grant the test process verifier authority.
   **Decision Required:** Approve the isolation model and receipt authority before default-on or release qualification.
   **Validation test:** Malicious project modifies its manifest and ledger or attempts receipt forgery; verifier rejects it and emits no success receipt.

2. **FHM-005-SRE-02 — High**
   **Type:** Timeout/process cleanup
   **Evidence:** `agent/verify/runner.py:93-108`.
   **Why:** Phase commands use `subprocess.run(..., shell=True)`. On timeout, the function returns a failed result but does not terminate or verify descendants. A timed-out test can continue writing files, consuming resources, or racing a subsequent verification run.
   **Recommendation:** Use `Popen` with an owned process group/job object for every phase, bounded TERM/KILL escalation, and postcondition checks that the complete tree is gone.
   **Decision Required:** Require identical descendant-cleanup semantics on Linux and Windows.
   **Validation test:** A phase spawns a delayed writer and grandchild, times out, then assert no descendant survives and no late file mutation occurs on either OS.

3. **FHM-005-SRE-03 — High**
   **Type:** Crash/restart recovery and remediation
   **Evidence:** `tools/async_delegation.py:268-289,282-331,334-362`.
   **Why:** If the owner-liveness probe cannot be imported or read, recovery returns `0`; rows remain `running`, and startup replay considers only non-running rows. Work is safely not replayed, but can remain indefinitely stranded with no explicit unknown/degraded state.
   **Recommendation:** Convert inability to prove ownership into an explicit durable `unknown`/recovery-blocked state, with bounded boot reconciliation and operator remediation; never replay the child.
   **Decision Required:** Define the recovery SLA and manual action for permanently stranded rows.
   **Validation test:** Simulate dead owner plus unavailable liveness probe; assert durable unknown state, alert, no child replay, and eventual operator-clear path.

4. **FHM-005-SRE-04 — Medium**
   **Type:** Health metrics/observability
   **Evidence:** `agent/monitoring/gateway_health_export.py:46-54,148-185`.
   **Why:** No verification-pending/ledger-health metric exists. Metric read failures are converted to zero, so active or unresolved work can appear healthy.
   **Recommendation:** Export pending, unknown, stale-age, ledger-readable, and recovery-blocked metrics; emit degraded health when reads fail rather than reporting zero.
   **Validation test:** Lock/corrupt the ledger and inject pending rows; assert non-zero/degraded telemetry.

5. **FHM-005-SRE-05 — Medium**
   **Type:** Offline operation/boot ordering
   **Evidence:** `agent/verify/recipes.py:162-164,183-185`; `hermes_cli/subcommands/verify.py:44-48`; `agent/verify/runner.py:99-124`.
   **Why:** Auto-detected recipes may run `npm install`, `pip install`, or `uv sync`; defaults permit 600-second phases and no explicit offline mode. Offline boot can stall or partially mutate the project before producing an unusable receipt.
   **Recommendation:** Add explicit offline/cache-only policy and classify dependency-unavailable separately from test failure.
   **Validation test:** Linux and Windows offline runs complete within bounded time, leave no descendants, and produce `verification_unavailable`, never success.

**Credible alternative:** Keep same-identity verification permanently opt-in as diagnostic evidence only, while release acceptance requires an external CI/verifier attestation.

**Uncertainties:** Live Windows process-tree behavior and owner-liveness failure behavior are not qualified by the recorded E2E evidence; that evidence is explicitly Linux-only and excludes trusted-verifier, gateway/async qualification (`FHM-005-E2E-QUALIFICATION.md:3,25-32,87-90`).


# Independent first pass: test

118,669
Independent Test Architect review of frozen SHA `de83ce3b01fdc910a117e285a7acb72a98bf2841`.

Top recommendation: keep FHM-005 opt-in and fail-closed; do not promote/default-on until a separately authorized verifier boundary is implemented and qualified on both Linux and Windows. The verifier must not run untrusted project tests with its own privileges merely because it has a different service identity.

### FHM005-TA-001 — High

- Type: Security / forged evidence
- Evidence: `agent/verification_evidence.py:487-505, 509-543, 652-667`; `agent/verification_stop.py:116-147`
- Why: `record_verify_run()` accepts caller-supplied success, root, session, and scope into the profile SQLite ledger. A same-identity child can write a `kind="verify"` pass or alter SQLite. A full verify also clears other sessions’ state (`:537-543`). This is confirmed by the design docs, not merely inferred.
- Recommendation: separate trusted verifier/service identity, authenticated local IPC, opaque one-time request binding, protected receipts, and no direct ledger writes from workers. The verifier itself must isolate untrusted test execution.
- Decision Required: no trusted-verifier or default-on qualification until this boundary is approved.
- Validation test: after a child side effect, attempt `record_verify_run()` and direct SQLite forgery under the worker identity; parent must remain incomplete. Authorized receipt succeeds; altered, duplicated, or replayed receipt fails.

### FHM005-TA-002 — High

- Type: Cross-platform acceptance gap
- Evidence: `tests/hermes_cli/test_fermes_fhm005_qualification.py:46-53, 201-307`; `FHM-005-E2E-QUALIFICATION.md:25-32`
- Why: The only live qualification is Linux-only and depends on `/proc`, POSIX process groups, and `killpg`. The required Windows half is absent; existing Windows CI does not select this qualification test.
- Recommendation: add native Windows live E2E using Windows process/job and IPC primitives, while retaining Linux coverage. Matrix every verdict state on both hosts.
- Decision Required: Linux-only 6/6 must not be called a release qualification.
- Validation test: real-process Linux and Windows runs for success, missing evidence, forged receipt, verifier crash, owner crash, timeout, cancellation, and no-replay behavior; skipped or unavailable host runs are not PASS.

### FHM005-TA-003 — High

- Type: Race / TOCTOU integrity
- Evidence: `agent/verification_evidence.py:587-604, 607-649`; `agent/turn_verification_finalize.py:27-53`
- Why: Freshness is timestamp-based, and verification lookup, pending-state evaluation, and retirement are separate operations. There is no immutable worktree generation, artifact hash set, verifier run ID, or atomic post-child binding. A concurrent writer or late child can change the workspace between verification and finalization, or a full pass can validate a different state.
- Recommendation: trusted verifier must bind a post-child snapshot, exact roots/paths/hashes, child attempt, authority, and freshness token in one protected receipt.
- Decision Required: approve the race/TOCTOU contract before accepting any “verified” result.
- Validation test: mutate/swap a file during verification and immediately after verification but before finalization; verdict must be unresolved, never successful.

### FHM005-TA-004 — Medium

- Type: External-side-effect and crash coverage gap
- Evidence: `agent/tool_result_classification.py:23-44`; `tools/delegate_verification.py:19-35`; `FHM-005-E2E-QUALIFICATION.md:87-90`
- Why: Current E2E proves one terminal file write and one read. It does not prove browser JavaScript, `execute_code`, network/API effects, subprocesses, hooks, Git effects, or verifier/IPC crash recovery.
- Recommendation: add independent negative tests per effect class and service lifecycle tests: crash before receipt, disconnect, timeout, restart, duplicate receipt, and late delivery.
- Decision Required: these remain unresolved until tested; no generic external-side-effect success claim.
- Validation test: each effect path must either produce a scoped trusted receipt or return `completed=false`; uncertain external actions must never replay automatically.

Uncertainties: no trusted verifier or IPC implementation exists in this baseline, so protocol details and Windows behavior cannot yet be assessed. Existing receipts are source/test evidence, not hosted cross-platform qualification.


# Independent first pass: appsec

84,696
## Top recommendation

Do not promote `hermes verify` into a privileged verifier as currently designed. First establish a separate, authenticated verifier boundary that accepts only fixed, policy-owned checks, runs project code in a disposable least-privilege sandbox, binds immutable workspace identity/content, and mints protected non-replayable receipts.

### FHM005-SEC-01

- **Severity:** Critical
- **Type:** Privileged verifier / command execution
- **Evidence:** `agent/verify/runner.py:4-5,28-30,93-108,176`; `agent/verify/environment.py:25-41`; `agent/verify/recipes.py:27-40`
- **Why:** Verification executes project-authored or user-editable shell strings with `shell=True`, inherited environment, and project-root access. A dedicated service identity would execute attacker-controlled tests with that identity’s privileges. This is confirmed; impact depends on what privileges/secrets the service receives.
- **Recommendation:** Keep the signer/verdict authority separate from the test runner. Run fixed allowlisted checks in a disposable sandbox with no secrets, restricted filesystem/network, resource limits, and explicit artifact export.
- **Decision Required:** Approve whether project tests may ever execute under the verifier identity. Recommended answer: no.
- **Validation test:** A malicious manifest/test attempts shell injection, reads a secret, writes outside the workspace, mounts/creates devices, and spawns a child. No external effect or secret exposure may occur, and no receipt is minted.

### FHM005-SEC-02

- **Severity:** High
- **Type:** Worker forgery / IPC impersonation
- **Evidence:** `agent/verification_evidence.py:139-169,487-505,509-545,652-667`; `hermes_cli/verify_cmd.py:83-103`
- **Why:** Evidence is stored in profile-local SQLite and `record_verify_run()` accepts caller-supplied root/session/result fields without authenticated provenance. `verification_authority()` is a plain UI/session string and deliberately has no process identity. Any same-identity worker or local process able to access the profile can forge a passing `kind='verify'` row or impersonate the authority.
- **Recommendation:** Use authenticated local IPC with peer credential validation, nonce-bound requests, signer-only receipt creation, protected storage, and replay rejection. Do not treat SQLite kind or session strings as trust evidence.
- **Decision Required:** Approve the independent service identity and IPC authentication design before implementation.
- **Validation test:** A worker inserts a forged row and sends a forged completion for another attempt/session; finalization must reject both.

### FHM005-SEC-03

- **Severity:** High
- **Type:** Symlink/hardlink/mount and TOCTOU
- **Evidence:** `agent/verification_evidence.py:720-740`; `tools/delegate_verification.py:53-66`; `agent/verification_stop.py:81-90,123-145`
- **Why:** Changed paths are untrusted strings. The system records them without inode/file-ID, mount identity, immutable root, or content hash; later checks resolve paths again. A child can modify one object, then swap a symlink/hardlink or mount before verification, causing the verifier to inspect a different object or root.
- **Recommendation:** Capture canonical root identity, device/file IDs, symlink policy, mount boundary, and pre/post hashes; reject identity changes and path escapes.
- **Decision Required:** Define whether verification covers names, filesystem objects, or exact content.
- **Validation test:** Swap a reported file between child completion and verification using symlink, hardlink, rename, and mount changes; all must fail closed.

### FHM005-SEC-04

- **Severity:** High
- **Type:** Process containment / Windows cleanup
- **Evidence:** `agent/verify/runner.py:127-166,175-186`
- **Why:** On Windows, cleanup targets only the direct child; descendants can survive, retain pipes, continue modifying the workspace, or keep ports active after a reported pass. This conflicts with the approved Linux-and-Windows qualification scope.
- **Recommendation:** Use Windows Job Objects with kill-on-close, descendant accounting, bounded pipe handling, and post-exit verification.
- **Decision Required:** Require equivalent descendant containment on both platforms before qualification.
- **Validation test:** Start a detached descendant that writes after parent exit and holds stdout open; verification must terminate it and fail if cleanup is incomplete.

### FHM005-SEC-05

- **Severity:** Medium
- **Type:** Cross-session state contamination
- **Evidence:** `agent/verification_evidence.py:535-543,587-604`; `tests/agent/test_verification_evidence.py:350-363`
- **Why:** A full verify pass updates other sessions’ workspace state and can clear their edit markers. Current finalization additionally checks evidence session identity (`agent/verification_stop.py:136-143`), so a direct completion bypass is not confirmed; ledger-state clearing is confirmed and can create future ambiguity.
- **Recommendation:** Separate workspace-wide immutable receipts from per-session pending state; never mutate another session’s pending marker as a side effect.
- **Decision Required:** Choose whether evidence is workspace-scoped or session-scoped, then enforce one model consistently.
- **Validation test:** Concurrent sessions edit the same root while one verifies; neither session may lose its pending state or accept a stale/foreign receipt.


# Independent first pass: privacy

63,745
Privacy Governance Review — FHM-005

Overall decision: Do not qualify or merge a trusted verifier yet. The current phase is appropriately fail-closed, but receipts are not privacy-minimized and have no independent authorization boundary.

1. ID: PG-001
Severity: High
Type: Receipt data minimization / path and content leakage
Evidence: `agent/verification_evidence.py:64-74,378-386,469-473,515-520`; `agent/verification_stop.py:187-195,244-251`
Why: Absolute `cwd`, workspace root, commands, changed paths, and up to 2,000 characters of raw command output are persisted. The same data can be inserted into the model-facing verification nudge. Output may contain personal-file contents, credentials, internal paths, or test diagnostics. Truncation is not redaction.
Recommendation: Store opaque workspace/session identifiers, relative or hashed paths where possible, command fingerprints rather than raw commands, and structured status only. Redact secrets and suppress output by default; require explicit local diagnostics for raw tails.
Decision Required: Approve the minimum receipt schema and whether any raw output may leave the local profile.
Validation test: Inject secrets, home-directory paths, and personal-file content into verifier output; assert neither SQLite receipts nor model-facing nudges contain them.

2. ID: PG-002
Severity: High
Type: Local-only egress / privileged-boundary risk
Evidence: `agent/verify/runner.py:4-5,28-30,93-108,111-124,168-186`
Why: Verification executes project-authored `shell=True` commands and performs HTTP readiness polling. The readiness URL is loopback, but project commands can access arbitrary network destinations, environment variables, files, and credentials. A future dedicated service identity would therefore be unsafe if it runs untrusted project tests with its own privileges.
Recommendation: Require an OS-enforced sandbox or container, deny network egress by default, provide only an allowlisted workspace, scrub inherited secrets, and use separate low-privilege identities. Authenticated local IPC must be the only receipt ingress.
Decision Required: Approve the threat model and explicit network/filesystem policy before any verifier service implementation.
Validation test: Run a recipe attempting external DNS/HTTP, reading personal files, and accessing environment secrets; assert denial on Linux and Windows.

3. ID: PG-003
Severity: Critical
Type: Authorization / provenance / approval separation
Evidence: `agent/verification_evidence.py:487-505,535-543,587-604,607-649`
Why: Any same-profile caller can submit `ok=True`, arbitrary `session_id`, root, command, and output. A full passing `verify` event can satisfy another session and overwrite its state. This confirms the documented forgeability and cross-session-clearing problem. There is no authenticated verifier role or protected receipt format.
Recommendation: Require a separately authorized verifier identity, authenticated local IPC, nonce/attempt binding, immutable scope and artifact hashes, and non-replayable receipts. Do not accept caller-supplied “passed” claims as trusted evidence.
Decision Required: Reject promotion/default-on status until this boundary is independently reviewed.
Validation test: Forge a same-profile pass and replay a prior pass across sessions, roots, and attempts; all must remain unresolved.

4. ID: PG-004
Severity: Medium
Type: Retention and deletion governance
Evidence: `agent/verification_evidence.py:389-421,544,748-809`
Why: Event pruning is capped at 30 days/100 events per session-root, but runs only during insertion for that session/root. Delegated pending rows have no age-based expiry. The visible deletion paths remove only specific pending rows; no user-facing purge/export policy for verification data is evident. SQLite deletion also does not establish secure erasure from journal/backups.
Recommendation: Define retention by data class, run profile-scoped cleanup independently of new events, expire abandoned pending rows, provide an explicit “forget verification history” action, and document residual SQLite backup/journal handling.
Decision Required: Approve retention periods and deletion semantics.
Validation test: Create inactive roots, abandoned pending rows, WAL/journal files, and expired receipts; verify deterministic purge and no stale receipt can later qualify work.

5. ID: PG-005
Severity: Medium
Type: Cross-platform cleanup / privacy containment
Evidence: `agent/verify/runner.py:127-165`; `FHM-005-E2E-QUALIFICATION.md` Scope/Limits
Why: Windows cleanup targets only the direct child, while the runner returns immediately if the leader has exited; descendant cleanup is not established. Qualification evidence is Linux-only despite Windows being in scope. Lingering descendants may retain access to project or personal data.
Recommendation: Use Windows Job Objects and equivalent verified process-tree containment on Linux; require both-platform qualification before release.
Decision Required: Treat Windows privacy cleanup as unqualified.
Validation test: Spawn descendants that outlive the leader and verify termination, handle closure, and no continued file/network access on both OSes.

Top recommendation: keep FHM-005 fail-closed and block trusted-verifier promotion until PG-001–PG-003 are resolved.

Credible alternative: retain the current passive ledger, but make it diagnostic-only and never a completion authority; require explicit operator review for every untrusted receipt.

Uncertainties: I confirmed no trusted verifier/IPC implementation in this baseline. Deployment-specific ACLs, sandboxing, model endpoint routing, and backup policies were not established by the reviewed source.


# Independent first pass: cost

124,407
Independent FinOps review — FHM-005

**FHM-FIN-001 — High — Release qualification gap**

- **Evidence:** `tests/hermes_cli/test_fermes_fhm005_qualification.py:46-53` is Linux-only; `.github/workflows/fermes-pr-checks.yml:130-139` runs it only on Ubuntu. Existing Windows lanes do not execute FHM-005.
- **Why:** The approved release scope requires both Linux and Windows. Current evidence cannot qualify one release across both, and enabling Windows is not a marker-only change: the test relies on `/proc`, `os.killpg`, POSIX sessions, and signals (`test_fermes_fhm005_qualification.py:201-305`).
- **Recommendation:** Add native Windows qualification using Windows process/job cleanup and native IPC/ACL behavior. Keep deterministic unit tests in ordinary CI; run real-process qualification on one Linux and one Windows x64 lane.
- **Decision Required:** Do both native lanes become mandatory release gates, despite additional runner time?
- **Validation test:** Same frozen SHA passes the complete runtime, crash/restart, no-replay, and cleanup cases on both hosts; skipped tests do not count.

**FHM-FIN-002 — High — Verifier service total cost of ownership**

- **Evidence:** The approved candidate requires a separate security identity, authenticated local IPC, protected receipts, and no replay (`FHM-005-PHASE-1.md`, Architecture review gate). No such service or deployment contract exists in the inspected source. Current implementation is profile-local SQLite and opt-in only (`agent/verification_evidence.py:139-149`).
- **Why:** A verifier identity creates a new install, upgrade, startup, crash-recovery, logging, ACL, and support surface on two operating systems. Windows service/ACL behavior and Linux user/service behavior will diverge. A dedicated identity alone is not an independent boundary if it executes untrusted project tests with its own privileges.
- **Recommendation:** Prefer a bounded, on-demand verifier process per verification request, with deterministic allowlisted checks against a restricted/read-only artifact view. Avoid an always-on daemon unless measured demand justifies it.
- **Decision Required:** Accept the ongoing cross-platform service maintenance burden, or retain opt-in fail-closed behavior until the verifier is independently designed and qualified?
- **Validation test:** Native install/start/stop/update, authenticated IPC spoof/replay rejection, crash/orphan cleanup, and upgrade rollback tests on Linux and Windows.

**FHM-FIN-003 — Medium — Unbounded local resource overhead**

- **Evidence:** Current finalization reads SQLite state and clears evidence synchronously (`agent/turn_verification_finalize.py:27-53`); ledger writes use locked transactions (`agent/verification_evidence.py:509-545`). Existing live qualification permits up to 90 seconds for results plus process cleanup (`test_fermes_fhm005_qualification.py:327-331`), while CI gives the Linux job a 25-minute budget (`fermes-pr-checks.yml:20-24`).
- **Why:** A trusted verifier may rerun tests after the child already ran them, multiplying CPU, disk I/O, battery use, and wall time across concurrent local sessions.
- **Recommendation:** Define hard budgets: one verifier per parent, bounded queue, wall-clock/CPU/RSS/disk caps, output-size caps, and guaranteed cleanup. Measure rather than assume acceptable overhead.
- **Decision Required:** Set explicit local FinOps SLOs for verification latency and resource consumption.
- **Validation test:** Stress multiple concurrent profiles and record P50/P95 latency, CPU, RSS, disk growth, and orphan count on both OSes.

**FHM-FIN-004 — High — Current evidence model causes recurring compute waste**

- **Evidence:** Full passing verification can clear other-session state (`agent/verification_evidence.py:535-543`), and status accepts the newest full pass for a root across sessions (`:587-604`). DEC-004 and `FHM-005-PHASE-1.md` explicitly identify same-identity forgeability and cross-session clearing.
- **Why:** Developers may receive false clearance, then incur repeated full verification after later discovery; conversely, conservative unresolved states trigger unnecessary reruns and operator time.
- **Recommendation:** Protected receipts must bind session, child attempt, root, exact artifact/content digest, verifier identity, freshness, and nonce; never clear unrelated state.
- **Decision Required:** Keep FHM-005 non-default and unqualified until this receipt contract is implemented.
- **Validation test:** Same-identity forged rows, cross-session full passes, post-verification mutation, stale receipts, and replayed receipts must all remain unresolved.

**Top recommendation:** Hold release qualification and default-on adoption. Keep the current opt-in fail-closed phase, then qualify a bounded verifier through mandatory native Linux and Windows lanes.

**Credible alternative:** Avoid the privileged verifier entirely and require operator review for all effect-capable delegated work. This minimizes service and matrix cost but materially reduces automation.

**Uncertainties:** Runner prices, real project test durations, verifier deployment model, and expected concurrent local sessions are not specified; cost figures should not be inferred until measured.


# Independent first pass: delivery

70,900
Delivery recommendation: do not merge or promote PR #21/#22 yet. Keep phase one opt-in and fail-closed; make the trusted-verifier boundary the release-critical predecessor.

Confirmed: current qualification is Linux-only, trusted verification remains unqualified, and the current ledger is profile-local rather than independently trusted.

1. **FHM005-DEM-01 — Critical — Trusted-boundary dependency**

   **Evidence:** `FHM-005-PHASE-1.md:18-21,45-54,61-63`; `agent/verification_evidence.py:487-506`; `agent/verification_stop.py:116-145`.

   **Why:** `record_verify_run()` can mint `kind=verify` rows into the same profile SQLite database used by the worker. A child or same-identity process can therefore forge admissible evidence. A dedicated service identity is necessary but not sufficient if that service executes project-controlled tests with its own privileges.

   **Recommendation:** Introduce the approved candidate architecture only: authenticated local IPC to a separately authorised verifier, deterministic trusted checks, isolated worktree/environment, scoped post-child evidence, protected receipts, freshness/version binding, and no replay.

   **Decision Required:** Keep default-off and PRs unmerged until architecture review approves the verifier boundary.

   **Validation test:** A worker with profile write access must be unable to create, alter, replay, or consume a trusted receipt; verifier receipts must bind to exact parent/session, worktree version, paths, and post-child state.

2. **FHM005-DEM-02 — High — Cross-session provenance loss**

   **Evidence:** `agent/verification_evidence.py:535-543,587-604,635-639`; regression intent in `tests/agent/test_verification_evidence.py:350-364`.

   **Why:** A full pass from another session updates/clears the owner session’s `verification_state` for the same root. The final stop check currently rejects foreign-session evidence, but the durable edit paths and provenance have already been overwritten. This is unsafe for concurrent sessions and makes later policy changes vulnerable to false clearance.

   **Recommendation:** Do not mutate another session’s state. Trusted evidence should reference an immutable workspace/version and exact parent scope; shared workspace results should be cache data, never authority to retire another session’s pending state.

   **Decision Required:** Treat current cross-session clearing as a release blocker, not merely a test-policy choice.

   **Validation test:** Concurrent owner/foreign-session tests must show the owner’s pending paths and edit timestamp remain intact after foreign full, targeted, failed, stale, and replayed receipts.

3. **FHM005-DEM-03 — High — Missing Windows release qualification**

   **Evidence:** `FHM-005-E2E-QUALIFICATION.md:25-32,87-90`; `tests/hermes_cli/test_fermes_fhm005_qualification.py:46-53`; `.github/workflows/fermes-pr-checks.yml:23,130-139`.

   **Why:** The real-process suite is explicitly Linux-only; CI runs only `ubuntu-latest`. Windows shell parsing, process-tree cleanup, path identity, SQLite locking, and authenticated IPC are unqualified, despite both OSes being in scope for one release.

   **Recommendation:** Add a native Windows candidate job and require Linux + Windows passes on the same candidate SHA before promotion.

   **Decision Required:** No single-platform “qualified release” claim.

   **Validation test:** Native Windows tests cover child crash/no-replay, descendant cleanup, path scoping, ledger locking, verifier IPC authentication, and optimized/runtime modes.

4. **FHM005-DEM-04 — High — Release gate and rollback are not enforced**

   **Evidence:** `.github/workflows/fermes-pr-checks.yml:98-125,130-142` conditionally skips FHM-005 suites when files are absent; `FHM-005-PHASE-1.md:40-43,63-64` states no default promotion.

   **Why:** The current workflow is a source/test check, not a mandatory staged promotion gate. There is no documented candidate artifact, two-OS acceptance record, or rollback trigger.

   **Recommendation:** Sequence: review PR #21 → qualify stacked PR #22 on both OSes → trusted-verifier implementation/ARB → candidate release gate → only then consider default-on. Roll back by retaining the previous qualified release and disabling/reverting the candidate; never replay uncertain effects.

   **Decision Required:** Require explicit owner acceptance of the gate and rollback policy before merge.

   **Validation test:** A missing, skipped, stale, or failed OS/verifier job blocks promotion; rollback leaves the prior release usable and pending work unresolved.

**Credible alternative:** retain phase-one opt-in permanently as a conservative bookkeeping feature and defer independent verification to a separate release, accepting false-positive `INCOMPLETE` outcomes.

**Uncertainties:** I did not inspect live GitHub branch protections, hosted Windows results, or other reviewers’ reports. No files were modified and no production activity occurred.


# Independent first pass: ux

192,504
Top recommendation: define one outcome contract before implementing a trusted verifier. `verification_unresolved` must never render or propagate as success; expose distinct `verified`, `failed`, `unknown/incomplete`, and `verifier unavailable` states with safe, non-replay remediation.

1. **FHM-UX-001 — High — UX/state contract**

   **Evidence:** `agent/turn_finalizer.py:701-705`; `tui_gateway/prompt_turn.py:311-327, 901-919`.

   **Why:** A verification-blocked result has `failed=true`, `completed=false`, and `verification_unresolved=true`, but no `error`. `_result_status()` therefore reports `"complete"`. TUI/Desktop consumers can show a normal completion state even while the text says work is incomplete. This conflates unknown outcome with success.

   **Recommendation:** Derive status from `verification_unresolved`/`failed` before `error`; add an explicit incomplete/unknown status and a dedicated `verification_unresolved` error surface. Show “some effects may have occurred; inspect before retrying,” never an automatic retry.

   **Decision Required:** Approve the user-facing distinction between deterministic failure and unknown/incomplete outcome.

   **Validation test:** Real child side effect plus missing/untrusted evidence must produce non-success status, explicit copy, and no replay action on Linux and Windows.

2. **FHM-UX-002 — High — Trust semantics**

   **Evidence:** `agent/verification_evidence.py:535-542, 607-649`; `FHM-005-PHASE-1.md:18-21, 36-38`.

   **Why:** A same-profile SQLite `kind=verify` record is not independent proof. Cross-session full verification can satisfy status and clear state, while the current ledger is forgeable by the same execution identity. A future green “Verified” UI would communicate stronger assurance than the system possesses.

   **Recommendation:** Display “checks passed” only as advisory until protected receipts exist. Trusted UI status should require issuer identity, authenticated IPC, exact scope/root, post-child freshness, artifact hashes, and replay protection.

   **Decision Required:** Reserve “Verified” exclusively for the separately authorized verifier, or explicitly label current results “local checks.”

   **Validation test:** Cross-session forged pass, stale receipt, altered path, and replayed receipt must remain unknown/incomplete.

3. **FHM-UX-003 — Medium — Install/remediation friction**

   **Evidence:** `hermes_cli/gateway_setup_service.py:95-108`; `hermes_cli/gateway_runtime_service.py:74-81`.

   **Why:** Service identity failures collapse into generic `service_identity_unverified` or raw “Gateway service setup failed” plus “retry install.” A separate verifier identity will add Linux/Windows account, service-manager, permission, and profile-binding failure modes; repeated retry gives little guidance and may encourage unsafe elevation.

   **Recommendation:** Provide an explicit preflight/status experience: what identity is expected, what was observed, which profile/root is affected, and the least-privilege remediation for each OS. Noninteractive flows must report “verification unavailable,” not silently install or downgrade.

   **Decision Required:** Installation consent/default policy for the verifier service; no current approval exists for this boundary.

   **Validation test:** Simulate account mismatch, inaccessible manager, wrong profile, disabled service, and Windows task misbinding; verify actionable CLI/UI copy and no hidden elevation.

4. **FHM-UX-004 — Medium — Approval uncertainty/replay**

   **Evidence:** `apps/desktop/src/components/assistant-ui/tool/approval.tsx:297-322`; `apps/desktop/src/i18n/en.ts:4531-4533`.

   **Why:** A lost approval response is shown only as “Could not send your answer,” while the command may still be pending or may already have been accepted. “Send it again” does not explain whether repeating is safe.

   **Recommendation:** Return/render `accepted`, `denied`, `expired`, and `unknown/not confirmed` using the same request ID. Preserve the pending card for unknown responses and never issue a fresh approval/replay automatically.

   **Decision Required:** Confirm that approval uncertainty is a first-class state.

   **Validation test:** Resolve-then-disconnect and disconnect-before-resolve races must not duplicate execution.

5. **FHM-UX-005 — Medium — Accessibility/scope clarity**

   **Evidence:** `apps/desktop/src/i18n/en.ts:4546-4549`; `approval.tsx:244-246`.

   **Why:** “Always allow” describes a permanent allowlist using hard-coded `~/.hermes/config.yaml`, which is misleading for Windows/custom profiles and does not state the active profile scope. The existing focus restoration is good (`approval.test.tsx:147-205`), but scope ambiguity can cause over-approval.

   **Recommendation:** Show platform-neutral wording, active profile, exact pattern, and whether the rule applies to this session or future sessions; ensure the confirmation description is announced accessibly.

   **Alternative:** Keep phase one service-free and CLI-first: surface explicit incomplete/unknown results and require operator-run `hermes verify`. This minimizes install friction but does not qualify trusted completion.

**Uncertainties:** No trusted verifier/service implementation is present in the reviewed baseline; gateway ingress, detached async delivery, and live Windows qualification remain unproven.


# Independent first pass: identity

148,218
Identity Architect review — FHM-005

Top recommendation: do not promote a trusted verifier yet. Design it as two boundaries: a minimally privileged verifier authority and a separately sandboxed/untrusted test executor. The authority alone may mint receipts; neither worker nor test code may write receipt storage.

1. ID: IA-001
Severity: Critical
Type: Identity/provenance forgery
Evidence: `agent/verification_evidence.py:487-506`, `:652-667`; `hermes_cli/sqlite_util.py:42-45`
Why: Any same-identity child can invoke `record_verify_run()` with arbitrary `root`, `session_id`, `ok=True`, and write the profile SQLite ledger. Authority is only a predictable session/UI string, not an authenticated principal. The database has no separate ownership boundary.
Recommendation: Service-owned receipt store; authenticated IPC; reject caller-supplied identity fields; mint receipts only after service-controlled checks.
Decision Required: Approve a genuinely separate service identity and receipt authority before any trusted-verifier claim.
Validation test: Worker attempts direct SQLite writes, forged `record_verify_run`, arbitrary session IDs, and receipt deletion; all must fail.

2. ID: IA-002
Severity: High
Type: Privilege escalation / confused deputy
Evidence: `agent/verify/runner.py:4-7, 27-30, 93-108, 214-259`; `agent/verify/environment.py:25-41`
Why: Verification executes project-authored or project-detected commands through `shell=True`, including bootstrap, build, test, and start. A dedicated service SID/user is insufficient if that identity runs attacker-controlled project code: tests can read service-accessible secrets, mutate outside the worktree, spawn descendants, or deliberately produce a passing result.
Recommendation: Split authority from executor. Run project commands under a disposable low-privilege sandbox with no credentials/network, constrained filesystem, fixed argv allowlists, resource limits, and immutable snapshot/digest binding.
Decision Required: Decide whether verification may execute arbitrary project code at all; if yes, require the executor sandbox as a prerequisite.
Validation test: Malicious fixture attempts secret reads, writes outside root, network access, shell expansion, and child spawning; receipt must fail closed and show no escape.

3. ID: IA-003
Severity: High
Type: Scope/provenance confusion and replay
Evidence: `agent/verification_evidence.py:537-543, 587-604, 610-612`; `:652-667`
Why: A full pass updates every session’s state for the same root, and status may select the newest full pass across sessions. Although the final same-session check may block one immediate false-success path, foreign sessions can still clear or repoint durable state. There is no authenticated nonce, artifact version, or one-time receipt binding.
Recommendation: Bind each receipt to an immutable worktree/snapshot digest, exact parent attempt, monotonic nonce, service identity, and expiry; never mutate another session’s state.
Decision Required: Choose strict per-attempt evidence or explicitly design shared verification with separate authorization.
Validation test: Concurrent foreign session, replayed receipt, stale receipt, and same-root different-snapshot cases must not clear parent state.

4. ID: IA-004
Severity: High
Type: OS coverage/IPC boundary gap
Evidence: `docs/fermes/memory/workstreams/reliability/FHM-005-E2E-QUALIFICATION.md:25-32, 87-90`; `FHM-005-PHASE-1.md:45-54`
Why: Qualification is Linux-only and explicitly excludes trusted verifier receipts. No Windows service SID/named-pipe boundary or Linux service-user/Unix-socket peer-credential implementation is present in the reviewed code.
Recommendation: Linux: dedicated service user, root-owned socket, restrictive mode/ownership, `SO_PEERCRED` validation. Windows: virtual service account/service SID, named-pipe DACL, impersonation/token validation, no broad user-accessible endpoint.
Decision Required: Require native Linux and Windows adversarial qualification before one release is qualified.
Validation test: Worker and privileged same-user attackers attempt IPC connection, impersonation, pipe substitution, socket replacement, and profile crossover.

5. ID: IA-005
Severity: High
Type: Process containment/lifecycle
Evidence: `agent/verify/runner.py:127-165, 175-186`
Why: On Windows, teardown is documented as terminating only the direct child. A project start command can leave descendants alive after readiness and after the apparent verification result, allowing continued effects outside the receipt’s scope.
Recommendation: Use Windows Job Objects with kill-on-close and Linux cgroup/process-group containment; wait for verified descendant cleanup before minting evidence.
Decision Required: Treat cleanup proof as part of receipt validity, not best-effort teardown.
Validation test: Fixture spawns detached descendants; receipt remains unresolved until every owned descendant is terminated and identity-checked.

Credible alternative: retain phase-one fail-closed behavior and require operator/external review; do not add a privileged verifier boundary until separately approved.

Uncertainties: I found no implemented verifier service/IPC to assess deployment ACLs. I did not establish an end-to-end false completion through cross-session state because the same-session check may stop that path; the durable state corruption remains confirmed.\n
