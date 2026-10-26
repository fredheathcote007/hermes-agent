# Evidence Index
project_id: fermes-hermes

| ID | Evidence | Location | Observed | Valid against | Revalidate when |
|---|---|---|---|---|---|
| E-001 | 65 focused v0.22.5 Qwen/LM Studio tests PASS | Local /tmp/fermes-host-pytest-final.log | 2026-10-26 | fee4b6a0 and prior source changes | Source or dependencies change |
| E-002 | 142 adjacent auxiliary route/retry regressions PASS | Local /tmp/fermes-host-broader-tests.log | 2026-10-26 | fee4b6a0 source state | Source or dependencies change |
| E-003 | Direct Qwen tool-call output is structured API tool_calls | Dad-PC local LM Studio; session observation | 2026-10-26 | qwen96k-nomtp 98304; LM Studio local port 1234 | Model/config/backend changes |
| E-004 | Historical third draft patch with obsolete auxiliary_lmstudio module | `7dbfcf5a7d` commit | 2026-10-21 | Historical branch, not v0.22.5 | Adapted port completed |
| E-005 | Existing current fixes on fork | `26decd20`, `7d879727`, `fee4b6a0` | 2026-10-26 | v0.22.5 tagged baseline | Any upstream merge |
| E-006 | Third fix port: 518 host tests PASS, Cursor independent review | /tmp/fermes-thirdfix-final-host-regression.log; /tmp/fermes-thirdfix-broad-host-regression.log; PR #15 | 2026-10-26 | 24840479 | Source or runtime changes |
| E-007 | Fork CI fixed: GitHub-hosted tests and Ruff PASS | https://github.com/fredheathcote007/hermes-agent/actions/runs/40289753454 | 2026-10-26 | 016cba2d | Workflow changes |
| E-008 | Qwen recovery: 140 host pytest, Ruff, independent Cursor review no P0 | /tmp/fermes-toolcall-reviewed-broad.log; /tmp/fermes-toolcall-review-v2.log | 2026-10-26 | e1541755 | Source change |
| E-009 | Fork recovery PR #18 GitHub-hosted CI PASS | https://github.com/fredheathcote007/hermes-agent/actions/runs/40290526021 | 2026-10-26 | 5fde8068 | Head SHA or workflow change |
| E-010 | Real Hermes→LM Studio→Qwen E2E | NOT YET VALIDATED (FHM-002) | 2026-10-26 | N/A | Must execute before production acceptance |
