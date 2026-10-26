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
| E-010 | FHM-007 architecture/gaps review and staged implementation plan | `docs/fermes/memory/workstreams/memory-v2/ARCHITECTURE-AND-GAPS.md`, `IMPLEMENTATION-PLAN.md` | 2026-10-26 | `e0bb2a82` | Owner/ARB review or source/dependency changes |
| E-011 | Isolated memory-v2 ledger fallback focused tests: 6 passed | `tests/agent/test_memory_v2_store.py`, local command recorded in implementation plan | 2026-10-26 | `e0bb2a82` plus worktree changes | Final source/test changes; provisioned runner still required |
| E-012 | Required `scripts/run_tests.sh` attempt blocked by managed sandbox uv cache/network setup; not a PASS | Local command output; implementation plan | 2026-10-26 | Worktree environment | Provisioned environment or dependency state changes |
| E-013 | Codex source audit of 7 pinned GitHub memory engines; HYBRID recommended (not approved), licence cross-check | `docs/fermes/memory/workstreams/memory-v2/EXTERNAL-CODE-AUDIT.md`, FHM-007 issue comments | 2026-10-26 | pinned upstream SHAs listed in report | Source versions, licence or upstream issues change |
| E-014 | Canonical Hermes runner: isolated ledger tests 6 passed / 0 failed | `/tmp/fhm007/host-canonical-tests.log`; `scripts/run_tests.sh tests/agent/test_memory_v2_store.py` with compatible baseline venv | 2026-10-26 | `e0bb2a82` + isolated worktree edits | Ledger or test changes |
| E-015 | Cursor independent source review: non-runtime prototype may be committed; P1 runtime gates remain, some allegations need discriminating tests | `docs/fermes/memory/workstreams/memory-v2/INDEPENDENT-CODE-REVIEW.md` | 2026-10-26 | pre-remediation prototype | P1 fixes, runtime adapter or schema changes |
| E-016 | Draft fork PR #19 holds source-audited unwired memory-v2 prototype and review records; main untouched | https://github.com/fredheathcote007/hermes-agent/pull/19 | 2026-10-26 | 285fdc74 | PR/CI/status or branch changes |
| E-017 | Full ReMe fork created; fork-first decision DEC-004 | https://github.com/fredheathcote007/fermes-reme | 2026-10-26 | upstream 363e497 | ReMe fork branch, source or plugin changes |
| E-018 | FHM-007 inherited CI/Docker/Nix Blacksmith jobs queued/pending; dedicated Ubuntu 24.04 workflow staged (execution pending) | .github/workflows/fermes-fhm007-ci.yml and PR #19 GitHub Actions | 2026-10-26 | FHM-007 runner fix branch | Workflow changes and next PR run |
| E-019 | Fermes ReMe embedded Hermes integration implementation, durable replay journal, request-id receipts, safe no-Dream config and independent Cursor review | https://github.com/fredheathcote007/fermes-reme/pull/1 ; `dc34a7fb` | 2026-10-26 | ReMe upstream `363e497` | Fork/source/CI/owner-approved scope changes |
| E-020 | Independent host validation: 47 focused tests PASS; real Hermes Doctor/loader PASS; embedded BM25 PASS, two-profile restart recall and separate-workspace isolation PASS | `/tmp/fhm007/reme-stage1-final-host-tests.log`, `reme-plugin-doctor-host.log`, `real-hermes-loader-smoke.log`, `offline-bm25-probe.log`, `two-profile-bm25-probe.log`, `real-provider-alpha.log`, `real-provider-beta.log` | 2026-10-26 | ReMe `dc34a7fb`, Hermes `96517c3f` | Integration/runtime/config change |
| E-021 | ReMe FHM-007 GitHub-hosted Ubuntu 24.04 focused CI PASS; PR semantic-title policy corrected; broader upstream CI still running | https://github.com/fredheathcote007/fermes-reme/actions/runs/40303028576 ; run 40303242396 | 2026-10-26 | ReMe `dc34a7fb` | GitHub check/re-run or code change |
