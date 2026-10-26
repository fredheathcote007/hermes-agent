# Project, objective and boundaries

project_id: fermes-hermes

## Objective
Build fully local, Hermes-owned memory with semantic, episodic, procedural and failure/lesson retention. Require provenance/confidence, deduplication and supersession, agent/profile isolation, efficient context retrieval, controlled consolidation/forgetting, backup/recovery, injection/poisoning resistance and measurable improved recall. Integrate later with FHM-006 compaction, FHM-008 SkillHone and FHM-009 SkillOpt-Sleep using explicit evaluation and approval gates before learned content becomes trusted instructions or skills.

## Owner-approved approach
- **DEC-004**: fork the entire Apache-2.0 ReMe engine to `fredheathcote007/fermes-reme`, adapt its embedded `MemoryProvider` as a Fermes Hermes plugin. Keep local Markdown/file memory and BM25 Stage 1; ReMe's existing facilities may remain, but defer additional SQLite or vector backend until the plugin is truly working.
- Hermes source stays based on maintained v0.22.5 fork. Isolate branches and preserve existing Qwen/LM Studio worktrees and draft PRs.
- The Hermes-native SQLite/FTS5 prototype in draft PR #19 is **deferred**, not the selected implementation; no mandatory Hindsight, external/cloud model or Project Coordinator service.
- ReMe Dream/proactive jobs remain **disabled**; FHM-006 durable checkpoint v2 is only a proposal and must not be enabled.
- FHM-007 GitHub Issue is the priority/acceptance backlog; versioned canonical Markdown and PR comments capture state and evidence. No competing independent tracker.

## Execution and change control
Use Codex with high reasoning for bounded implementation; use Cursor or an independent Codex reviewer. Close stdin `</dev/null`, use hard deadlines/log capture, confirm actual tests rather than relying on worker claims. GitHub Actions uses GitHub-hosted `ubuntu-24.04`, not stalled Blacksmith runners.

Do **not** merge to `main`, modify active Hermes, deploy to production, change Dad-PC network/firewall again, activate Dream, introduce new credentials, or change material memory/security/compaction trust contracts without evidence and approval. Use synthetic data and isolated test profiles. Preserve unrelated worktrees, no force-push/reset.
