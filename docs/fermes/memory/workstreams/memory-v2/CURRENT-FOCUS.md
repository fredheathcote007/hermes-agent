# FHM-007 — Current Focus

project_id: fermes-hermes
issue: https://github.com/fredheathcote007/hermes-agent/issues/7
workstream_id: memory-v2
priority: P1
status: Full ReMe fork Stage 1 implemented, draft PR open; partial qualification PASSED, runtime acceptance NOT PASSED
updated: 2026-10-26 Australia/Perth
source_reme_fork: https://github.com/fredheathcote007/fermes-reme
source_reme_branch: fermes/hermes-provider-stage1
source_reme_commit: fa93e09
reme_draft_pr: https://github.com/fredheathcote007/fermes-reme/pull/1
hermes_deferred_sqlite_draft_pr: https://github.com/fredheathcote007/hermes-agent/pull/19

## Approved direction

DEC-004: Full ReMe fork first. Maintain ReMe file-backed workspace and BM25.
Stage 1 uses embedded Hermes MemoryProvider and dedicated local-only
`reme/config/fermes-hermes-stage1.yaml` with CLI/no network listener,
no Dream/proactive scheduled jobs, and loopback-only LLM defaults. Profile
config must explicitly choose this file, not upstream ReMe `default`.
SQLite ledger and new vector backend are deferred, Hermes PR #19 stays draft.
No Hindsight or Project Coordinator service dependency.

## What changed on isolated ReMe fork

- Fsynced, profile-local JSONL journal for accepted Hermes turns, private
  directories/files, safe path/symlink handling, replay after interruption,
  backoff and later-record processing after failures.
- Stable journal IDs are sent via ReMe's existing `auto_memory(request_id)`
  idempotency receipt interface through embedded/HTTP adapters.
- Existing Hermes loader and plugin manager interfaces retained.
- Focused GitHub-hosted Ubuntu 24.04 fork CI; no Blacksmith.
- Independent Cursor findings and exact host evidence captured in fork docs.
- Draft fork PR #1 is open and unmerged; Hermes active runtime unchanged.

## Verified evidence

- ReMe focused Hermes adapter suite: 47/47 PASS, log
  `/tmp/fhm007/reme-stage1-final-host-tests.log`.
- Real maintained Hermes plugin doctor PASS:
  `/tmp/fhm007/reme-plugin-doctor-host.log`.
- Real loader discovery/registration PASS in disposable HERMES_HOME:
  `/tmp/fhm007/real-hermes-loader-smoke.log`.
- Real ReMe embedded local BM25 retrieved synthetic file:
  `/tmp/fhm007/offline-bm25-probe.log`.
- Distinct alpha/beta profiles and workspaces: own synthetic evidence recalled,
  other profile's token absent; fresh session and post-restart retrieval PASS:
  `/tmp/fhm007/two-profile-bm25-probe.log`,
  `/tmp/fhm007/real-provider-alpha.log`, `real-provider-beta.log`.
- Stage 1 config resolves with no cron/Dream, CLI service and loopback model default.
- ReMe CI `Fermes ReMe Stage 1 CI` run 40303028576 PASS on ubuntu-24.04;
  ReMe full upstream workflows still checking; PR semantic title corrected and
  replacement title-policy run 40303242396 PASS.
- Code review in `docs/fermes/INDEPENDENT-REVIEW.md` says draft PR ready,
  but **NO GO** for production or full FHM-007 acceptance.

## Blocking/unverified capabilities

- Real LLM-backed Hermes conversational auto-memory capture and evidence
  provenance not yet proven. Dad-PC LM Studio currently only listens on
  `127.0.0.1:1234` on Dad-PC; do not change bind/firewall without approval.
- Real ReMe model write/receipt crash-window side-effect idempotency remains
  untested end-to-end; journal ensures at-least-once, not universal exactly-once.
- Same Hermes profile / same journal accessed by multiple processes is
  unqualified; do not run multiple ReMe writer processes against same profile.
