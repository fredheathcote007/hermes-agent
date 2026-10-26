# Current Focus — Qwen / LM Studio

project_id: fermes-hermes
workstream_id: qwen-lmstudio
workstream_name: Hermes Qwen/LM Studio compatibility qualification
Updated: 2026-10-26 Australia/Perth
State: SOURCE MERGED / LIVE E2E ACCEPTED / PRODUCTION NOT DEPLOYED

## Verified outcome

- Completed and merged fork PR #15 → compatibility branch at `01c6b375`.
- Completed and merged fork PR #18 → same branch at `25b6ab4c60b5d61626b78310b4bf1a9c7253521f`.
- Existing alias, failed capability-probe, reasoning-route and retry credential/vision fixes retained. Qwen malformed tool-call recovery is bounded and never directly executes raw assistant text.
- Independent Cursor reviews no acceptance-blocking findings; 668 combined source tests, 44 stop/verification and 56 session-persistence tests passed.
- Actual Hermes on Dad-PC WSL, LM Studio localhost-only, Qwen alias `qwen96k-nomtp`: answer-only, actual restricted terminal tool with result and final answer, malformed first response + real Qwen corrective reprompt, and repeated-malformed bounded failure all passed.
- Merge-tree identity verified: no file differences between validated PR #18 head `b3c1ff75` and merged commit `25b6ab4c`. Both final PR CI runs SUCCESS.
- Main and active Hermes installations were not changed. No self-hosted runner or permanent LAN exposure is needed for source CI.

## Canonical evidence

Read `MERGE-CLOSURE.md`, issues FHM-001, FHM-002, FHM-013, FHM-014, FHM-015 and the merged PRs. Historical local test logs are indexed there.

## Next steps

1. Keep this source baseline pinned and available for rollback.
2. For upstream adoption, use FHM-011 and inspect new official releases rather than automatically merging moving upstream main.
3. For full autonomous stop/recovery and verification, work independently in FHM-004/FHM-005; source qualification of these Qwen PRs is not blanket certification of autonomous agents.
4. Preserve FHM-007 Local Memory v2 worktree and draft PR #19 as independent concurrent work.
