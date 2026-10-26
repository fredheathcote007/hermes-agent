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
