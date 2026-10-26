# New chat continuation — Fermes Hermes FHM-007 (P1)

Continue the existing **Fermes Hermes Fork — Hermes-owned Local Memory v2 / FHM-007** workstream. Take implementation ownership using **Codex with high reasoning**, with Cursor or a separate Codex worker for independent read-only review. Do not restart the original research or change the approved full ReMe fork direction.

## Mandatory identity bootstrap
On authorised Project Coordinator, **first read** `/srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007/docs/fermes/memory/MEMORY-INDEX.md`. Confirm exactly `project_id: fermes-hermes`; STOP on mismatch. Then read the entire handoff folder `docs/fermes/memory/handoffs/fhm-007-reme-2026-10-26/` starting at `00-START-HERE.md`, in numeric order. Read canonical project state, decisions, constraints, evidence, open loops, lessons and `workstreams/memory-v2/CURRENT-FOCUS.md` before touching code.

## Live repositories
- Hermes: https://github.com/fredheathcote007/hermes-agent
- FHM-007 P1: https://github.com/fredheathcote007/hermes-agent/issues/7 (OPEN)
- ReMe full fork: https://github.com/fredheathcote007/fermes-reme
- ReMe draft PR #1: https://github.com/fredheathcote007/fermes-reme/pull/1
- ReMe worktree: `/srv/project-coordinator/projects/fermes-reme-fhm007-20261026`, branch `fermes/hermes-provider-stage1`, snapshot HEAD `661a5ed` (code fix `473c880`).
- Hermes memory worktree: `/srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007`, branch `fermes/memory-v2-fhm007-20261026`. Verify latest HEAD and active workers live.

## Approved design and confirmed evidence
Full Apache-2.0 ReMe fork with embedded Hermes MemoryProvider and native file/Markdown BM25 search. Dream off. No mandatory Hindsight or Project Coordinator runtime; defer Hermes SQLite prototype PR #19 and additional vector work. Future FHM-006 compaction, SkillHone and SkillOpt-Sleep must be supported with safe evidence/approval gates.

Dad-PC Bionic 1.1.8 LM Studio listener was restored with explicit owner approval to `10.1.1.50:1234` (configuration backups exist). Project Coordinator `10.1.1.40` received HTTP 200 and model listings; Qwen 3.5 4B direct synthetic text and valid four-argument function call both PASS.

**But actual ReMe learning FAILS:** real Hermes provider / ReMe / AgentScope with Qwen 3.5 4B attempted seven `daily_write` calls with empty `{}` arguments; no daily note or fresh-session recall. The original version falsely reported success and removed the pending turn. Draft ReMe code `473c880` makes the **observed all-failed case** return failure; a real retest retained one pending turn with no successful receipt. Focused host tests **69/69 PASS**. Independent reviewer accepted draft PR preservation only and identified remaining P1 missing-result/mixed-result/call-ID/current-turn defects. `RuntimeError: Event loop is closed` occurred during failed-run cleanup. CI snapshot: **seven of eight workflows passed on `661a5ed`; Docker still running**. Re-query.

## Exact next task
1. Verify canonical identity and latest FHM-007 issue/PR, branch, CI and workers. Resolve pending CI or real failures.
2. Implement **fail-closed, current-turn scoped and call-ID paired tool-execution accounting** for missing/unknown/interrupted/mixed results. Preserve no-op correctness, successful partial writes, idempotent request IDs and pending spool. Add model-free negative regression tests and obtain independent review.
3. Diagnose/fix the ReMe/AgentScope `daily_write` complex argument failure with a local Qwen or another qualified small local model, using synthetic input; bound retries and graceful async shutdown. **Prove genuine model-created durable note, source provenance, restart and correct fresh-session BM25 recall** before calling FHM-007 learning accepted.
4. Update GitHub Issue #7 and PR #1 with P1 priority, commits, tests, review findings and precise next action; update canonical project memory. Keep PR draft and issue open until all acceptance gates.

## Execution and safety
Use bounded Codex invocations with `</dev/null`, high reasoning, captured logs and host verification. Avoid the stalled Blacksmith runner; use GitHub-hosted `ubuntu-24.04`. Do not modify an active Hermes installation, Dad-PC bind/firewall, credentials, Dream state, external services, unrelated worktrees or `main` without separate approval. Do not activate the FHM-006 checkpoint v2 marker or automatically promote memory into trusted skills. Distinguish network/model API PASS, unit/CI PASS, failure containment PASS and real useful memory recall PASS. No merge or deployment without evidence, independent review and owner approval.

**First response:** brief BLUF with (1) objective, (2) actual live status, (3) three key outstanding risks, (4) first bounded action. Then perform the authorised work, not merely suggest another plan.
