"""Pure contract tests for the unpromoted FHM-005 trusted-verifier boundary."""

from datetime import UTC, datetime, timedelta
import json

import pytest

from agent.trusted_verifier_contract import (
    CONTRACT_ROOT,
    CONTRACT_VERSION,
    ArtifactSubject,
    ExpectedEffect,
    ReceiptStatus,
    ValidationStatus,
    VerificationRequest,
    validate_receipt,
)


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
POLICY_DIGEST = "sha256:" + "1" * 64
ARTIFACT_DIGEST = "sha256:" + "2" * 64


def _request(**changes):
    values = {
        "root": CONTRACT_ROOT,
        "version": CONTRACT_VERSION,
        "session_id": "session-1",
        "attempt_id": "attempt-1",
        "authority": "parent-authority",
        "scope": ("workspace:hermes",),
        "policy_digest": POLICY_DIGEST,
        "nonce": "nonce-1",
        "correlation_id": "corr-1",
        "expected_effects": (
            ExpectedEffect(effect="write", subject="file:src/app.py", digest=ARTIFACT_DIGEST),
        ),
        "expires_at": NOW + timedelta(minutes=10),
        "freshness_seconds": 60,
    }
    values.update(changes)
    return VerificationRequest(**values)


def _receipt(request=None, **changes):
    request = request or _request()
    values = {
        **request.to_mapping(),
        "artifact_subjects": [
            ArtifactSubject(subject="file:src/app.py", digest=ARTIFACT_DIGEST).to_mapping(),
        ],
        "status": ReceiptStatus.VERIFIED.value,
        "issued_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }
    values.pop("freshness_seconds")
    values.update(changes)
    return values


def _validate(payload=None, request=None, **kwargs):
    request = request or _request()
    return validate_receipt(
        request, _receipt(request) if payload is None else payload,
        consumed_nonces=kwargs.pop("consumed_nonces", set()),
        trusted_source=kwargs.pop("trusted_source", True),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def test_current_receipt_verifies_only_with_external_trust_and_consumes_nonce():
    consumed = set()
    result = _validate(consumed_nonces=consumed, trusted_source=True)

    assert result.status is ValidationStatus.VERIFIED
    assert result.verified
    assert consumed == {"nonce-1"}


def test_worker_forged_trusted_flag_is_not_receipt_authority():
    payload = _receipt()
    payload["trusted_source"] = True

    result = _validate(payload, trusted_source=True)

    assert result.status is ValidationStatus.INCOMPLETE
    assert result.reasons[0].startswith("unparseable_receipt:")


def test_missing_external_provenance_is_incomplete():
    result = _validate(trusted_source=False)

    assert result.status is ValidationStatus.INCOMPLETE
    assert result.reasons == ("untrusted_provenance",)


@pytest.mark.parametrize("field", ["session_id", "attempt_id", "authority", "scope", "policy_digest", "nonce"])
def test_request_identity_mismatch_is_incomplete(field):
    payload = _receipt()
    if field == "scope":
        payload[field] = ["workspace:other"]
    elif field == "policy_digest":
        payload[field] = "sha256:" + "3" * 64
    elif field == "nonce":
        payload[field] = "nonce-other"
    else:
        payload[field] = f"other-{field}"

    result = _validate(payload)

    assert result.status is ValidationStatus.INCOMPLETE
    assert f"request_mismatch:{field}" in result.reasons


@pytest.mark.parametrize("field", ["policy_digest", "nonce", "correlation_id", "expected_effects"])
def test_receipt_binding_mismatch_is_incomplete(field):
    request = _request()
    payload = _receipt(request)
    if field == "policy_digest":
        payload[field] = "sha256:" + "3" * 64
    elif field == "nonce":
        payload[field] = "nonce-other"
    elif field == "correlation_id":
        payload[field] = "corr-other"
    else:
        payload[field] = []

    result = _validate(payload, request=request)

    assert result.status is ValidationStatus.INCOMPLETE
    assert f"request_mismatch:{field}" in result.reasons


@pytest.mark.parametrize(
    "status", [ReceiptStatus.REJECTED.value, ReceiptStatus.UNAVAILABLE.value, ReceiptStatus.NOT_VERIFIED.value],
)
def test_non_verified_receipt_status_never_succeeds(status):
    result = _validate(_receipt(status=status))

    assert result.status is ValidationStatus.INCOMPLETE
    assert f"receipt_status:{status}" in result.reasons


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"expires_at": NOW.isoformat()}, "receipt_expired"),
        ({"issued_at": (NOW + timedelta(seconds=1)).isoformat()}, "receipt_from_future"),
        ({"issued_at": (NOW - timedelta(seconds=61)).isoformat()}, "receipt_stale"),
        ({"expires_at": (NOW + timedelta(minutes=11)).isoformat()}, "receipt_expiry_exceeds_request"),
    ],
)
def test_stale_future_or_expiry_receipt_is_incomplete(changes, reason):
    result = _validate(_receipt(**changes))

    assert result.status is ValidationStatus.INCOMPLETE
    assert reason in result.reasons