- FHM-006 v2 precompress fail-closed checkpoint, poisoning resistance, and
  future SkillHone / SkillOpt-Sleep promotion/rollback remain unqualified.
- Shared ReMe workspace between identities is NOT authorised; per-profile
  distinct workspace is required.
- ReMe Dream issues #659, #660, #661 and pending patches #664, #668; Dream
  remains disabled until independent qualification.
- User approval is mandatory for any live deployment or main merge.

## Exact next action

Complete remaining inherited ReMe CI and triage real failures only. In isolated
work, add deterministic tests of ReMe's real request_id replay receipts and
same-profile multi-process spool safety/lock strategy; then separately qualify
memory extraction through a safe local-model endpoint. Keep PR #1 draft and
issue #7 OPEN P1. Preserve existing Qwen / LM Studio worktrees and draft PRs.

## 2026-10-26 latest FHM-007 reliability checkpoint

- Full ReMe fork draft PR #1 now includes commit `fa93e09`; no main merge or production deployment.
- Cross-process same-profile single-writer lock is implemented and fails closed on contention. Linux competing process test PASS (`/tmp/fhm007/multiprocess-lock-host.log`). Windows implementation still requires CI qualification.
- ReMe real `Application.run_job` synthetic request-ID replay PASS. Combined focused provider and ReMe receipts test suite: **65/65 PASS** (`/tmp/fhm007/reliability-final-combined-host.log`).
- Cursor independent code review found no draft-PR blocker; not approved for production. Remaining: Windows CI, full LLM-backed memory extraction, arbitrary crash mid-agent action, FHM-006 precompress checkpoint, source provenance and memory-poisoning gates.
- Exact next action: inspect CI for `fa93e09`, remediate proven platform failures, rerun independent checks, then qualify model-backed memory through an authorised local endpoint. Keep Dream disabled and PR draft.

## 2026-10-26 final Stage 1 CI checkpoint

- ReMe draft PR #1 latest compatibility commit `a9e9d38` (docstring remediation after pylint failure). All **8/8** GitHub workflows on this commit PASS: Python quality, Python test matrix, Windows CLI smoke, packages, documentation, Docker, CodeQL, focused Fermes Stage 1 CI. Earlier failed runs belong to superseded commits, not unresolved current failures.
- Offline end-to-end synthetic capture workstream in separate worktree `fermes/fhm007-offline-capture-20261026`, based on `fa93e09`. Preliminary independent host run of the synthetic actual Hermes provider->ReMe AgentScope tool->saved daily note->restart->BM25 recall test PASS (`/tmp/fhm007/host-capture-first.log`). This test monkeypatches model transport; it is not a real LM Studio LLM test. Pending Cursor review and separate branch handback.
- Remaining production gates unchanged: authorised real model call, mid-write crash consistency, shared workspace protection, FHM-006 checkpoint, injection/provenance, background Dream and skill improvement safety. No active Hermes deployment or main merge.

## 2026-10-26 Stage 1 synthetic capture qualification (commit ab106af)

- ReMe fork draft PR #1 branch fermes/hermes-provider-stage1 now includes `ab106af00948a3319144e85827eb39ccf228bbfd`, adding a deterministic AgentScope model-transport substitution that leaves ReMe embedded backend, model tool execution, async file I/O, session provenance, durable journal, shutdown/restart and BM25 retrieval real. Test source `tests/unit/test_fermes_capture_integration.py` and qualification record `docs/fermes/CAPTURE-QUALIFICATION.md`.
- Authorised host **66/66** focused tests PASS (`/tmp/fhm007/all-stage1-host.log`). Ruff/Black and git diff whitespace PASS. New test uses dynamic UTC date (not pinned 2026-10-26), checks session source and retrieval path, and is included in `.github/workflows/fermes-reme-ci.yml` on ubuntu-24.04.
- Independent Cursor review `/tmp/fhm007/cursor-capture-review.log` found valid real provider/tool path, distinguished synthetic scripted model versus actual LLM extraction and recommended CI/date/source changes, all applied. The first Codex sandbox attempt failed to execute real async I/O; it was terminated rather than accepting a replacement mocked file/backend test. Main ReMe worktree clean, separate exploratory worktree preserved as evidence.
- GitHub ReMe CI triggered for `ab106af`, runs beginning 40310001274; statuses not yet verified PASS. Keep draft PR and issue OPEN; no merge/deploy or Dad-PC configuration changes.
- Next: check CI, remediate any concrete regressions, validate real local-model inference over an already-authorised model route when available. Remain blocked for FHM-006 pre-compaction fail-closed, memory poisoning, provenance trust, mid-agent partial-crash semantics, and future SkillHone/SkillOpt-Sleep policy.

