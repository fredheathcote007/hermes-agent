# security-cross

92,483
## Consolidated cross-review

Scope: baseline `de83ce3b`; PR #21/#22 unmerged; no edits. DEC-004 remains the controlling policy: missing, stale, untrusted, or unobservable proof is incomplete—not success.

Consensus was unusually strong: the current ledger is diagnostic, not independent proof; untrusted project code must not execute with verifier authority; and Linux-only evidence cannot qualify a Linux/Windows release. Dissent is preserved where material.

1. **FHM005-C01 — Critical — Completion authority is forgeable**

   Facts: `record_verify_run()` accepts caller-supplied `ok`, root, session, scope, and output, then writes a profile-local SQLite row (`agent/verification_evidence.py:487`). The CLI obtains session identity from `HERMES_SESSION_ID` and suppresses persistence failures (`hermes_cli/verify_cmd.py:83`). Same-identity worker code can therefore forge or replay `kind=verify, status=passed`.

   Decision: Existing SQLite rows must never satisfy trusted completion. Only a separately authorized verifier may mint admissible receipts.

   Mitigation/test: Service-owned receipt storage, authenticated local IPC, per-attempt nonce, exact parent binding, freshness, and replay rejection. Direct SQLite insertion, row editing, wrong-session/root receipts, and duplicate replay must all remain unresolved on both OSes.

2. **FHM005-C02 — Critical — Broker/worker privilege confusion**

   Facts: recipes and `.hermes/environment.json` are project-controlled; commands execute with `shell=True`, inherited environment, project-root access, bootstrap/install/build/test/start phases (`agent/verify/runner.py:4`, `:93`). A different service identity is insufficient if it runs hostile tests under that identity.

   Decision: Project-authored tests may not run with receipt authority, verifier credentials, or privileged filesystem access.

   Mitigation/test: Two-tier design: trusted broker/controller plus disposable lower-privilege executor. Malicious manifests/tests must attempt secret reads, outside-root writes, receipt-store/IPC access, verifier binary modification, shell injection, and detached descendants; no trusted receipt may be minted.

3. **FHM005-C03 — High — Scope, cross-session state, and TOCTOU are not authoritative**

   Facts: evidence is bound primarily to textual root, timestamps, and paths; no artifact/tree digest, command digest, immutable generation, or attempt nonce exists. A full pass rewrites and clears other sessions’ state (`agent/verification_evidence.py:535`), and lookup selects the newest full pass for a root (`:587`).

   Contradiction: several reviewers describe this as an immediate foreign-session false-success; Identity/AppSec note the finalizer’s same-session check may block that exact path (`agent/verification_stop.py:136`). The durable state corruption and future-policy exposure are confirmed even if the direct bypass is not.

   Response: retain High, release-blocking status, but do not claim a proven direct bypass. Use per-attempt receipts bound to canonical root, exact changed artifacts/content hashes, parent attempt, and post-child generation. Never mutate another session’s pending state.

4. **FHM005-C04 — High — Completion status can contradict fail-closed policy**

   Facts: unresolved work produces `completed=false`, `failed=true`, and `verification_unresolved=true`; TUI status reduction checks only interruption/error and can return `"complete"` (`tui_gateway/prompt_turn.py:311`). Malformed/missing child messages become an empty trace (`tools/delegate_tool_child_run.py:563`), potentially resembling “no effects.”

   Decision: `verified`, `failed`, `unknown/incomplete`, and `verifier unavailable` must be distinct machine and UI states.

   Mitigation/test: Status must prioritize unresolved/failed before success. Missing, truncated, unpaired, or late telemetry must remain pending; clients must show “inspect before retry,” with no automatic replay.

5. **FHM005-C05 — High — Process containment and late effects are unqualified**

   Facts: phase timeout uses `subprocess.run` and does not establish descendant ownership; Windows teardown targets only the direct child (`agent/verify/runner.py:127`). A descendant can mutate files or retain ports after apparent success.

   Decision: Quiescence and descendant cleanup are receipt prerequisites.

   Mitigation/test: Linux process group plus cgroup/pidfd-style ownership; Windows Job Object with kill-on-close; bounded pipe draining and identity checks. Spawn delayed writers, grandchild processes, held stdout pipes, PID reuse, and timeout races. Any survivor or late mutation yields unresolved.

