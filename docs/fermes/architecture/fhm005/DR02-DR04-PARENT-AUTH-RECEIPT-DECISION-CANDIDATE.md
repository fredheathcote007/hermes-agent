# FHM-005 DR-02/DR-04 parent authentication and receipt decision candidate

**Status: CANDIDATE ONLY — detailed security options for owner decision; not an approval,
implementation authorization, deployment plan, or trusted-verifier qualification.**

| Field | Value |
| --- | --- |
| Project | `fermes-hermes` |
| Workstream | FHM-005; no FHM-007 scope |
| Baseline | Branch `fermes/fhm005-dr02-dr04-security-detail-20261027`, source-only baseline `f2a6f089c4463794a48446bf40f5a85d3391fd59` |
| Inputs | `ADR-DR02-DR07-CANDIDATE.md`, `DETAILED-DESIGN-CANDIDATE.md`, `VALIDATION-PLAN.md`, `DECISIONS.md` DEC-004–DEC-007, and Cursor independent review evidence |
| Decision surface | DR-02 parent/controller authentication and DR-04 protected receipt authority |
| Current disposition | Separation principle is approved by DEC-007; these concrete mechanisms remain unapproved |

## 1. Boundary and source reality

DEC-004 is the governing result rule: missing, failed, stale, untrusted, or unobservable proof is
`INCOMPLETE`/blocked, and an uncertain external effect is never automatically replayed. DEC-005
requires native Linux **and** native Windows qualification. DEC-006 includes compromised workers
and unprivileged local processes, while excluding local root/Administrator or an equivalent host
compromise. DEC-007 approves the three-role baseline—protected controller, authenticated parent,
and constrained worker—but does not approve a same-user authentication mechanism, service
packaging, IPC/DACL, receipt cryptography, storage, default-on promotion, or merge.

