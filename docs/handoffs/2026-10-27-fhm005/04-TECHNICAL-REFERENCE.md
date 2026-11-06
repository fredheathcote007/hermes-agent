# 04 — Technical reference and guardrails

## Git and machine

- Maintained repository: https://github.com/fredheathcote007/hermes-agent
- Qualified branch: fermes/qwen-lmstudio-v0225-20261026
- **Current qualified branch remote SHA at handoff:** 97c5a51eff68598bc209c0ab716c991f6fa19635 (merged PR #24). Re-fetch, never assume this remains latest.
- PR #42 head: 7dbdb69f7487a5868cf8d355461defea803a4617; draft branch fermes/fhm005-imp003-hardening-20261027; current CI #40449660701 was in progress at handoff.
- Authorised Linux host: Project Coordinator (proj-coord), Remote Desktop Commander device ID 3cd57240-7d29-4c24-a154-5ec82b9c31cb. Device connectivity is not guaranteed in a different chat.
- Repository clone/worktrees under /srv/project-coordinator/projects/. Inspect worktrees for concurrent developers before writes.
- Project ID gate: docs/fermes/memory/MEMORY-INDEX.md, project_id: fermes-hermes.
- Owner prefers Codex as primary coding agent and Cursor for independent PR review; do not use Cursor for primary coding by default.

## Important existing worktrees (confirmed)

| Purpose | Path | Last observed commit |
|---|---|---|
| PR #42 candidate | /srv/project-coordinator/projects/fermes-hermes-fhm005-imp003-hardening-20261027 | 7dbdb69f |
| Base receipt-model PR #40 | /srv/project-coordinator/projects/fermes-hermes-fhm005-imp003-20261027 | e2b9aaee |
| Detailed design PR #25 | /srv/project-coordinator/projects/fermes-hermes-fhm005-detailed-design-20261027 | f2a6f089 |
| ARB PR #23 / DEC-007 | /srv/project-coordinator/projects/fermes-hermes-fhm005-arb-20261027 | f00f1ebc |
| Sandbox docs PR #39 | /srv/project-coordinator/projects/fermes-hermes-fhm005-sandbox-research-20261027 | 218e9013 |
| POSIX observation | /srv/project-coordinator/projects/fermes-hermes-fhm005-artifact-identity-20261027 | 687012c4 |
| Attempt state machine | /srv/project-coordinator/projects/fermes-hermes-fhm005-state-machine-20261027 | 7cd062fb |
| Separate memory workstream — DO NOT MODIFY | /srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007 | 703b08c9 |

## Source modules and their security significance

| File | Currently implements | Does NOT prove |
|---|---|---|
| agent/trusted_verifier_contract.py | Strict request/receipt DTO and non-authoritative validation; rejects forged/stale/foreign/malformed claims | Independent trusted caller/provenance |
| agent/trusted_verifier_attempt.py | Pure monotonic attempt state and crash/late-event rules | Protected or durable state machine |
| agent/verification_artifacts.py | Bounded Linux POSIX nofollow descriptor-based observations | Immutable files after observation; complete mount isolation; native Windows |
| agent/trusted_verifier_receipt_store.py | SQLite candidate one-use receipt CAS and restart states | Protected issuance, service identity, independent effect success |
| tui_gateway/prompt_turn.py | Display failure/unresolved rather than falsely COMPLETE (PR #24 merged) | Gateway/ACP/CLI status parity or trusted verifier |
| agent/verification_evidence.py and hermes_cli/verify_cmd.py | Existing same-user ledger/diagnostics | Authoritative independent receipt. Do not promote as trusted. |
| agent/verify/runner.py | Project-supplied shell recipes (shell=True) | Safe to run under protected controller; MUST NOT. |

## PR #42 specific design

Code changes: candidate receipt store, tests and receipt CAS documentation. Core hardening:

- Opening an existing SQLite database requires explicit reconcile_after_restart or a separately authorised live-generation join before issue/consume.
- Commit-outcome failures make the candidate store fail closed; subsequent operations on invalidated handle must be rejected.
- Parent-symlink pathname checks, stronger generation bounds, erroneous stored state, clock rollback and crash-injection negative tests.
- **Critical limit:** open_for_live_generation() accepts caller-provided generation. It is **not authentication**, and if an untrusted caller can invoke it, it can bypass reconciliation. Do not expose it to runtime until protected controller authenticates liveness, source and generation.
- PR body reports 114 focused host tests PASS; recheck exact-head CI and independent Cursor review before merge.

## Approved controller security model (principle only)

- Protected controller performs final verification and owns receipts; no untrusted project scripts executed at controller privilege.
- Authenticated Hermes parent must resist same-user unprivileged impersonation. Unix peer UID or Windows user SID alone does **not** establish authorised parent identity if processes share it.
- Restricted low-trust worker/effect executor; control descendants and late effects; fail closed for uncertain remote actions.
- SQLite WAL + synchronous=FULL and conditional atomic compare-and-swap are credible *building blocks*, but only protected ownership and native tests establish trust.
- Linux candidate uses OS service identity, peer authentication and filesystem/cgroup isolation; evaluate openat2 RESOLVE_* flags for stronger path control. Windows candidate uses SCM service SID, explicitly secured named pipe, restricted tokens, Job Objects and native volume/file-ID/reparse-point handling.
- The initial release needs real native Linux **and** Windows tests on the same candidate, including symlink/junction, impersonation, replay, late writes, crash/restart, denied egress and privileged identity boundary.
- External provider effects (e.g. GitHub commits or SaaS writes) need independent read-back and reconciliation; no auto-repeat if outcome unknown.
- Current Project Coordinator Ubuntu 26.04 has Bubblewrap 0.11.1-1ubuntu0.3, non-setuid; issue #38 assesses the reverted CVE-2026-87766 patch. Do not qualify hostile-worker isolation using it without approved remediation.

## Testing and troubleshooting patterns

- GitHub Actions exact-SHA checks are authoritative for hosted CI, not branch-green from an older commit.
- Host pytest environment used in previous work: /home/fred/.hermes/installs/68fc13a80951fcd6/test-environment/gen-e2914a30739c442cb49b28cbd98ff7b0/venv/bin/python
- Host tests used TMPDIR=/home/fred/.cache/fermes-pytest-tmp, pytest -p no:cacheprovider, explicit timeout and process clean-up.
- Historical failures: Codex sandbox /var/tmp read-only and HomeIOGuard wrappers around os.open/os.stat. Re-run real tests on authorised host; do not bypass security prechecks or declare PASS from a sandbox error.
- Review PR head/diff, then have Cursor review in READ ONLY, fix with Codex, re-run tests and re-review. Do not treat 'cursor review' comment alone as evidence of a review result.
