# Fermes Hermes — Project State

project_id: fermes-hermes
Updated: 2026-10-26 Australia/Perth

## Current authoritative state

- **Fork:** https://github.com/fredheathcote007/hermes-agent
- **Maintained Qwen/LM Studio v0.22.5 compatibility branch:** `fermes/qwen-lmstudio-v0225-20261026`, merged head `25b6ab4c60b5d61626b78310b4bf1a9c7253521f`.
- **Official upstream baseline:** `NousResearch/hermes-agent` `v0.22.5`, commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`. Follow `docs/fermes/UPSTREAM-SYNC.md` for deliberate upstream updates.
- **Fork PR #15:** MERGED 2026-10-26, merge `01c6b375970b6fd23aa12fd0b3c90de395d896f8` (alias/LM Studio reasoning, auxiliary retry routes, credential and vision fallback hardening).
- **Fork PR #18:** MERGED 2026-10-26, merge `25b6ab4c60b5d61626b78310b4bf1a9c7253521f` (bounded malformed Qwen tool-call recovery, no raw-text execution).
- **Main and production:** `main` remained at `0e427d788d253630d38a3a51cd76849e73cd6925` when the PRs were merged. NO production Hermes deployment; this merge did not promote to `main`.
- **Code equivalence:** `git diff` between validated PR #18 head `b3c1ff75e78ce763452d4caa78bd24b2ccc3ceff` and postmerge head `25b6ab4c` returned no changed files. The final merge creates a recorded merge commit without changing the tested source tree.

## Validation and outcome

- 668 combined auxiliary/Qwen/reasoning/finalisation regression tests passed on final PR #18 code; 341 route/credential/vision targeted tests passed, with independent Cursor reviewer finding no P0/P1.
- 44 stop/verification tests and 56 session-persistence/recovery tests passed after isolating the test TMPDIR. A previously red verification test was environment contamination from an unrelated `/tmp/.git`, not a Qwen PR regression.
- Dad-PC WSL Ubuntu isolated Hermes runtime → LM Studio localhost-only `127.0.0.1:1234` → Qwen `qwen96k-nomtp` (98,304 context) passed actual tool execution, tool-result transcript, final response, answer-only response, malformed-call corrective retry, and bounded retry exhaustion.
- GitHub-hosted Python/Ruff CI green on final heads PR #15 `26f9ea19` and PR #18 `b3c1ff75`. No local runner or model endpoint LAN exposure was needed.
- Independent review was conducted for the combined source and credential/vision hardening; no P0/P1 findings remained for these PRs.
- Full source/evidence details: `workstreams/qwen-lmstudio/MERGE-CLOSURE.md` and GitHub Issue comments.

## Closed and continuing work

- FHM-001, FHM-002, FHM-013, FHM-014, FHM-015: CLOSED completed with evidence after PR merges.
- FHM-016: CLOSED completed (GitHub-hosted runner CI fix).
- FHM-003: instruction/launcher procedure rather than a Hermes runtime defect; operating format is in `AGENT-EXECUTION-PROTOCOL.md`; GitHub Issue closure status is the authority.
- Continuing: FHM-004 bounded stop/recovery, FHM-005 independent verification, FHM-006 compaction, FHM-007 Hermes-owned Local Memory v2, FHM-008 SkillHone, FHM-009 SkillOpt, FHM-010 evaluation, FHM-011 upstream compatibility and FHM-012 code harvesting. Query live Issues before changing state.
- FHM-007 is a **separate active workstream**, draft fork PR #19. Do not overwrite, reset, rebase or silently modify its branch/worktree.

## Next engineering action

Preserve the validated compatibility branch. Qualify the next stable upstream release in an isolated update worktree under FHM-011, test Qwen regression gates before adoption and avoid automatically updating a production installation. Continue FHM-007 independently; no Project Coordinator service dependency is introduced.