## Verified CI closure for Stage 1 synthetic gate

- ReMe commit `ab106af`: all eight GitHub PR workflows PASS, including Windows, Python quality, Python tests, CodeQL, Docker and Fermes Stage 1 Ubuntu CI.
- Dedicated Fermes Ubuntu 24.04 workflow run `40310001274`: **66 passed in 18.54s**. Test creates and recalls a synthetic memory using actual ReMe provider/storage and deterministic model transport; no real LLM inference claim.
- Project Coordinator inspected for existing LM Studio local listener/tunnel; no active model listener/tunnel identified. Do not alter Dad-PC binding or firewall without explicit security authorisation.
- Stage 1 integration accepted as a **draft-only evidence milestone**, not production or full FHM-007 acceptance. Issue #7 remains OPEN P1 and ReMe fork PR #1 remains unmerged.

## 2026-10-26 security-boundary and checkpoint-design checkpoint

- ReMe fork draft PR #1 latest pushed HEAD `d19ef09caba295e749566e3e3d14e12680b40f67` (implementation/test `bdcd2c151bb5cdf3e22870f70d6b598783d2e5ff`). Existing file/BM25 engine retained; no Dream/SQLite/new vector, no production changes.
- Project Coordinator authorised host three-suite test command: **67 passed in 15.27s** (baseline 66); log `/tmp/fhm007/poisoning-full-host.log`. New synthetic hostile-source test uses real ReMe BM25 retrieval and maintained Hermes MemoryManager/context fence plus output scrubber. It proves passive recall/fence behaviour only, NOT real-model resistance to prompt injection, not complete top-level turn composition or skill-promotion safety.
- Independent Cursor source review: `/tmp/fhm007/cursor-security-review.log` and `/tmp/fhm007/cursor-security-final-review.log`. Findings: prior qualification matrix had mixed sandbox-vs-host conclusions; clarified in `docs/fermes/INTEGRATION-QUALIFICATION.md`. A security test skip without Hermes on PYTHONPATH cannot count as PASS; dedicated Fermes CI checks out Hermes. Raw memory source session metadata is not cryptographically signed and not all metadata is necessarily present in recall text.
- Proposed checkpoint design (not enabled): `docs/fermes/FHM006-CHECKPOINT-GAP.md`. Existing ReMe provider stays v1. Hermes-side v2 currently treats a non-raising provider as checkpoint success; design requires durable fsync-backed scoped receipt, evidence hash validation, bounded synchronous operation and fail-closed abort before v2 marker can be enabled. Material host/API changes require review and owner approval.
- GitHub `Fermes ReMe Stage 1 CI` for `d19ef09` PASS, run 40312513379. At initial checkpoint other inherited checks were still running. Track actual CI conclusion before claiming all green.
- Model gate: Dad-PC LM Studio is healthy but bound to 127.0.0.1:1234; Project Coordinator had no active authorised tunnel detected. No firewall/bind change made or approved. Genuine model-generated Hermes memory extraction remains outstanding.
- Exact next action: reconcile GitHub CI on `d19ef09`; preserve draft PR and FHM-007 OPEN P1. Then resolve workspace-ownership and FHM-006 checkpoint trust-boundary design through controlled architecture review, and qualify local-model extraction via an authorised endpoint without changing Dad-PC firewall/binding automatically. Keep other Fermes PRs/worktrees untouched.
