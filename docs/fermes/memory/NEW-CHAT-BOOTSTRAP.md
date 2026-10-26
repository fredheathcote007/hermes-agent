# Resume Fermes Hermes in a New Chat
1. Project identity MUST be `project_id: fermes-hermes` and repository `fredheathcote007/hermes-agent`. Do not adopt memory for Ideas, Hermes/Hindsight or Project Coordinator.
2. Read this folder's `MEMORY-INDEX.md` **first**. Stop on mismatch.
3. Resolve workstream from `WORKSTREAMS.md`; for Qwen fixes use `workstreams/qwen-lmstudio/CURRENT-FOCUS.md`.
4. Read `PROJECT-STATE.md`, `CONSTRAINTS.md`, `OPEN-LOOPS.md`, then relevant decisions/evidence/lessons.
5. Check live GitHub Issues, branch/PR state and real worktree tests. Snapshot may be stale whenever the source SHA changes.
6. Work against isolated branches; use Codex implementation and independent review. Update the issue and minimal project-memory delta at each milestone.
7. Read `AGENT-EXECUTION-PROTOCOL.md` before invoking Codex, Cursor or another agent. Explicitly close stdin for bounded non-interactive processes and use isolated worktrees.
8. Qwen PRs #15/#18 were merged into compatibility branch at `25b6ab4c`, NOT into fork main. Read `workstreams/qwen-lmstudio/MERGE-CLOSURE.md`.
9. For current work select an OPEN issue from https://github.com/fredheathcote007/hermes-agent/issues; FHM-007 is separate memory-v2 PR #19; FHM-004 is merged (PR #20, source SHA 0bb167d1); FHM-005 remains P0 for independent delegated/external outcome verification.
