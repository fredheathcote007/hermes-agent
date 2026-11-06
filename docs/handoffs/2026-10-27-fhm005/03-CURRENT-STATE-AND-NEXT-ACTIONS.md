# 03 — Current state and exact next actions

## BLUF

The completed source-only foundations do not add up to a trusted verifier. The **immediate job** is PR #42 exact-head Cursor/security review, red/green regression and hosted CI on the current SHA, then safe source-only merge decision. Keep issues #5, #36 and #38 OPEN/P0. Resolve DR-02/04 material security design before enabling or installing protected authority.

## Current PRs (live checked ~12:25 Perth, 27 Oct 2026)

| PR | State | Scope |
|---|---|---|
| [#21](https://github.com/fredheathcote007/hermes-agent/pull/21), [#22](https://github.com/fredheathcote007/hermes-agent/pull/22) | MERGED | Phase-one fail-closed and one-shot E2E groundwork |
| [#26](https://github.com/fredheathcote007/hermes-agent/pull/26) | MERGED | Non-authoritative versioned request/receipt contract; 77 focused host tests passed at qualification |
| [#31](https://github.com/fredheathcote007/hermes-agent/pull/31) | MERGED | Non-authoritative attempt state machine; 56 focused host tests and follow-up independent review |
| [#33](https://github.com/fredheathcote007/hermes-agent/pull/33) | MERGED | Linux POSIX artefact observations; 82 focused host tests and Cursor review |
| [#40](https://github.com/fredheathcote007/hermes-agent/pull/40) | MERGED | Non-authoritative SQLite receipt CAS; 73 focused host tests and Cursor review |
| [#24](https://github.com/fredheathcote007/hermes-agent/pull/24) | MERGED | TUI unresolved-verification false-success fix, merge 97c5a51e |
| [#42](https://github.com/fredheathcote007/hermes-agent/pull/42) | **DRAFT/OPEN** | Receipt-store reopen barrier, ambiguous commit invalidation, join-generation, symlink-parent checks. Head 7dbdb69f7487a5868cf8d355461defea803a4617. CI #40449660701 IN PROGRESS at last check; no final exact-head Cursor review yet. PR body reports 114 focused host tests PASS on exact head. |
| [#23](https://github.com/fredheathcote007/hermes-agent/pull/23) | DRAFT/OPEN | Full 17-role ARB evidence and DEC-005/006/007 decisions |
| [#25](https://github.com/fredheathcote007/hermes-agent/pull/25) | DRAFT/OPEN | Linux/Windows detailed candidate design and 17-task implementation manifest. Head f2a6f089c4463794a48446bf40f5a85d3391fd59; hosted CI PASS |
| [#39](https://github.com/fredheathcote007/hermes-agent/pull/39) | DRAFT/OPEN | Bubblewrap advisory and qualification gate; head 218e9013d7e9c9af60c8781222c43fbc78440859; CI PASS, Cursor docs-only review no P0/P1 |

## Current issues

- [#5](https://github.com/fredheathcote007/hermes-agent/issues/5) FHM-005 P0 OPEN; real protected verifier not released.
- [#36](https://github.com/fredheathcote007/hermes-agent/issues/36) FHM005-IMP-003 P0 OPEN; source-only SQLite candidate merged, authoritative protected store not complete.
- [#38](https://github.com/fredheathcote007/hermes-agent/issues/38) P0 OPEN; Bubblewrap vulnerability/hostile-worker qualification.
- [#27](https://github.com/fredheathcote007/hermes-agent/issues/27) IMP-001 CLOSED source-only; [#35](https://github.com/fredheathcote007/hermes-agent/issues/35) IMP-002 CLOSED source-only.
- Adjacent risks: FHM-017 repeated successful mutating actions, FHM-018 timeouts/late effects. FHM-011 upstream compatibility has its own parallel workstream; avoid overlap.

## Exact next actions

1. **First** reconstruct PR #42 live state, exact SHA, CI, Cursor/Bugbot review comments, worktree cleanliness and other active processes. Review the explicit open_for_live_generation bypass limitation and the ambiguous commit/restart recovery tests.
2. Request independent **Cursor** exact-head review of PR #42. Codex implements required fixes; rerun focused and full relevant tests, Ruff, compile, negative concurrency and crash-injection tests. Cursor re-reviews before merge. Keep source-only.
3. Merge PR #42 only if exact-head hosted CI is green, reviewer has no blocking findings, change impact is bounded, and repo rules permit. Otherwise leave draft and record precise blocker. **Do not treat merge as trusted service acceptance.**
4. Reconcile draft PR #23/25/39 bases and evidence and consider docs-only promotions after review, without prematurely signing off unapproved DR-02..07. Preserve decision records and other workstreams.
5. Prepare evidence-backed DR-02/DR-04 design choices: protected controller identity, authenticated parent resistant to same-user impersonation, protected receipt DB and boot reconciliation. Route material choices to ARB/owner before any OS privileged write.
6. In disposable environment, qualify patched Linux containment vs Bubblewrap issue #38 and build native Windows service SID/named pipe/reparse file identity/Job Object tests on same approved security candidate.
7. Implement protected controller plus effect-specific authoritative checks (GitHub/Git/CI, files, external API provider read-back), and parent/CLI/TUI/gateway/ACP status parity. Run native Linux and Windows full negative/E2E verification; issue #5 stays P0/open until then.
8. Update GitHub issues/PRs and existing canonical project memory with exact evidence and next state. Do not restart completed 17-role ARB.

## Stop conditions

Stop before production deployment, host permission/service changes, credential use, accepting High/Critical residual security risk or promoting unauthenticated Python/SQLite into trusted authority. Request explicit owner approval for these material boundaries.

## Failure history / useful lessons

- Cursor CLI sometimes returns resource_exhausted; retry bounded or use PR 'cursor review' Bugbot trigger, but **do not claim review PASS without an actual report**.
- Codex sandbox sometimes cannot use the full test runner because of /var/tmp and HomeIOGuard filesystem wrappers. An authorised host rerun gave actual evidence; no loosening security checks just to make tests green.
- The selected Bubblewrap Ubuntu package is not an accepted hostile-worker sandbox; no unisolated exploit testing on the Project Coordinator.
- A long-running legacy Codex sandbox process exists (PID 3746650 and descendants at last check, over 16 hours), apparently stuck on an older worktree. Inspect ownership and scope before stopping it. Do not count its historical 32 tests or sandbox hang as current exact-SHA acceptance.
