# FHM-007 — Fermes Hermes / ReMe continuation pack

project_id: fermes-hermes
priority: P1
date: 2026-10-26 (Australia/Perth)
mode: Full
status: In qualification; NOT approved for deployment or merge

## BLUF
Owner-approved full ReMe fork integration is on an isolated draft PR. Dad-PC's LM Studio API is restored and real model inference works, but Qwen 3.5 4B cannot yet write a ReMe daily memory. A tested fail-closed patch now retains the pending memory turn rather than falsely acknowledging it; the next chat must fix remaining tool-result correctness, model/tool interoperability and recovery before functional acceptance.

## Reading sequence
1. **Read first**: `/srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007/docs/fermes/memory/MEMORY-INDEX.md`; confirm `project_id: fermes-hermes`, stop on mismatch.
2. Read canonical `PROJECT-STATE.md`, `DECISIONS.md`, `CONSTRAINTS.md`, `OPEN-LOOPS.md`, `EVIDENCE-INDEX.md`, `LESSONS-AND-REJECTED-PATHS.md`, and `workstreams/memory-v2/CURRENT-FOCUS.md` from the same directory.
3. Read this pack `01` through `05`, then paste `NEW-CHAT-PROMPT.md` into a new ChatGPT chat.
4. Check live FHM-007 Issue #7, ReMe PR #1, latest Git/CI and other active workers: this file's CI values are only a snapshot.

## Exact continuation
Verify latest ReMe PR #1 CI at `661a5ed`; then close the independent review's fail-open missing/unknown/mixed tool-result and call-ID gaps. Diagnose why ReMe/AgentScope yields empty `daily_write` arguments against a model that emits valid direct tool calls. Prove real model-created durable note and fresh-session retrieval before acceptance.

This is **Fermes Hermes**, not Ideas/Hindsight, Project Coordinator, FHM-003, or the local LLM development harness. Project Coordinator is a test host, not a runtime dependency. No new chat has been created automatically.
