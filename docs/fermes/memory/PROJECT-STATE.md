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
- HISTORICAL Stage1 `40444770674`, Python tests `40444799796`, Python quality `40444802373` on prior PR #2 SHA. Superseded by subsequent CI evidence; see latest checkpoint below.
## FHM-007 Codex hardening closure checkpoint — 2026-10-27 Australia/Perth
- Option B stacked ReMe **Draft PR #2** updated by ordinary fast-forward to `2f640f66bc54c1bdd404a33da4672b6eb3265205`, including Pylint/CI matrix fix `9f46541`, format correction `86b05ef`, and independent-reviewed protected caller fail-closed fix `2f640f6`. PR #1 stays Draft at `4463d20`; no merge or deployment.
- Protected `durable_commit=True` no longer falls back to legacy model-owned tools for non-AgentScope wrappers, subclasses or invalid scope; strict boolean semantics enforced. The synthetic legacy pre-Option-B receipt/ack test explicitly uses a disposable `durable_commit=False` custom config rather than disabling Option B in protected mode.
- Codex implementation work in preserved isolated `fermes/fhm007-final-hardening-20261027` committed as `b932bc6`, then cherry-picked onto PR #2 as `2f640f6`. Cursor independent review `/tmp/fhm007/owner-hardening-cursor-final.log`: **GO for Draft integration; no P0**. Supervisor full host focused tests **152/152 PASS** (`/tmp/fhm007/owner-hardening-full-retest.log`); 3/3 SIGKILL PASS (`/tmp/fhm007/owner-hardening-crash-retest.log`); pinned Pylint 10.00/10, Black, Ruff F/I and diff checks PASS. Old 150-pass/2-fail evidence superseded.
- Exact published PR #2 head `2f640f66bc54c1bdd404a33da4672b6eb3265205` GitHub Actions **3/3 workflows PASS**, confirmed 2026-10-27 Perth: Fermes ReMe Stage 1 CI `40453336025`, Python tests 3.11/3.12/3.13/3.14 all 4/4 PASS `40453345527`, Python quality `40453348609`. Cursor local independent security review GO for Draft; optional GitHub `@cursor review` requested, no formal review submission confirmed. Continue keeping PR Draft; these tests do not by themselves approve FHM-006, immediate restart BM25 readiness, production deployment or merge.
- Remaining FHM-007 merge gates: all current-head hosted CI; deterministic immediate-restart BM25 retrieval readiness (earlier first fetch empty, later fetch succeeded); broader security/fault acceptance and supported filesystem limits; separate FHM-006 checkpoint v2 design approval. Keep PRs Draft and production unchanged.
