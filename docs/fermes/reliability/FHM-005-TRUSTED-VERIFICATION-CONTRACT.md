# FHM-005 trusted-verification contract foundation

Status: safe, unpromoted foundation; the trusted-verifier architecture remains draft.

`agent/trusted_verifier_contract.py` defines a small versioned wire contract for a future
independently verified transport adapter. It is intentionally disconnected from Hermes defaults,
the CLI/TUI/gateway, process launch, sockets, ACLs, installers, keys, persistence, and external
effect inspection.

## Contract shape

Every receipt carries `root=hermes.trusted_verification` and `version=1`, then echoes the immutable
request identity:

- `session_id`, `attempt_id`, `authority`, ordered `scope`, `policy_digest`, `nonce`, and
  `correlation_id`;
- the ordered `expected_effects`, each with an effect name, subject identity, and expected SHA-256
  digest;
- `status`, `issued_at`, `expires_at`, and ordered `artifact_subjects`, each with a subject and
  observed SHA-256 digest.

The receipt deliberately has no `trusted_source` field. A worker cannot make its own JSON
authoritative. `validate_receipt(..., trusted_source=True)` accepts that boolean only as an
out-of-band fact injected by a future independently verified transport adapter; the default is
false.

## Fail-closed rules

Validation returns `INCOMPLETE` for malformed or non-object input, unknown root/version, unknown
fields (including a worker-supplied trust flag), missing fields, invalid digests or timestamps,
untrusted provenance, any request identity mismatch, non-`VERIFIED` status, stale/future/expired
receipts, expiry beyond the request, replayed nonces, or unobservable/mismatched effects. A
`VERIFIED` outcome requires the artifact subject/digest sequence to exactly account for every
expected effect. A caller-owned mutable nonce set is required; the validator adds a nonce only
after all checks pass and never maintains global replay state.

A request with no observable expected effects cannot produce automated VERIFIED;
prose-only tasks and external effects without independent readback use the
manual/external fallback pending a separately approved evidence policy.
Ambiguous duplicate JSON object keys are rejected rather than last-key-wins.

The caller owns synchronization and durable storage for that set. Until those properties are
provided by a qualified adapter/controller, this module cannot provide replay protection across
threads or restarts by itself.

## Security limits and next qualification gate

This contract validates shape, binding, freshness, and caller-provided provenance. It does not
prove that a worker did or did not perform an effect, inspect the platform, authenticate a peer,
protect the nonce set, isolate privileges, or establish a trusted root. The four receipt statuses
are data, not independent evidence. Existing phase-one verify-on-stop evidence remains
non-authoritative under DEC-004.

The next permissible action is an architecture-reviewed transport/controller design that can
independently inject provenance and durable nonce ownership, followed by native Linux and Windows
security/operational qualification under DEC-005. No deployment or trust-boundary change is part
of this foundation.

## Monotonic attempt state contract

`agent/trusted_verifier_attempt.py` adds a pure, immutable snapshot model for one bound attempt. It
is not enabled by Hermes and does not implement a controller. The request identity binds the
session, attempt, authority and expected effects; every event must repeat the exact session and
attempt identity. Event timestamps cannot be from the future or older than the current snapshot.
Invalid mappings, unknown fields, wrong sources and regressive transitions fail closed.

The allowed progression is:

```text
requested -> reserved -> running -> evidence_observed -> awaiting_verification
                                                        -> verified_accepted
```

The exact event/source branches are:

| Event | Source | Allowed from | Result |
| --- | --- | --- | --- |
| `reserve` | controller | requested | reserved |
| `start` | controller | reserved | running |
| `worker_progress` | worker | running | running (idempotent) |
| `evidence_observed` | controller | running | evidence_observed |
| `await_verification` | controller | running or evidence_observed | awaiting_verification |
| `trusted_verified` | future trusted-verifier seam | awaiting_verification | verified_accepted |
| `worker_failed` | worker | reserved, running, or evidence_observed | rejected_failed |
| `worker_unknown` | worker | reserved through verifier_unavailable | unknown_incomplete |
| `interrupt_cancel` | controller | any active state | interrupted_cancelled |
| `verifier_unavailable` | controller | awaiting_verification | verifier_unavailable |
| `await_manual_or_external` | controller | verifier_unavailable | awaiting_manual_or_external_resolver |

`controller_reject` may move any active state to `rejected_failed`; all duplicate events whose
result is already the current state are idempotent. No other edges exist.

Worker telemetry can report progress, failure (`rejected_failed`) or unknown
(`unknown_incomplete`), but it cannot report success, observe trusted evidence, or authorize
acceptance. `unknown_incomplete` is sticky. A verifier outage may progress through
`verifier_unavailable` to `awaiting_manual_or_external_resolver`; no manual resolver is implemented,
so that state remains awaiting. Failed, interrupted/cancelled and verified/accepted states are
terminal and immutable, apart from a future separately approved operator evidence path.

Reloading a snapshot that was reserved, running, evidence-observed, awaiting verification, or
verifier-unavailable converts it to `unknown_incomplete`. The model never replays work. A verified
transition requires a `TrustedVerificationProof` produced only after `validate_receipt` returned
`VERIFIED` with caller-injected `trusted_source=True`; receipt text, model output, and worker claims
cannot create that proof. This is only a test/future-adapter seam: Python object construction is not
authentication, and the model is not atomic persistent state until a future controller supplies
protected storage and compare-and-swap semantics. Zero expected effects remain ineligible for
automatic verification.


The pure attempt-state snapshot loader is **not a trusted proof store**. It rejects
a serialized `verified_accepted` status, even when the other snapshot fields
match. Any future recovery of a genuine verified result needs independently
authenticated service-owned persistence and a separately reviewed load path.
Untrusted saved status text must never restore verified success.
