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
