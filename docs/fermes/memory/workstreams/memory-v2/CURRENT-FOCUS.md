# FHM-007 — Current Focus

project_id: fermes-hermes
project_name: Fermes Hermes
workstream_id: memory-v2
workstream_name: FHM-007 ReMe-backed local memory v2
priority: P1
last_updated: 2026-11-10 (Australia/Perth)
status: Stage 2B OPEN / NOT ACCEPTED; broader FHM-007 OPEN
classification: current tracking focus, not runtime acceptance

## Current objective

Deliver the **original** FHM-007 scope: local-first semantic, episodic, procedural and failure memory with attributable sources, scoped identity, governed change history, conflict handling, reliable retrieval, crash recovery, compaction and backup/rollback. This is **not a new roadmap** or new architecture selection.

Canonical tracking: [Hermes #7](https://github.com/fredheathcote007/hermes-agent/issues/7). Deferred original-roadmap mapping: [Hermes #66](https://github.com/fredheathcote007/hermes-agent/issues/66). Active Stage 2B defect/acceptance: [fermes-reme #17](https://github.com/fredheathcote007/fermes-reme/issues/17), related [#16](https://github.com/fredheathcote007/fermes-reme/issues/16).

## Where we are now

- **Approved architecture:** DEC-004 chooses full ReMe fork and embedded Hermes MemoryProvider with local file-backed store + BM25; SQLite-first prototype in [Hermes draft PR #19](https://github.com/fredheathcote007/hermes-agent/pull/19) is historical/deferred. DEC-006 adds application-owned, scoped, deterministic protected commit/recovery. Neither cancels original FHM-007 capabilities.
- **Proven source progress, not full acceptance:** ReMe Option B and durable FIFO/recovery [PR #13](https://github.com/fredheathcote007/fermes-reme/pull/13) merged 5 November; lifecycle and queue [PR #19](https://github.com/fredheathcote007/fermes-reme/pull/19) merged 10 November. Earlier isolated genuine-model note/restart/BM25 recall has passed, but a second live-model case durably committed a placeholder instead of the requested fact.
- **Active blocker:** Stage 2B explicit, application-owned **no-op versus retention-required** semantics, bounded refusal/retry/quarantine and truthful receipts/FIFO. The merged Stage 2A code is not Stage 2B acceptance; production activation is **NO-GO** until independently accepted.
- **Deferred capabilities:** typed semantic/episodic/procedural/failure extraction, governed revisions/contradictions, complete source authority, graded retrieval and fully qualified FHM-006 compaction and operations. FHM-008 SkillHone and FHM-009 SkillOpt are separate downstream workstreams; FHM-010 supplies versioned test corpus/metrics.

## What we are concentrating on — and why

**Now:** complete the existing Stage 2B track through its current assigned supervisor/implementation/review workflow. Do not duplicate an active Codex worker, reset the stage, start architectural redesign or divert attention into upstream contributions. The trusted memory foundation must avoid false durable success and FIFO starvation before richer memory types can safely depend on it.

**Later, only after explicit Stage 2B acceptance:** resume #66 beginning with Phase A design, source/decision freshness review and independent challenge. Define the FHM-010 graded corpus and success thresholds *in Phase A*; validate throughout later phases, not only at final qualification.

## Immediate next action

Continue the **existing** [fermes-reme #17](https://github.com/fredheathcote007/fermes-reme/issues/17) workstream from its live source/evidence and review state; verify whether Stage 2B has an approved contract, exact-head tests, native Windows, live-model proof, independent acceptance and explicit owner go-ahead. If missing, work only on those agreed Stage 2B gaps. Keep original Hermes #7 open; keep deferred #66 inactive.

## Decision / stop gate

Stage 2B is complete only on actual acceptance evidence and owner approval, not on Stage 2A merge, test counts or a green PR. Phase A can start after that gate; Phase B source changes require separate reviewed design and authorisation. No unreviewed migrations, new frameworks, production profile changes, deployments or merges.

## Evidence / freshness

Observed 10 November 2026 from Hermes #7, #66, existing DEC-003/004/006, ReMe #16/#17, merged PRs #13/#19, and the original [implementation plan](https://github.com/fredheathcote007/hermes-agent/blob/fermes/memory-v2-fhm007-20261026/docs/fermes/memory/workstreams/memory-v2/IMPLEMENTATION-PLAN.md). This supersedes the dated operational next actions in [historical focus snapshot](HISTORICAL-FOCUS-TO-20261027.md). Exact local Stage 2B source commit and test status must be refreshed from its live worktree before implementation; GitHub Issue #17 comments after 7 November do not establish Stage 2B acceptance.
