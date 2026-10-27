# FHM-011 Step 3 — Hermes canary rehearsal evidence

**Review date:** 2026-10-27 (UTC)
**Project:** `fermes-hermes`
**Scope:** documentation-only release-impact report; no source, runtime, installation, production, or maintained-branch change

## Decision

| Gate | Verdict | Meaning |
|---|---|---|
| Release adoption of the canary | **INCONCLUSIVE** | The evidence does not establish compatibility, semantic deduplication, or release readiness. Do not adopt it. |
| Isolation and rollback rehearsal | **PASS** | The candidate was isolated, the attempted merge was aborted, and the maintained SHA was reported unchanged and clean. |

There is **no production compatibility acceptance** in this report. The canary is an experimental
official tag, not a newer stable release, and the offline comparator stopped fail closed before
producing a complete large-release comparison.

## Identity, pinned refs, and provenance

The identity gate passed before evidence collection: the checkout is the exact fork
`fredheathcote007/hermes-agent`, project `fermes-hermes`, on branch
`fermes/fhm011-canary-evidence-20261027`, at maintained SHA
`0645e1cafcd1703fdb2a7cb0d6dfa3fe042ac635`. The required [memory index](../memory/MEMORY-INDEX.md),
[constraints](../memory/CONSTRAINTS.md), [decisions](../memory/DECISIONS.md), and
[controlled upstream procedure](../UPSTREAM-SYNC.md) were read before writing.

| Role | Pinned identity |
|---|---|
| Official stable baseline | Hermes `v0.22.5`, published 2026-10-23, commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e` |
| Official experimental canary tag | Annotated tag `v0.22.5+canary.20261026T071310Z`, tag object `1d97e4066fafda503373605051bd2ca461d54f4c`, peeling to commit `765933299d885e850390ed1d8e4fd4d37fae8342` |
| Canary provenance | Tagged by `github-actions[bot]` on 2026-10-26. The official GitHub REST annotated-tag record reports `verification.verified=false` and `verification.reason=unsigned`. The tag is therefore **unsigned**; no successful cryptographic signature verification is claimed. |
| Fermes maintained source | `0645e1cafcd1703fdb2a7cb0d6dfa3fe042ac635` (the requested fork-maintained SHA) |

The official [GitHub comparison](https://github.com/NousResearch/hermes-agent/compare/bf0203a794a07aac3ff764972ab9087baa4e4f4e...765933299d885e850390ed1d8e4fd4d37fae8342)
reported `ahead_by: 1591`, `behind_by: 0`; its Files API view is capped at 300 files. Independent
local Git diffs from the same stable baseline found 2,178 changed paths to the canary and 76 changed
paths to the maintained fork. These counts are scope evidence, not a compatibility result.

## Rehearsal procedure and observed result

The evidence was collected with existing local refs and closed, non-interactive Git subprocesses.
The material commands were:

```bash
git remote -v
git status --short --branch
git rev-parse HEAD
git diff --name-only bf0203a794a07aac3ff764972ab9087baa4e4f4e 765933299d885e850390ed1d8e4fd4d37fae8342
git diff --name-only bf0203a794a07aac3ff764972ab9087baa4e4f4e 0645e1cafcd1703fdb2a7cb0d6dfa3fe042ac635
git merge-tree --write-tree --name-only --messages 0645e1cafcd1703fdb2a7cb0d6dfa3fe042ac635 765933299d885e850390ed1d8e4fd4d37fae8342
git -C /srv/project-coordinator/projects/fermes-hermes-fhm011-canary-candidate-20261027 -c user.name='FHM-011 temporary test' -c user.email='fhm011-test@invalid.example' merge --no-commit --no-ff 765933299d885e850390ed1d8e4fd4d37fae8342
git -C /srv/project-coordinator/projects/fermes-hermes-fhm011-canary-candidate-20261027 merge --abort
git -C /srv/project-coordinator/projects/fermes-hermes-fhm011-canary-candidate-20261027 status --short --branch
git -C /srv/project-coordinator/projects/fermes-hermes-fhm011-canary-candidate-20261027 rev-parse HEAD
git cherry 0645e1cafcd1703fdb2a7cb0d6dfa3fe042ac635 765933299d885e850390ed1d8e4fd4d37fae8342 bf0203a794a07aac3ff764972ab9087baa4e4f4e
python3 scripts/fermes_upstream_compare.py \\
  --repo /srv/project-coordinator/projects/fermes-hermes-fhm011-canary-candidate-20261027 \\
  --upstream-base bf0203a794a07aac3ff764972ab9087baa4e4f4e \\
  --upstream-target 765933299d885e850390ed1d8e4fd4d37fae8342 \\
  --fork 0645e1cafcd1703fdb2a7cb0d6dfa3fe042ac635 \\
  --format json
