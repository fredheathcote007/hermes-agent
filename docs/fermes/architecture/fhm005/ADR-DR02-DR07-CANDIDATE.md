# FHM-005 DR-02–DR-07 ADR candidates

**Status: DR-02 separation principle approved under DEC-007; concrete mechanisms and DR-03–DR-07 remain CANDIDATE, not approved for deployment.**

DEC-006 approves the local attacker boundary and manual/external fallback. DEC-005 requires
native Linux **and** Windows qualification. **DEC-007 approves DR-02 controller/parent/worker
separation as an architecture principle**, but not the concrete same-user impersonation-resistant
authentication mechanism. DR-03–DR-07 and DR-02 mechanism remain open; nothing here authorises
privileged installation, deployment, default-on, or High/Critical residual risk acceptance.

## Decision summary

| Decision | Recommended candidate | Alternatives retained | Owner decision needed |
| --- | --- | --- | --- |
| DR-02 | **Principle approved DEC-007:** protected controller, independently authenticated parent, restricted worker, no privileged project scripts | Manual/external fallback remains required when trust unavailable | Design, independently review and natively prove same-user impersonation-resistant parent authentication and protected receipts before enabling |
| DR-03 | Native Linux system UID/socket and Windows SCM service SID/named-pipe DACL/Job Objects | User daemon; interactive/startup fallback; remote verifier | Approve supported install/runtime matrix and fail-closed unsupported behavior |
| DR-04 | Per-attempt nonce, immutable scope, object/digest binding, policy generation, freshness, one-use CAS | Advisory receipt only; signed receipt without OS boundary | Approve receipt fields, state transitions, and replay/TOCTOU rules |
| DR-05 | Action-specific readback; unknown is sticky; manual/external resolution without replay | Best-effort retry; manual-only | Approve effect taxonomy, resolver authority, and UX |
| DR-06 | Minimized redacted local receipt; explicit retention/purge; crypto optional defense-in-depth | Rich local diagnostics; signatures/MACs as primary | Approve privacy/retention and whether optional crypto is worth cost |
| DR-07 | Same-SHA native Linux+Windows adversarial release gate; trusted mode opt-in | Manual-only release; narrower capability | Approve CI/release gates and separate default-on review |

## DR-02 — Explicit trust/execution model

**Approval:** DEC-007 establishes the mandatory three-role separation. The choice and native proof of secure parent authentication, IPC, OS identities and protected receipts remain open engineering/security decisions.

### Recommended candidate: two-tier local model

The controller is separately authorized and is the sole receipt authority. It authenticates the
parent through OS IPC, derives peer identity, validates immutable attempt scope, launches a disposable
lower-trust executor, independently validates the result, and mints a protected receipt only after
quiescence and artifact/readback predicates pass. Project-controlled recipes never run under the
controller identity and never receive controller credentials, receipt-store access, profile secrets,
or unrestricted egress.

This is the minimum model consistent with DEC-006’s unprivileged-worker threat and DEC-004’s
independent-proof requirement. It still excludes local root/Administrator compromise and does not
prove arbitrary external effects.

### Alternatives

* **Manual/external only:** safest operational boundary; no local trusted receipts for arbitrary
  project work, but preserves fail-closed behavior and has lower service complexity.
* **Privileged broker directly runs existing recipes:** rejected candidate. `shell=True`, inherited
  environment, project manifests, and subprocess effects make the broker a confused deputy.
* **Remote/hardware attestation:** strongest host-compromise story, but materially expands deployment,
  trust, cost, and owner scope.

### Unresolved material decision/risk

Owner already confirmed (DEC-006/007) that “unprivileged workers and unrelated local processes in scope; local
root/Administrator out of scope” is the intended assurance boundary and that arbitrary project tests
are either adequately constrained or limited to advisory/manual evidence. A controller/executor split
alone is not approval.

## DR-03 — Supported installation and platform matrix

### Recommended candidate: native protected service on both operating systems

Linux uses a dedicated non-login system UID, protected service-owned state, restrictive Unix socket,
peer-credential validation, and cgroup/process ownership checks. Windows uses an explicit noninteractive
SCM service identity/service SID, protected state, named-pipe DACL and token validation, and Job Objects
with kill-on-close. One-time elevated installation is allowed; normal runtime does not require root or
Administrator. User-daemon, interactive-token, Startup-folder, or inherited-credential fallback is
diagnostic/manual only and never trusted mode.

The controller reports `verifier_unavailable` when installation owner/mode/DACL, service identity,
protocol generation, socket/pipe, storage protection, or containment cannot be proven.

### Alternatives

* **Per-user daemon:** simpler installation but insufficient against same-user worker forgery unless
  the owner narrows the guarantee to manual/advisory evidence.
* **Interactive/startup fallback:** rejected for trusted mode; it collapses identity and lifecycle
  boundaries.
* **Remote verifier:** valid fallback/alternative where local native support is unavailable, but a
  separate system and attestation contract is required.

### Unresolved material decision/risk

Owner must select supported Linux distributions/systemd assumptions, Windows service identity, upgrade
and rollback behavior, and whether an on-demand controller or resident service is the initial lifecycle.
The exact mechanism must be proven on native hosts, not inferred from configuration files.

## DR-04 — Receipt and acceptance protocol

