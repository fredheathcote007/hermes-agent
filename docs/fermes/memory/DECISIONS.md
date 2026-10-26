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

## Proposed decisions — not approved

### FHM-007-PD-001 — Keep the memory-v2 ledger independent during architecture review

Scope: FHM-007 Phase 1/2
Status: Proposed; owner/ARB approval required
Date: 2026-10-26
Proposal: Use a profile-local SQLite/FTS5 ledger with an explicit agent namespace, immutable
revisions, provenance/confidence metadata, and explicit relation edges. Do not route existing memory
writes, alter `state.db`, add dependencies, or rebuild prompts until the adapter and FHM-006 checkpoint
contract are approved.
Evidence: `docs/fermes/memory/workstreams/memory-v2/ARCHITECTURE-AND-GAPS.md`,
`agent/memory_v2_store.py`, six focused behavior tests.
Decision gate: Owner/ARB review of profile/agent authorization, governed writes, PII/retention,
checkpoint coupling, and backup/restore policy.

### FHM-007-PD-002 — Selective reuse rather than wholesale upstream replacement

Scope: FHM-007 local memory v2
Status: Proposed; owner/ARB approval required before runtime integration
Date: 2026-10-26
Proposal: Preserve the Hermes MemoryProvider/MemoryManager, profile enforcement, write-governance and FHM-006 checkpoint seams. Treat the native profile-local SQLite/FTS5 ledger as the proposed authoritative storage foundation, subject to independent P1 remediation and objective retrieval/durability tests. Study ReMe embedded and memU local as offline comparators; harvest proven algorithms and patterns from open-source projects under verified licences/attribution. Do not install ReMe, memU, Mem0, Letta, LangMem, Graphiti or Memvid wholesale in the active runtime.
Evidence: `docs/fermes/memory/workstreams/memory-v2/EXTERNAL-CODE-AUDIT.md` and `INDEPENDENT-CODE-REVIEW.md`; GitHub FHM-007; canonical host 6/6 test result. LangMem is MIT; other surveyed primary projects are Apache-2.0, subject to per-component notices.
Decision gate: Owner/ARB selection of runtime architecture, profile and agent boundaries, governed writes/provenance, PII and retention, FHM-006 checkpoint coupling. Do not treat this proposal as approval or an E2E qualification.
