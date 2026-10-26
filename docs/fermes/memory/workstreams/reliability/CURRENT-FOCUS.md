# FHM-004 — Supervised Stop and Recovery (Merged)

project_id: fermes-hermes
workstream_id: reliability
priority: P0 (completed)
date: 2026-10-26 Australia/Perth
issue: https://github.com/fredheathcote007/hermes-agent/issues/4

## Accepted and merged
- Fork PR #20 merged to `fermes/qwen-lmstudio-v0225-20261026` at `0bb167d18758b7465f44043ff54e0fa4cfe56460`, with validated PR code `aa8dd17df4919cd80f0dd39f80b7d68d8c769361`.
- Source tree verified identical between validated PR head and merge commit; this workstream is **source integrated only**, not installed, enabled as a background service, or deployed to fork `main`.
- Real disposable Linux Hermes gateway SIGTERM and supervisor SIGKILL verified; checkpointed admission/session/generation identity preserved; one-time explicit orphan observation; no duplicate user prompt or durable gateway admission; gateway restart/authority drift BLOCKED safely for operator review.
- Fast success without exact admission is `SETTLED_UNKNOWN`, return 125 instead of false success 0; negative red/green test passed.
- New/adjacent source tests 89 PASS and 20 subtests, live real-gateway pytest 2 PASS. Independent Cursor review no P0/P1 blockers. GitHub-hosted CI on final PR head [40312422340](https://github.com/fredheathcote007/hermes-agent/actions/runs/40312422340) SUCCESS.
- Full operational evidence: `docs/fermes/reliability/EVIDENCE-JOURNAL.md`; original implementation and tests retained in merged source.

## Critical boundary: FHM-005 remains OPEN P0
A matched `TERMINAL` receipt proves only the gateway admission lifecycle, **not** independent proof that a delegated tool, subprocess or external side effect satisfied acceptance. Continue [FHM-005](https://github.com/fredheathcote007/hermes-agent/issues/5) separately with independent verification artifacts, false-success prevention and interruption/unknown-outcome tests.
Recovery remains preview-only by default; explicit `--observe` may allow an already admitted turn to progress, but never submits a new prompt. There is no autonomous replay, startup timer or production deployment.

## Future requalification
Re-run source and disposable live gateway tests whenever gateway/session contracts, Python/runtime dependencies, execution fencing, or recovery state schema change. Use FHM-011 before adopting newer upstream Hermes releases. Preserve FHM-007 memory-v2 worktree and PR #19.