```

Observed evidence:

- Actual merge-tree analysis and an actual `git merge --no-commit` found two content conflicts:
  `agent/verification_stop.py` and `tests/agent/test_verification_stop.py`. Ten other overlapping
  paths auto-merged textually; that is not evidence that their behavior is compatible.
- The candidate merge was aborted. The supplied candidate log records the candidate at the fork
  SHA with clean status and `ROLLBACK_PASS`; no merge commit, source commit, or production/runtime
  change was made.
- The offline comparator stopped with `FAIL CLOSED` / `bounded_output` when the aggregate Git binary
  diff exceeded its 4 MiB bound. This is a comparator capacity limit, not evidence that the candidate
  is unsafe or safe.
- No source/runtime test suite was run by this documentation-only rehearsal. The result is therefore
  not a test PASS and cannot replace the qualification gates listed in [UPSTREAM-SYNC](../UPSTREAM-SYNC.md).

## Overlap and conflict inventory

The exact path overlap between the maintained fork delta and the canary delta is:

1. `agent/auxiliary_client.py`
2. `agent/conversation_loop.py`
3. `agent/reasoning_params.py`
4. `agent/turn_context.py`
5. `agent/turn_final_response.py`
6. `agent/turn_finalizer.py`
7. `agent/turn_tool_round.py`
8. `agent/verification_evidence.py`
9. `agent/verification_stop.py`
10. `hermes_cli/models_local.py`
11. `tests/agent/test_verification_stop.py`
12. `tools/delegate_tool.py`

The two conflicts deserve an explicit policy decision:

| Path | Maintained branch behavior | Canary behavior | Impact of choosing without review |
|---|---|---|---|
| `agent/verification_stop.py` | Adds `verification_unresolved` and `has_verifiable_paths`; a code edit is unresolved unless current, same-session, full `hermes verify` evidence is recorded. It removes the ad-hoc temporary-script escape path. | Keeps terminal/worker receipts in the stop narrative and adds `last_unattributed_run` / pipeline-status guidance, while retaining the temporary-script path. | The branches disagree on what constitutes admissible independent verification and on the fail-closed stop contract. This is a direct FHM-005 decision, not a textual merge. |
| `tests/agent/test_verification_stop.py` | Tests worker receipts, missing/stale/foreign/failed verifier evidence as unresolved; current full verifier evidence clears the gate; docs-only paths remain non-verifiable. | Tests ad-hoc worker success as sufficient, pipeline status attribution, and warnings for unscored shell runs. | The tests encode mutually different acceptance contracts. Combining them without a chosen policy could make a green test result assert the wrong release behavior. |

The remaining ten paths are only **textually** auto-merged in the rehearsal. They remain in the
semantic review scope because they touch turn flow, model/provider resolution, delegation, and
verification evidence.

## Near-term Fermes blast radius

This is a requalification map, not a claim that the canary broke each issue. It is grounded in the
overlap list and the dated [upstream issue/PR crosswalk](UPSTREAM-ISSUE-PR-CROSSWALK-20261027.md).

| Fermes gate | Why this rehearsal is in scope | Required follow-up before any adoption decision |
|---|---|---|
| [FHM-001](https://github.com/fredheathcote007/hermes-agent/issues/1) | `agent/auxiliary_client.py`, `agent/reasoning_params.py`, and `hermes_cli/models_local.py` overlap the qualified LM Studio aliases, auxiliary routing, and model-resolution work. | Re-run route, credential, reasoning-parameter, and local-model tests on the selected stable candidate. |
| [FHM-002](https://github.com/fredheathcote007/hermes-agent/issues/2) | Conversation, turn, tool-round, auxiliary, and delegation paths overlap the Qwen malformed-tool/no-tool and terminal-cycle behavior. | Repeat the exact disposable Hermes→LM Studio→Qwen no-tool, tool/result, and malformed-call regression evidence. |
| [FHM-004](https://github.com/fredheathcote007/hermes-agent/issues/4) | Turn finalisation, tool rounds, conversation flow, and delegation are adjacent to bounded gateway stop/recovery even though the gateway files are not in the 12-path list. | Re-run bounded stop, SIGTERM/SIGKILL, restart, orphan-recovery, and no-duplicate-admission evidence. |
| [FHM-005](https://github.com/fredheathcote007/hermes-agent/issues/5) | The direct two-file conflict changes the definition of independent verification and fail-closed completion. | Select the verifier policy, resolve both files deliberately, and run the trusted-verifier, restart/eviction, scope, and native Linux/Windows gates. |
| [FHM-006](https://github.com/fredheathcote007/hermes-agent/issues/6) | `turn_context.py`, `turn_finalizer.py`, and `turn_final_response.py` overlap context/turn completion paths relevant to compaction and exact source recall. | Re-run compaction integrity, tail-boundary, and source-history recovery tests. |
| [FHM-007](https://github.com/fredheathcote007/hermes-agent/issues/7) | Conversation/context/auxiliary overlap can affect the integration surface around memory precedence and sidecar compaction; this report contains no memory acceptance evidence. | Re-run Local Memory v2 precedence, sidecar, and integration acceptance independently. |
| [FHM-017](https://github.com/fredheathcote007/hermes-agent/issues/28) | Conversation, tool-round, finalisation, verification, and delegation overlap the repeated-success/no-op finalisation path. | Exercise repeated successful tool loops and no-op finalisation; inspect effects beyond result-hash or patch equivalence. |
| [FHM-018](https://github.com/fredheathcote007/hermes-agent/issues/29) | Conversation, tool-round, delegation, and finalisation overlap the timeout/cancellation boundary where late effects can occur. | Exercise cancellation, timeout, process quiescence, and late-side-effect suppression with real bounded processes. |

## Exact-patch deduplication versus semantic unknown

The requested `git cherry` comparison completed successfully with **1,575 distinct non-merge
commits** and **0 equivalent patch IDs**. That is useful exact-patch evidence only: it found no
patch-ID matches under that comparison. It does **not** prove that the canary has no semantic
duplicate of a Fermes change. A patch may be adapted, reordered, split, squashed, or restructured
and still implement the same behavior. The 12 overlapping paths and the two direct conflicts are
therefore not cleared by the zero patch-ID result.

The comparator itself is intentionally bounded in
[comparator implementation](../../../scripts/fermes_upstream_compare.py): 256 non-merge
commits, 4 MiB Git output and 4 MiB patch input, with bounded report items and output. Its binary
diff aggregate exceeded the 4 MiB Git bound and returned `bounded_output`. The correct classification
is **comparison incomplete / fail closed**, not candidate unsafe and not candidate safe.

## Status taxonomy

| Layer | Status after this rehearsal |
|---|---|
| This source branch | Documentation evidence only, based at the requested maintained SHA; no runtime/source adoption. |
| Maintained Fermes compatibility branch | Untouched by this rehearsal; the attempted candidate merge was isolated and aborted. |
| Fork `main` | No merge or promotion was performed or inferred. A maintained-branch result is not fork-main status. |
| Runtime/installation | No installation, updater, service, profile, credential, or deployment was changed. Runtime compatibility remains unaccepted. |

## Next steps when an actual newer stable release exists

1. Verify a real official stable release tag, its peeled commit SHA, tag signature/GitHub
   verification, release notes, dependencies, migrations, and security notes. Do not substitute a
   canary or moving upstream `main`.
2. Freeze and record the maintained SHA, tested runtime/model versions, clean status, and rollback
   point. Create a new disposable worktree at the maintained SHA; do not touch active FHM-005 or
   FHM-007 worktrees.
3. Re-run bounded comparison, then inspect all overlapping paths and the full three-way diffs. Use
   deliberate policy review for `verification_stop.py` and its test rather than accepting an
   automatic textual merge. Revisit exact and semantic deduplication for PRs #15, #18, #20, #21,
   and #22.
4. Run the affected source, integration, real Qwen/LM Studio, bounded stop/recovery, verification,
   compaction, memory, FHM-017, and FHM-018 gates. Record PASS, FAIL, and SKIP separately with exact
   SHAs; an unrun test is not a PASS. Obtain independent review.
5. Open a review PR against the maintained compatibility branch with the diff, deduplication
   rationale, test receipts, and rollback instructions. Do not merge to the maintained branch,
   fork `main`, an installer, or a runtime until the owner accepts the release gate.
6. Rehearse abort/rollback again and update the [FHM-011 issue](https://github.com/fredheathcote007/hermes-agent/issues/11)
   with the source SHAs, evidence, decision, and explicit source-vs-runtime status.

## Evidence inputs

- [FHM-011](https://github.com/fredheathcote007/hermes-agent/issues/11) and the
  [controlled upstream procedure](../UPSTREAM-SYNC.md).
- Host evidence: `/tmp/fhm011-overlap-20261027.txt`, `/tmp/fhm011-merge-tree-20261027.txt`, and
  `/tmp/fhm011-canary-actual-merge-20261027.log`.
- Focused source and tests: [`agent/verification_stop.py`](../../../agent/verification_stop.py),
  [`tests/agent/test_verification_stop.py`](../../../tests/agent/test_verification_stop.py), and
  the comparator source linked above.

**Final outcome:** isolation/rollback **PASS**; release adoption **INCONCLUSIVE**; no production
compatibility acceptance; no source/runtime merge or push.
