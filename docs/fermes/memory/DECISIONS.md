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

## DEC-004 — Full ReMe fork first for FHM-007 memory provider
Scope: FHM-007, FHM-006, FHM-008 and FHM-009 integration
Status: Owner-approved implementation direction (not production acceptance)
Date: 2026-10-26
Decision: Fork the complete Apache-2.0 ReMe repository as fredheathcote007/fermes-reme and first qualify its existing embedded Hermes MemoryProvider plugin against the maintained Hermes v0.22.5 fork. Preserve ReMe's native file-based memory, BM25 and existing capability in Stage 1. Repair specific proven compatibility, queue, concurrency, isolation, prompt-injection, write-approval and crash/recovery deficiencies in the fork. Defer integrating the separate Hermes SQLite ledger and adding/changing vector storage until the working fork-plugin baseline is demonstrated, then reassess on evidence. Do not require Project Coordinator, Hindsight, a remote service, or cloud credentials. Future SkillHone and SkillOpt-Sleep must consume source-bound candidate memories, failures/lessons and evaluation evidence through a stable boundary. Keep existing Hermes memory unchanged until acceptance and deployment approval.
Evidence: Explicit owner direction; agentscope-ai/ReMe upstream commit 363e497; source audit and independent review in memory-v2 workstream; live fork at https://github.com/fredheathcote007/fermes-reme.
Supersedes FHM-007-PD-002 as the current Stage 1 implementation path; does not invalidate its recorded architecture research. Current Hermes SQLite prototype PR #19 stays draft/deferred; do not merge into main.

## DEC-005 — GitHub-hosted CI for Fermes fork PRs
Scope: FHM-007 GitHub Actions
Status: Owner-approved correction
Date: 2026-10-26
Decision: For FHM-007 PR validation, do not schedule Blacksmith runners that remain queued. Disable inherited CI/Docker/Nix pull_request triggers on this isolated workstream and use a dedicated secret-free GitHub-hosted ubuntu-24.04 workflow for bounded tests. This reproduces the previously successful Fermes Fork CI workaround but pins the OS version because ubuntu-latest is migrating to Ubuntu 26.04 in October-November 2026. Preserve upstream release-only workflows. Do not weaken acceptance gates silently; document skipped inherited checks.
Evidence: PR #19 queued workflows, GitHub runner reference, previous Fermes fork workflow fermes-pr-checks.yml.

## DEC-006 — FHM-007 crash-safe deterministic memory commit (Option B)
Scope: FHM-007 ReMe Stage 1 crash/replay integrity
Status: Owner-approved ARCHITECTURE BASELINE; detailed security design and validation are mandatory, not implementation acceptance
Date: 2026-10-27 (Australia/Perth)
Decision: Select Option B from docs/fermes/FHM007-CRASH-IDEMPOTENCY-PROPOSAL.md. Preserve the full ReMe fork's file/BM25 engine while separating model-generated memory proposals from an application-authorised deterministic durable commit. Commit must bind request ID/fingerprint, actual source transcript hash, profile/agent/session and note ownership, and a server-controlled commit marker; replays must recognise committed effects without a second model mutation, and ambiguous or unverifiable outcomes fail closed. Treat only as effectively-once within a defined supported-filesystem fault model, never distributed exactly-once. Require independent detailed security review, SIGKILL/fault injection, CI matrix, real Qwen capture/retrieval, and separate FHM-006 checkpoint v2 design approval. No main merge, deployment, active Hermes change or relaxation of gates authorised.
Evidence: Explicit owner approval in 2026-10-27 continuation; SIGKILL red test 5bbeabf; design candidate 942381f; ReMe draft PR #1. Revisit only when security review reveals a material defect or new owner decision is necessary.

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
