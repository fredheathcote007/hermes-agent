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
- Third fix still needs final acceptance/commit/push unless issue #1 evidence explicitly proves otherwise.
- GitHub Issues are now enabled and issue #1 through #12 exist.
- Direct LM Studio model call confirms native tool_calls, but real Hermes integration test outstanding.

## Immediate next action
Query issue #1, the third-fix branch, the Codex output `/tmp/fermes-thirdfix-codex.log`, and live test evidence. Complete focused and broader regression verification, independent review, then commit/push isolated third-fix branch; update issue #1. Do not merge into main until acceptance gates pass.

## Stop/decision gate
No false success claims; no production deployment; preserve other worktrees and baseline. No auto-update on moving upstream main. Do not restart Qwen evaluation without validating endpoint binding and model availability.

## Continuity
The first two fixes, plus the v0.22.5 reasoning adaptation, are already in fork. The third fix is about **auxiliary route identity, API transport and credential scope across retry/fallback**, not another alias lookup patch.
