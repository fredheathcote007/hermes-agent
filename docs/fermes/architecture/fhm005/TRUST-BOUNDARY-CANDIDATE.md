# FHM-005 — Trusted verifier security boundary (candidate architecture)

project_id: fermes-hermes
status: PROPOSED — NOT APPROVED
related: DEC-004, DEC-005 (cross-platform scope), issue FHM-005
baseline: de83ce3b01fdc910a117e285a7acb72a98bf2841

## Context

The opt-in Phase 1 SQLite ledger records pending and verification observations, but process-local/user-profile-writable events do not establish an independent attestation boundary. The existing recipe runner executes project-authored shell commands under its own trust level. PRs #21/#22 do not implement a protected verifier or qualify Windows.

## Proposed target (conditional on DR-01 and remaining decisions)

1. The parent creates an immutable attempt and exact acceptance scope; the controller authenticates requests over local OS IPC. Worker-reported verdicts, root, session, command and receipt IDs are untrusted.
2. A minimally privileged controller is the only component authorised to mint and atomically consume protected verification receipts. The user-facing CLI/TUI/gateway status must derive from this authoritative result, not model prose.
3. Project-defined checks execute only in a constrained, disposable lower-trust runner with no controller credentials or receipt-storage access. No arbitrary shell command runs under a privileged service identity.
4. After execution has fully quiesced, the controller independently validates scope, root/artifact object identity, version/content digests, policy generation, authorized read-back, attempt nonce, time/freshness, and terminal executor state.
5. A protected receipt binds parent authority, attempt, policy version, scoped artifact set/generation and proof; it is consumed exactly once using atomic compare-and-swap. Failed/missing/foreign/stale/ambiguous receipts yield INCOMPLETE or UNAVAILABLE.
6. No automatic retry or replay of uncertain external effects. Unsupported arbitrary SaaS/browser effects require an explicit, authoritative provider readback or operator resolution.
7. Local installation on Linux/Windows must enforce separate service identity, protected IPC and storage, bound process containment, and safe rollback. No service fallback to same-user/interactive execution counts as trusted mode.

## Proposed operating-system adapters (research required)

- Linux: system-owned service with non-login service identity, protected state directory and Unix-domain socket peer authentication. Validate actual systemd sandbox/cgroup behaviour on target kernels; do not assume per-user units provide equivalent isolation.
- Windows: Windows Service Control Manager identity/service SID, explicit named-pipe DACL and token checks, protected receipt ACLs, and Job Objects with kill-on-close. No Startup-folder fallback, and no unchecked inherited privileges.
- In both cases: installation may require administrator elevation, but normal runtime must not. Local root/Administrator compromise is *not* currently approved as in scope or out of scope; DR-01 must resolve that.

## Alternatives

- **Manual operator / externally attested CI only:** safest simpler alternative with low operational complexity, but no general automated independent local completion.
- **Privileged standalone service directly running existing recipes:** REJECT, because untrusted project-authored code inherits trusted identity and becomes a confused deputy.
- **Hardware-backed / remote attestation:** DEFER pending an explicit owner threat-model requirement; cost and installation complexity far greater.

## Consequences and open gates

Potential new local service/installer/IPC attack surface. Strict Linux and Windows test matrix, privacy policy, no-secret egress, configuration upgrades, rollback, and human-visible status semantics must be designed and independently qualified. No default-on and no production deployment authorised. This is a draft ADR, not an accepted design.
