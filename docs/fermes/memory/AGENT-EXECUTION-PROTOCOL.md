# Fermes Hermes — Codex, Cursor and LLM Execution Protocol

project_id: fermes-hermes
Status: Approved operational procedure
Updated: 2026-10-26 Australia/Perth

This is a **supervisor/LLM delegation instruction**, not a defect in the Hermes agent product. Project Coordinator may host an authorised worktree or a model connection, but no Fermes service may depend on Project Coordinator.

## Mandatory worker instruction envelope

Every Codex, Cursor or other LLM implementation/review task MUST include, in order:

1. **Identity:** `project_id=fermes-hermes`, exact repository URL, target branch/worktree, starting SHA. Read `MEMORY-INDEX.md` first and stop on mismatch.
2. **Goal and issue:** GitHub Issue URL/ID, approved requirements, observable acceptance criteria.
3. **Sources:** current project state/constraints/decisions, the live GitHub Issue/PR and applicable upstream release/PR/commit references.
4. **Permitted scope:** specific code paths, test data, isolated worktree and available environments; distinguish read-only inspection from write authority.
5. **Forbidden operations:** force push, destructive branch reset, deployment, credential exposure, firewall changes, unapproved network access, external provider onboarding, modification of unrelated active worktrees or source-of-truth records.
6. **Deliverables:** minimal patch, positive/negative regression tests, logs, source/behaviour rationale, known limitations and exact next action.
7. **Verification:** baseline reproduction where useful; unit, integration, live-model, CI and independent-review gates labelled separately. Never convert a missing runtime test into a reported PASS.
8. **Execution limits:** wall-time deadline, explicit stdin mode, finite iterations, process-tree cleanup, exit status, log location and stop/handback instructions.
9. **Handoff:** tested SHA, commands/versions, PASS/FAIL/SKIP with causes, changes made, remaining unknowns and next permissible action.

## Launcher requirements

A one-shot prompt does not ensure inherited stdin is closed. A historical Codex command stalled at `Reading additional input from stdin...`. For non-interactive executions redirect `</dev/null` explicitly, apply a bounded timeout and report the actual exit code:

```sh
WORKTREE="/path/to/isolated/fermes-hermes"
timeout --signal=TERM --kill-after=10s 600s \
  codex exec -C "$WORKTREE" -s workspace-write -m "<approved-available-model>" \
  'PROJECT ID: fermes-hermes. ISSUE: ... GOAL: ... SCOPE: ... GATES: ...' \
  </dev/null > /tmp/fermes-agent-task.log 2>&1
rc=$?
printf 'codex_exit_code=%s\n' "$rc"
```

Review must use `-s read-only` or the corresponding installed CLI's supported read-only mode. Validate each installed model/CLI and options before use. Close stdin in other non-interactive workers too, but do not assume they accept Codex flags. Do not entrust tool workers with unbounded repair loops; the supervisor must detect blocked processes and preserve accurate partial checkpoints. Where the agent sandbox causes test stalls, the supervisor runs tests separately on the authorised host with explicit timeouts.

## GitHub issue lifecycle

- Exactly one priority label: `priority:P0` (acceptance/security/reliability blocker), `priority:P1` (core capability), `priority:P2` (future research/improvement).
- Include objective, acceptance tests, owner or active workstream, current state, last verified SHA, evidence and exact next action.
- Update at each substantive milestone; close as `completed` only with acceptance evidence. Close `not_planned` when explicitly out of scope, retaining provenance and any procedural learning.
- Use GitHub Issues as canonical backlog; versioned repository Markdown for decisions, protocols and cross-chat current state, not a second competing task tracker.
- Do not delete historic Actions evidence; cancel genuinely obsolete queued runs, preserve passing CI artifacts, and never introduce publishing credentials into PR jobs.

## Security and project boundaries

Use isolated worktrees and read-only-first diagnostics. Keep secrets out of prompts, logs and public issues. Retain reviewable commits, rollback points, and independent review before promotion. For LM Studio live qualification, inspect Project Coordinator's existing local model connection before adding any new tunnel; do not expose localhost-only LM Studio to the LAN or modify firewall/SSH credentials without separate approval.

Project-level CI/launcher operating practices belong here. Product-level reliable termination, crash recovery and independent verification remain distinct Hermes issues FHM-004/FHM-005.