6. **FHM005-C06 — High — Service identity and IPC are design gaps on both platforms**

   Facts: no verifier service or IPC implementation exists in the baseline. Existing Windows persistence uses `InteractiveToken`/`LeastPrivilege` and a Startup fallback (`hermes_cli/gateway_windows.py:513`); existing Linux systemd support is gateway-oriented, not verifier-hardened (`hermes_cli/gateway.py:3211`). Neither proves a trusted verifier boundary.

   Decision: Unsupported, misbound, interactive, or fallback installation must report unavailable—not downgrade to success. Runtime should not require root/admin; installation may, but elevated operator identity is not the verifier identity.

   Mitigation/test: Linux dedicated non-login service account, root-owned Unix socket with peer credentials, protected state directory; Windows SCM/virtual service account, named-pipe DACL and token validation, no Startup fallback. Test standard user, admin, logoff, reboot, ACL tampering, profile crossover, restart, and upgrade.

7. **FHM005-C07 — High — Runtime egress and inherited secrets violate least privilege**

   Facts: project commands can access arbitrary environment variables, files, network destinations, package registries, and subprocesses; readiness polling is loopback-only but does not restrict recipe commands.

   Decision: Network, personal files, credentials, mounts/devices, and external services are denied by default. External side effects remain unresolved unless separately attested.

   Mitigation/test: scrub environment, restrict filesystem to disposable workspace, deny egress by default, impose CPU/RSS/disk/wall limits, and test DNS/HTTP exfiltration, secret reads, symlink/mount escapes, and package-install side effects on Linux and Windows.

8. **FHM005-C08 — High — Crash, retry, and retirement semantics can lose authority**

   Facts: pending IDs are deterministic; transitions lack expected-version/monotonic checks; finalization reads and retires state in separate operations. `disarm_delegated_verification()` can delete a marker after the spawn boundary. SRE also found owner-liveness uncertainty can leave rows indefinitely running.

   Decision: “Unknown is sticky”; no replay of uncertain effects and no deletion of ambiguous attempts.

   Mitigation/test: immutable attempt history with `supersedes`, CAS/fence-based transactional evaluation, explicit operator resolution, durable `unknown/recovery-blocked` state, and tests killing the process between arm/spawn/receipt/retirement.

9. **FHM005-C09 — High — Privacy leakage and retention are under-specified**

   Facts: receipts store absolute cwd/root, commands, paths, and up to 2,000 characters of output; summaries can enter model-facing nudges (`agent/verification_evidence.py:469`). Truncation is not redaction. Pruning is not an explicit user-controlled retention/erasure policy.

   Decision: Define minimum receipt data, retention, purge, and whether raw output may leave local profile state.

   Mitigation/test: opaque or hashed identifiers, relative paths, command fingerprints, structured status, secret redaction, raw tails opt-in and local-only. Inject credentials and personal-file contents and verify they cannot appear in receipts or prompts.

10. **FHM005-C10 — High — Release qualification is incomplete**

   Facts: recorded evidence is 6/6 Linux-only and explicitly excludes gateway/async and trusted-verifier qualification (`FHM-005-E2E-QUALIFICATION.md:3`). CI conditionally skips the live suite (`.github/workflows/fermes-pr-checks.yml:98`).

   Decision: Owner-approved Linux + Windows qualification is a hard release gate; skipped, timed-out, or environment-blocked runs are not passes. Keep default-off and do not merge/promote trusted-success claims.

## Decision queue

- Approve the untrusted-worker threat model; explicitly exclude fully privileged local root/admin as a boundary that OS ACLs can defend.
- Approve the two-tier broker/executor architecture and per-attempt receipt contract.
- Choose per-attempt/artifact scope; foreign-session verification is advisory only.
- Select Linux service-user/socket and Windows SCM/named-pipe mechanisms, including install failure behavior.
- Approve privacy minimization, retention, and operator resolution UX.
- Require native adversarial E2E on both Linux and Windows before release.

Cryptographic signatures/MACs are optional defense-in-depth, not the default boundary. Mandatory controls are OS-authenticated IPC, protected service-owned storage, exact scope/freshness binding, and atomic non-replayable consumption. Crypto cannot compensate for a worker that can access the signing key or execute inside the trusted broker.

## Best reference architecture

Parent creates an attempt nonce and immutable scope; broker authenticates the parent over OS IPC; broker launches untrusted checks in a disposable, low-privilege, no-secret/no-egress executor; broker independently validates hashes, paths, process quiescence, and effect scope; broker stores and returns a protected receipt. The parent finalizer transactionally consumes only that exact fresh receipt. Otherwise the result is incomplete/unavailable, never successful.


# delivery-cross

55,568
# FHM-005 cross-review consolidation

