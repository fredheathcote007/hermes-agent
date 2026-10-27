# Fermes Hermes — Project Memory Index

project_id: fermes-hermes
project_name: Fermes Hermes
memory_schema_version: 4
memory_status: Active
Last material update: 2026-10-27 (Australia/Perth)

## Identity gate
This memory belongs **only** to the maintained fork of `NousResearch/hermes-agent` at `fredheathcote007/hermes-agent`, project_id `fermes-hermes`. Do not confuse it with the Ideas/Hermes + Hindsight qualification, local LLM dev harness or Project Coordinator. Stop on any project identity mismatch.

## Authoritative locations
- Implementation source: [GitHub fork](https://github.com/fredheathcote007/hermes-agent).
- **Issue backlog and acceptance state:** [GitHub Issues](https://github.com/fredheathcote007/hermes-agent/issues). Each open item has a permanent FHM-### tracking ID.
- Workstream state: this folder's `PROJECT-STATE.md`, `OPEN-LOOPS.md`, `WORKSTREAMS.md`, `DECISIONS.md`, `CONSTRAINTS.md`, `EVIDENCE-INDEX.md` and `LESSONS-AND-REJECTED-PATHS.md`.
- Current qwen/LM Studio workstream: `workstreams/qwen-lmstudio/CURRENT-FOCUS.md`.
- New-chat entrypoint: `NEW-CHAT-BOOTSTRAP.md`.
- Evidence, source diffs and test results: source commits and issue/PR comments; do not paste large logs into memory files.
- FHM-007 host runtime and archived logs: `/srv/project-coordinator/workspaces/fermes-hermes/fhm007`. **Source `/srv/project-coordinator/workspaces/fermes-hermes/fhm007/env.sh` before new tests/Codex runs** so TMPDIR, UV and pip caches use /srv rather than the /tmp tmpfs; `venv/bin/python` is the migrated test interpreter. The old `/tmp/fhm007` is a compatibility symlink only; never use it as the working path.

## Source precedence
User objective > approved decisions/constraints > live branch and tests > issue/PR evidence > this snapshot > historical chat.
GitHub Issues are **canonical for work items**, not duplicated as an independently maintained task list here.
