# 05 — Files, URLs and evidence access

**Access rule:** these links are source locators, not guaranteed access in the new chat. Connect the relevant GitHub plugin and, for host-only logs, connect the Project Coordinator Remote Desktop Commander. If unavailable, ask for the exact file or evidence rather than inventing it.

## Canonical repo sources

| Evidence | Purpose / status | Where | New-chat access |
|---|---|---|---|
| Identity index | Verify project isolation before commands | docs/fermes/memory/MEMORY-INDEX.md, repo | Re-fetch from GitHub |
| DECISIONS.md | Approved DEC-004..DEC-007 | docs/fermes/memory/DECISIONS.md in draft PR #23 | Fetch PR #23 branch; merged base may be stale |
| ARB-REVIEW-20261027.md | Original 17-role ARB evidence and dissent | docs/fermes/architecture/fhm005/ in draft PR #23 | Re-fetch; don't repeat completed ARB |
| TRUST-BOUNDARY-CANDIDATE.md | Security model and parent impersonation gate | docs/fermes/architecture/fhm005/ draft PR #23 | Re-fetch |
| DETAILED-DESIGN-CANDIDATE.md | Proposed Linux/Windows controller design | docs/fermes/architecture/fhm005/ draft PR #25 | Re-fetch |
| ADR-DR02-DR07-CANDIDATE.md | Open material choices, approvals and alternatives | docs/fermes/architecture/fhm005/ draft PR #25 | Re-fetch |
| IMPLEMENTATION-MANIFEST.json | 17-task dependency graph | docs/fermes/architecture/fhm005/ draft PR #25 | Re-fetch |
| IMPLEMENTATION-STATE.md | Source-only status and next gates | docs/fermes/architecture/fhm005/ draft PR #25, stacked PR #39 includes sandbox update | Re-fetch and reconcile |
| VALIDATION-PLAN.md | Required native adversarial and regression matrix | docs/fermes/architecture/fhm005/ draft PR #25 / #39 | Re-fetch |
| SANDBOX-DEPENDENCY-SECURITY-20261027.md | CVE preflight, non-setuid host and safe alternatives | docs/fermes/architecture/fhm005/ draft PR #39 | Re-fetch |
| FHM-005-RECEIPT-CAS-CANDIDATE.md | Source-only receipt model and PR #42 hardening | docs/fermes/reliability/ in PR #42 branch | Re-fetch |
| FHM-005-TRUSTED-VERIFICATION-CONTRACT.md | DTO and state-machine limitations | docs/fermes/reliability/ merged fork | Re-fetch |
| FHM-005-ARTIFACT-IDENTITY-CANDIDATE.md | POSIX observation and Windows pending | docs/fermes/reliability/ merged fork | Re-fetch |

## GitHub issues / PRs to query first

- Parent FHM-005: https://github.com/fredheathcote007/hermes-agent/issues/5 — OPEN/P0.
- Protected receipts IMP-003: https://github.com/fredheathcote007/hermes-agent/issues/36 — OPEN/P0.
- Sandbox dependency: https://github.com/fredheathcote007/hermes-agent/issues/38 — OPEN/P0.
- PR #42: https://github.com/fredheathcote007/hermes-agent/pull/42 — DRAFT, needs exact-head CI and independent Cursor review; CI last seen in progress.
- PR #23: https://github.com/fredheathcote007/hermes-agent/pull/23 — DRAFT ARB.
- PR #25: https://github.com/fredheathcote007/hermes-agent/pull/25 — DRAFT detailed blueprint, CI success.
- PR #39: https://github.com/fredheathcote007/hermes-agent/pull/39 — DRAFT sandbox evidence, CI success.
- Completed source: PRs #21, #22, #24, #26, #31, #33, #40 MERGED; do not reopen implementation from scratch.
- Adjacent: FHM-017 and FHM-018 issues, upstream Hermes compatibility FHM-011. Do not change FHM-007.

## Device-local test/review evidence (must be re-fetched; not attached)

| Log | Evidence | Accessibility |
|---|---|---|
| /tmp/fhm005-imp003-cursor-review-20261027.log | Initial Cursor SQLite candidate review | Project Coordinator Remote Desktop only |
| /tmp/fhm005-imp003-cursor-recheck-20261027.log | Refuted UNIQUE/correlation concern | Project Coordinator |
| /tmp/fhm005-imp003-host-hardened-tests.log | 73 tests from PR #40 candidate | Project Coordinator |
| /tmp/fermes-fhm005-sandbox-cursor-review-20261027.log | PR #39 docs-only independent review | Project Coordinator |
| /tmp/fhm005-imp002-cursorfix-tests.log | PR #33 82 tests | Project Coordinator |
| /tmp/fhm005-pr33-cursor-recheck-20261027.log | PR #33 follow-up Cursor review | Project Coordinator |
| /tmp/fhm005-pr31-recheck-review.log | PR #31 later worker-state review | Project Coordinator |
| /tmp/fermes-fhm005-durability-codex.log | Historical old worktree sandbox hang and 32 focused tests; NOT current qualification | Project Coordinator |

PR #42 local worktree at /srv/project-coordinator/projects/fermes-hermes-fhm005-imp003-hardening-20261027. PR body claims 114 host tests PASS; inspect the current exact run and independent review evidence before treating that as complete. The worktree was clean at snapshot.

## Authoritative public vendor references (verify freshness)

- Bubblewrap advisory: https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx
- Ubuntu notice: https://ubuntu.com/security/notices/USN-8779-2
- Native Linux openat2 documentation: https://man7.org/linux/man-pages/man2/openat2.2.html
- SQLite transactional and WAL docs: https://www.sqlite.org/lang_transaction.html and https://www.sqlite.org/wal.html
- Microsoft Windows Job Objects: https://learn.microsoft.com/windows/win32/procthread/job-objects
- Microsoft file identity and reparse-point APIs: https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_id_info

## Handoff-file availability

This continuation pack is stored in a new **docs-only GitHub draft PR branch** under docs/handoffs/2026-10-27-fhm005. The new chat must re-fetch it via connected GitHub or paste NEW-CHAT-PROMPT.md. It is not represented as a synced Google Drive file, a downloaded archive or a mounted Project file.