**Disposition:** Hold PR #21/#22 unmerged and keep Phase 1 opt-in/fail-closed. The baseline `de83ce3b` proves bounded Linux one-shot behavior and durable no-replay recovery, but not trusted verification or a qualified release. No High/Critical risk is acceptable for owner approval.

## Prioritised findings

1. **FHM5-C1 — Critical — Untrusted code crosses the verifier boundary**

   `agent/verify/runner.py` executes project-controlled, `shell=True` recipes and manifests; `environment.py` permits bootstrap/build/test/start behavior. A separate service identity is insufficient if it runs hostile project code with verifier privileges.

   **Decision:** Explicitly reject privileged execution of project-authored tests. Approve a two-tier design: trusted authority plus isolated, least-privilege executor.

   **Mitigation/test:** Fixed policy-owned checks; disposable worktree/sandbox; no verifier secrets, receipt storage, broad filesystem or network access; bounded descendants/resources. A malicious fixture must not read secrets, write outside the worktree, access verifier IPC, persist descendants, or receive a trusted receipt.

2. **FHM5-C2 — Critical — Verification provenance is forgeable**

   `record_verify_run()` accepts caller-supplied `ok`, root, session and command data and writes a profile-local SQLite `kind="verify"` row. Same-profile code can forge or replay apparent success. Existing rows must remain diagnostic, never trusted proof.

   **Decision:** Approve the receipt authority, authenticated local IPC, key/MAC protection, and mandatory behavior when the verifier is unavailable.

   **Mitigation/test:** Service-only receipt minting after verifier exit; bind nonce, parent attempt, session, root, policy/version, artifact hashes, freshness and one-time consumption. Direct SQLite insertion, forged IPC, cross-session/root receipts and replay must remain unresolved.

3. **FHM5-C3 — High — Atomicity, TOCTOU and cross-session contamination**

   Verification reads state/evidence separately and later deletes completed rows; `_DB_LOCK` is process-local. A late update can be evaluated or retired outside the intended snapshot. Full verification also rewrites/clears other sessions’ state, while path strings lack immutable object/content binding; symlink, hardlink, rename or mount swaps are not excluded.

   **Decision:** Use session/attempt-scoped proof, consistent with DEC-004. Workspace-wide results may be advisory cache data only unless an explicit global lock/snapshot contract is approved.

   **Mitigation/test:** Transactional `evaluate_and_retire()` with generation/CAS fence; immutable root/tree and artifact hashes, canonical path/object identity and mount policy; never mutate another session’s pending state. Race finalization against late telemetry and mutate/swap files before verification; all cases stay unresolved.

4. **FHM5-C4 — High — Async recovery and retry state are incomplete**

   Owner-liveness failure can leave rows `running`; startup replay excludes them, safely avoiding replay but stranding work indefinitely. Dispatch failures can delete markers after spawn reservation. Retries leave prior unknown/failed attempts active, with no explicit supersession or operator resolution.

   **Decision:** Make `unknown` sticky after reservation; define recovery SLA, authorized resolution, and whether retry B can supersede attempt A.

   **Mitigation/test:** Durable `requested → running → observed → receipt-minted`; crash/restart becomes `unknown`, never success or replay. Test kill between spawn and marker deletion, unavailable liveness probe, retry-after-crash, and verifier crash at every transition.

5. **FHM5-C5 — High — External effects cannot be generalized from code-test receipts**

   Phase 1 correctly treats `terminal`, `execute_code`, and `browser_console` as effect-capable/unobservable, even when commands appear read-only. A green `hermes verify` cannot prove shell, browser, connector, deployment or external-service outcomes.

   **Decision:** Define action-specific acceptance contracts and explicitly list unsupported effects.

   **Mitigation/test:** Use authoritative readback only where the external system provides it; otherwise report unresolved and prohibit automatic replay. A successful code suite after a shell/browser/external effect must not produce `completed=true`.

6. **FHM5-C6 — High — Process containment is not cross-platform qualified**

   Current evidence is Linux-only. Windows teardown targets the direct child, so detached descendants may continue modifying files or holding pipes/ports after apparent success.

   **Decision:** Require equivalent native Linux and Windows containment before qualification.

   **Mitigation/test:** Linux process-group/cgroup or equivalent ownership; Windows Job Objects with kill-on-close; post-exit descendant and quiescence verification. Test timeout, daemonized descendants, late writers, PID reuse and held pipes on both operating systems.

