# Independent Challenger

71,907
# FHM-005 Independent Challenger Review

## Verdict

Reject approval of the proposed architecture as a release-ready design. Approve only a conditional architecture investigation.

The candidate addresses a real defect: same-profile SQLite evidence is not independent proof. However, “standalone broker” does not itself establish a security boundary. It protects parent/gateway status only if the child cannot write receipt state, impersonate the IPC client, alter the inspected artifacts, or execute under the broker’s authority.

DEC-004 remains satisfied by the current opt-in fail-closed behavior. The proposed trusted-success path is not yet justified.

## Challenge findings

### 1. Critical — A broker running project tests becomes a confused deputy

**Code evidence:** `agent/verify/runner.py:4-7,93-108,168-186`; `agent/verify/environment.py:25-41`; `agent/verify/recipes.py:27-40`. Project-controlled shell strings and manifests run with `shell=True`, inherited environment, filesystem access, and possible network/subprocess effects.

**Challenge:** A separate service identity does not protect the parent if the broker executes hostile tests with its credentials. The LLM child can rewrite files, alter manifests, access broker-visible secrets, spawn descendants, or manufacture convincing output.

**Test:** Malicious manifest/test attempts receipt-store writes, broker IPC calls, secret reads, outside-root writes, network egress, and detached descendants while returning exit 0.

**Decision:** Project-authored tests must never execute with receipt authority or privileged filesystem access. This is essential.

**Alternative:** Do not mint trusted receipts for arbitrary project tests; keep them advisory/manual.

### 2. Critical — The owner threat model is unresolved

**Code/design evidence:** The proposal relies on OS IPC, ACLs, service identity, and protected local storage. Existing `verification_authority()` is only a session/UI string (`agent/verification_evidence.py:652-667`).

**Challenge:** Same-user processes may often access the same profile; local administrator/root can normally replace binaries, inspect memory, alter ACLs, impersonate services, or modify local state. A nonprivileged installer cannot create a stronger trust boundary. A privileged installer can install the service, but that does not make runtime execution trustworthy.

**Test:** Attempt IPC/storage/binary tampering as an ordinary same-user process, elevated admin/root, after reboot, and after ACL replacement.

**Decision:** The owner must explicitly state whether malicious same-user code and local admin/root are in scope. If root/admin compromise is in scope, local verification cannot provide the claimed guarantee; use remote CI, hardware-backed identity, or accept that limitation. Do not silently claim protection.

**Alternative:** Define the boundary as “protects against unprivileged unrelated local processes and accidental child forgery,” not host compromise.

### 3. Critical — Receipts remain unsafe without artifact and attempt binding

**Code evidence:** `record_verify_run()` accepts caller-supplied `ok`, `root`, `session_id`, scope, and output (`agent/verification_evidence.py:487-505`). Lookup is principally by root/time (`:587-649`). Full verification mutates other sessions’ state (`:535-543`).

**Challenge:** A broker receipt for “this root passed” does not prove that the exact child attempt, files, or post-child state were checked. Several reviews call this a direct foreign-session false-success; the finalizer’s same-session check may block that exact bypass, so that claim is not fully proven. The cross-session state corruption and future ambiguity are proven.

**Test:** Replay a receipt across attempts/sessions, mutate files after verification, replace paths with symlinks/hardlinks, and race finalization with late telemetry.

**Decision:** Essential: service-issued random nonce; exact parent attempt/authority; canonical root identity; artifact/tree hashes or immutable snapshot; policy/command digest; freshness; atomic one-time consumption. Never clear another session’s pending state.

**Alternative:** Existing SQLite remains diagnostic only; no trusted completion.

### 4. High — Process cleanup is not a completion proof

**Code evidence:** `agent/verify/runner.py:127-186` uses process groups on POSIX but only direct-child termination on Windows. Timeout handling can return without proving descendants are gone.

**Challenge:** A child can exit successfully while a grandchild continues writing files, holding ports, or keeping pipes open. A receipt minted before quiescence can be invalid immediately.

**Test:** Spawn delayed writers, detached grandchildren, held stdout pipes, PID reuse, and timeout races on native Linux and Windows.

**Decision:** Essential: Linux cgroup/process ownership or equivalent; Windows Job Objects with kill-on-close; post-exit descendant and late-mutation checks. Any survivor means unresolved.

**Alternative:** Never issue trusted completion for start/server/browser-style checks; require operator inspection.

### 5. High — Generic SaaS/browser verification is impossible

**Code evidence:** `tools/delegate_verification.py:19-35`; `agent/tool_result_classification.py`; `FHM-005-PHASE-1.md:61-63`. Terminal, `execute_code`, and `browser_console` are conservatively effect-capable/unobservable.