def test_replay_is_rejected_by_caller_owned_nonce_set():
    consumed = {"nonce-1"}

    result = _validate(consumed_nonces=consumed)

    assert result.status is ValidationStatus.INCOMPLETE
    assert result.reasons == ("nonce_replay",)


def test_nonce_set_is_required_and_failed_receipt_does_not_consume_nonce():
    stale = _receipt(issued_at=(NOW - timedelta(seconds=61)).isoformat())
    consumed = set()

    result = _validate(stale, consumed_nonces=consumed)

    assert result.status is ValidationStatus.INCOMPLETE
    assert consumed == set()
    assert _validate(consumed_nonces=frozenset()).status is ValidationStatus.INCOMPLETE


def test_unknown_schema_and_malformed_payload_are_incomplete():
    unknown = _receipt(version=CONTRACT_VERSION + 1)
    malformed = "{not-json"

    assert _validate(unknown).status is ValidationStatus.INCOMPLETE
    assert _validate(malformed).status is ValidationStatus.INCOMPLETE


def test_external_effect_without_observable_artifact_is_incomplete():
    payload = _receipt(artifact_subjects=[])

    result = _validate(payload)

    assert result.status is ValidationStatus.INCOMPLETE
    assert "effects_unobservable_or_mismatched" in result.reasons


def test_json_round_trip_is_platform_neutral():
    payload = _receipt()
    encoded = json.dumps(payload, sort_keys=True)

    result = _validate(encoded)

    assert result.status is ValidationStatus.VERIFIED


def test_invalid_digest_is_incomplete_without_exception():
    payload = _receipt(policy_digest="not-a-digest")

    result = _validate(payload)

    assert result.status is ValidationStatus.INCOMPLETE
    assert result.reasons[0].startswith("unparseable_receipt:")


def test_duplicate_json_keys_at_any_depth_fail_closed():
    payload = _receipt()
    wire = json.dumps(payload)
    # A second trusted-status claim must not be resolved by last-key-wins.
    wire = wire[:-1] + ', "status": "VERIFIED"}'
    assert _validate(wire).status is ValidationStatus.INCOMPLETE
    nested = wire.replace(', "status": "VERIFIED"}', '}')
    nested = nested.replace('"subject": "file:src/app.py"',
                            '"subject": "file:src/app.py", "subject": "file:src/app.py"')
    assert _validate(nested).status is ValidationStatus.INCOMPLETE


def test_empty_expected_effects_never_automatically_verify():
    request = _request(expected_effects=())
    payload = _receipt(request, artifact_subjects=[])
    result = _validate(payload, request=request)
    assert result.status is ValidationStatus.INCOMPLETE
    assert "no_observable_expected_effects" in result.reasons


def test_extra_artifact_subjects_fail_closed():
    payload = _receipt()
    payload["artifact_subjects"].append(
        {"subject": "file:extra.txt", "digest": "sha256:" + "3" * 64}
    )
    result = _validate(payload)
    assert result.status is ValidationStatus.INCOMPLETE
    assert "effects_unobservable_or_mismatched" in result.reasons


def test_expired_request_fails_closed():
    req = _request(expires_at=NOW)
    result = _validate(_receipt(req, expires_at=NOW.isoformat()), request=req)
    assert result.status is ValidationStatus.INCOMPLETE
    assert "request_expired" in result.reasons


def test_truthy_nonboolean_provenance_is_not_authority():
    result = _validate(trusted_source=1)
    assert result.status is ValidationStatus.INCOMPLETE
    assert result.reasons == ("untrusted_provenance",)


def test_invalid_request_and_validation_clock_are_incomplete():
    assert validate_receipt(
        {}, _receipt(), consumed_nonces=set(), trusted_source=True, now=NOW,
    ).status is ValidationStatus.INCOMPLETE
    assert _validate(now="not-a-clock").status is ValidationStatus.INCOMPLETE
