# FHM-005 DR-02 / DR-04 security design candidate

**Status: SECURITY CANDIDATE ONLY.** This document proposes a mechanism for owner and independent
security review. It is not an approved design, implementation authorization, security guarantee,
installation plan, or qualification result. No protection described here is implemented or proven.

| Field | Value |
| --- | --- |
| Project | `fermes-hermes` |
| Issue | [FHM-005 P0](https://github.com/fredheathcote007/hermes-agent/issues/5), receipt #36 |
| Branch / worktree | `fermes/fhm005-dr02-dr04-security-detail-20261027` |
| Declared starting SHA | `f2a6f089c4463794a48446bf40f5a85d3391fd59` |
| Source-only design commit already present at inspection | `cd5de816f94ccb4497cad3496bf1d6487dab8728` |
| Inputs | [ADR candidates](ADR-DR02-DR07-CANDIDATE.md), [detailed design](DETAILED-DESIGN-CANDIDATE.md), [trust boundary](TRUST-BOUNDARY-CANDIDATE.md), [ARB review](ARB-REVIEW-20261027.md), [implementation manifest](IMPLEMENTATION-MANIFEST.json), DEC-004–DEC-007, and source-only PR #40/#42 receipt contract |
| Scope | DR-02 parent/controller authentication and DR-04 protected receipt authority only; FHM-007 excluded |

The declared starting SHA is in this worktree's history, but the checked-out tree was already at
`cd5de816` when this task began. This document records that fact so its review context is auditable.

## 1. Decision context and present implementation boundary

DEC-004 requires fail-closed outcomes: missing, failed, stale, untrusted, or unobservable proof is
incomplete, never success; uncertain external effects are not automatically replayed. DEC-005
requires native Linux and Windows qualification together. DEC-006 includes compromised workers and
malicious unprivileged local processes, including same-user/same-logon attackers; local root,
Administrator, kernel compromise, or equivalent privileged control is outside the initial guarantee.
DEC-007 approves a protected controller, authenticated legitimate parent, and restricted worker as
the separation principle. It does not approve this mechanism or authorize services, ACL changes,
installation, deployment, trusted-mode enablement, or risk acceptance. Manual operator or external
attestation remains the fallback.

PR #25's ADR/design stack is preserved and extended by this proposal. Merged source-only PRs #40/#42
supply DTO, attempt, artifact-observation, and candidate SQLite/CAS contracts. They are not an
authenticated controller, protected receipt authority, or trusted completion path. In the separate
read-only worktree, `agent/trusted_verifier_receipt_store.py` documents this limit explicitly. In
particular, `open_for_live_generation(db_path, generation=...)` accepts a caller-supplied generation
and calls `join_existing_live_generation(generation=...)`; that method sets `_joined_generation` and
clears `_reconcile_required` without authenticating the caller or proving liveness. It is an unsafe
seam if treated as authority. A future service must not expose or trust that caller-controlled join.
The source was inspected read-only; no changes were made there.

Fermes PR #48's Ares-derived tests at `9babc34d` provide source-only adversarial coverage; they do not integrate
the Ares execution ledger with FHM-005 receipt authority or qualify a trusted verifier. Existing
FHM-005 replay and forged-proof tests already cover their in-process contract cases and are not
duplicated here. Remaining security evidence includes native Linux and Windows attacks in which a
same-user worker obtains or reuses a live authority handle, and tampers with or joins a generation
through `open_for_live_generation` / `join_existing_live_generation`; these must be denied by the
protected service boundary and fail closed. This candidate records those as open proof obligations,
not implementation findings or completed tests.

The future trusted boundary is a separately installed and protected **controller service** plus a
narrow **parent authority service** running as a dedicated OS identity. A user-facing Hermes process
and all project-authored checks are lower trust. The controller accepts authority requests only from
the parent service identity through OS-authenticated local IPC and a controller-issued per-instance
capability. If a platform cannot maintain this separation, trusted verification is unavailable and
Hermes uses manual/external resolution. This proposal deliberately does not claim that a service
identity makes arbitrary caller intent safe: a dedicated parent broker must separately constrain
requests and bind them to the legitimate Hermes session/task lifecycle.

## 2. Roles and trust boundary

| Principal | Candidate authority | Must not be able to |
| --- | --- | --- |
| Controller service | Derive generation; own protected ledger; authenticate parent; observe verifier execution; issue and consume receipts | Execute project-authored scripts or trust caller verdicts |
| Parent authority service | Authenticate to controller; bind a request to a Hermes session/attempt; request status and exact receipt consumption | Write the protected ledger, mint receipts, or delegate its capability to a worker |
| Interactive Hermes UI/CLI and worker | Submit bounded task intent; run in a restricted executor; return untrusted observations | Open trusted service endpoints as parent, read capability/store, change policy/generation, or assert verified |
| Manual/external resolver | Resolve otherwise unverifiable outcomes under its separately approved authority | Turn an unresolved local attempt into a local controller-minted receipt without an explicit resolution contract |

The controller and parent service identities are distinct from the interactive account and each other.
A worker is created under a restricted identity/token and containment boundary with no inherited
controller/parent handles, secrets, writable service paths, service-control rights, or privileged
IPC. If a design cannot give the parent service a distinct protected identity on a supported host,
there is no same-user-resistant automatic path.

**Important limit:** any interactive caller may be able to ask a legitimate parent service to do work
unless the parent service authenticates/authorizes task intent. OS IPC authentication establishes
which service process sent a controller request; it does not establish that an interactive user's
request is benign, nor does it prove a remote side effect. The parent service must bind every request
to a durable session/attempt and enforce task policy. Unresolved authorization semantics are an owner
decision below.

## 3. Why account credentials and process descriptions do not authenticate the parent

* **Linux `SO_PEERCRED`: insufficient alone.** It reports peer credentials for a Unix-domain socket;
  two processes under the same UID have the same UID authority class. Socket mode/owner, GID, PID,
  `/proc` path, command line, process ancestry, start time, environment, and profile are not an
  unforgeable parent-instance identity. PIDs can be reused, process observations race exit/restart,
  and descriptors can be passed unless explicitly prevented. An AF_UNIX socket is transport, not a
  parent identity proof. See [unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html).
* **Windows SID/DACL: insufficient alone.** A SID names an account/group/logon principal, not one
  authorized Hermes instance. Two same-SID processes both pass an allow ACE. A named-pipe DACL is
  necessary to exclude other principals but does not separate same-logon attackers from a permitted
  client. Pipe-instance creation rights, client impersonation and impersonation failure handling
  are security-critical; a failed impersonation must never fall through to privileged service
  access. See Microsoft [named-pipe client impersonation](https://learn.microsoft.com/en-us/windows/win32/ipc/impersonating-a-named-pipe-client),
  [ImpersonateNamedPipeClient](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-impersonatenamedpipeclient),
  and [named-pipe access rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).
* **Shared secrets in same-user space: insufficient.** A token in a profile file, SQLite row,
  environment variable, command line, log, inherited handle, worker-readable memory, or ordinary
  user key store is available to the same-user attacker or may be forwarded/replayed. MAC/signature
  verification adds integrity only when the signing key is inaccessible and the signer interface
  itself cannot be abused. Cryptography cannot repair a compromised authority boundary.
* **PID/process handle: not an identity primitive.** PID alone is reusable. A process handle can
  pin an object while held, but acquisition and access rights must come from a trusted authority;
  handles must be non-inheritable and never duplicated into workers. A handle to a process does not
  prove that it is the policy-approved parent unless a trusted supervisor created and recorded it.

## 4. Candidate mechanism and platform realization

### 4.1 Common protocol identity

Candidate topology: a protected parent authority service is the only controller client. It is
started/managed by the platform service manager under a dedicated noninteractive identity. The
interactive Hermes frontend is a lower-trust client of that service; it cannot contact the controller
or access the controller's capability. The parent service creates a per-instance capability from
controller-originated secure randomness over an authenticated bootstrap channel, binds it to the
service instance and monotonically increasing controller generation, and retains it in protected
non-inheritable process memory/handle state. It does not persist the bearer value. The controller
stores only a verifier/derived capability hash where feasible, and revokes the capability on service
restart, generation rotation, disconnect ambiguity, or protocol mismatch. Capability bytes never
enter worker IPC, environment, profile storage, logs, command lines, or user-visible diagnostics.

The bootstrap channel itself must authenticate service identity, be protected against endpoint
substitution and downgrade, and bind both service instances to fresh nonces. The controller must
obtain peer identity from the OS on the accepted channel, not from request fields. The capability
is an additional per-instance possession check, not a replacement for a separate service identity.
Capability forwarding/replay, process memory inspection, handle duplication, stale bootstrap,
controller restart, and parent restart are native adversarial tests. If the host cannot protect the
service process and its memory from the attacker principal, no capability is considered private.

This is a concrete candidate, not a proven universal implementation. Service-manager provisioning,
bootstrap API, identity creation, and whether one service or a paired controller/parent service is
operationally acceptable remain owner decisions.

### 4.2 Linux

Candidate deployment uses a dedicated system service account for the controller and a distinct
non-login account for the parent authority service. Neither account is the interactive Hermes user;
workers run under a separate restricted identity. A root-owned system service manager creates the
service processes and endpoint directories. The controller uses an AF_UNIX endpoint in a protected
runtime directory (not a user profile or `/tmp`), restrictive directory/socket ownership and mode,
peer credentials, and service-manager identity/lifecycle evidence. It verifies the peer UID against
the exact configured parent service account, checks endpoint and parent directory object identity,
and requires the per-instance capability. `SO_PEERCRED` confirms the connecting process UID/PID at
connection establishment but cannot distinguish same-UID processes; the dedicated service UID is
the isolation boundary. A user service or a same-UID Hermes parent is not eligible.

The system service manager must launch only the approved parent binary/configuration from protected
paths and prevent an interactive user from modifying unit files, executable, libraries, environment,
state, or service control policy. Use process/cgroup ownership for service lifecycle; use separate
cgroup and sandbox policy for worker execution. Apply least privilege and only supported namespace,
filesystem, syscall, and network restrictions. systemd hardening directives (for example
`ProtectSystem=`) are defense in depth and must be verified on each supported distribution; they
are not substitutes for identity separation. See [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).

**Linux deny conditions:** wrong UID/PID binding, unexpected credentials, endpoint path/object
change, writable parent directory, stale socket, passed/received unexpected FDs, capability mismatch,
service-manager identity uncertainty, missing mandatory sandbox feature, or unavailable native
security mechanism => `verifier_unavailable`; never fall back to user socket authorization.

### 4.3 Windows

Candidate deployment uses two noninteractive Windows services managed by SCM: a controller service
with a dedicated service identity/service SID and a parent authority service with a distinct service
identity/service SID. The interactive Hermes process and restricted worker do not run as either
service identity. A protected service state directory has an explicit DACL granting only the
controller service SID, required system administrators, and narrowly selected service maintenance
principal; parent service and worker have no write access. The controller's named pipe has a protected
DACL limited to the parent service SID and controller/system principals; only the controller may
create server instances. The controller obtains the connected client's token, validates exact
service SID/logon/service identity and expected integrity/restriction attributes, and binds it to the
specific pipe instance plus capability challenge. It must fail closed if token query, impersonation,
revert, or pipe-instance verification fails. Never trust only the interactive account SID.

All bootstrap and receipt/capability handles are created non-inheritable; process creation uses an
explicit handle allowlist. The worker runs under a restricted token and a Job Object configured
before it can execute with breakaway disabled, kill-on-close, process-count/resource limits as
approved, and no inherited controller handles. Job Object membership/containment is separately
verified; it authenticates no parent. See Microsoft [service user accounts](https://learn.microsoft.com/en-us/windows/win32/services/service-user-accounts),
[named pipe security](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights),
and [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

**Windows deny conditions:** unexpected service SID/token/logon, pipe DACL or owner mismatch,
client-created or substituted pipe instance, pipe impersonation failure, unexpected impersonation
level, handle inheritance/duplication, service state ACL mismatch, SCM configuration tampering, or
Job Object breakaway/assignment failure => `verifier_unavailable`; no interactive-token fallback.

### 4.4 Threat and failure coverage

| Threat | Candidate control | Required residual behavior |
| --- | --- | --- |
| Malicious same UID/SID process | Distinct controller and parent service principals; protected endpoint and store; per-instance capability; no worker handles | Any identity ambiguity or capability exposure fences generation and yields unavailable/unknown |
| Peer impersonation / endpoint race | OS peer token/credentials, protected endpoint parent, service-manager launch, challenge-bound pipe/socket instance | Replaced endpoint, wrong token/UID, extra passed descriptor, or failed identity query is denied |
| Capability theft/replay | No disk/environment/argv/log exposure; non-inheritable handles; per-instance nonce and generation; revocation | Old capability cannot join/reopen; ambiguous use becomes sticky unknown |
| PID reuse / late process | PID used only with pinned OS process handle/start identity from trusted supervisor; durable attempt ID is primary | PID-only lookup or uncertain process liveness is not proof; leave attempt unknown |
| Worker privilege escape | Separate restricted token/account, cgroup/sandbox or Windows Job Object; no service control/store/credential access | Escape, containment feature missing, delayed writer, or survivor means unknown and no receipt |
| Filesystem attack | Protected service directories; no user-writable ancestor; open relative to trusted directory handle; no-follow/reparse checks; stable object identity; DB sidecars same ACL | Symlink/junction/reparse swap, mount/device ambiguity, hardlink/rename race, ACL change, or object mismatch denies |
| Crash/restart/upgrade | Durable attempt journal, mandatory reconciliation, generation fencing and atomic state transitions | Any uncertain commit or absent liveness proof is sticky unknown; never auto-replay effect |
| Local root/Admin | Explicitly out of scope per DEC-006 | Report limitation; stronger guarantee needs remote/hardware-backed authority |

Secrets are minimized: capability in protected volatile service memory only; no shared signing key
in profile state. If receipt signing is later selected, private key custody belongs to a platform
protected service identity or hardware-backed provider and remains optional defense in depth. Raw
commands, credentials, full environment, unbounded output, personal paths, and secrets do not enter
receipts. Redacted bounded diagnostic references may be retained under DR-06 policy.

## 5. DR-04 protected receipt authority

### 5.1 Store ownership and access

The authoritative store is a controller-owned directory/database outside the Hermes profile and
project tree. Its directory, database, journal/WAL/SHM files, lock files, backups, and parent path
must be inaccessible for read/write/rename/delete by the interactive account, parent service, and
worker except for explicitly approved API access. Only the controller can mutate it. The platform
installer/service manager creates the directory with verified owner, ACL, mode, and stable identity;
no user-writable ancestor is permitted. The controller opens by a trusted directory handle, rejects
symlinks/reparse points and unexpected hardlink/object identities, verifies ACL/owner and database
schema on every guarded open, and keeps the database handle anchored to the verified object.

SQLite with WAL and `synchronous=FULL` is one candidate, not an approved durability guarantee.
Qualification must demonstrate the exact filesystem, locking, sidecar ACL, flush, power-loss, and
backup/restore behavior on supported Linux and Windows hosts. Unsupported or remote filesystems are
unavailable. A MAC/signature does not make an attacker-writable database authoritative.

### 5.2 Receipt binding and issuance conditions

The controller creates and owns the authoritative request record. Caller-supplied fields are
untrusted claims to match, never authority. A receipt may be issued only after all of the following
are true and durably recorded:

1. Parent service identity and live capability authenticated for the current controller generation.
2. Exact session, attempt ID, unique nonce, parent-authority instance, protocol version, policy
   digest, verifier generation, and expiry bound in the controller ledger.
3. Canonical root identity and immutable snapshot/artifact identity validated using the artifact
   contract; root and object IDs, volume/device/mount rules, file IDs, hashes, and before/after
   mutation checks meet the platform policy. Unsupported object semantics remain unknown.
4. Exact allowed effect class and scope match the approved policy. The controller performs an
   independent check or authoritative readback for that effect; worker output, exit status, worker
   digest, profile DB, legacy receipt, or self-reported success is only untrusted observation.
5. Executor is proven quiescent and every owned descendant/handle/writer is closed or accounted
   for. PID alone is insufficient; uncertain process identity or delayed writes prevent issuance.
6. All freshness, policy, controller health, storage ownership, generation, and authorization checks
   remain valid at commit time. A single controller transaction records observations and moves the
   exact attempt to issued; commit/response ambiguity yields unknown and generation fencing.

Suggested protected row fields (opaque/minimized):

```text
schema_version, controller_generation, parent_instance_id,
session_id, attempt_id, nonce, request_digest,
root_object_id, snapshot_digest, artifact_set_digest,
effect_class, effect_scope_digest, policy_digest, protocol_version,
observation_digest, result, issued_at, expires_at,
state = prepared | issued | consumed | expired | rejected | unknown_incomplete,
transition_version, consumed_at, resolution_reference
```

Never accept caller-provided `trusted_source`, authority, root, policy, generation, `issued`,
`consumed`, verifier result, or status as true because it parses. The controller computes or
independently validates each field and writes the authoritative state.

### 5.3 One-use compare-and-swap and generation lifecycle

Issuance and consumption are separate durable transitions. The parent can request consumption only
for the exact receipt ID and expected tuple `(controller_generation, parent_instance_id, session_id,
attempt_id, nonce, root_object_id, snapshot_digest, effect_scope_digest, policy_digest,
protocol_version)`. In one transaction, controller checks exact equality, unexpired `issued` state,
current generation, live authenticated parent capability, and unused transition version, then changes
`issued -> consumed` and increments transition version. Exactly one concurrent consumer may win; every
replay, stale tuple, duplicate, foreign session, or uncertain result is non-success. The parent/UI
finalizer independently matches the returned receipt to its own attempt. A successful store CAS is
not by itself an end-to-end success proof if the finalizer cannot authenticate the response.

Generation is controller-owned monotonic state anchored in protected storage and service lifecycle.
It is never supplied by the client, worker, profile store, or CLI. First installation provisions a
fresh generation only after protected storage verification. On controller restart, parent restart,
upgrade, rollback, identity/config/policy/protocol change, capability revocation, uncertain commit,
or store recovery, controller first enters **reconcile-only** mode. It authenticates service state,
checks schema/ACL/object identity, reads durable attempt transitions, fences the previous generation,
and converts every nonterminal or ambiguously issued/consumed attempt to sticky
`unknown_incomplete`. Only after a durable reconciliation marker and new generation commit may new
attempts be armed. No issued receipt survives a restart as consumable unless a future owner-approved
protocol proves continuity and same-instance liveness; this proposal defaults to invalidation.

`open_for_live_generation(generation=...)` and any equivalent caller-controlled join must never be
used by an authority path. The controller may join a live connection only after it has authenticated
the peer and itself, derived the current generation, verified the process/service instance through an
OS-pinned identity, and completed mandatory store reconciliation. PID, a live socket, same UID/SID,
caller generation, or a stale store row is not liveness proof. If process/service continuity or
reconciliation cannot be proved, fence and mark unknown.

### 5.4 Durable crash reconciliation

The controller journals transitions before acknowledging them. At minimum, fault injection kills the
controller/parent at: request reservation, executor spawn, observation collection, quiescence,
receipt prepare, durable issue commit, issue response, consume CAS, consume response, generation
rotation, and reconciliation commit. After every restart, no API can issue or consume until store
integrity and reconciliation finish. Uncommitted transactions roll back only when the storage engine
proves rollback; ambiguous commit outcomes remain unknown. Orphaned WAL/SHM, corrupt schema, failed
flush, inaccessible state, torn marker, backup restore, rollback to older generation, or service
identity mismatch fences the generation. Reconciliation must be idempotent and monotonic; it never
resumes/replays an external effect or clears unknown based only on a later worker claim.

A manual/external resolution is a separate audited transition with an explicit resolver identity,
resolution evidence reference, scope, and owner-approved policy. It does not rewrite history to
pretend a local receipt existed. Unknown stays sticky until such a separately authorized resolution
is recorded; no resolver means unresolved.

## 6. Proposed API and protocol sketch

All requests have bounded size, strict versioned schemas, exact fields, canonical encoding, replay
nonce, deadlines, and explicit response correlation. Unknown fields, downgrade, malformed IDs,
oversized payloads, duplicate nonce, stale generation, and invalid transitions are rejected. No
endpoint accepts a path to execute, command, arbitrary SQL, caller verdict, or store path. Executor
requests are policy IDs resolved by controller policy, not shell text supplied as authority.

```text
bootstrap_parent(os_peer) -> {protocol, controller_generation, challenge}
  controller verifies OS service identity and protected endpoint
  parent proves service identity; mutual challenge binds pipe/socket instance
  controller returns ephemeral capability; parent keeps non-inheritable/in-memory

begin_attempt(capability, request_claims) -> {attempt_id, nonce, controller_generation}
  controller authenticates parent, derives session/policy/root bindings,
  reserves attempt durably; caller cannot choose authority or generation

run_check(capability, attempt_id, policy_id) -> {observation_ref, state}
  controller creates restricted executor; worker cannot address receipt API/store

issue(capability, attempt_id) -> {receipt_id, exact_binding, expires_at} | unavailable
  controller independently validates artifacts/effect/readback/quiescence and
  durable issuance predicates; ambiguous result -> unknown_incomplete

consume(capability, receipt_id, expected_binding) -> {consumed_binding} | incomplete
  single protected CAS against current generation and every bound field

reconcile(os_peer) -> {generation, fenced_attempts, ready}
  only service lifecycle path; no public caller chooses generation or clears barrier
```

Pseudocode authority guard:

```python
def handle_issue(channel, msg):
    peer = os_authenticate_accepted_channel(channel)     # service SID / service UID
    require(peer == configured_parent_service)
    require(protected_endpoint_and_controller_identity_ok())
    capability = validate_live_instance_capability(peer, msg.capability, channel.instance)
    require(store_integrity_and_acl_ok())
    require(reconcile_complete_for_controller_generation())
    attempt = store.load_exact_attempt(msg.attempt_id)
    require(match_controller_derived_parent_session_policy(attempt, peer))
    require(exact_nonce_root_snapshot_effect_policy(attempt, msg.claims))
    require(independent_observation_and_readback_pass(attempt))
    require(executor_quiescent_with_no_survivors(attempt))
    return store.issue_transactionally(attempt, generation=controller_generation)
```

Every failed `require` has a typed denial. Authentication/endpoint/config/store/lifecycle failures
return `verifier_unavailable`; invalid binding, replay, policy denial, stale evidence, or failed
independent check returns rejected/failed or `unknown_incomplete` as appropriate. API errors never
map to completed. IPC disconnect after state-changing call is ambiguous, so caller queries status
only through a fresh authenticated channel; if status cannot prove a single durable result, unknown.

## 7. Native adversarial qualification and proof obligations

Linux and Windows must run native tests against the same candidate SHA. Simulated identities or
platform-independent mocks can test contracts but do not satisfy OS proof. No skipped, timed-out,
blocked, or emulated security test is a pass.

| Area | Linux native attack | Windows native attack | Required evidence |
| --- | --- | --- | --- |
| Same-account impersonation | Malicious same-UID process opens socket, copies public fields, races parent, forwards FD, attempts capability read/use | Same-logon/SID process opens pipe, creates competing pipe instance, duplicates handle, races legitimate parent | Denial of unauthorized process; accepted OS identity is dedicated parent service principal; no capability disclosure |
| Service identity | Replace unit/binary/config/library, alter service env, stop/restart service, use wrong UID | Change SCM account/service SID/config/image, impersonate client, force impersonation failure | Exact service identity/config/endpoint audit and fail-closed behavior |
| Endpoint and peer | Symlink/socket replacement, stale path, unexpected ancillary FDs, directory permission race | Pipe DACL tampering, instance substitution, client token/SID/logon mismatch, impersonation-level downgrade | Endpoint object binding and every mismatch denied |
| Capability/process | Read `/proc`/memory where permitted, inherited FD, FD passing, stale capability after restart, PID reuse | Handle inheritance/duplication, token theft attempts, process restart, PID reuse, stale pipe handle | Capability only in protected parent/controller process; stale instance rejected; PID never sole proof |
| Worker containment | Spawn descendants, detach, escape cgroup/namespace, delayed writer, access store/socket/secrets, network egress | Job breakaway, nested job/child, inherited handles, service-control access, delayed writer/network | No authority/store/secret access; all descendants accounted; uncertainty blocks receipt |
| Store and filesystem | User-writable ancestor, symlink/hardlink/mount swap, WAL/SHM ACL, rename/restore/corruption, concurrent CAS | Reparse/junction/hardlink swap, ACL inheritance, alternate stream/rename, WAL/SHM ACL, restore/corruption | Controller-only writes; object identity stable; tamper/recovery fences generation |
| Crash and replay | Kill at every protocol/store transition, reboot, truncate/corrupt WAL, replay old receipt | Terminate services, reboot/logoff, service upgrade/rollback, pipe disconnect at commit, replay old receipt | Reconcile before reopen; sticky unknown; one-use CAS; no external effect replay |
| Negative proof | Worker exits zero but lies; root/artifact mutates after check; no authoritative external readback | Same, including late child writes and pipe response loss | No receipt or completion; manual/external fallback recorded |

Exact proof obligations before any trusted-success claim:

1. Native identity proof: controller accepted only the configured parent service identity on both OSes;
   same-user/same-logon process cannot authenticate as parent or obtain/forward its capability.
2. Authority proof: worker and interactive processes cannot read/write store, use controller API as
   parent, inherit trusted handles, invoke arbitrary signing authority, or run under trusted identity.
3. Object proof: endpoint, service executable/config, protected directory/database/sidecars and
   referenced artifacts resolve to expected OS object identities with no user-writable path race.
4. Protocol proof: strict fields/version/size, authenticated challenge, nonce uniqueness, no downgrade,
   exact root/object/policy/effect/session/attempt bindings, response correlation and stale-channel denial.
5. Durability proof: issue/consume CAS survives supported crash model; all ambiguous/restarted
   nonterminal states reconcile to unknown before any reopen; generation cannot be caller-selected.
6. Lifecycle proof: upgrade, rollback, service restart, credential rotation and uninstall fence old
   capabilities and receipts; failure preserves diagnostics and manual fallback without replay.
7. Outcome proof: CLI/TUI/gateway/ACP completion derives only from a freshly consumed exact protected
   receipt or separately authorized resolver outcome. No legacy row, worker claim, exit code, or UI
   status projection can create success.

The candidate currently satisfies none of these as an implementation claim. Each obligation requires
reviewable native artifacts and independent review; absence of evidence is not a pass.

## 8. Denied paths, dependencies, and rollback

**Always deny automatic trusted completion** when service identities collapse to the interactive
account; caller presents generation/authority/root/status; capability is in shared user state;
OS peer/token check is missing or ambiguous; endpoint/store owner/ACL/object identity is wrong;
parent/controller liveness is uncertain; policy/effect is unsupported; artifact is mutable or
ambiguous; executor descendant remains; readback is absent/stale; receipt is stale/duplicate/foreign;
commit outcome is uncertain; reconciliation has not completed; or native OS qualification is absent.
Return `verifier_unavailable`, `failed`, or `unknown_incomplete` per DEC-004. Preserve manual or
external attestation fallback and never automatically replay uncertain effects.

Dependencies: DR-03 must approve service lifecycle, identity provisioning, OS support matrix,
installation, IPC endpoint and upgrade/rollback model before implementation. DR-05 must define
which effect classes have authoritative readback and manual/external resolution. DR-06 must approve
receipt minimization, redaction, retention/purge, diagnostics access, and whether hardware-backed or
software signing is warranted. DR-07 must require same-SHA native Linux+Windows gates, independent
review, opt-in qualification, and a separate default-on decision. Existing IMP-001/002/003 contracts
remain model-only until the protected controller and parent authentication exist. No feature should
use the existing diagnostic/profile ledger as trusted authority.

Rollback disables trusted mode, stops/fences the controller generation, revokes capabilities,
invalidates unconsumed receipts, marks active/ambiguous attempts `unknown_incomplete`, preserves
minimal audit evidence, and returns to manual/external resolution. It does not delete unresolved
history, silently downgrade to profile SQLite, consume old-generation receipts, or replay actions.
Uninstall/repair must preserve or export unresolved status under an owner-approved retention policy.

## 9. Material owner approval questions

These answers are required before an implementation proposal can become an approved architecture;
they are intentionally not inferred from DEC-004–DEC-007.

1. **Approve the paired protected-service identity model?** Specifically, may Hermes require a
   dedicated noninteractive parent authority service and distinct controller service on Linux and
   Windows, with the interactive UI treated as lower trust? This changes packaging, resource use,
   user-session integration, credential access, and operations. If no, automatic local trusted mode
   must remain unavailable for same-user threat protection.
2. **Approve the service-mediated task-intent boundary?** What authentication/authorization does the
   parent service require from interactive CLI/TUI/gateway callers, and can a same-user caller ask it
   to run arbitrary verification policies? Service identity authenticates the service, not user
   intent; a confused-deputy rule is required.
3. **Approve platform matrix and assumptions?** Which Linux distributions/service managers and
   Windows editions/SCM identities are supported? Are dedicated service users/SIDs and one-time
   elevated installation acceptable? What is the behavior when account creation or required kernel
   features are unavailable?
4. **Approve IPC/capability model for native prototyping?** May the implementation evaluate
   protected AF_UNIX + OS service identity + per-instance capability on Linux and SCM/named pipe with
   exact service-token validation + capability challenge on Windows? Which bootstrap trust root,
   capability lifetime, revocation, and rotation rules are acceptable?
5. **Approve store and durability semantics?** Is controller-owned SQLite on explicitly qualified
   local filesystems acceptable, or is an OS-native transactional store required? Which power-loss,
   backup/restore, ACL, and sidecar behavior is required? Is conservative invalidation of all
   outstanding receipts on every restart acceptable?
6. **Approve receipt and privacy policy?** Which opaque bindings, redacted observation fields,
   retention period, purge semantics, operator access, and optional signature/key custody are
   acceptable? These affect incident review and privacy exposure.
7. **Approve the rollback and qualification gate?** Confirm same-SHA native Linux and Windows
   adversarial qualification, no skips/timeouts counted, trusted mode stays opt-in, and default-on
   requires a later separate explicit decision. This prevents a design review from being mistaken
   for release authorization.

Until the owner answers these and DR-03–DR-07 are resolved, this remains a bounded source-only
proposal. No approval, implementation, deployment, privilege change, network change, or FHM-007 work
is implied.

## 10. References and verification status

Official platform references informing the candidate (they describe APIs, not proof that this design
is correctly implemented):

* Linux [`unix(7)`](https://man7.org/linux/man-pages/man7/unix.7.html), including `SO_PEERCRED`.
* systemd [`systemd.exec`](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html),
  service hardening and filesystem namespace options.
* Microsoft [named-pipe security and access rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights),
  [client impersonation](https://learn.microsoft.com/en-us/windows/win32/ipc/impersonating-a-named-pipe-client),
  [service user accounts](https://learn.microsoft.com/en-us/windows/win32/services/service-user-accounts),
  and [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

**Unverified details:** exact Linux service-manager configuration, account provisioning and namespace
availability; Windows service SID/token inspection and pipe-instance code; capability bootstrap and
memory protections; filesystem durability/ACL behavior; SQLite power-loss semantics on supported
Windows filesystems; artifact/object binding; end-to-end effect readbacks; and all native adversarial
tests. These require platform-specific design review and execution. No statement here should be read
as a proven protection claim.
