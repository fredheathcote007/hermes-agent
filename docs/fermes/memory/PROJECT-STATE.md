# Project State
project_id: fermes-hermes
Updated: 2026-10-26 Australia/Perth

## BLUF
Goal: maintain an upstream-syncable fork of Hermes with dependable local Qwen/LM Studio execution and eventually native self-learning, memory, compaction and validation-gated self-optimisation.
Owner fork: `fredheathcote007/hermes-agent`.
Current *proven* v0.22.5 code baseline: `fee4b6a0df4947e154fcb81a5d7f5ea67459c4d1` on `fermes/qwen-lmstudio-v0225-20261026`, derived from upstream `bf0203a794a07aac3ff764972ab9087baa4e4f4e` (`v0.22.5`).
The three original Qwen/LM Studio fixes and coordinated malformed tool-call recovery have passed source tests on separate fork branches. Full live Hermes/Qwen E2E acceptance remains UNVERIFIED (FHM-002).

## Evidence and status
- Fixes ported: `26decd20` LM Studio loaded-instance alias metadata; `7d879727` failed LM Studio probe caching; `fee4b6a0` v0.22.5 reasoning probe adaptation and test changes.
- 65 focused tests and 142 adjacent routing/credential/retry tests passed on Linux source checkout (2026-10-26); Ruff and git diff checks passed. This is not live Hermes runtime acceptance.
- Dad-PC LM Studio Qwen loaded instance `qwen96k-nomtp`, context 98,304, native direct tool call returned API `tool_calls` with correct arguments. Does not prove Hermes agent loop.
- Third fix: upstream draft PR #142395 ported as `24840479`, fork draft PR #15; 518 host source tests PASS and GitHub-hosted CI PASS (run 40289753454); no deployment or main merge.
- Recovery: upstream PRs #139986/#129445/#135120 selectively adapted as `e1541755`, fork draft PR #18; 140 host tests PASS, Cursor second review no P0, GitHub-hosted CI PASS (run 40290526021). Three previously failing synthetic model-format cases recovered without executing raw markup.
- Official upstream remains `NousResearch/hermes-agent`; fork remote for pushes; update procedure `docs/fermes/UPSTREAM-SYNC.md`.
- GitHub issue register through FHM-016 is active: FHM-016 (fork runner repair) CLOSED after hosted CI success; FHM-015 recovery source patch in draft PR #18; FHM-002 live Hermes/Qwen E2E remains OPEN.
- Independent third-fix review retained P1 follow-ups FHM-013 (named custom-provider credential scope) and FHM-014 (vision auto fallback).
- 2026-10-26 pre-merge scratch included current compatibility base e0bb2a82 + PR #15 + PR #18: 518 auxiliary/provider tests PASS, 140 tool/reasoning tests PASS, 124 additional executions PASS / 4 SKIP (some overlap); Ruff PASS; independent Cursor source review no P0. Real Hermes E2E remains unverified.
- Live Dad-PC LM Studio Qwen `qwen96k-nomtp` responded READY on no-tools request and returned native `add_numbers(a=3,b=5)` structured tool_calls. This is direct API smoke, not Hermes E2E. LM Studio server restored to stopped status.
- No production Hermes install has been changed by the fork work.
