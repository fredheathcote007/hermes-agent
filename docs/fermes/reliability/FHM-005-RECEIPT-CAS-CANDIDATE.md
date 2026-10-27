# FHM-005 receipt CAS candidate model

Status: source-only, non-authoritative candidate model. This document and
`agent/trusted_verifier_receipt_store.py` do not implement the protected
controller, verifier, transport, service identity, or any runtime completion
path. The SQLite row, lifecycle flags, and Python API can never attest that an
external effect happened.

## Scope and inputs

`CandidateReceiptStore` is a small stdlib `sqlite3` model for a future
architecture-reviewed controller. It accepts the existing immutable
`VerificationRequest` as logical input plus a caller-provided `root_digest`
and positive `generation`. These values are identifiers and digests, not
authenticators. In particular, a nonce is not secret and is never treated as
peer authentication.

The store records only:

- contract root/version and the opaque session, attempt, authority, correlation,
  nonce, policy digest, root digest, and generation;
- ordered scope identifiers and their canonical digest;
- a digest of the complete logical request, issue/expiry timestamps, and the
  candidate lifecycle state.

It does not persist receipt JSON, expected-effect text, commands, output,
credentials, secrets, or a `trusted_source` claim. `CandidateConsumeResult`
reports only a candidate database transition. Even `consumed=True` is not a
`TrustedVerificationProof` and must not be wired to attempt acceptance.

## Atomic state model

The schema is SQLite `user_version=1`; unknown versions, partially present
unversioned tables, missing columns, and unexpected tables fail closed. There
are no implicit migrations. New versions require an explicit reviewed model
and migration instead of silently interpreting old rows.

Every issue and consume/reconcile operation uses `BEGIN IMMEDIATE`. A bounded
busy timeout prevents indefinite lock waits. Issue inserts are unique on:

```text
(attempt_id, nonce, authority, session_id, policy_digest, root_digest, generation)
```

The UNIQUE key intentionally **omits `correlation_id`**: adding correlation
would allow a second record with the same nonce/attempt/authority/session/policy/root/generation
by changing only the correlation ID. The full request digest still binds the
correlation during consume, so the two checks provide separate guarantees.
Adversarial tests explicitly reject different-correlation and different-freshness
re-issuance under the same nonce and reject consuming a modified expected effect.

Consume performs one conditional `UPDATE ... WHERE state='issued'` including
the full request digest, exact ordered scope, timestamps, and all identity
fields. Exactly one committed update can produce `CONSUMED`; replay, foreign
identity, wrong nonce/attempt/session/scope, stale generation, expiry, or
already reconciled state returns `INCOMPLETE`. Failed bodies roll back. A
commit error is treated as ambiguous and the connection is invalidated rather
than retried.

Rows are `issued`, `consumed`, `expired`, or `unknown_incomplete`. Expired
rows are fenced before a consume attempt. After a crash or uncertain restart,
reopening an existing database enters a `reconcile_required` startup barrier.
The future controller must call `reconcile_after_restart` before issue/consume
operations: all still-issued rows are durably changed to `unknown_incomplete`.
They cannot be consumed, resumed, or converted to verified success. A
controller that has independently established that another process still owns
the live generation may use the explicit `open_for_live_generation` API (or
its join method), passing that generation. This is only a non-authenticating
candidate-model gate: it does not establish service identity, liveness,
authority, or trusted completion. This deliberately does not infer whether an
external mutation happened, and it does not replay the mutation.

## P1 integration gate

This source-only model is not integration-ready. Before any protected
controller or worker wiring, integration must provide an explicit architecture
and security gate for restart fencing, live-generation ownership, service
identity, and manual recovery. The `open_for_live_generation` API is a
caller-controlled, unsafe bypass of crash fencing: it can consume an existing
issued row without reconciliation when the caller supplies the matching
generation. It MUST NEVER be exposed to workers or routine callers. A future
protected controller must authenticate the live generation with out-of-band
proof, or remove this API. `CandidateConsumeResult.consumed` remains only a
candidate transition and never authorizes completion.

If that gate is unavailable or a live-generation proof is ambiguous, the
required behavior is fail-closed: do not issue or consume, reconcile the store
to `unknown_incomplete` when safe, and use an operator-approved manual fallback
for any retry or recovery. No automatic resume or completion claim is valid.

## Durability and scope limits

The model requests SQLite WAL mode and `synchronous=FULL`, and tests use local
POSIX temporary files. This is a candidate local-file durability profile for
local POSIX/NTFS behavior only; it makes no unsupported guarantee for network,
remote, or otherwise unusual filesystems. The model requires an absolute path,
an existing parent directory whose path components are not symlinks, and a
non-symlink regular database file. This is an open-time check only and is not
a TOCTOU defense. A future protected controller still has to enforce owner-only
directory/file permissions, service identity, process isolation, retention/purge,
and its native Linux and Windows qualification gates. The model does not
establish any of those boundaries.

The adversarial tests cover duplicate identity rollback, one-use replay,
cross-session and foreign scope rejection, expiry, generation/root mismatch,
bounded `BEGIN IMMEDIATE` contention, multiple processes, restart
reconciliation, schema fail-closed behavior, interrupted writes, and complete
close. They are model tests only. They do not prove external-effect
verification, crash-point coverage of a protected controller, OS identity,
remote-filesystem behavior, or authorization to report Hermes work complete.
