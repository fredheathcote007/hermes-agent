# Approved decisions
project_id: fermes-hermes

## DEC-001 — Maintain a fork and pull upstream deliberately
Scope: Project-wide
Status: Approved decision
Date: 2026-10-26
Decision: Preserve `NousResearch/hermes-agent` as upstream; maintain own fork and qualified local branches. Avoid unattended upstream updates to patched runtime.
Evidence: User request, fork branch and `docs/fermes/UPSTREAM-SYNC.md`.
Reconsider only if upstream maintenance compatibility becomes untenable.

## DEC-002 — GitHub is the central backlog and project-continuity store
Scope: Project-wide
Status: Approved implementation direction
Date: 2026-10-26
Decision: Use GitHub Issues for live work/acceptance; versioned Markdown in fork for state, decisions and handoff. No mandatory Google Drive. Avoid two independently maintained trackers.
Evidence: User requested durable issue list; GitHub Issues enabled and 12 initial issues opened.
Reconsider only if repository ownership or access strategy changes.

## DEC-003 — Goal is self-learning and self-optimising Hermes, local-first
Scope: Project-wide
Status: Approved direction
Date: 2026-10-26
Decision: Harvest selected open-source code and patterns for native memory, context and skills. External Hindsight/other services not required. Keep compaction history recoverable and candidate skill changes gated by evidence.
Evidence: Current chat requirements; FHM-006 to FHM-012.

## DEC-004 — Fail closed on unverified delegated outcomes
Scope: FHM-005 / delegated worker and code-change verification
Status: Owner approved policy; implementation qualification pending
Date: 2026-10-26
Decision: Hermes must not report delegated or external work complete merely because a worker reported success or a gateway admission reached TERMINAL. Missing, failed, stale, untrusted or unobservable proof means BLOCKED/INCOMPLETE, never completed=true. Parent must select/execute independent checks matched to each action and its acceptance criteria; prose-only tasks must not be forced through code test suites. Bounded retries may stop work but must never convert missing verification into success. No automatic replay of uncertain external side effects.
Evidence: User explicitly approved 'fail closed' after review of FHM-005; issue #5 and FHM-004 merge tests.
Implementation boundary: Phase-one opt-in verify-on-stop hardening is not complete independent verification. Trusted verifier execution, durable proof, scope and authority contracts require architecture assurance and operational tests before promotion/default-on. Never claim generic external side-effect verification from a code-test receipt.


## DEC-005 — Linux and Windows trusted-verifier scope
Scope: FHM-005 trusted-verifier release qualification
Status: Owner-approved platform scope; architecture decision pending
Date: 2026-10-27 (Australia/Perth)
Decision: The first qualified trusted-verifier capability must support and pass native security and operational acceptance on both Linux and Windows. Neither platform may be skipped or treated as equivalent solely through simulations. This does not approve the implementation architecture, trusted-verifier identity/IPC design, deployment, default-on promotion or acceptance of local privileged attacker risk.
Evidence: Owner expressly approved Option B and requested the Full FHM-005 Architecture Review Board. Candidate review: `docs/fermes/architecture/fhm005/ARB-REVIEW-20261027.md`.


## DEC-006 — Trusted-verifier local attacker boundary and fallback
Scope: FHM-005 / ARB DR-01
Status: Owner-approved threat scope and fallback policy; detailed architecture unapproved
Date: 2026-10-27 (Australia/Perth)
Decision: Protect against compromised/malicious delegated workers and unprivileged local processes by enforcing a separate restricted execution context and protected verifier/controller authority. One-time elevated installation is permitted. Compromise of local root/Administrator or an equivalently privileged principal is outside the initial assurance guarantee. When independent automated verification is unavailable, fall back to manual operator verification or externally attested verification; do not manufacture a trusted success verdict and preserve DEC-004 fail closed. This does not waive native Linux and Windows qualification required by DEC-005.
Evidence: User explicitly agreed, “Approve Option A, with Option B retained as the fallback when independent verification is unavailable.”
Not approved by this decision: controller implementation/language, IPC/authentication mechanism, receipt crypto, process isolation tooling, external effects proof, installation or deployment, merging PRs, default-on, accepting outstanding High/Critical risks. These remain DR-02 to DR-07.
