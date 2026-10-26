# Evidence Index
project_id: fermes-hermes

| ID | Evidence | Location | Observed | Valid against | Revalidate when |
|---|---|---|---|---|---|
| E-001 | 65 focused v0.22.5 Qwen/LM Studio tests PASS | Local /tmp/fermes-host-pytest-final.log | 2026-10-26 | fee4b6a0 and prior source changes | Source or dependencies change |
| E-002 | 142 adjacent auxiliary route/retry regressions PASS | Local /tmp/fermes-host-broader-tests.log | 2026-10-26 | fee4b6a0 source state | Source or dependencies change |
| E-003 | Direct Qwen tool-call output is structured API tool_calls | Dad-PC local LM Studio; session observation | 2026-10-26 | qwen96k-nomtp 98304; LM Studio local port 1234 | Model/config/backend changes |
| E-004 | Historical third draft patch with obsolete auxiliary_lmstudio module | `7dbfcf5a7d` commit | 2026-10-21 | Historical branch, not v0.22.5 | Adapted port completed |
| E-005 | Existing current fixes on fork | `26decd20`, `7d879727`, `fee4b6a0` | 2026-10-26 | v0.22.5 tagged baseline | Any upstream merge |

| E-006 | 340 current third-fix focused/adjacent tests PASS | Local /tmp/fermes-thirdfix-final-host-regression.log | 2026-10-26 | patch 24840479, v0.22.5 | Patch/test runtime change |
| E-007 | 178 additional current auxiliary/provider tests PASS | Local /tmp/fermes-thirdfix-broad-host-regression.log | 2026-10-26 | patch 24840479, v0.22.5 | Patch/test runtime change |
| E-008 | Cursor independent read-only review: no P0; P1 named custom key/vision auto fallback | Local /tmp/fermes-thirdfix-cursor-review.log, FHM-013/014 | 2026-10-26 | patch 24840479 | Patch or PR change |
| E-009 | Fork draft PR #15 against compatibility branch; live E2E unverified | https://github.com/fredheathcote007/hermes-agent/pull/15 | 2026-10-26 | fork port branch | Merge/CI/review change |
