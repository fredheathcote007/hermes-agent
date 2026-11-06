# 02 — Confirmed facts, approved decisions and unresolved approvals

**Verified snapshot:** 27 October 2026 around 12:25 Perth, from connected GitHub and authorised Project Coordinator; recheck live state in the new chat.

## Confirmed

| Item | Evidence / meaning |
|---|---|
| GitHub fork | https://github.com/fredheathcote007/hermes-agent; project_id fermes-hermes in MEMORY-INDEX.md |
| FHM-005 parent remains P0/open | https://github.com/fredheathcote007/hermes-agent/issues/5 |
| Phases 1/E2E merged | PR #21 and #22; opt-in fail-closed groundwork, not trusted independent authority |
| Source-only contracts merged | PR #26 receipt DTO, PR #31 attempt state machine |
| POSIX observation merged | PR #33; Windows path explicitly unsupported in this helper |
| SQLite receipt model merged | PR #40; one-use CAS is non-authoritative in a same-user Python process |
| TUI false-success correction merged | PR #24; **this supersedes earlier notes that #24 was draft** |
| New hardening PR exists | PR #42: draft/open at head 7dbdb69f7487a5868cf8d355461defea803a4617; CI #40449660701 in progress when checked |
| Design/ARB/sandbox docs still draft | PR #23, #25, #39 unmerged as of the snapshot; #25 and #39 exact-head CI passed |
| Owner asked to continue using Codex and Cursor | Codex implements, Cursor independently reviews PRs before merge |
| No trusted verifier released | No authenticated controller service, service-owned evidence authority or native both-platform security qualification proven |

## Approved decisions (user-authorised)

| ID | Decision | Consequence |
|---|---|---|
| DEC-004 | **Fail closed** for unverified delegated/external effects; no automatic replay of uncertain effects | Neither worker prose, terminal admission, status field nor untrusted ledger may mark COMPLETE. |
| DEC-005 | **Linux and Windows together** for first trusted-verifier release | A Linux-only build and simulated Windows tests cannot qualify release. |
| DEC-006 | **Option A** protection against compromised delegated/unprivileged workers; **Option B** manual/external fallback. Full local root/Administrator compromise outside initial guarantee. | Protected trust boundary mandatory; explicit UNKNOWN when independent proof unavailable. |
| DEC-007 | Owner explicitly approved **protected controller / authenticated parent / restricted worker** separation as design baseline. | Same-user impersonation prevention mandatory; exact OS mechanism still unapproved. |

Approved decisions are recorded under docs/fermes/memory/DECISIONS.md in **draft PR #23**. The currently merged base branch may still expose an older decision index containing only DEC-004. Do not mistake an unmerged documentation branch for revoked owner approval.

## Proposed / not approved

- DR-02 **concrete** same-user-resistant caller authentication, OS identities, Unix socket/named-pipe ACLs/capability.
- DR-03 native controller lifecycle/service packaging and restricted executor deployment.
- DR-04 protected receipt ownership, atomic issuance/consume and restart/commit-failure semantics as **trusted service**.
- DR-05–DR-07 effect verification, policy, retention, operational recovery and release details per draft design.
- Privileged installation, host security changes, default-on, production deployment and acceptance of unresolved High/Critical risks.

## Rejected / superseded

- **Rejected** trusting same-user worker-written SQLite, tool logs, arbitrary validated JSON or public Python DTOs as independent proof.
- **Rejected** allowing untrusted project shell recipes to execute as controller.
- **Rejected** replaying uncertain external effects or treating missing telemetry as no side effects.
- **Superseded:** earlier status that PR #24 was draft. It is now merged (PR #24 merge 97c5a51eff68598bc209c0ab716c991f6fa19635).
- **Refuted finding:** the initial Cursor claim that omitting correlation_id from a SQLite UNIQUE key permits same-key duplicate issuance. Tests proved the contrary; Cursor follow-up confirmed closure in PR #40.

## Risks / unknowns

**Risk:** the locally installed Ubuntu 26.04 Bubblewrap 0.11.1-1ubuntu0.3 is associated with the reverted fix for CVE-2026-87766. See GHSA-pxhw-h44j-8pfx, Ubuntu USN-8779-2, P0 issue #38 and draft PR #39. Threat applicability depends on setup arguments and attacker-controlled filesystem paths; no exploitation or compromise has been established. No live package change authorised.

**Risk:** current POSIX file observations do not prove safety against same-device bind mounts, fully restored TOCTOU or unbounded FUSE/kernel read stalls. Windows native file-ID/reparse-safe implementation is not built.

**Risk:** PR #42's open_for_live_generation API is explicitly caller-controlled and may bypass reconciliation if wired into untrusted callers. It is not authentication. Keep source-only until independent controller liveness authority exists.

**Unknown:** exact final same-user-resistant mechanism, native Windows test environment/service deployment configuration, external provider effect coverage and operator residual risk acceptance.
