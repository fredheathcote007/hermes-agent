# New chat prompt — continue FHM-005 (Fermes Hermes)

Continue **FHM-005 independent trusted outcome verification** in the maintained fork: https://github.com/fredheathcote007/hermes-agent , parent https://github.com/fredheathcote007/hermes-agent/issues/5 . **project_id: fermes-hermes.**

**First read the GitHub-backed handoff at docs/handoffs/2026-10-27-fhm005/00-START-HERE.md and its other files**, then the canonical repo docs/fermes/memory/MEMORY-INDEX.md. Stop on project identity mismatch. Fetch the latest issue/PR/CI/source state; the handoff is a snapshot, not authority over newer evidence.

**Goal:** progress FHM-005 to a protected, independently verified, native Linux+Windows capability. Use **Codex as primary developer, Cursor for independent review of each PR**, fixing P0/P1 findings and asking Cursor to re-review before merge. Keep project issues prioritised, current and closed when their specific acceptance is proven.

**As of 27 Oct 2026 ~12:25 Perth:**
- **PRs #21, #22, #24, #26, #31, #33, #40 are MERGED** into the qualified Fermes branch. These provide opt-in fail-closed work, TUI status fix, non-authoritative request/receipt and attempt contracts, POSIX observation and SQLite candidate one-use CAS. **None is a trusted verifier.**
- **Draft PR #42** https://github.com/fredheathcote007/hermes-agent/pull/42 head **7dbdb69f7487a5868cf8d355461defea803a4617**, CI run **40449660701** was **IN PROGRESS** at last check. It hardens restart reconciliation and ambiguous commit handling, but has a deliberately *untrusted* caller-supplied live-generation join API. PR says 114 focused tests PASS. Exact-head **Cursor independent review still required**.
- **Draft PR #23** is 17-role ARB evidence and owner-approved DEC-004..DEC-007. **Draft PR #25** is the 17-task Linux/Windows design, CI green. **Draft PR #39** is the Bubblewrap CVE-2026-87766 security gate, CI green and Cursor reviewed.
- Parent [#5](https://github.com/fredheathcote007/hermes-agent/issues/5), IMP-003 [#36](https://github.com/fredheathcote007/hermes-agent/issues/36) and Linux sandbox [#38](https://github.com/fredheathcote007/hermes-agent/issues/38) remain **OPEN P0**. IMP-001 #27 and POSIX-only IMP-002 #35 are closed as bounded source-only milestones.

**Approved owner decisions:**
- DEC-004 fail closed; no automatic replay of uncertain external effects.
- DEC-005 **native Linux AND Windows** together for the first trusted-verifier release.
- DEC-006 **Option A** protect against compromised unprivileged workers, **Option B** manual/external fallback if independent automation unavailable; privileged root/Administrator compromise out of scope initially.
- DEC-007 protected **controller / authenticated legitimate parent / restricted worker** separation, resisting same-user impersonation. **Only the principle approved**; DR-02 precise auth and DR-03..07 protected service/receipt/effect/release design, privileged installation and risk acceptance remain **unapproved**.

**Exact first action:**
1. Inspect **PR #42 current head and CI** plus any Cursor/Bugbot review, local worktree and concurrent work. Do not duplicate the PR #40 candidate. Request **independent Cursor exact-head code/security review** focusing on whether restart reconciliation can be bypassed by open_for_live_generation, ambiguous commit invalidation, symlink parents, replay/foreign generation and hostile process access. Have Codex fix actual issues in isolated scope and rerun negative tests and hosted exact-head CI; Cursor re-review. Merge only if source-only gates pass. **Never treat successful candidate SQLite consumption as trusted completion.**
2. Reconcile PR #23/#25/#39 docs/decisions and open security issues after review. Preserve unmerged owners' decisions; avoid accidental drift in default branch docs.
3. Prepare/resolve concrete DR-02/04 with evidence-backed design and owner/security approval before any privileged controller or production security changes; then build/qualify Linux and Windows native isolated test environments (including patched/qualified Bubblewrap).
4. Implement independent effect read-back, protected receipt authority and parent/CLI/TUI/gateway/ACP status projection; test malicious workers, same-user process spoofing, duplicate/late effects, crash recovery, remote uncertainty, no-op and external provider effects.

**Hard constraints:** No FHM-007 edits; no privileged service, package upgrades, ACL/security-policy changes, credentials, default-on or deployment without explicit owner authorisation. Do not rely on old same-user SQLite or CLI hermes verify to mint trusted receipts. Native Windows absence cannot be waived. Use British English, BLUF, exact evidence/risks/rollback. Document work in GitHub Issues and canonical docs, preserving current branches. Bounded Codex/Cursor processes; old stuck sandbox process exists and must not be counted as acceptance.

**First response:** Give the current objective, latest verified status, three most important constraints, and immediate next execution action; then proceed with the task rather than redoing prior research.
