# FHM-007 Technical reference

project_id: fermes-hermes

## Repositories and exact worktrees
- Hermes fork: https://github.com/fredheathcote007/hermes-agent
- FHM-007: https://github.com/fredheathcote007/hermes-agent/issues/7 (OPEN, P1)
- Canonical worktree: /srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007
- Canonical branch: fermes/memory-v2-fhm007-20261026, latest handoff SHA d04d24f0 (new handoff commit will supersede this).
- ReMe fork: https://github.com/fredheathcote007/fermes-reme
- Draft ReMe PR: https://github.com/fredheathcote007/fermes-reme/pull/1
- ReMe worktree: /srv/project-coordinator/projects/fermes-reme-fhm007-20261026
- ReMe branch: fermes/hermes-provider-stage1, SHA 661a5ed. Code fix 473c880. Original upstream 363e497.
- Hermes baseline: maintained v0.22.5 fork. Deferred SQLite prototype PR #19 must not merge.
- Relevant source: ReMe integrations/hermes_agent; reme/components/agent_wrapper/as_agent_wrapper.py; reme/steps/evolve/auto_memory.py.
- Stage 1 config: reme/config/fermes-hermes-stage1.yaml, embedded and file/BM25, Dream disabled.

## Network and service
- Dad-PC (Windows): 10.1.1.50/24. Bionic/LM Studio 1.1.8 binds explicitly to 10.1.1.50:1234.
- Project Coordinator (Linux): 10.1.1.40/24; test host only.
- Local API: http://10.1.1.50:1234/v1. Model probe qwen_qwen3.5-4b.
- Backups on Dad-PC at %USERPROFILE%\.lmstudio\apps\bionic\.internal\http-server-config.json.pre-fermes-restore-20261026-192859.bak and %USERPROFILE%\.lmstudio\.internal\http-server-config.json.pre-fermes-restore-20261026-192859.bak. No Windows Firewall rule was added. Do not revert without owner authorisation and active-client prechecks.
- Bionic Windows Ethernet profile is Public. Evaluate scope of LAN reachability and authentication as a separate security decision prior to production.

## Read-only bootstrap/CI verification (Project Coordinator)
```bash
H=/srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007
R=/srv/project-coordinator/projects/fermes-reme-fhm007-20261026
grep -m1 '^project_id:' "$H/docs/fermes/memory/MEMORY-INDEX.md"
git -C "$H" status --short --branch
git -C "$R" status --short --branch
gh pr view 1 --repo fredheathcote007/fermes-reme --json isDraft,state,headRefOid
gh run list --repo fredheathcote007/fermes-reme --branch fermes/hermes-provider-stage1 --limit 8
curl --noproxy '*' -sS --connect-timeout 3 --max-time 8 -o /dev/null -w '%{http_code}\n' http://10.1.1.50:1234/v1/models
```

## Re-run focused host tests after any source modification
```bash
H=/srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007
R=/srv/project-coordinator/projects/fermes-reme-fhm007-20261026
cd "$R"
PYTHONPATH="$H:$R" HERMES_HOME=/tmp/fhm007/new-chat-host-home PYTHONDONTWRITEBYTECODE=1 \
  timeout --signal=TERM --kill-after=5s 90s \
  /tmp/fhm007/reme-fork-testvenv/bin/python -m pytest -p no:cacheprovider -q --maxfail=1 \
  tests/unit/test_hermes_agent_integration.py tests/unit/test_auto_memory_idempotency.py tests/unit/test_fermes_capture_integration.py
```
Last proven: 69 passed in 16.23 seconds, /tmp/fhm007/final-livefix-host-tests.log. Verify the venv still exists before use.

## Codex pattern
Use project-approved worker model/runner. Always `</dev/null`, bounded `timeout`, separate worktrees/scopes, save logs and use an independent reviewer:
```bash
timeout --signal=TERM --kill-after=10s 300s codex exec \
  -m gpt-5.6-luna -c 'model_reasoning_effort="high"' \
  -s workspace-write --color never -o /tmp/fhm007/worker-result.txt \
  "$(cat /tmp/fhm007/worker-instructions.txt)" \
  </dev/null > /tmp/fhm007/worker.log 2>&1
```
Check actual installed model availability. Avoid inherited stdin/hanging processes. Do not interpret sandbox socket EPERM as a host regression without proving it independently.
