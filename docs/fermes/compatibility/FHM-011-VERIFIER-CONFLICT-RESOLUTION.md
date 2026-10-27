# FHM-011 verifier conflict resolution contract

Status: source-only compatibility contract; no canary adoption, production change,
merge, push, or trusted-verifier approval.

This document records the deliberate resolution for the two actual experimental
canary conflicts found during the FHM-011 rehearsal. The controlled upstream
procedure remains in [UPSTREAM-SYNC](../UPSTREAM-SYNC.md).

## Pinned inputs and decision

| Role | Exact commit |
|---|---|
| Official stable baseline | `bf0203a794a07aac3ff764972ab9087baa4e4f4e` |
| Official experimental canary | `765933299d885e850390ed1d8e4fd4d37fae8342` |
| Maintained Fermes source under review | `6fd54dc4c17831c0c7e0b5fb1627522f6c218384` |

Policy choice: retain approved [DEC-004](../memory/DECISIONS.md#dec-004--fail-closed-on-unverified-delegated-outcomes).
Worker terminal success, an ad-hoc temporary script, missing evidence, failed
evidence, stale evidence, foreign/session-mismatched evidence, and bounded retry
exhaustion cannot produce verified completion. Only the existing phase-one source
contract's current same-session full `hermes verify` record can clear this guard.
That record is still not an independently protected trusted verifier.

## The two conflict hunks

The merge base for these paths is the pinned official baseline. The following is
the behavior-bearing content of each side of each conflict, with exact source
locations at the pinned refs.

### `agent/verification_stop.py`

Maintained hunk (`6fd54dc`, lines 116–147 and 207–218) keeps the fail-closed
exports and checks evidence identity and scope:

```python
def verification_unresolved(*, session_id, changed_paths):
    """Fail closed for code edits unless a current same-session Hermes verifier passed."""
    # terminal receipts are diagnostics; only kind=verify, same session, scope=full clears
    ...
    if not (status == "passed" and kind == "verify" and same_session and scope == "full"):
        return True
```

It also avoids inventing a temporary verifier when no recipe exists and emits a
bounded follow-up that says the verifier is unavailable.

Canary hunk (`7659332`, lines 169–241) removes `verification_unresolved` and
`has_verifiable_paths` from the public surface, changes the nudge condition to
`status == "passed"`, imports `last_unattributed_run`, and offers a
`hermes-verify-` temporary-script path. In effect, a passed worker/ad-hoc receipt
can make `build_verify_on_stop_nudge()` return `None`; that is incompatible with
DEC-004. Its pipeline-status warning is diagnostic material only and is not an
approved change to the completion authority.

### `tests/agent/test_verification_stop.py`

Maintained hunk (`6fd54dc`, lines 122–196) asserts that an ad-hoc worker pass,
worker command receipt, and missing/stale/foreign/failed verifier evidence remain
unresolved; it separately permits current full verifier evidence and suppresses
docs-only work.

Canary hunk (`7659332`, lines 119–209) changes the ad-hoc assertion to expect no
nudge, adds a piped-command success path, and adds warnings for unattributed shell
status. Those expectations would make a worker-controlled or temporary-script
receipt look like independent completion evidence, so they are not adopted.

The new [FHM-011 compatibility test](../../../tests/agent/test_fhm011_canary_verification_compatibility.py)
adds a cross-function contract rather than copying the existing cases: it checks
the recorded receipt kind, status, independent unresolved result, and nudge result
together; covers default-session mismatch and pre-edit/targeted verifier cases;
and checks both retry boundaries and docs/code path filtering.

## Keep / adapt / reject / unknown

| Item from the canary conflict | Disposition | Contract |
|---|---|---|
| Maintained strict `verification_unresolved` and `has_verifiable_paths` exports | **KEEP** | Preserve DEC-004 fail-closed behavior and the docs-only exception. |
| Maintained same-session, current, full `hermes verify` acceptance | **KEEP** | This is the only phase-one source receipt that clears the guard; it is not trusted attestation. |
| Worker-only terminal receipt treated as completion | **REJECT** | A worker controls its own report and cannot independently attest its effect. |
| `/tmp` ad-hoc script receipt treated as completion | **REJECT** | A temporary script is targeted evidence at most, never independent acceptance. |
| Canary `last_unattributed_run` / pipeline status message | **ADAPT** | Candidate diagnostic only, if it remains observational and cannot change status, scope, authority, or completion. No adoption is made here. |
| Canary temporary-script nudge guidance | **REJECT** | It conflicts with the maintained no-recipe fail-closed message and could invite false acceptance. |
| Canary positive ad-hoc/piped test expectations | **REJECT** | They encode the incompatible completion contract. |
| Any missing trusted verifier, authority, or OS identity boundary | **UNKNOWN** | Requires the separate FHM-005 architecture, security, durability, and native qualification gates; this task does not invent approval. |

## Scope boundary and downstream gates

Only the separate compatibility test and this document are added. The ten other
textually overlapping paths from the rehearsal are unchanged and remain semantic
review scope:

`agent/auxiliary_client.py`, `agent/conversation_loop.py`,
`agent/reasoning_params.py`, `agent/turn_context.py`,
`agent/turn_final_response.py`, `agent/turn_finalizer.py`,
`agent/turn_tool_round.py`, `agent/verification_evidence.py`,
`hermes_cli/models_local.py`, and `tools/delegate_tool.py`.

No FHM-005 production code, trusted verifier, decision file, or existing verifier
test was edited. No canary merge or release qualification is implied. Before any
future adoption review, the selected candidate must re-run the affected gates for
FHM-001, FHM-002, FHM-004, FHM-005, FHM-006, FHM-007, FHM-017, and FHM-018,
including their required real-process, persistence, compaction, memory, bounded
stop/recovery, and model/provider checks where applicable.

The negative tests are source-contract regression tests only. They are not
independent attestation, Linux/Windows trust qualification, canary merge
qualification, or real-model acceptance. They use temporary local fixtures and do
not contact LM Studio, require secrets, or use the network.

## Acceptance conditions for this gate

- The maintained SHA remains unchanged and the worktree contains no production
  verifier change.
- The compatibility test fails if a future canary merge makes worker terminal
  success or an ad-hoc `/tmp` script clear the independent guard.
- The compatibility test fails if failed, stale, foreign, session-mismatched,
  targeted/zero-work, or missing evidence is reported as completed.
- Docs-only edits do not create a verification demand; mixed edits retain the code
  demand; retry attempts stop at the configured bound.
- Focused test, lint/format, and diff checks are reported with PASS/SKIP/blocked
  status separately. No unrun hosted, native-OS, Cursor, or canary qualification
  gate is represented as passed by this source-only change.
