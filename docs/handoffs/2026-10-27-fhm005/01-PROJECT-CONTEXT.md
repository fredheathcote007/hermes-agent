# 01 — Project context and operating contract

## Objective

Make Fermes Hermes able to truthfully say an autonomous worker's task is COMPLETE only when an **independently trusted verifier** has checked the actual effect against the correct attempt, authority, scope and acceptance criteria. Missing/stale/untrusted/failed/unobservable evidence must yield INCOMPLETE/BLOCKED, never success. Some prose-only tasks need other suitable evidence; not all work should be forced through build/test suites.

Repository: https://github.com/fredheathcote007/hermes-agent (maintained fork of NousResearch/hermes-agent).
Tracked parent: https://github.com/fredheathcote007/hermes-agent/issues/5 (P0/open).

## In scope

- Protected service/controller and independent outcome authority.
- Authenticated legitimate Hermes parent and constrained delegated workers (Codex and other agents).
- Native Linux and Windows verifier and isolation components in the **initial qualified release**.
- Per-attempt immutable identity, policy/nonce/freshness and protected one-use receipts; crash-consistent fail-closed states.
- Real local artefact, Git/CI and provider-specific external-effect checks; no replay when remote outcomes are uncertain.
- Correct status projection in parent, CLI, TUI, gateway and ACP; anti-forgery, replay, late-write, no-op and lifecycle tests.
- Independent security review, reproducible exact-SHA CI, native adversarial tests, operator runbooks and rollback.

## Not in scope without additional approval

- Protection against a fully compromised local root/Administrator (excluded from initial threat boundary).
- Installing or enabling a privileged controller/service, changing host ACLs, service accounts, sandbox binaries, credentials, production routing or default-on verification.
- Assuming same-user SQLite, client-supplied trusted_source=True, successful test exit, or an LLM's text is authoritative verification.
- Changing unrelated FHM-007 ReMe/memory work; conflating the Ideas/Hindsight project or project-coordinator state with fermes-hermes.

## Approved architecture direction

Three logical roles: **protected controller** (only trusted verification/receipt authority), **separately authenticated parent** (legitimate orchestration requester) and **low-privilege, disposable worker/executor** (never gains controller rights). Malicious delegated workers and other unprivileged processes, including same-user impersonators, are in scope. When true independent verification is unavailable, operator/manual or external attestation is the fallback.

Exact local IPC/capability, service packaging, protected receipt issuance, worker isolation and policy are still architecture choices awaiting approval/native assurance. The user has not approved a privileged deployment.

## Working conventions

- British English; BLUF and evidence first; clearly label Confirmed / Approved / Risk / Unknown / Next check.
- Use GitHub as source of truth for issues, PRs, exact SHAs and CI; use docs/fermes/memory and draft architecture records for decisions. Treat stale copy in an unmerged branch cautiously.
- Codex primary developer and Cursor independent reviewer. Implement in separate worktrees, keep parent branches current, review, test, remediate, re-review, then merge eligible changes. Update issues with P0 priority and close only when the narrow acceptance definition is proven.
- No fake background progress. Use bounded agent invocations and close stdin to avoid historical Codex/harness hangs. Reuse known successful tests; validate exact candidate, native platform and operational effect separately.
