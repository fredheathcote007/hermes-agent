# FHM-005 — new-chat handoff (start here)

**Project ID:** fermes-hermes. **Snapshot:** 27 October 2026, approximately 12:25 Australia/Perth. **Mode:** Full. This is a GitHub-backed, read-only handoff; its documents do not approve deployment or security risk.

## BLUF

FHM-005 remains **P0/open**. Source-only fail-closed, contract, state-machine, Linux file-observation and SQLite receipt-model changes are merged; there is **no operational trusted verifier**. The next chat must **check draft PR #42 at its actual head and its CI/Cursor reviews**, resolve its findings and only merge if the existing source-only acceptance gates pass. Then reconcile open architecture decisions and implementation blockers without installing or enabling privileged services.

## Read in this order

1. This file.
2. 02-CONFIRMED-FACTS-AND-DECISIONS.md — approved DEC-004 to DEC-007 and threat boundaries.
3. 03-CURRENT-STATE-AND-NEXT-ACTIONS.md — live statuses, PR #42 and next task.
4. 04-TECHNICAL-REFERENCE.md — code, machines, paths, interfaces and safety gates.
5. 05-FILES-AND-EVIDENCE.md — exact GitHub and device sources.
6. 01-PROJECT-CONTEXT.md — mission, scope and workflow.
7. NEW-CHAT-PROMPT.md — paste into a new chat to start execution.

## Authoritative bootstrap

- Repository: https://github.com/fredheathcote007/hermes-agent
- Canonical parent: https://github.com/fredheathcote007/hermes-agent/issues/5
- Identity gate: docs/fermes/memory/MEMORY-INDEX.md must say **project_id: fermes-hermes**; stop on mismatch.
- Current implementation/design work is in stacked **draft** PRs #23, #25 and #39. Their contents are not automatically merged into the qualified fork branch.
- Latest reviewed candidate: https://github.com/fredheathcote007/hermes-agent/pull/42
- The next chat should use connected GitHub and, where available, the authorised Project Coordinator device to reconstruct fresh state; do not assume the device is always connected.
- Read detailed design manifest from draft PR #25, rather than inventing another independent backlog.

## What to do first

Fetch current PR #42 head, changes, Cursor review, test evidence and exact-head CI. Check for concurrent workers and local changes. Only progress to merge if the review, tests, risk boundaries and repository authorisation warrant it. Do not prematurely close issue #36 or parent #5.

## Delivery controls

Codex is primary implementer; Cursor is independent reviewer. Correct P0/P1 findings, then have Cursor re-review before merge. Keep GitHub issues prioritised, statuses current and stuck workflows clean **without deleting evidence or disrupting unrelated jobs**. No production security-policy modifications, privileged installations, credentials, external actions with uncertain outcomes, or FHM-007 changes without separate authorisation.