### Recommended candidate: immutable per-attempt receipt with atomic one-use consumption

Every attempt has a random nonce, parent/session authority, canonical root identity, immutable effect
and artifact scope, policy/protocol digest, verifier generation, freshness window, and supersession
link. The controller independently records pre/post artifact object identity and SHA-256 (or an approved
immutable snapshot/generation proof), process quiescence, and action-specific readback. The protected
store accepts one exact `(attempt, nonce, authority, generation)` CAS consume; successful consumption
is terminal. Foreign, stale, replayed, mismatched, malformed, concurrent, or unreadable evidence is
not success.

Legacy `verification_evidence.db` remains diagnostic and cannot satisfy this protocol. Cross-session
cache data must not mutate or retire another session’s pending state.

### Alternatives

* **Advisory receipt only:** retain current behavior; no trusted local success claim.
* **Cryptographic signature/MAC as primary:** not sufficient if the worker can access the key or the
  host is root/Admin-compromised; optional after OS isolation.
* **Path/time lookup:** rejected; it cannot address TOCTOU, replay, or cross-session scope.

### Unresolved material decision/risk

Owner must approve the exact artifact scope model (file set, tree, snapshot, or accepted generation),
expiry clock/source, receipt retention, crash commit points, and whether external readback is inside or
outside the first trusted capability set.

## DR-05 — External action and human resolution

### Recommended candidate: explicit effect classes with authoritative readback

Classify local checks, filesystem mutations, process/service changes, browser/UI effects, connector/API
calls, deployments, email, and remote/SaaS mutations separately. Each trusted class must specify an
authoritative readback issuer, request/effect identity, scope, freshness, consistency behavior, and
failure/timeout semantics. Missing or delayed readback is `unknown_incomplete`; no automatic retry or
replay. Unsupported classes use manual operator verification or external attestation, recorded as a
resolution—not as a controller-minted automated receipt.

### Alternatives

* **Manual-only:** safest and acceptable fallback; reduces automation.
* **Best-effort retry:** rejected for uncertain effects because the first request may have succeeded.
* **Generic “success” from transport/exit code:** rejected; it does not establish semantic state.

### Unresolved material decision/risk

Owner must choose initial effect classes and authoritative issuers. The first release may need to limit
trusted receipts to local, well-scoped artifacts while all remote/browser effects remain manual/external.

## DR-06 — Privacy, retention, diagnostics, and cryptography

### Recommended candidate: minimal protected receipt plus redacted local diagnostics

Receipts contain opaque IDs, relative paths or approved digests, structured state/reason, effect class,
policy/protocol/verifier generation, timestamps, and bounded redacted evidence. Absolute paths, raw
commands, full output, and secrets stay out of authoritative state and model-facing prompts by default.
Retention, purge, export, and operator access are explicit and tested. A failed purge or unreadable
diagnostic store must not become trusted success.

OS identity/ACL/process isolation is the primary boundary. Signatures/MACs may be added as defense in
depth after key custody, rotation, rollback, and root/Admin limitations are understood; they cannot
replace isolation.

### Alternatives

* **Rich local diagnostic retention:** useful for debugging but requires strict access, redaction,
  encryption-at-rest, expiry, and erasure policy.
* **Sign every receipt:** useful for transport/integrity, but adds key lifecycle and does not solve a
  compromised worker with key access or a privileged host.
* **No retained diagnostics:** privacy-minimal, but weakens operator resolution and post-crash review.

### Unresolved material decision/risk

Owner must select retention duration, operator roles, local export policy, redaction rules, and whether
raw tails are ever retained. No privacy risk is accepted by this candidate.

## DR-07 — Implementation release and promotion gates

### Recommended candidate: staged opt-in release with same-SHA native gates

The pure contract is implemented and tested first. Controller, executor, platform, receipt, surface,
and effect support are then enabled only behind explicit opt-in and capability checks. A candidate is
qualified only when the exact same source SHA passes native Linux and Windows security, containment,
crash/recovery, expiry, UI/gateway/ACP, privacy, and supported-effect tests. A skipped, timed-out,
environment-blocked, simulated-host, or manually waived lane is not PASS. Default-on requires a
separate future owner decision.

Rollback disables trusted mode, fences the verifier generation, invalidates its receipts, preserves
unknown attempts, and leaves manual/external fallback available.

### Alternatives

* **Manual/external-only release:** acceptable if native service qualification is not worth the
  operational burden.
* **Linux-only first release:** conflicts with DEC-005 and is not a qualified FHM-005 trusted release.
* **Default-on after local unit tests:** rejected; unit tests cannot establish native identity,
  containment, crash, or release behavior.

### Unresolved material decision/risk

Owner must approve CI runner availability, native service installation policy, artifact/evidence
retention, expiry and rerun rules, and separate default-on criteria. The release gate cannot be marked
complete from the existing Linux-only Phase 1 evidence.

## Decision discipline

The recommended options are engineering recommendations only. Implementation tasks may prepare pure
contracts and test scaffolding, but service identity, IPC, trusted receipts, and any trusted-success
claim remain gated until the owner resolves the material decisions above. See
[IMPLEMENTATION-MANIFEST.json](IMPLEMENTATION-MANIFEST.json) and [VALIDATION-PLAN.md](VALIDATION-PLAN.md).