**Challenge:** A local green test cannot prove that a browser click, SaaS mutation, connector call, deployment, email, or remote API effect completed correctly. Network acknowledgement may be delayed, duplicated, eventually consistent, or semantically misleading.

**Test:** Exercise browser/API effects with success responses, timeouts after server acceptance, duplicate requests, stale reads, and remote-side rollback.

**Decision:** Essential: define action-specific acceptance contracts. Require authoritative readback or external attestation where available; otherwise return `unknown/incomplete` and prohibit replay.

**Alternative:** Separate “local checks passed” from “external effect verified”; do not force all work through a code-test gate.

### 6. High — State machine and UI can still contradict fail-closed policy

**Code evidence:** `tools/delegate_tool_child_run.py:563-596` treats malformed/missing messages as an empty trace. `agent/verification_evidence.py:702-745` permits broad state updates and deletion. `tui_gateway/prompt_turn.py:311-327` reports `"complete"` unless interrupted/error, despite `verification_unresolved=true`.

**Challenge:** Missing telemetry can resemble no effects; final status can render success while the machine result says incomplete. `disarm_delegated_verification()` can delete a marker after dispatch ambiguity.

**Test:** Missing/truncated messages, unmatched tool calls, crash between arm/spawn/receipt, late completion, and retry after crash.

**Decision:** Essential: `unknown` is sticky after spawn reservation; monotonic/CAS transitions; transactional evaluation/retirement; distinct `verified`, `failed`, `unknown/incomplete`, and `verifier unavailable` states.

**Alternative:** Manual resolution only; never automatically replay uncertain effects.

### 7. High — Both-OS release qualification is currently absent

**Evidence:** `FHM-005-E2E-QUALIFICATION.md` explicitly limits qualification to Linux and excludes trusted verifier, gateway/async, and detached completion. `tests/hermes_cli/test_fermes_fhm005_qualification.py` is marked Linux-only. CI conditionally skips the live suite in `.github/workflows/fermes-pr-checks.yml`.

**Challenge:** No broker, IPC, installer, identity, upgrade, or Windows containment implementation is qualified. Simulated parsing or skipped tests cannot support the stated Windows-and-Linux release promise.

**Test:** Same candidate SHA, native Linux and Windows: install, reboot, IPC spoofing, ACL tampering, crash/restart, receipt replay, descendant cleanup, upgrade/rollback, and profile isolation.

**Decision:** Release blocker. A skipped, timed-out, or environment-blocked OS is not a pass.

**Alternative:** Ship only opt-in fail-closed/manual review until both native lanes exist.

### 8. Medium — The broker may be economically unnecessary overengineering

**Evidence:** Current evidence is already opt-in and fail-closed (`FHM-005-PHASE-1.md:58-64`). A trusted broker adds installation, service lifecycle, ACL, upgrade, rollback, logging, privacy, and two-OS support burden.

**Test:** Measure verification demand, latency, CPU/RSS/disk, concurrent profiles, orphan rate, and operator resolution time.

**Decision:** Prefer an on-demand controller, not an always-on daemon; impose resource limits. This is optional for the trust boundary but essential for operational viability.

**Alternative:** Cheapest safe path: retain manual/operator verification locally, or use externally attested CI for trusted completion. Treat local checks as diagnostic and preserve `INCOMPLETE`.

## Minimum viable architecture

1. Parent creates an immutable attempt and scope.
2. A minimally privileged, separately authorized controller authenticates the parent over OS IPC.
3. Untrusted project checks run in a disposable lower-privilege executor with no broker secrets, receipt storage, or unrestricted network/filesystem access.
4. The controller independently validates scope, hashes, process quiescence, and effect class.
5. It stores a protected, fresh, one-time receipt bound to attempt, root/snapshot, policy, and artifact hashes.
6. Parent consumes only that exact receipt atomically.
7. Any uncertainty becomes `unknown/incomplete`; no replay.
8. Native Linux and Windows adversarial qualification is mandatory before release.

## Essential versus optional controls

**Essential:** two-tier authority/executor separation; explicit threat-model boundary; authenticated IPC; protected service-owned receipts; nonce/attempt/snapshot binding; no replay; descendant containment; action-specific external-effect semantics; sticky unknown; distinct UI states; native Linux/Windows gates.

**Optional defense-in-depth:** cryptographic signatures/MACs, always-on service, raw diagnostic retention, broad recipe support, cross-session verification caches. Cryptography cannot repair a broker that executes hostile code or a local root compromise.\n
