# FHM-004 Reliability — Current Focus

project_id: fermes-hermes
workstream_id: reliability
date: 2026-10-26 Australia/Perth
priority: P0
issue: https://github.com/fredheathcote007/hermes-agent/issues/4

## State
Isolated source branch `fermes/fhm004-bounded-recovery-20261026` based on Qwen-qualified compatibility `1db86fb2`; this is a draft opt-in supervisor and observation-only recovery implementation, **not an enabled gateway service**. FHM-007 memory v2 remains separate and untouched.

## Verified
- Historical Phase1/2 contract tests 55/55 plus 20 subtests.
- Current fork port 67/67 plus 20 subtests on isolated locked Python 3.14.
- Existing gateway/delegation regressions 22/22.
- Isolated Linux process-group test proves SIGTERM-resistant owned descendant stopped; shared process-group negative test proves no group signal when not owned.
- Ruff lint, CLI help and empty preview scanner PASS.

## Decision and safety
- Recovery NEVER submits a prompt, even after supervisor death.
- Orphan scanner preview only by default; explicit `--observe` is required for a single claim/attachment.
- Gateway session resume is not guaranteed side-effect-free; source test PASS does not prove no automatic continuation.
- Missing admission identity, stale checkpoint, uncertainty and unverified side effects are BLOCKED/attention-required, never auto-success.
- No VM/timer/production change. No deployment or merge.

## Pending
Independent second Cursor review, GitHub hosted PR CI, and explicitly isolated crash/stop/restart E2E. FHM-005 independent outcome-verification remains separate P0.
Exact next action: finish reviewer gate, patch any P0/P1, run CI and preserve a draft PR; then plan an authorised disposable gateway interruption test with immutable attempt/admission evidence. Do not close FHM-004 on mock/unit evidence.
