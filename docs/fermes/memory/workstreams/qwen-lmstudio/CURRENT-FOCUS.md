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
- Third fix source port committed as `24840479` and pushed; fork draft PR #15 opened targeting compatibility branch. The port branch later merged project-memory documentation. Full live Hermes/Qwen E2E remains unverified.
- GitHub Issues are enabled; FHM-001 through FHM-014 exist, with FHM-013 and FHM-014 recording residual reviewer P1 concerns.
- Direct LM Studio model call confirms native tool_calls, but real Hermes integration test outstanding.

## Immediate next action
Query GitHub issue #1 and fork draft PR #15. Confirm CI status and decide whether to close FHM-013/FHM-014 before integrating source changes into the compatibility baseline. Then perform isolated live Hermes -> LM Studio -> Qwen end-to-end acceptance under FHM-002. Do not merge into main or deploy without relevant gates.

## Stop/decision gate
No false success claims; no production deployment; preserve other worktrees and baseline. No auto-update on moving upstream main. Do not restart Qwen evaluation without validating endpoint binding and model availability.

## Continuity
The first two fixes, plus the v0.22.5 reasoning adaptation, are already in fork. The third fix is about **auxiliary route identity, API transport and credential scope across retry/fallback**, not another alias lookup patch.
