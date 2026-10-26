# FHM-007 — Current Focus

project_id: fermes-hermes
issue: https://github.com/fredheathcote007/hermes-agent/issues/7
workstream_id: memory-v2
status: Full ReMe fork Stage 1 selected; plugin qualification pending
updated: 2026-10-26 Australia/Perth

## Approved implementation direction

DEC-004 supersedes the previous native-first proposal. Full ReMe fork:
https://github.com/fredheathcote007/fermes-reme
Stage 1 local branch: fermes/hermes-provider-stage1
Upstream source baseline: agentscope-ai/ReMe 363e497
Initial mode: ReMe embedded Hermes MemoryProvider with existing file store/BM25,
no mandatory cloud/service dependency. Existing vector functionality is not deleted;
additional/revised SQLite/vector implementation is explicitly deferred.

Existing Hermes SQLite/FTS5 ledger in draft PR #19 remains an unwired,
unmerged, independently reviewed reference. Do not activate or merge it.
Maintain Hermes provider and profile boundaries; preserve Qwen/LM Studio worktrees.

## CI recovery

FHM-007 PR #19 inherited CI, Docker and Nix runs were queued/pending on
unavailable Blacksmith runner labels. Previous Fermes fix: disable their PR
triggers and provide a GitHub-hosted lightweight workflow. Current FHM-007
workflow uses explicitly pinned ubuntu-24.04 because ubuntu-latest is
migrating to Ubuntu 26.04 during 2026-10-19 to 2026-11-19.
Validate new PR run and document conclusion before claiming recovered CI.

## Stage 1 next action

1. Verify fork's Hermes embedded provider against local Hermes v0.22.5 and
   project plugin loader with isolated, disposable HERMES_HOME/workspace.
2. Preserve local-only operation, source provenance and per-profile separation.
3. Reproduce or rule out upstream ReMe known issues #660/#661/#666/#673
   including hangs, interrupted batches, corrected transcripts and vector NaNs.
4. Implement bounded fork fixes only after discriminating tests. Do not
   introduce SQLite/vector replacement until plug-in functionality qualifies.
5. Prove capture across sessions, correct recall, crash/restart, no lost
   approved writes, injection resistance, cancellation and backup/recovery.
6. Expose stable candidate-memory/lesson hooks for future SkillHone and
   SkillOpt-Sleep, without permitting model-generated skill mutation.

Acceptance: No active Hermes deploy or main merge without independent review,
documented acceptance evidence and owner approval. FHM-007 remains OPEN P1.
