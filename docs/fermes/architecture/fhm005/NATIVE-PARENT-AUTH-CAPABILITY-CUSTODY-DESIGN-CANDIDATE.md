# FHM-005 native parent authentication and capability custody candidate

**Status: unapproved security-design candidate.** DEC-008 approves two independently protected
services (parent authority and verifier controller) on Linux and Windows. It does not approve this
authentication mechanism, service provisioning, installation, OS policy, receipt authority,
implementation, deployment, merge, or trusted-mode enablement. This document proposes one concrete
candidate per OS for independent challenge and security approval; it is not a security proof.

| Field | Value |
| --- | --- |
| Project / issue | `fermes-hermes` / [FHM-005 P0](https://github.com/fredheathcote007/hermes-agent/issues/5) |
| Branch / reviewed source SHA | `fermes/fhm005-dr02-native-security-20261027` / `ab06b12102edb306bca33c8c1c6f433abe8a5937` |
| Decisions | [DEC-004–008](../../memory/DECISIONS.md) |
| Related design | [DR-02/DR-04 candidate](DR02-DR04-SECURITY-DESIGN-CANDIDATE.md), [ADR candidates](ADR-DR02-DR07-CANDIDATE.md), [detailed design](DETAILED-DESIGN-CANDIDATE.md), [validation plan](VALIDATION-PLAN.md) |
| Scope | DR-02 parent/controller identity and capability custody, plus DR-04 protected store fencing; FHM-007 excluded |

## 1. Decision proposed for review

Candidate topology only: a noninteractive **systemd system-service pair** on Linux and a **Windows
SCM service pair** on Windows. Any privileged installation or OS/service provisioning remains
unapproved. Each platform has separately protected parent-authority and
verifier-controller service principals, binaries, configuration, runtime endpoints, and state. The
interactive Hermes process authenticates to the parent service as an ordinary user; it never receives
the parent-to-controller capability. A compromised worker and any ordinary process using the same
interactive account must be unable to authenticate as either service, read service memory, acquire
service handles, or alter service files. Controller acceptance requires both OS-authenticated
service identity and a fresh, instance-bound capability proof. Neither user SID/UID, logon/session,
PID, ancestry, executable metadata, nor an OS peer credential can reliably distinguish an ordinary
interactive caller from a hostile process running as the same user. The authenticated parent must
therefore never treat those facts alone as authorization of task intent.

This is the selected candidate because the approved trust boundary already requires two protected
services, and both OS service managers can launch processes under identities distinct from the
interactive account. A same-account daemon, user unit, profile token, process ancestry check, or
cryptographic token stored in user-readable state collapses the required boundary. The service
manager and protected service identity are therefore prerequisites, not optional hardening. If a
host cannot provision or demonstrate the selected boundary, it has no automatic trusted-verification
path; it reports unavailable and uses DEC-004/006 manual-operator or separately approved external
attestation.

### Attacker classes and boundary

In scope: malicious or compromised project workers; unprivileged same-UID Linux processes; Windows
processes with the same user SID/logon; another normal user; malicious project content; IPC replay,
endpoint races, PID reuse, process/handle/FD inheritance, service restart, and storage replacement.
The attacker may invoke ordinary account APIs and inspect its own processes. Out of scope per DEC-006:
local root, Windows Administrator/SYSTEM-equivalent control, kernel compromise, or an attacker who
has already gained equivalent service-manager or service-process control. Out-of-scope status does
not turn an unverified result into success.

| Threat | Required control | Denial / residual result |
| --- | --- | --- |
| Same UID/SID process claims to be parent or supplies unauthorized intent | Distinct protected service identity and live capability challenge authenticate service-to-service only; policy-approved non-mutating artifact readback, attempt and scope are controller-derived | No caller-derived authority; reject or unavailable, no status becomes verified |
| Worker obtains capability | No user files/env/argv/logs; service-only memory; no inherited FDs/handles; restricted worker | Fence generation and mark ambiguous attempts `unknown_incomplete` |
| Endpoint substitution / TOCTOU | Protected endpoint parent and service paths; pin OS endpoint/instance and service-manager generation; open relative to trusted directory/handle | `verifier_unavailable`; never retry over an unverified endpoint |
| PID reuse / stale process observation | PID is diagnostic only; hold and validate process object/handle, service instance and generation; attempt ID is durable authority | Liveness uncertainty means unknown; no PID-only authorization |
| Confused deputy | Parent accepts bounded task intent and policy IDs only; controller never executes project scripts | Unsupported intent rejected; no arbitrary command endpoint |
| Receipt/store tampering or rollback | Controller-owned durable store, monotonic version and generation fencing, ACL verification, restart/restore reconciliation | Fence service generation and all outstanding receipts |
| Local root/Administrator | Explicitly outside initial guarantee | No claim of resistance; preserve fallback and report boundary |

## 2. Why UID/SID, process metadata, and `_PEER_EVIDENCE_SEAL` are not enough

`SO_PEERCRED` supplies credentials for the connected Unix-domain peer, but two processes running as
the same UID have the same account identity. A Windows user SID or named-pipe allow ACE likewise
identifies an account class, not the one approved parent service instance. PIDs can be reused;
ancestry, executable path, command line, environment, profile, start time, and a client-provided
service name are observations that an unprivileged peer can spoof, race, or make stale. A process
handle helps pin a process object only after trusted code acquires it with suitable rights; it does
not by itself establish policy identity. In this candidate OS identity is the **distinct service
principal**, and service-manager-controlled launch/configuration protects which binary runs as it.

`_PEER_EVIDENCE_SEAL` is an in-process evidence marker, not authentication. It cannot authenticate a
remote/local IPC peer, secure a key from a same-user process, establish service identity, or replace
the OS boundary. No API may elevate that marker or a caller-supplied generation into authority.

## 3. Candidate platform implementations

### Linux: system services with distinct static UIDs

Use two **system** units managed by PID 1 (not `systemd --user` units): `hermes-parent.service` under
dedicated static, non-login `hermes-parent` UID and `hermes-verifier.service` under a different
static, non-login `hermes-verifier` UID. Neither is the interactive account; workers use a separate
restricted execution identity. A static identity makes ownership and peer-credential policy stable
across restart. Do not run either service as root. Root owns the unit files, drop-ins, executable,
libraries/dependencies, and configuration; service identities cannot modify them. All unit path
ancestors are non-writable by ordinary users. Use a system-service-managed endpoint directory
in which the controller can create or receive sockets, with traversal limited to the designated
parent service principal. A distinct parent UID
cannot traverse a controller-only `0700` directory or connect to a controller-only `0600` socket:
that configuration is invalid. The candidate is a controller-owned directory with a narrowly
provisioned parent-only execute/search ACL (or a dedicated parent group with directory mode `0710`),
and a controller-owned stream socket with parent-only connect permission through a tightly scoped
POSIX ACL or group mode `0660`. The parent group/ACL must not include any interactive Hermes account,
worker or other service; the installer must provision and verify exact group/ACL ownership, including
sticky ancestor protections. Alternately use a root/systemd-created socket explicitly handed to
the controller with a reviewed ACL. No endpoint resides under a profile or `/tmp`. Verify socket
and parent-directory device/inode/owner/mode/ACL from trusted directory descriptors before use.
Reject stale socket paths and unexpected ancillary FDs; close all received descriptors unless an
explicit protocol field and descriptor policy allow them.

On every accepted stream connection, controller obtains `SO_PEERCRED` immediately after `accept`,
requires the exact parent UID, expected PID, and expected systemd service instance/cgroup membership,
then confirms the process object remains the same while the handshake runs. Credentials are checked
again on each new connection; they are not inferred from a prior PID. systemd unit/service manager
state and cgroup identity are independently queried through a root-owned local interface or other
reviewed manager API; unavailable or inconsistent manager evidence denies. `SO_PEERCRED` alone is
not sufficient because another process with the parent UID could impersonate it if that UID were
exposed. The UID must be non-login and usable only by the service manager; no worker receives it,
its supplementary groups, service-control permission, or writable service path.

Candidate systemd hardening includes `NoNewPrivileges=yes`, a strict system filesystem view,
private temporary storage, restricted address families and syscall surface where supported, no
ambient capabilities, a private controller-owned runtime directory, and an explicit write-path
allowlist. Exact directives and dependencies require distro-specific review. `ProtectSystem=` and
other sandbox flags are defense in depth, not identity proof. The controller service must not have
`ptrace` capability, `CAP_SYS_PTRACE`, or permissions that allow it to read unrelated processes.
Linux Yama ptrace restrictions and `/proc` mount options are not reliable secrets from same-UID
processes unless the service identity, dumpability, capabilities and host policy actually enforce
denial; native tests must attempt `ptrace`, `/proc/<pid>/mem`, `process_vm_readv`, `/proc/<pid>/fd`,
`pidfd_getfd`, and FD passing. Make service processes non-dumpable, disable core dumps, close
unapproved descriptors at startup, use `CLOEXEC`, and never rely on `memfd` secrecy (a memfd is
readable through a leaked descriptor). If the normal account can inspect capability memory or
obtain service descriptors on a supported host, capability bootstrap fails qualification.

References: Linux [`unix(7)`](https://man7.org/linux/man-pages/man7/unix.7.html) for local sockets
and peer credentials; systemd [`systemd.exec`](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
for execution identity and service restrictions.

### Windows: two SCM services with distinct service principals

Use two noninteractive Windows SCM services, each with a distinct service principal and a distinct
service SID configured as a restricted service SID where supported. Candidate is two dedicated
virtual service accounts (for example `NT SERVICE\HermesParent` and
`NT SERVICE\HermesVerifier`) with `SERVICE_SID_TYPE_RESTRICTED`; validate actual access tokens and
logon restrictions on the target Windows build. If SCM cannot create or enforce two distinct
service identities/service SIDs, stop qualification. Never use LocalSystem, LocalService,
NetworkService, the interactive account, or one shared service account for both services. A service
SID added to an interactive/shared account token is not a distinct identity: service SID alone does
not protect against a same-user process if the underlying logon/account is shared or the token can
be duplicated. The service SID must be present only in the correct SCM service token and be denied
to ordinary account processes by token construction and DACLs.

Controller creates a local named-pipe **byte stream** with an explicit protected DACL granting
connect rights only to the parent service SID, controller service SID, and required SYSTEM/service
maintenance identities. Deny remote clients in pipe creation and verify client PID/session/token
after connect. Candidate creation flags include `FILE_FLAG_FIRST_PIPE_INSTANCE` for the first
instance, `PIPE_REJECT_REMOTE_CLIENTS`, and `PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT`; use
`PIPE_UNLIMITED_INSTANCES` only if every instance has equivalent ACL and generation handling. Set
the minimum impersonation level needed for token inspection; do not enable delegation. Inspect the
connected client token for expected user/service SID membership, restricted-SID state, logon type,
integrity level, elevation state, session, and expected service process. Pin the process with a
process handle opened with minimum query/synchronization rights; compare creation time and service
instance to defeat PID reuse, then verify the handle still names the process through the challenge.
Do not trust a pipe name, PID, or token account SID by itself.

If token opening/querying fails, expected SID/logon restrictions are missing, pipe instance identity
is ambiguous, or impersonation fails, close the connection and return unavailable. If the service
impersonates the client, it must check every API result, always revert in a `finally`-equivalent
scope, and perform no privileged operation after a failed impersonation or failed revert. Client
impersonation is only for authorization checks; do not allow client impersonation to become a
controller credential. Server impersonation and token delegation are forbidden. Protect pipe
creation from squatting with the first-instance flag and service-only create/connect rights; deny
remote named pipes explicitly.

Service executable, DLL/dependency search paths, configuration, service registry configuration,
service object DACLs, parent directories, and controller state are protected from the ordinary user.
Disable untrusted DLL search and current-directory loading; validate signed/hashed installation
manifest and file identity before each service generation. Drop `SeDebugPrivilege`; neither service
may enable `SeDebugPrivilege`, take ownership, debug another process, or open worker process memory
with read/write rights. Use non-inheritable handles by default. Worker creation uses
`STARTUPINFOEX` with `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` allowlisting only necessary standard
handles; also clear handle inheritance at `CreateProcess`. Do not pass pipe, service token, process
handle, section, file, registry, or store handles. Validate worker token and Job Object membership
before resuming execution. Test `DuplicateHandle`, debug privilege, process memory, named object
squatting, and service control access as the normal user.

References: Microsoft [named-pipe security and access rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights),
[`ImpersonateNamedPipeClient`](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-impersonatenamedpipeclient),
[`SERVICE_SID_INFO`](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_sid_info),
and [`STARTUPINFOEX`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-startupinfoexw).

## 4. Authenticated bootstrap and wire state machine

The controller generates a 256-bit capability with the OS CSPRNG after an authenticated bootstrap;
the parent does not choose it. The controller keeps only a one-way verifier (HMAC-derived verifier
under a controller service key, or constant-time hash of a uniformly random 256-bit bearer) in
protected volatile state. The parent retains the capability only in locked/non-dumpable service
memory for its service instance. Neither service writes the capability or a reversible form to
SQLite, config, logs, crash dumps, profile files, environment, command line, worker IPC, or backups.
The controller's service key, if required, is controller-only and never shared with the parent;
prefer per-generation random capability verifier material so a database disclosure alone cannot
mint a new capability. Minimize lifetime and rotate on restart, disconnect ambiguity, failed proof,
upgrade, policy change, or store recovery.

All messages use a versioned, canonical, bounded schema (maximum frame 16 KiB, strict field
allowlist, no unknown extensions, no arbitrary paths/commands, monotonic deadlines). The state
machine is sequential; no caller-supplied UID, service identity, generation, role, policy, verdict,
root authority, receipt state, or capability is trusted without derivation/validation:

1. **LISTEN:** controller validates its own service-manager launch identity, protected executable,
   configuration, endpoint parent and store ACL/object identity. Failure means no listener.
2. **OS_AUTH:** accept local stream; authenticate peer using the native checks above. Bind the
   accepted socket/pipe instance to the pinned peer process object. Reject all other principals.
3. **CHALLENGE:** controller sends protocol range, fresh 256-bit `Nc`, controller instance ID,
   durable controller generation `Gc`, and endpoint-instance ID. Parent returns fresh 256-bit `Np`,
   parent instance ID, and an exact echo of `Nc`, `Gc`, endpoint-instance ID and negotiated protocol.
   This response binds the service's bootstrap state to the authenticated connection; the identity
   authority remains the already-checked OS service principal and manager evidence. No pre-shared
   secret is claimed to exist before this step.
4. **MINT:** after parent process/service-instance validation, controller mints random `K`, stores
   verifier and binding `(parent process object, parent instance, controller instance, Gc, protocol,
   endpoint instance)`, and returns `K` once over the authenticated local channel. Parent stores K
   only in protected memory. The bootstrap connection is then closed; no later channel inherits its
   authority implicitly.
5. **PROVE:** for each new connection controller redoes OS_AUTH, sends fresh `Nc2` and current
   `(Gc, controller instance, endpoint instance)`. Parent responds with `HMAC-SHA-256(K, "parent" ||
   Nc2 || Np2 || Gc || parent instance || controller instance || endpoint instance || protocol ||
   channel binding)`. Controller uses constant-time comparison, single-use nonce tracking, and
   exact live-instance binding. Reject duplicate, stale, early, wrong-generation, wrong-channel,
   or cross-service proof. `Np2` is also fresh CSPRNG data.
6. **AUTHORIZE:** authenticated parent submits only typed `INTENT`, `BEGIN_ATTEMPT`, `STATUS`, or
   exact `CONSUME` requests. Controller resolves policy IDs from root-owned policy and derives the
   attempt, nonce, generation and store state itself. It never accepts shell text or project-supplied
   scripts for privileged execution.
7. **ROTATE / FENCE:** restart or uncertainty increments a durable monotonic generation before
   readiness; invalidate K and outstanding receipts; require a fresh bootstrap. If generation
   persistence/advance is uncertain, stay unavailable. Old channels and capabilities cannot join a
   new generation. Parent restart also revokes its capability through controller-observed service
   instance change and requires full bootstrap.

On timeout or disconnect during any state-changing request, the caller reconnects and queries exact
status; it never resubmits an external effect. If a unique committed result cannot be established,
record `unknown_incomplete`. Rate limit failed proofs; repeated failures fence the generation and
produce a security diagnostic without exposing challenge, capability, token, or personal data.

### Parent intent and confused-deputy contract

The parent service is an authority broker, not a generic authenticated proxy. **V1 is limited to
policy-approved, non-mutating local artifact/readback verification** against a controller-created,
immutable, pre-armed attempt and scope. The controller derives attempt identity, approved root/object
set, expected artifacts, and policy ID from root-owned policy and protected state. The interactive
caller cannot choose paths, commands, scripts, executable, environment, outputs, policy definitions,
store paths, generation, attempt IDs, or a “verified” field; arbitrary caller input cannot mint an
authoritative success. Trust binds to the protected policy plus controller-created attempt/scope and
independent observation/readback, not to the identity of the interactive caller. Caller-provided
intent is only an untrusted request to select an already armed eligible attempt; ambiguity, mismatch,
or unsupported scope denies.

All mutation and external-effect intents, and all untrusted or ambiguous intent, remain unavailable
for automatic trusted verification and require manual operator review or separately approved external
attestation. Project scripts never execute with trusted controller authority. If high-impact intent
requires proving that a request came from a legitimate same-user Hermes instance, it additionally
requires a separately protected broker-origin instance identity with owner review or another
independently reviewed proof; absent that proof, fail closed. Service authentication does not
authorize arbitrary user intent. Explicit owner approval of this v1 effect taxonomy is still pending.

## 5. DR-04 durable receipt custody and restart fencing

Controller-owned store resides outside profile/project trees under the service state directory. On
Linux, root creates the state root and only verifier UID may traverse/write it; on Windows, protected
DACL grants access only to verifier service SID, SYSTEM, and narrowly defined maintenance identity.
Parent gets no database write/read access; workers and interactive users get none. Database,
SQLite `-wal`, `-shm`, journal, lock, temporary, backup and migration files inherit the same effective
protection. Verify ACLs and object identities on every open; use local filesystem only. Reject
network, removable, user-mounted, reparse/symlink, or unknown filesystem roots unless separately
qualified. Open service directories with no-follow semantics (Linux `openat2` with
`RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS`; Windows open directory handles with
`FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT` and reject reparse points), then create/open
database and sidecars relative to the pinned directory handle. Canonical paths are descriptive, not
identity. No-follow is required on every component; verify device/inode or volume/file ID before
and after operations.

Use SQLite only after platform qualification, configured for WAL, `synchronous=FULL`, foreign keys,
busy timeout, and a single controller writer. Each mutating transaction uses `BEGIN IMMEDIATE`,
checks exact prior row version and controller generation, increments a monotonic store version, and
commits attempt transition plus receipt issue/consume atomically. Receipts bind attempt ID, random
nonce, parent authority, session, canonical root object, artifact identities/digests, policy/protocol
digest, effect contract/readback, executor generation/quiescence, controller generation, issuance
time, expiry and state. A caller cannot nominate or join a generation. A unique database constraint
and CAS enforce one receipt per exact attempt and one consume only.

Candidate rollback fence is a second, small generation anchor excluded from application database
backups and inaccessible to the ordinary account. On Linux, place it in a root-owned, non-user-writable
ancestor, with a separate verifier-UID-owned directory/file and narrowly restricted `0700`/`0600`
access; no ordinary user has access. The same nonroot verifier service is the sole runtime writer via
an audited single-writer operation (write temporary file, `fsync` file, atomic rename, then `fsync`
parent directory); no privileged helper or service privilege expansion is introduced. On Windows,
use a dedicated HKLM key with SYSTEM installer ACL and write access limited to the verifier service
SID. The anchor is excluded from application database backups. The installer/service configuration
generation is not silently treated as a rollback-resistant third store.

For a generation advance, persist and sync the new anchor first, then commit and sync the same
generation in SQLite; only exact equality permits readiness. If a crash or sync error occurs after
the anchor write but before the database commit, startup detects anchor/database mismatch, fences
readiness, invalidates outstanding receipts and requires manual recovery to create a fresh empty
generation. A database generation ahead of, behind, missing from, or malformed relative to the anchor
is likewise a detected interrupted update or rollback and fails closed; recovery imports unresolved
attempts only as `unknown_incomplete`, never as consumable receipts. Application backup tooling must
exclude the anchor and must not restore a database without this recovery path. A full machine restore
that restores both anchor and database consistently is undetectable by these local mechanisms; after
such a restore, trusted mode remains disabled pending manual recovery and fresh-generation setup.
SQLite rows alone cannot prove anti-rollback against privileged restore.

Before accepting requests after process restart, controller acquires exclusive store lock, validates
schema and ACL/object identity, advances generation durably, marks any dispatched nonterminal
attempt `unknown_incomplete`, invalidates all unconsumed receipts from previous generation, reconciles
WAL/sidecars, verifies no executor from an old generation can still write, then publishes ready.
Any corruption, missing sidecar, failed sync, stale backup, version rollback, uncertain commit,
parent/controller mismatch, or inability to prove old-worker quiescence fences readiness. A late
response cannot change the fenced attempt. Once an external effect may have been dispatched, no
automatic replay is allowed. Existing `open_for_live_generation` or `join_existing_live_generation`
caller-chosen generation semantics are not acceptable authority APIs.

## 6. Nonprivileged work sequence and privileged STOP gate

Permissible next implementation work is limited to nonprivileged artifacts in the isolated worktree:

1. **Mock protocol contract:** implement a deterministic in-memory client/server state machine for
   strict schemas, nonce freshness, channel/generation binding, replay rejection, disconnect
   ambiguity, rotation and no arbitrary command fields. These tests establish protocol behavior only.
2. **Native credential adapter unit tests:** write pure adapter tests around injected OS credential
   records (UID/PID/service-manager evidence on Linux; token SID/logon/restriction/process-instance
   evidence on Windows). Test every allow/deny predicate and error path; mocks do not qualify native
   authentication.
3. **Isolated non-system socket harness:** run Unix-domain stream peer-credential and endpoint
   replacement tests under two unprivileged test identities where available; no system unit,
   service account, privileged path, or installation. The harness is exploratory, not a trusted
   boundary or platform qualification.
4. Produce a read-only host preflight and design review checklist. No service files are installed or
   enabled by these work packages.

**STOP before any privileged action:** do not create accounts, service SIDs, SCM/systemd services,
system paths, ACLs, capabilities, service keys, pipes under protected namespaces, alter host security
policy, install dependencies, or change service configuration until owner explicitly approves a
separate concrete implementation/install plan after security review of this candidate. That later
plan must name exact files, commands, identities, ACLs, rollback, and host-specific privilege impact.

## 7. Native qualification matrix and release gates

Required candidate qualification targets are **Ubuntu 26.04 with systemd 259** and **Windows 11 Pro
build 26300**. First run a read-only preflight: exact edition/build/kernel/systemd version, filesystem
and mount type, service-manager features, security policy, service identity availability, privilege
boundary, and API availability. A mismatch is `BLOCKED/NOT QUALIFIED`, not substituted silently.
The same source SHA must pass both native lanes. All rows require actual execution and retained
bounded artifacts; skipped, simulated, emulated, timed out, or unobservable means NOT PASS.

| Area | Linux native checks | Windows native checks | Required result |
| --- | --- | --- | --- |
| Positive identity | Approved systemd parent UID connects; exact `SO_PEERCRED`, system-unit/cgroup and endpoint instance agree; fresh challenge proves live generation | Approved SCM parent service token connects; service SID, restricted token, logon restrictions, process object, pipe instance agree; fresh challenge proves live generation | Only designated service accepted; ordinary Hermes remains lower trust |
| Same-user hostile peer | Ordinary same-UID process attempts socket access, UID/service spoof, stale PID, FD passing, capability replay, `/proc` memory/fd access, `ptrace`, `process_vm_readv`, `pidfd_getfd` | Same-logon process opens pipe, squats first instance, forges SID fields, duplicates handles, attempts debug/memory access, stale PID, service control, remote pipe | Deny without capability leakage or service action; no false PASS on exception alone |
| Binary/config and identity custody | Normal user attempts edit/replace unit, drop-in, executable, dependency, config, state ancestor; attempt user-unit impersonation | Normal user attempts edit service image/config/registry/DACL/dependency; shared-identity and service-SID misuse fixtures | Integrity/access check fails closed; distinct service identities proven |
| Protocol | Wrong UID/PID/cgroup, nonce reuse, changed channel, stale generation, downgrade, unknown field, frame over 16 KiB, missing FD policy | Wrong token/SID/logon/integrity, failed impersonation/revert, pipe replacement, remote client, duplicate nonce, handle inheritance, downgrade | Typed reject/unavailable; never success |
| Capability custody | Inspect service dumpability/core settings, inherited/passable FDs and worker access; restart/replay old K; attempt attach as ordinary account | Inspect token/handle inheritance allowlist, dump/debug behavior, worker handle table; restart/replay old K; attempt duplicate/debug | Secret never appears in user-readable artifacts; old K rejected |
| Store durability | No-follow/root ownership, DB/WAL/SHM/backup ACL, symlink/hardlink/mount/rename races, crash at every commit boundary, backup restore/rollback, CAS race | No-reparse/ACL, DB/WAL/SHM, junction/alternate path races, service crash/reboot, backup restore/rollback, CAS race | Fenced generation, exactly-once consume or sticky unknown; no auto-replay |
| Artifact/effect boundary | Replace root/artifact during check, hardlink or mount substitution, late writer, bounded readback | Junction/reparse/file-ID/case/volume substitution, late writer/lock, bounded readback | Root/object identity stable and effect-specific authoritative readback; otherwise unknown |
| Teardown / rollback | Stop candidate process, fence generation, revoke K, preserve unresolved attempts, verify no orphan; restore prior nontrusted behavior | Stop services, revoke K, preserve unresolved attempts, remove candidate test state only, verify no orphan; restore prior nontrusted behavior | No receipt survives rollback as current; no uncertain action replay |

Independent security approval is a gate before any privileged implementation. Further non-negotiable
gates: owner approval of exact service identity/provisioning and host policy; review of endpoint and
bootstrap implementation by OS security reviewers; demonstrable denial from normal same-user account
on both platforms; protected-store rollback model; full DR-04 receipt/effect contract; native test
evidence at the exact same SHA with no skipped PASS; independent review; and a separate explicit
owner decision before trusted-mode promotion/default-on. Root/Administrator remains excluded and
must be stated wherever this capability is described. This document supplies none of those approvals
or runtime evidence.

## 8. Unsupported hosts, alternatives and fallback

On unsupported systemd versions/distributions, Windows editions/builds, unavailable service
identities, changed ACL semantics, unqualified filesystems, missing peer/token evidence, or any
failed native gate: do not downgrade to a user unit, shared UID/SID, per-user broker, profile secret,
same-user keyring, process ancestry, executable-path check, or `_PEER_EVIDENCE_SEAL`. Mark trusted
verification unavailable and require manual operator review or a separately approved external
attestor. A remote verifier or hardware-backed authority could be considered as a new design with its
own threat model, deployment and approval; it is not an implicit fallback implementation. Receipt
signatures/MACs can add integrity after key custody is established but do not replace service identity
or prevent a confused deputy.

## 9. Prior challenger P1 remediation status and pending owner decisions

The independent PR50 challenger identified two P1 design gaps. **Intent authorization:** addressed in
this candidate by limiting v1 to controller-created immutable attempts and policy-approved
non-mutating local readback, while explicitly leaving same-user legitimate-Hermes attribution for
high-impact intent unavailable without separately protected, owner-reviewed instance proof.
**Rollback anchor:** addressed as a proposed nonroot verifier-UID single-writer anchor separate from
the database, with explicit ownership, sync ordering, mismatch/crash detection, manual recovery, and
the undetectable consistent full-machine restore boundary. These are design remediations only; neither
is implemented or natively proven.

Pending owner decisions include explicit approval of the v1 effect taxonomy, any same-user
broker-origin proof for high-impact intents, exact service identity/provisioning and OS policy,
concrete installation/upgrade/rollback plan, DR-04 details, and any trusted-mode promotion. No owner
approval is inferred here. Privileged implementation and trusted mode remain gated on owner and
independent security review plus native Linux and Windows evidence.

## 10. Approval questions / challenge points

Security review must specifically challenge: whether static Linux service UIDs and systemd/cgroup
evidence defeat all ordinary same-UID access on the selected Ubuntu build; whether the selected
Windows virtual accounts and restricted service SIDs are actually distinct from ordinary logon
tokens; whether the proposed capability proof adds a sound binding beyond protected OS identity;
how the durable monotonic generation survives crash and backup restore without a hardware root; how
parent authorizes user task intent without becoming a confused deputy; and whether the selected
`openat2`, SQLite WAL/full-sync, pipe ACL and process-handle APIs meet the exact race/durability
claims. Unresolved answers block privileged implementation and trusted mode. These details are
candidate assumptions subject to native prototype evidence, not claims that APIs guarantee the
properties by themselves.
