"""Negative contract tests for the non-authoritative FHM-005 IPC boundary."""

import json
from datetime import UTC, datetime

import pytest

from agent.trusted_verifier_controller_protocol import (
    MAX_CONTROLLER_MESSAGE_BYTES,
    AuthorizationResult,
    ControllerAuthority,
    ControllerBinding,
    ControllerMessage,
    ControllerProtocolError,
    ControllerStatus,
    MessageKind,
    PeerAuthentication,
    ServiceRole,
    _peer_evidence_from_native_adapter,
)
from agent.trusted_verifier_contract import (
    CONTRACT_ROOT,
    CONTRACT_VERSION,
    ExpectedEffect,
    VerificationRequest,
)


def _binding(**changes):
    binding_values = {"root_digest": "sha256:" + "a" * 64, "generation": 3}
    request_values = {
        "root": CONTRACT_ROOT,
        "version": CONTRACT_VERSION,
        "session_id": "session-1",
        "attempt_id": "attempt-1",
        "authority": "parent-authority",
        "scope": ("workspace:hermes",),
        "policy_digest": "sha256:" + "b" * 64,
        "nonce": "nonce-1",
        "correlation_id": "correlation-1",
        "expected_effects": (
            ExpectedEffect(
                effect="write", subject="file:result.txt", digest="sha256:" + "c" * 64
            ),
        ),
        "expires_at": datetime(2026, 10, 27, 12, 5, tzinfo=UTC),
        "freshness_seconds": 60,
    }
    request_changes = {
        key: value for key, value in changes.items() if key in request_values
    }
    binding_changes = {
        key: value for key, value in changes.items() if key in binding_values
    }
    request_values.update(request_changes)
    binding_values.update(binding_changes)
    request = VerificationRequest(**request_values)
    return ControllerBinding(request=request, **binding_values)


def _peer(role=ServiceRole.PARENT_AUTHORITY, *, generation=3):
    # Synthetic DTOs exercise only fail-closed negative decisions. They are not
    # evidence of OS authentication or a native security qualification.
    return _peer_evidence_from_native_adapter(
        role=role,
        principal_id="service-parent",
        process_id=41,
        generation=generation,
    )


def _authority(binding=None, consumed=None):
    binding = binding or _binding()
    return ControllerAuthority(
        binding=binding, consumed_nonces=consumed if consumed is not None else set()
    )


def test_wire_round_trip_preserves_exact_binding_and_request_has_no_claim_field():
    message = ControllerMessage(kind=MessageKind.REQUEST, binding=_binding())

    decoded = ControllerMessage.from_wire(message.to_wire())

    assert decoded == message
    assert "trusted_source" not in decoded.to_mapping()
    assert "authenticated" not in decoded.to_mapping()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"root":"hermes.trusted_verifier_controller","version":true}',
        b'{"root":"hermes.trusted_verifier_controller","root":"forged"}',
        b"{}",
    ],
)
def test_malformed_or_duplicate_wire_message_fails_closed(payload):
    with pytest.raises(ControllerProtocolError):
        ControllerMessage.from_wire(payload)


def test_unknown_fields_and_worker_trust_claim_are_rejected():
    mapping = ControllerMessage(
        kind=MessageKind.REQUEST, binding=_binding()
    ).to_mapping()
    mapping["trusted_source"] = True

    with pytest.raises(ControllerProtocolError, match="fields are not exact"):
        ControllerMessage.from_wire(json.dumps(mapping).encode())


def test_oversized_wire_message_is_rejected_before_json_parse():
    with pytest.raises(ControllerProtocolError, match="byte limit"):
        ControllerMessage.from_wire(b" " * (MAX_CONTROLLER_MESSAGE_BYTES + 1))


def test_same_user_arbitrary_caller_and_forged_peer_dto_cannot_authorize():
    message = ControllerMessage(kind=MessageKind.REQUEST, binding=_binding())
    authority = _authority()
    forged = object.__new__(PeerAuthentication)

    assert (
        authority.authorize_request(message, object()).result
        is AuthorizationResult.INCOMPLETE
    )
    assert (
        authority.authorize_request(message, forged).result
        is AuthorizationResult.INCOMPLETE
    )


@pytest.mark.parametrize("missing_attribute", ["_seal", "role", "generation"])
def test_incomplete_peer_dto_fails_closed(missing_attribute):
    message = ControllerMessage(kind=MessageKind.REQUEST, binding=_binding())
    authority = _authority()
    forged = object.__new__(PeerAuthentication)
    for attribute in ("_seal", "role", "generation"):
        if attribute != missing_attribute:
            object.__setattr__(
                forged,
                attribute,
                {
                    "_seal": object(),
                    "role": ServiceRole.PARENT_AUTHORITY,
                    "generation": 3,
                }[attribute],
            )

    result = authority.authorize_request(message, forged)

    assert result.result is AuthorizationResult.INCOMPLETE
    assert result.reason == "peer_unverified"


def test_worker_role_and_generation_mismatch_cannot_authorize():
    message = ControllerMessage(kind=MessageKind.REQUEST, binding=_binding())
    authority = _authority()

    worker = _peer(ServiceRole.WORKER)
    foreign_generation = _peer(generation=4)

    assert (
        authority.authorize_request(message, worker).result
        is AuthorizationResult.INCOMPLETE
    )
    assert (
        authority.authorize_request(message, foreign_generation).result
        is AuthorizationResult.INCOMPLETE
    )


def test_foreign_session_attempt_scope_policy_or_root_is_rejected():
    expected = _binding()
    authority = _authority(expected)
    peer = _peer()
    foreign_values = (
        {"session_id": "session-foreign"},
        {"attempt_id": "attempt-foreign"},
        {"scope": ("workspace:other",)},
        {"policy_digest": "sha256:" + "c" * 64},
        {"root_digest": "sha256:" + "d" * 64},
    )

    for changes in foreign_values:
        message = ControllerMessage(
            kind=MessageKind.REQUEST, binding=_binding(**changes)
        )
        assert (
            authority.authorize_request(message, peer).result
            is AuthorizationResult.REJECTED
        )

    foreign_generation = ControllerMessage(
        kind=MessageKind.REQUEST,
        binding=_binding(generation=4),
    )
    result = authority.authorize_request(foreign_generation, peer)

    assert result.result is AuthorizationResult.INCOMPLETE
    assert result.reason == "peer_unverified"


def test_replayed_nonce_is_rejected_even_with_matching_peer_and_binding():
    binding = _binding()
    authority = _authority(binding, {binding.nonce})
    message = ControllerMessage(kind=MessageKind.REQUEST, binding=binding)

    result = authority.authorize_request(message, _peer())

    assert result.result is AuthorizationResult.REJECTED
    assert result.reason == "replay"


def test_unavailable_or_unverified_status_never_reports_verified_success():
    binding = _binding()
    authority = _authority(binding)
    message = ControllerMessage(
        kind=MessageKind.STATUS,
        binding=binding,
        status=ControllerStatus.UNAVAILABLE,
    )

    result = authority.accept_status(message, _peer(ServiceRole.VERIFIER_CONTROLLER))

    assert result.result is AuthorizationResult.INCOMPLETE
    assert result.reason == "unavailable"
