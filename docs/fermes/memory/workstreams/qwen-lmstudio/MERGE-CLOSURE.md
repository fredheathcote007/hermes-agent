# Qwen / LM Studio — Merge and Acceptance Closure

project_id: fermes-hermes
Date: 2026-10-26 Australia/Perth
Status: Source merged; local live Qwen E2E qualified; no production deployment

## Integration record

| Order | PR | Target | Merge SHA |
|---|---|---|---|
| 1 | https://github.com/fredheathcote007/hermes-agent/pull/15 | `fermes/qwen-lmstudio-v0225-20261026` | `01c6b375970b6fd23aa12fd0b3c90de395d896f8` |
| 2 | https://github.com/fredheathcote007/hermes-agent/pull/18 | Same branch, retargeted after PR #15 | `25b6ab4c60b5d61626b78310b4bf1a9c7253521f` |

The second PR was retargeted after #15, checked CLEAN and CI SUCCESS, then merged using the repository's merge-commit method. Both original branches were preserved. `main` was verified unchanged at `0e427d788d253630d38a3a51cd76849e73cd6925`.

`git diff --stat b3c1ff75 25b6ab4c` and `git diff --name-only` showed **no differences**: the exact tested source tree was merged.

## Gates and outcome

- Latest combined PR #18 commit: `b3c1ff75e78ce763452d4caa78bd24b2ccc3ceff`.
- Combined source regressions: **668 PASS, 0 FAIL** (`/tmp/fermes-final-source-suites.log` on the authorised Linux host).
- Named custom credentials, pool retry, vision provider fallback: **341 PASS**, independent Cursor review **no P0/P1** (`/tmp/fermes-route-final-regression.log`, `/tmp/fermes-route-cursor-final.log`).
- Stop/verification **44 PASS** after changing TMPDIR to avoid the unrelated `/tmp/.git` contamination (`/tmp/fermes-stop-isolated-suite.log`). This does not close FHM-005's broader verification design.
- Session/rotation/restart **56 PASS** (`/tmp/fermes-session-persist-qualification.log`).
- Host GitHub Actions CI: PR #15 and #18 final SHA checks SUCCESS (`Hermes Python tests and lint`, runs `40296757624` and `40296761964`). This is the fork's targeted Python/Ruff workflow, not full upstream CI/Docker/Nix qualification.
- Independent Cursor reviewers checked combined routing/recovery and final credential/vision patches; no outstanding P0/P1 defects in this scope.

### Live Hermes/Qwen evidence

Isolated WSL Ubuntu on Dad-PC, Hermes source at final PR #18 SHA, Python 3.14, LM Studio on local `127.0.0.1:1234`, model `qwen96k-nomtp` (98,304 context):

- Answer only: `READY`, one model request, completed=true, no tools.
- True Hermes tool cycle: structured `terminal` command `echo FERMES_E2E_TOOL_OK`, allowlist-guarded real terminal result, one tool response and final assistant answer, two API calls.
- One malformed tool payload injected at provider boundary; real Qwen corrective reprompt returned `READY`, zero unintended tools, clean transient transcript.
- Four malformed payloads injected; exactly three corrective reprompts, `completed=false`, `failed=true`, no tool execution or stale nudge rows.

Dad-PC WSL logs: `/tmp/fermes-final-answer.log`, `/tmp/fermes-final-tool.log`, `/tmp/fermes-final-recovery.log`, `/tmp/fermes-final-exhaust.log`.
The active production Hermes installation was not changed. The model server remains a localhost-only test dependency.

## Issue closure and remaining scope

Closed completed with links and evidence: FHM-001/#1, FHM-002/#2, FHM-013/#13, FHM-014/#14 and FHM-015/#16. FHM-016 runner fix already closed.

FHM-004 and FHM-005 continue: enterprise/autonomous stop, delegated worker verification and crash recovery were not certified by the Qwen smoke cases. FHM-006 compaction and FHM-007 Local Memory v2 also remain separate.

## Rollback and upstream compatibility

This is an isolated compatibility branch; production and fork main are unaffected. Preserve the tag `v0.22.5`, pre-merge baseline `e0bb2a82`, and tested PR #18 SHA `b3c1ff75`. Do not force-push or erase branches. Future release updates go through FHM-011 and require a new regression/evidence cycle.
