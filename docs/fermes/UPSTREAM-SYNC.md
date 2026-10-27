# Fermes Hermes — controlled upstream maintenance

project_id: fermes-hermes
Issue owner: [FHM-011](https://github.com/fredheathcote007/hermes-agent/issues/11)
Policy: [DEC-001](memory/DECISIONS.md) — no unattended upstream adoption
Last evidence review: 2026-10-27 (Australia/Perth)

## Repository identity and branch boundaries

- **Official upstream:** [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).
- **Our fork:** [fredheathcote007/hermes-agent](https://github.com/fredheathcote007/hermes-agent).
- **Pinned upstream baseline:** Hermes v0.22.5, commit bf0203a794a07aac3ff764972ab9087baa4e4f4e. Verify the release tag and SHA before reuse.
- **Maintained fork compatibility branch:** fermes/qwen-lmstudio-v0225-20261026. This branch contains multiple separately tested Fermes modifications, not only LM Studio aliases: routing/credentials, malformed Qwen tool-call recovery, bounded supervision/crash recovery and verification hardening.
- **Fork main:** separate integration channel. A merge into the maintained compatibility branch is **not** a merge into fork main, an installation, or a runtime deployment. Compare GitHub branch SHAs and actual installation provenance before asserting promotion.
- **Canonical issue tracker:** [FHM-011](https://github.com/fredheathcote007/hermes-agent/issues/11); [dated upstream crosswalk](compatibility/UPSTREAM-ISSUE-PR-CROSSWALK-20261027.md) is a review snapshot, not a second backlog.

This guide covers **source maintenance**; no running Hermes service, LM Studio endpoint, credentials, unrelated worktrees or fork main may be changed as a side effect of a documentation or comparison task.

## Verified remote names — Project Coordinator (27 October 2026)

For the **existing clean** checkout at /srv/project-coordinator/projects/fermes-hermes-qwen-v0225:

| Remote | Observed URL | Purpose |
|---|---|---|
| origin | https://github.com/NousResearch/hermes-agent.git | Official upstream, fetch for this workflow |
| fork | https://github.com/fredheathcote007/hermes-agent.git | Fermes fork, push only with approval |

The verified checkout was on branch fermes/qwen-lmstudio-v0225-20261026 and had a clean short status. **These observed remote names are not universal.** A different clone may use origin for the fork and upstream for official source.

Before every fetch, branch, merge or push, run the read-only checks below *inside the intended checkout*:

    git status --short --branch
    git branch --show-current
    git remote -v
    git remote get-url origin
    git remote get-url fork
    git rev-parse HEAD

If either name does not exist, inspect the actual remotes and replace the names in the commands **only after validating both repository URLs**. Never rewrite remotes merely to match this guide. Stop on project identity mismatch; see [MEMORY-INDEX.md](memory/MEMORY-INDEX.md).

## Deliberate, source-only upstream release adoption

**FHM-011 implementation and upgrade rehearsal are still open.** This is the planned runbook, not a claim of a completed update.

1. **Freeze state:** record the current qualified fork SHA, tested upstream release/tag, model/provider/runtime versions, clean worktree, CI and rollback point. Back up profile, configuration and any schema-sensitive data separately if a deployment is later considered. Never reset an active worktree.
2. **Verify and fetch:** ensure the selected remote URL actually points to official NousResearch, then fetch its refs/tags (e.g. git fetch origin --tags *only when origin is verified as official*). Choose an **existing, verified release tag and SHA**; a version placeholder is not a verified release. Do not merge moving upstream main.
3. **Analyse changes:** compare official notes/code/dependencies/security and migrations with fork patches. Specifically check whether upstream fixes duplicate merged fork [PR #15](https://github.com/fredheathcote007/hermes-agent/pull/15), [#18](https://github.com/fredheathcote007/hermes-agent/pull/18), [#20](https://github.com/fredheathcote007/hermes-agent/pull/20), [#21](https://github.com/fredheathcote007/hermes-agent/pull/21), [#22](https://github.com/fredheathcote007/hermes-agent/pull/22) or subsequent additions. Record the actual upstream and fork SHAs and avoid duplicate implementations.
4. **Isolate candidate:** make a **new unique branch/worktree** based on the verified qualified fork SHA. Merge or adapt only the selected pinned release in that disposable worktree. Address patch overlap with focused tests and rationale; do not modify an active FHM-005 or FHM-007 worktree.
5. **Qualify:** run lint/unit/integration and affected regression tests; exercise real Hermes to LM Studio/Qwen tool and no-tool paths when relevant, bounded stop/recovery, evidence verification, compaction/memory, and Linux/Windows gates where applicable. Record exact source SHA/model and PASS/FAIL/SKIP separately; an unrun test is not PASS. Require independent Cursor review.
6. **Review before promotion:** open a PR targeting the maintained compatibility branch, include the upstream diff, patch-deduplication rationale and rollback instructions. No automatic merge into fork main, runtime installer or production.
7. **Rehearse rollback:** demonstrate that a rejected update candidate leaves the qualified branch untouched. A deployed rollback requires separately authorised backups/restoration and compatible profiles/databases, not just reverting Git.
8. **Close out evidence:** update [FHM-011](https://github.com/fredheathcote007/hermes-agent/issues/11) and impacted issues with source/fork SHAs, test and review links, decision and explicit distinction between code merged and runtime deployed.

Do **not** use an unreviewed Hermes updater to advance a patched checkout; the updater may follow an incompatible channel. Do not force-push, silently replace source, change host/network security or publish secrets.

## Qualified behaviour versus open work (27 October 2026)

**Source merged and scoped behaviour qualified:**
- [Fermes PR #15](https://github.com/fredheathcote007/hermes-agent/pull/15) and [#18](https://github.com/fredheathcote007/hermes-agent/pull/18) merged to the maintained branch, with hosted CI and source tests. A disposable **real Hermes process** on Dad-PC WSL Ubuntu 24.04 connected to its local LM Studio endpoint (127.0.0.1:1234) and Qwen model qwen96k-nomtp (98,304-context setting). It passed no-tool finalisation, an actual terminal tool-use-and-result cycle, corrective retries for malformed tool calls, and fail-closed bounded exhaustion. See [FHM-002](https://github.com/fredheathcote007/hermes-agent/issues/2), [FHM-015](https://github.com/fredheathcote007/hermes-agent/issues/16) and [PROJECT-STATE.md](memory/PROJECT-STATE.md) for exact evidence.
- [PR #20](https://github.com/fredheathcote007/hermes-agent/pull/20) merged with independent review, hosted CI and disposable real gateway stop/crash/restart tests ([FHM-004](https://github.com/fredheathcote007/hermes-agent/issues/4)).
- [PR #21](https://github.com/fredheathcote007/hermes-agent/pull/21) and [#22](https://github.com/fredheathcote007/hermes-agent/pull/22) merged **phase-one, fail-closed verification** source and tests, not an independently protected trusted-verifier service.

**Still open / not implied by those tests:**
- They do **not** prove an update to fork main, a production installation, unattended operation or a general release-upgrade procedure.
- [FHM-005](https://github.com/fredheathcote007/hermes-agent/issues/5) P0 requires independent outcome attestation and native Linux and Windows security qualification.
- [FHM-006](https://github.com/fredheathcote007/hermes-agent/issues/6), [FHM-007](https://github.com/fredheathcote007/hermes-agent/issues/7), [FHM-008](https://github.com/fredheathcote007/hermes-agent/issues/8), [FHM-009](https://github.com/fredheathcote007/hermes-agent/issues/9) and [FHM-010](https://github.com/fredheathcote007/hermes-agent/issues/10) retain separate compaction integrity, local memory, learning and evaluation acceptance gates.
- [FHM-017](https://github.com/fredheathcote007/hermes-agent/issues/28) and [FHM-018](https://github.com/fredheathcote007/hermes-agent/issues/29) remain P0 for repeated successful tool loops and late side effects.
- No FHM-011 controlled release-upgrade exercise or rollback rehearsal has been accepted.

## Safeguards and follow-up

Use [AGENT-EXECUTION-PROTOCOL.md](memory/AGENT-EXECUTION-PROTOCOL.md) for bounded, non-interactive execution and independent review. Keep upstream changes untrusted until applicability and regression evidence are checked; FHM-011 remains open through comparison, qualification and rollback evidence.


## Offline comparison workflow (FHM-011 Step 2)

`scripts/fermes_upstream_compare.py` is an offline, read-only comparison wrapper around the
installed Git executable. It requires an explicit worktree and three existing local refs:

```bash
python3 scripts/fermes_upstream_compare.py \
  --repo /path/to/clean/hermes-agent \
  --upstream-base bf0203a794a07aac3ff764972ab9087baa4e4f4e \
  --upstream-target v0.22.5 \
  --fork fermes/qwen-lmstudio-v0225-20261026 \
  --format markdown
```

Use `--format json` for machine-readable reports. The command checks that the path is a Git
worktree, the checkout is clean, both canonical repository identities are present among the
configured remotes, refs resolve to commits, and the upstream baseline is an ancestor of both
comparison targets. It discovers remotes by their URLs; `origin`, `upstream`, and `fork` are not
special names. It does not fetch, contact GitHub, call an API, merge, checkout, update branches,
or write a report or any other output into the repository. Git subprocesses use argv directly,
closed stdin, timeouts, and bounded output.

The comparison has a shared monotonic 30-second budget and refuses histories over 256 non-merge
commits. Patch-ID input/output is streamed through bounded pipes and is killed and reaped on timeout.
Report path, change, and equivalent-pair evidence is deterministically capped at 256 items with
totals and truncation warnings; the rendered JSON or Markdown is capped at 1 MiB and fails closed
if that limit is still exceeded.

The report includes resolved commit SHAs, Git descriptions, changed paths and counts, Git
`patch-id --stable` equivalence evidence, path overlap, deterministic risk-review hints, warnings,
and a confidence status. Classifications are `exact-equivalent`, `possible-overlap-by-path`,
`no-overlap`, or `unknown/non-equivalent`. Patch equivalence is not compatibility: every successful
report has `review_required: true` and `compatibility_status: not-established`. High-risk path
categories (agent execution, tools, memory, tests, CI, security, and dependencies) are hints for
human review only; the tool cannot approve a release, establish safety, or authorize deployment.
For `exact-equivalent`, the confidence label is `patch-only`: matching patch IDs do not establish
compatibility, release readiness, or deployment safety.

Limitations: local Git must already contain every supplied ref; no network recovery is attempted.
Patch IDs do not replace review of semantics, dependencies, migrations, security, tests, or runtime
behaviour. A dirty checkout, spoofed/missing canonical remote, bad ref, broken ancestry, timeout, or
bounded-output failure returns nonzero. This workflow performs no merge and does not adopt or deploy
an upstream release.

Use [AGENT-EXECUTION-PROTOCOL.md](memory/AGENT-EXECUTION-PROTOCOL.md) for bounded tool and independent-review instructions, including non-interactive closed stdin, precise source SHA and stop criteria. Record upstream changes as untrusted inputs until version applicability and regression evidence are checked. FHM-011 remains open until the comparison, deduplication, qualification and rollback workflow are implemented and independently demonstrated.
