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