This design branch is stacked on an older draft ARB base and does not contain the later source-only
contracts directly. The qualified Fermes integration branch **does contain** the merged request/receipt
contract, attempt-state model, POSIX artifact observations and unprivileged SQLite candidate store
(PRs #26/#31/#33/#40/#42). Those modules have no runtime authentication, protected authority,
or trusted proof promotion. The actual production-attestation boundary remains the existing
profile-local diagnostic evidence and fail-closed compatibility seams, not independent authority. No current receipt row, session string, process exit status, or
worker report can be promoted by this document.

Likely ownership, subject to the implementation manifest and owner review:

* `agent/` owns the pure request/receipt contract and parent finalizer seam; it must not claim OS
  provenance merely because a DTO parses.
* A future controller/service adapter owns peer authentication, issuance, consumption, protected
  storage, reconciliation, and platform-specific lifecycle.
* A future restricted executor owns worker containment and observations only; it never imports
  receipt authority, receives controller credentials, or writes the protected ledger.
* `tests/` owns behavior contracts and native Linux/Windows fixtures; existing diagnostic evidence
  tests must remain diagnostic.

## 2. SAME-USER adversary: what must be distinguished

The threat is a malicious unrelated process running under the same ordinary interactive account as
the legitimate Hermes parent. It may be a delegated worker, a project script, a second terminal, a
malware process, or a process launched after the parent. It can know public protocol fields, race
requests, inspect worker-visible files and environment, and attempt to connect to or replay IPC.
The controller must distinguish “this request came from the authorized parent instance/capability”
from merely “this process has the same account.”

Unix UID/peer credentials alone are insufficient: `SO_PEERCRED` can establish the connecting process
credentials, but two same-UID processes produce the same identity class. A worker or second terminal
can therefore present the same UID and, if socket access permits, submit a forged parent request.
The UID does not prove parent lineage, authorized service relationship, non-worker role, or possession
of a capability unavailable to the same-user attacker. GID, socket mode, path ownership, PID, process
path, command line, start time, or a PID lookup do not repair this: they are shared, replaceable,
racy, or observational attributes rather than an unforgeable parent claim.

Windows SID/DACL alone has the same limitation. A SID identifies the account represented by a token,
not the legitimate Hermes parent instance. A DACL can prevent other accounts from opening a pipe or
file, but cannot distinguish two same-SID processes that are both allowed. A same-user worker may
inherit or obtain an allowed handle, open an allowed endpoint, or race an interactive parent. Image
path, command line, PID, window/session, and “the token was inherited from the parent” are not enough:
they are not a durable authority proof and inheritance can be changed or absent. A worker must never
inherit controller handles, service tokens, receipt paths, or signing material.

Consequently, “same user,” “same profile,” “same working directory,” “same process tree,” and
“parent supplied a string secret” are not independent authentication. A cryptographic MAC or signed
receipt also does not solve the boundary if a worker can read the key or invoke a signer; it is
defense in depth after OS authority and capability custody, not a replacement for them.

## 3. Options

### Option B — manual/external only (owner-approved fallback)

Keep local evidence advisory and require operator verification or an external attestor. This is the
lowest-risk option: no local same-user parent authentication claim and no local trusted receipt.
It preserves DEC-004 and is the mandatory fallback whenever the native controller boundary is
unavailable, degraded, unqualified, or ambiguous.

### Option A — preferred candidate: service-managed identities plus protected capability

Use a dedicated noninteractive parent identity managed by the OS/service supervisor, distinct from
workers and untrusted interactive users, and a separately protected verifier-controller identity.
The parent is a narrowly authorized broker/client component; the controller is the sole receipt
authority; workers are lower-trust and cannot run under either trusted identity.

The controller accepts a request only when all of these independently hold:

1. The OS authenticates the peer as the expected service-managed parent identity over native local
   IPC.
2. The peer presents a capability created or authorized by the controller/service for that parent
   instance, held in protected non-inheritable process state or an OS-protected handle/token. The
   capability is never placed in worker-readable files, environment variables, profile SQLite,
   command lines, logs, or inherited worker handles.
3. The request binds the capability to a fresh attempt, nonce, session, canonical root/snapshot,
   policy/protocol generation, and exact effect scope. The controller derives authoritative identity
   and generation; caller-provided identity fields are claims to validate, not authority.
4. The controller verifies its own service identity, protected endpoint and store before accepting
   any issue or consume operation. Any failed check returns `verifier_unavailable`.

This is a candidate mechanism, not a claim that a generic service identity automatically makes a
caller trustworthy. The native tests must demonstrate that a same-UID/SID worker cannot acquire,
reuse, forward, duplicate, or impersonate the parent capability, and that controller credentials
are not available to the executor.

#### Linux realization to qualify

Run the controller as a dedicated non-login system service identity and the parent as a dedicated
noninteractive service-managed identity distinct from the worker and interactive user. Use an
OS-owned AF_UNIX endpoint with restrictive owner/group/mode and `SO_PEERCRED` (and, where selected,
systemd/service identity or equivalent native service authorization). Bind the accepted peer to the
expected service identity and a controller-issued, non-inheritable capability. Store service state
and the capability only in a controller-protected directory; do not rely on a user profile socket,
same-UID file, PID/path, or inherited descriptor. Apply cgroup/process ownership and executor
containment separately; AF_UNIX peer credentials authenticate the peer class, not worker safety.

If the parent is merely an interactive same-UID process, this option must fail closed to manual or
external fallback unless a native test demonstrates an unforgeable per-process claim. A UID match
or a socket mode check is not that claim.

#### Windows realization to qualify

Install a noninteractive SCM service with a dedicated service identity/service SID distinct from
interactive users and workers. Expose a named pipe whose DACL grants only the intended service and
controller identities; validate the client token/service SID and pipe-instance binding, not just the
interactive account SID. Use restricted worker Job Objects with kill-on-close and breakaway denied,
and create all controller/parent capability handles non-inheritable. Keep service state and pipe
authorization data outside worker-accessible profile paths.

If the parent is launched as an interactive process under the same account/SID as the attacker,
trusted mode must fail closed/manual unless native tests establish an unforgeable per-process claim.
An allowed same-SID pipe open, inherited token, PID, executable path, or command line is insufficient.

### Option C — external remote or hardware-backed verifier

Use a remote CI/attestor or hardware-backed process identity to issue the trusted result, with an
authenticated request, immutable artifact/snapshot identity, remote readback, freshness, and
operator-visible audit. This can cover stronger host compromise than a local OS boundary, but adds
network, availability, artifact transfer, privacy, key lifecycle, and owner/trust-root decisions.
It is a separate alternative/fallback, not silently substituted for local qualification.

## 4. Preferred DR-04 protected ledger and receipt flow

The service-managed controller is the only authority. Its protected directory is not shared with
workers and is not the legacy diagnostic ledger. SQLite is a candidate implementation only if the
controller-owned directory, OS ACLs, and native durability behavior are proven. Configure WAL and
`synchronous=FULL`; use bounded write transactions and exact compare-and-swap transitions.

The mandatory sequence is:

1. **Guarded open/reconcile before any issue or consume.** Verify directory/store identity and
   schema, then reconcile after restart. Any pre-existing issued/ambiguous row becomes
   `unknown_incomplete` or is otherwise fenced. No issue or consume is allowed before this guard.
2. **Controller-derived generation.** Derive the verifier generation from the protected store and
   service lifecycle, not from caller input, a worker row, a profile database, or a timestamp. A
   stale generation cannot join or consume current state.
3. **Authenticated arm/issue.** Require the authenticated parent capability and immutable request
   binding: attempt, nonce, parent authority, session, canonical root/snapshot, artifact/object
   identity, effect scope, policy/protocol digest, freshness, and expected readback. Reject unknown,
   missing, oversized, downgraded, or caller-supplied authority fields.
4. **Independent observation.** The controller validates artifacts, quiescence/descendant cleanup,
   and action-specific authoritative readback. Worker exit code, output, hash, path, or “success”
   is evidence to inspect, never provenance.
5. **Durable issue and exact one-use consume.** The controller commits a receipt only after all
   predicates pass. Consume is a single CAS on the exact attempt, nonce, authority, scope,
   generation, and receipt state. A second or concurrent consume is non-success.
6. **Ambiguous commit is unknown.** If a commit, IPC response, controller crash, or store read leaves
   outcome uncertain, return `unknown_incomplete`, fence the attempt/generation, and perform no
   external replay. Do not retry merely because the caller did not receive a response.

`join_existing_live_generation` is forbidden unless the controller has authenticated parent/controller
liveness **and** a non-worker capability, and reconciled the protected store first. Same-user liveness,
PID, process path, command line, a live socket, or a caller-supplied generation does not qualify.
The legacy/profile diagnostic ledger may explain events, but it has no authority to issue, consume,
reconcile, or clear a protected receipt.

The receipt should contain opaque IDs and bounded redacted evidence, not raw commands, secrets, or
unbounded output. It must bind attempt/nonce/authority/root or snapshot/artifact digest/policy and
protocol/verifier generation/freshness/effect scope. A receipt signature or MAC is optional defense
in depth and cannot override an OS authentication or store-integrity failure.

## 5. Explicit owner approvals required (not authorized here)

This candidate does not authorize any of the following:

* creating service accounts/SIDs, SCM units, systemd units, named pipes, AF_UNIX endpoints, ACLs,
  DACLs, cgroups, Job Objects, sandbox policy, or one-time elevated installation;
* selecting a service identity, capability format/custody, IPC protocol, SQLite schema, WAL/FULL
  durability contract, generation derivation, retention, or external attestor trust root;
* changing file ownership/permissions, worker inheritance, environment propagation, firewall/network
  policy, package/dependency state, manifests, default-on behavior, or production deployment;
* claiming native Linux/Windows qualification, accepting root/Admin risk, or accepting any unresolved
  High/Critical risk.

The owner must explicitly choose the supported lifecycle and identities, approve the DR-02/DR-04
mechanism, and authorize a native qualification implementation. Until then, trusted mode remains
unavailable or opt-in fail-closed/manual.

## 6. Test matrix and qualification evidence

Tests must run with native OS fixtures, disposable service/store/profile directories, exact candidate
SHA, and recorded service identity, protocol/policy/generation, fixture, and raw evidence location.
Simulation, emulation, skip, timeout, or environment-blocked execution is not PASS.

| Fixture | Required assertion |
| --- | --- |
| Linux malicious same UID | Worker/second terminal cannot obtain capability, connect as parent, issue/consume, or alter protected store; AF_UNIX peer credentials and service identity are checked. |
| Linux other UID | Peer, endpoint, store, and service authorization reject the caller. |
| Linux worker | No receipt-store read/write, capability/secret/handle access, controller execution, detached descendant authority, or external replay. |
| Windows same interactive account | Same-SID process and worker cannot open/use the authorized pipe instance, impersonate parent, or access service state. |
| Windows service token | SCM service SID/token is validated; worker token and interactive token are rejected; capability handles are non-inheritable. |
| Windows pipe DACL | DACL tampering, alternate client, impersonation, and substituted pipe instance fail closed. |
| Windows breakaway | Job Object prevents breakaway; descendants, held handles, delayed writes, and cleanup failures yield unknown. |
| Restart/stale store | Mandatory guarded reconcile fences issued/ambiguous rows; stale generations and stale capabilities cannot join or consume. |
| Forged receipt | Legacy-row edit, worker payload, altered digest/path/status, copied receipt, and cross-session replay never qualify. |
| Concurrent CAS | Exactly one exact consume wins; stale/concurrent consume is rejected/non-success. |
| Compromised worker + external readback absence | Worker may return 0 and forge output; missing, stale, unauthorized, or ambiguous readback remains unknown with no replay. |
| Root/Administrator | Explicitly out of scope; test records boundary and must not be presented as a pass against that attacker. |

Also cover malformed/downgraded requests, nonce reuse, scope/path races, symlink/hardlink/junction/
reparse substitutions, post-check mutation, controller/parent crash at every commit point, upgrade/
rollback, logoff/reboot, and profile isolation. Evidence must prove absence of protected-store
access and controller capability leakage, not just a rejected final status.

## 7. Rollback, fallback, and decision options

Rollback disables trusted mode, fences the verifier generation and outstanding receipts, preserves
`unknown_incomplete`, and prohibits automatic replay. It leaves manual operator or external
attestation available; an external resolution is not converted into a local automated receipt unless
its separately approved attestation contract says so.

Owner decision options:

1. Retain **previously owner-approved Option A architecture principle** and consider the detailed protected service-managed identity and capability mechanism proposed here as the investigation target, subject to separate architecture approval and native proof; trusted mode unavailable until all gates pass.
2. Retain **previously owner-approved Option B fallback**: manual/external verification, with no local trusted receipt claim where the controller cannot be qualified.
3. Approve Option C as the trusted path/fallback with a separately documented remote or hardware
   trust root.
4. Reject local trusted receipts and retain DEC-004 fail-closed behavior.

**Recommendation:** retain the previously approved **Option A** protected local controller direction, assess this precise service-managed identity mechanism as a bounded, non-default candidate, and retain **Option B** manual/external verification as mandatory fallback. Option C remains a separate stronger-host-compromise alternative.
Do not treat the preferred mechanism as approved by this document.

## 8. ADR-constraint traceability and next gate

| Constraint | This candidate response |
| --- | --- |
| DEC-004 | Unknown, failed, stale, untrusted, or ambiguous proof never completes; no uncertain replay. |
| DEC-005 | Both native Linux and Windows mechanisms and adversarial fixtures are mandatory; no simulated pass. |
| DEC-006 | Same-user unprivileged workers/processes are in scope; root/Admin/equivalent host compromise is explicitly out of scope; manual/external fallback is preserved. |
| DEC-007 | Protected controller, authenticated parent, constrained worker, and worker non-authority are retained; only the concrete mechanism is proposed. |
| DR-02 candidate ADR | Dedicated service-managed identities, OS-native IPC, protected capability, and fail-closed interactive fallback are evaluated as unapproved options. |
| DR-04 candidate ADR | Controller-only protected ledger, derived generation, exact binding, WAL/FULL, reconcile, one-use CAS, and unknown-on-uncertain-commit are specified as candidate invariants. |

**Exact next gate:** owner reviews and selects A/B/C, approves or rejects the concrete identity,
capability, IPC, storage, and lifecycle assumptions, and authorizes a separate implementation and
native qualification work item. Before any trusted-success claim, Cursor or another independent
reviewer must inspect the implementation, and the exact same SHA must pass the required native
Linux and Windows matrix. Until that gate, this document is design input only.

## 9. Independent Cursor security review — not an approval

Independent Cursor read-only review, 27 October 2026, found this document fit as **decision input**, not an approved service architecture or authorised implementation. Review evidence on Project Coordinator: `/tmp/fhm005-trust-identity-cursor-review.log`. It confirmed Option A/B matches the previously owner-approved meanings, but identified **release-blocking unresolved questions**:

1. **Capability issuance and custody:** exactly how does a protected controller create, deliver, rotate, revoke, and authenticate a non-inheritable per-parent-instance OS capability across native Linux and Windows? Same UID/SID, PID, executable path, same-user secret or an interactive bridge do **not** meet the approved hostile-worker threat boundary.
2. **Runtime topology:** distinguish interactive CLI/TUI/gateway calls from the service-managed parent. Any interactive-to-parent bridge must not become an unverified same-user deputy. Never execute untrusted project recipes under either protected principal.
3. **Receipt authority and lifecycle:** protected service-owned DB/schema, derived generation, exact attempt/root/session scope, guarded restart/reconcile, ambiguous commit and client timeout state, one-use consume and rollback; prove no caller-controlled live-generation join can bypass fencing.
4. **Trusted effect scope:** choose which Hermes-owned, independently observable v1 checks can produce a receipt; reject generic `shell=True` project recipes or external/UI/API mutations without independently authoritative readback.
5. **Native acceptance:** owner-approved Linux service/UID/socket policy, Windows SCM identity/pipe ACL/token/Job Object policy, disposable malicious-client tests on the same SHA, and independent review without skipped gates. Bubblewrap CVE-2026-87766 dependency (#38) remains a separate blocker.

**No owner approval of the concrete mechanism is inferred from DEC-007.** Keep protected controller unavailable, no privileged installation or default-on, retain manual/external Option B for unsupported effect classes. Before an implementation PR, obtain an explicit decision on the parent runtime topology and capability custody, then refine DR-03/04/05 and the native test matrix.
