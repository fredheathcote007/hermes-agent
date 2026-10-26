# Current Focus
project_id: fermes-hermes
workstream_id: qwen-lmstudio
workstream_name: Qwen / LM Studio fork compatibility
Updated: 2026-10-26 Australia/Perth

## Current objective
Apply and qualify the third historical auxiliary retry-route fix after the initial two ported LM Studio/Qwen fixes while retaining an upstream-syncable Hermes v0.22.5 fork.

## Where we are now
- Fork owner `fredheathcote007`, qualified source branch `fermes/qwen-lmstudio-v0225-20261026` at `fee4b6a0`.
- Third-fix candidate original commit `7dbfcf5a7d` on historical `fix/qwen-reasoning-wire-20261021` worktree.
- Isolated third-fix development branch `fermes/auxiliary-retry-v0225-20261026`; local worktree `/srv/project-coordinator/projects/fermes-hermes-aux-retry-20261026`. This is a host storage path only; Project Coordinator is NOT a dependency or project focus.
- Third fix source port is committed and pushed as `24840479`, draft fork PR #15; 518 source-level host tests and GitHub Actions 40289753454 PASS, no merge to main or live E2E.
- Combined Qwen/GLM tool-call recovery from upstream #139986/#129445/#135120 in draft fork PR #18, change commit `e1541755` on `fermes/toolcall-recovery-v0225-20261026`. 140 host tests PASS, second Cursor independent review no P0, GitHub Actions 40290526021 PASS.
- GitHub runner issue FHM-016 fixed: hosted runner with pinned Python/uv, Ruff, relevant pytest; no self-hosted runner registered or needed.
- GitHub Issues are enabled; FHM-001 to FHM-016 exist. FHM-016 closed; FHM-015 open for source PR #18 and follow-on live qualification.
- Direct LM Studio model call confirms native tool_calls, but real Hermes integration test outstanding.

## Immediate next action
Query live GitHub PR #15 and PR #18 plus issues FHM-001, FHM-002, FHM-015. Re-check current CI/merge state and the exact branch SHA. Next required step is isolated real Hermes→LM Studio→Qwen tool execution, answer-only finalisation and bounded recovery, without changing active Hermes/production or exposing LM Studio to the LAN. Review current upstream changes and harden any remaining P1 cases before promotion. Do not merge to main merely on source-level tests.

## Stop/decision gate
No false success claims; no production deployment; preserve other worktrees and baseline. No auto-update on moving upstream main. Do not restart Qwen evaluation without validating endpoint binding and model availability.

## Continuity
The first two fixes, plus the v0.22.5 reasoning adaptation, are already in fork. The third fix is about **auxiliary route identity, API transport and credential scope across retry/fallback**, not another alias lookup patch.
