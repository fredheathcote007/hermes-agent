# Project State
project_id: fermes-hermes
Updated: 2026-10-27 Australia/Perth

## BLUF
Goal: maintain an upstream-syncable fork of Hermes with dependable local Qwen/LM Studio execution and eventually native self-learning, memory, compaction and validation-gated self-optimisation.
Owner fork: `fredheathcote007/hermes-agent`.
Current *proven* v0.22.5 code baseline: `fee4b6a0df4947e154fcb81a5d7f5ea67459c4d1` on `fermes/qwen-lmstudio-v0225-20261026`, derived from upstream `bf0203a794a07aac3ff764972ab9087baa4e4f4e` (`v0.22.5`).
The third auxiliary draft has been ported and accepted at the source-test level on a separate draft PR; full live Hermes/Qwen end-to-end acceptance remains UNVERIFIED.

## Evidence and status
- Fixes ported: `26decd20` LM Studio loaded-instance alias metadata; `7d879727` failed LM Studio probe caching; `fee4b6a0` v0.22.5 reasoning probe adaptation and test changes.
- 65 focused tests and 142 adjacent routing/credential/retry tests passed on Linux source checkout (2026-10-26); Ruff and git diff checks passed. This is not live Hermes runtime acceptance.
- Dad-PC LM Studio Qwen loaded instance `qwen96k-nomtp`, context 98,304, native direct tool call returned API `tool_calls` with correct arguments. Does not prove Hermes agent loop.
- Third draft was confirmed as upstream PR #142395, stacked on #142393. V0.22.5 port patch commit `24840479`, draft fork PR #15 targeting the compatibility branch, 518 host tests PASS; independent Cursor source review found no P0 block. P1 followups FHM-013 and FHM-014 open.
- Official upstream remains `NousResearch/hermes-agent`; fork remote for pushes; update procedure `docs/fermes/UPSTREAM-SYNC.md`.
- Repository GitHub Issues enabled 2026-10-26 and backlog FHM-001 to FHM-014 created.
- No production Hermes install has been changed by the fork work.
## FHM-007 status update — 2026-10-27 Australia/Perth
- ReMe fork PR #1 remains DRAFT; exact published commit `4463d20` has 8/8 GitHub workflows PASS, including Python 3.11–3.14. This proves CI compatibility, NOT crash safety or production acceptance.
- DEC-006 owner-approved Option B deterministic application-owned memory commit as architecture baseline **subject to detailed security design, fault injection and independent review**. Existing unreceipted note mutation can duplicate content after SIGKILL. Cursor adversarial review documents current 4 P0 / 6 P1 risks.
- Isolated Option B worktree `fermes-reme-fhm007-optionb-20261027` based on 4463d20 with crash regression commit 0348b47. Codex review/implementation in progress; no deployment or merge authorised.
- FHM-006 pre-compression checkpoint v2 remains separately unapproved and disabled. Protect all original worktrees; keep PR #1 draft until new exact-head CI, crash recovery and real Qwen testing pass.
- HISTORICAL RED reproduction, superseded by later checkpoint: Option B initially failed after-note/pre-receipt replay and grew the transcript; see E-033. Do not treat this as current candidate status.
## FHM-007 latest checkpoint — 2026-10-27 11:34 AWST
- ReMe Stage 1 draft PR #1 remains at `4463d20`, 8/8 workflows PASS; separate Option B stacked **draft PR #2** https://github.com/fredheathcote007/fermes-reme/pull/2 is published at `02ad65ef2f63bfc9dc6d86bb72de31988eb1d98c`, based on `fermes/hermes-provider-stage1`; worktree `fermes-reme-fhm007-optionb-20261027` clean. No force-push, merge or deployment.
- DEC-006 approved Option B as architecture baseline only. Durable application-owned note/marker/receipt commit, recovery BEFORE transcript append, and distinct-request supersession are implemented in isolated draft. Protected request-ID and scope fail closed; stage1 tagging stays disabled. Legacy non-opted-in behaviour is preserved.
- Fresh host validation exact source: **147 focused regressions PASS** (`/tmp/fhm007/optionb-p1-final-focused-20261027.log`); **3 SIGKILL crash windows PASS** (`/tmp/fhm007/optionb-p1-final-sigkill-20261027.log`); **16 atomic/digest tests PASS** (`/tmp/fhm007/optionb-supervisor-atomic-digest-tests.log`); Black, targeted Ruff, compile and diff checks PASS.
- Synthetic live Qwen 3.5 4B using explicit custom-config opt-in wrote memory and receipt, emptied pending queue. First immediate restarted recall returned empty; a subsequent fresh restart BM25 retrieved stored codephrase/colour. Readiness timing remains an acceptance gap (do not claim first immediate recall PASS).
- Cursor independent review `optionb-cursor-retry-short.log` and `optionb-cursor-p1-final-review.log`: **GO for DRAFT only**, no P0 in qualified embedded path; follow-ups: non-AgentScope direct-opt-in bypass, hosted atomic-write test coverage, deterministic retrieval readiness, broader security/operational acceptance. FHM-006 checkpoint v2 remains separately unapproved/disabled.
- GitHub workflow runs at published PR #2 SHA: Stage1 `40444770674`, Python tests `40444799796`, Python quality `40444802373` started; outcomes not yet verified. No merge/deploy until current-head CI and full independent/security acceptance.
