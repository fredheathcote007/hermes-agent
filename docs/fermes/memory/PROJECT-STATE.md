# Project State
project_id: fermes-hermes
Updated: 2026-10-26 Australia/Perth

## BLUF
Goal: maintain an upstream-syncable fork of Hermes with dependable local Qwen/LM Studio execution and eventually native self-learning, memory, compaction and validation-gated self-optimisation.
Owner fork: `fredheathcote007/hermes-agent`.
Current *proven* v0.22.5 code baseline: `fee4b6a0df4947e154fcb81a5d7f5ea67459c4d1` on `fermes/qwen-lmstudio-v0225-20261026`, derived from upstream `bf0203a794a07aac3ff764972ab9087baa4e4f4e` (`v0.22.5`).
Live end-to-end Hermes/Qwen and third draft auxiliary retry fix are NOT yet accepted.

## Evidence and status
- Fixes ported: `26decd20` LM Studio loaded-instance alias metadata; `7d879727` failed LM Studio probe caching; `fee4b6a0` v0.22.5 reasoning probe adaptation and test changes.
- 65 focused tests and 142 adjacent routing/credential/retry tests passed on Linux source checkout (2026-10-26); Ruff and git diff checks passed. This is not live Hermes runtime acceptance.
- Dad-PC LM Studio Qwen loaded instance `qwen96k-nomtp`, context 98,304, native direct tool call returned API `tool_calls` with correct arguments. Does not prove Hermes agent loop.
- Third draft fix candidate: historical commit `7dbfcf5a7d3c269cb59de840de13aa466449c2ab`, route-identity preservation. Draft port branch `fermes/auxiliary-retry-v0225-20261026` pending completion and review.
- Official upstream remains `NousResearch/hermes-agent`; fork remote for pushes; update procedure `docs/fermes/UPSTREAM-SYNC.md`.
- Repository GitHub Issues enabled 2026-10-26 and backlog FHM-001 to FHM-012 created.
- No production Hermes install has been changed by the fork work.