7. **FHM5-C7 — High — Packaging, identity and upgrade contracts are absent**

   Existing systemd and Windows launcher paths are gateway-oriented. Windows `InteractiveToken`/Startup fallback cannot establish trusted identity; no verifier-specific ACLs, protected state/key directories, protocol generation, key rotation or rollback invalidation exist.

   **Decision:** Choose SCM versus Task Scheduler on Windows, Linux service account/unit model, installer privilege policy and unsupported-installation behavior.

   **Mitigation/test:** Dedicated noninteractive principals, protected IPC endpoints and receipt stores, generation handshake, side-by-side upgrade, drain/rollback, and receipt invalidation on identity/protocol change. Test install, reboot, ACL tampering, upgrade interruption and rollback on both OSes.

8. **FHM5-C8 — High — Release qualification and staged development are underspecified**

   Recorded qualification is six Linux real-process tests, with gateway ingress, detached async completion, trusted receipts and Windows explicitly unqualified. CI runs the FHM-005 lane only on Ubuntu; skipped or environment-blocked tests cannot count.

   **Decision:** Accept this phase split: (A) current opt-in fail-closed/manual review; (B) architecture approval; (C) implementation and adversarial native Linux/Windows qualification; (D) one candidate release gate; only then consider default-on. No single-platform qualified-release claim.

9. **FHM5-C9 — Medium — Privacy and retention are excessive/ambiguous**

   SQLite and model-facing nudges can retain absolute roots, commands, changed paths and raw output. Truncation is not redaction. Events prune after 30 days/100 entries, but abandoned pending rows lack expiry and there is no clear purge/export policy.

   **Decision:** Approve minimum receipt fields, raw-output handling, retention periods and deletion semantics.

   **Mitigation/test:** Prefer opaque IDs, relative/hashed paths, command fingerprints, structured status and secret redaction; keep raw diagnostics local and opt-in; add expiry, tombstones and profile-scoped purge. Inject secrets/personal paths and verify they do not enter receipts or prompts.

10. **FHM5-C10 — Medium — Status and operator UX can report success ambiguously**

    `verification_unresolved=true`, `failed=true`, `completed=false` can still yield `_result_status() == "complete"` because no error is set. Generic “retry” messaging and approval-disconnect handling do not distinguish accepted, denied, expired or unknown execution.

    **Decision:** Approve `verified`, `failed`, `unknown/incomplete` and `verifier unavailable` as distinct states; reserve “Verified” for protected receipts.

    **Mitigation/test:** TUI/Desktop/CLI must render unresolved as non-success, explain possible effects, show attempt/effect scope, and offer inspect/resolve—not replay. Test disconnect-before/after approval and missing evidence.

11. **FHM5-C11 — Medium — FinOps/SRE cost is unbounded**

    A verifier may rerun expensive checks across concurrent profiles; current evidence allows long phase budgets and no verifier queue/resource SLO.

    **Decision:** Prefer bounded on-demand verification over an always-on daemon unless measured demand justifies the latter.

    **Mitigation/test:** Per-request wall/CPU/RSS/disk/output limits, bounded concurrency and orphan count; measure P50/P95 latency and resource use on Linux and Windows.

## Decision queue

1. Approve or reject the two-tier trusted-authority/untrusted-executor model.
2. Declare SQLite verdicts diagnostic-only.
3. Select session/attempt/artifact-scoped receipt semantics.
4. Define sticky-unknown, retry supersession and operator-resolution rules.
5. Define supported external-effect classes and readback authority.
6. Select native Linux/Windows service, IPC and containment mechanisms.
7. Approve privacy, retention and raw-output policy.
8. Mandate the staged release gate: both native OSes, no skips/timeouts, same candidate SHA, rollback defined.

## Acceptance test matrix

| Gate | Linux | Windows | Pass condition |
|---|---|---|---|
| Provenance | Forge/replay/cross-session/root receipt | Same cases via native IPC/ACL | Only service-minted, fresh, bound receipt can complete |
| Atomicity/TOCTOU | Late update, concurrent session, file swap | Same with native locking/path identity | No foreign mutation, stale acceptance or lost pending state |
| Recovery | Kill parent/verifier at every transition | Same | Durable `unknown`; no child replay; explicit resolution |
| Effects | Shell, terminal, browser and external-effect cases | Native equivalents | Unsupported/readback-limited effects remain unresolved |
| Containment | Timeout, descendant, pipe and PID-reuse tests | Job Object, descendant and pipe tests | No owned descendant or late mutation survives |
| Packaging | Install/restart/upgrade/rollback/ACL | SCM or Task Scheduler, reboot/logoff/ACL | Identity, keys, IPC and receipt generation remain valid |
| UX/privacy | Status, redaction, purge and approval races | Same platform-native surfaces | No false success, secret leakage or unsafe automatic retry |\n
