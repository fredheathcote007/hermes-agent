# Evidence Index
project_id: fermes-hermes

| ID | Evidence | Location | Observed | Valid against | Revalidate when |
|---|---|---|---|---|---|
| E-001 | 65 focused v0.22.5 Qwen/LM Studio tests PASS | Local /tmp/fermes-host-pytest-final.log | 2026-10-26 | fee4b6a0 and prior source changes | Source or dependencies change |
| E-002 | 142 adjacent auxiliary route/retry regressions PASS | Local /tmp/fermes-host-broader-tests.log | 2026-10-26 | fee4b6a0 source state | Source or dependencies change |
| E-003 | Direct Qwen tool-call output is structured API tool_calls | Dad-PC local LM Studio; session observation | 2026-10-26 | qwen96k-nomtp 98304; LM Studio local port 1234 | Model/config/backend changes |
| E-004 | Historical third draft patch with obsolete auxiliary_lmstudio module | `7dbfcf5a7d` commit | 2026-10-21 | Historical branch, not v0.22.5 | Adapted port completed |
| E-005 | Existing current fixes on fork | `26decd20`, `7d879727`, `fee4b6a0` | 2026-10-26 | v0.22.5 tagged baseline | Any upstream merge |
