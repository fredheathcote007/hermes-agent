# FHM-007 Current state and next actions

project_id: fermes-hermes
status: Draft PR, NOT accepted for merge or deployment.

## Completed
1. Full ReMe fork with embedded Hermes provider, file/BM25, no Dream, durable profile journal/request-ID receipts, profile writer locks, synthetic restart/retrieval/isolation proof.
2. Dad-PC Bionic 1.1.8 regression identified: its app-specific and shared LM Studio server configurations reverted to localhost. After owner approval, both files were backed up, listener restored on exact LAN address 10.1.1.50:1234 and validated from Project Coordinator 10.1.1.40 (HTTP 200, 21 models); real local text inference and direct tool call passed.
3. Real ReMe/Qwen 3.5 4B capture was tested in a disposable Bubblewrap sandbox. Seven daily_write calls used empty arguments; all tool calls failed. Old ReMe incorrectly wrote success:true, changes:[] and cleared the pending turn. Memory and recall both failed.
4. ReMe fix 473c880 returns failure when all durable tool calls fail, with an AgentScope tool-execution summary. In a real Qwen retest, no false receipt was saved and one pending Hermes journal entry remained. **69/69 focused host tests PASS**.
5. Independent review: changes suitable for draft PR only. Follow-up 661a5ed fixed documentation dead links; documentation CI passed.

## Failed attempts and lessons
- Previous assumption that 10.1.1.50 was never served was wrong: user confirmed it previously worked. Look for Bionic configuration regression rather than redesigning the network.
- Standard lms server stop failed to reach the Bionic daemon. Use app-specific service understanding, backups and controlled restart; do not blindly retry.
- Small Qwen max_tokens budget consumed entirely by reasoning; direct second text/tool probes succeeded. Direct API tool success does NOT qualify ReMe.
- Initial failure-handling patch looked at AgentScope last_message only; host test disproved it because failed tool calls were in the combined state. Tool-execution summary fix passed tests.
- Failed real-model test also produced RuntimeError: Event loop is closed during asynchronous HTTP client cleanup and retrieval timeout; track separate lifecycle issue.
- Docs build broke on ten absolute host-path links in reviewer report; corrected in 661a5ed.

## Independent review P1 gaps
1. Missing, incomplete, interrupted or unknown tool results may still be misclassified as no-op/success.
2. Repeated same-name calls lack call-ID/result-ID pairing; mixed success/error may be silently acknowledged.
3. Tool-execution summary reads agent.state.context[-1], not a proven explicit current-turn boundary.
4. Need no-op correctness, idempotency and partial-success safety.
5. Actual model-driven note creation and fresh-session recall remain FAIL; lifecycle/retry storm unresolved.

## Exact first task in the next chat
Read canonical memory identity first. Check live draft PR #1 HEAD, current CI and active workers. Then implement/test a fail-closed, accurately correlated current-turn tool-execution result contract, independent review, before working on the ReMe/AgentScope daily_write invalid-argument cause.

## Next gates
- Extend negative regressions for missing/unknown/duplicate/mixed and previous-turn tool results. Preserve stable IDs, durable queue and successful no-op behaviour.
- Inspect and benchmark local model-to-AgentScope daily_write schema and argument generation; solve compatibility without broadly rewriting ReMe or changing active Hermes.
- Bound retries and graceful async shutdown.
- Repeat real model-created daily note, source provenance, durable acknowledgement, restart and correct BM25 recall in disposable profile; verify no cross-profile leak.
- Qualify FHM-006 checkpoint and memory poisoning/security/retrieval-quality gates. Merge and deployment remain owner-controlled.

No background work is assumed after this chat. Resume with new explicit tool calls.
