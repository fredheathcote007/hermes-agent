"""Pure monotonic attempt-state contract tests for FHM-005."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.trusted_verifier_attempt import (
    AttemptContractError,
    AttemptEvent,
    AttemptEventKind,
    AttemptEventSource,
    AttemptState,
    AttemptStatus,
    make_trusted_verification_proof,
)
from agent.trusted_verifier_contract import (
    CONTRACT_ROOT,
    CONTRACT_VERSION,
    ArtifactSubject,
    ExpectedEffect,
    ReceiptStatus,
    VerificationRequest,
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
            ExpectedEffect(effect="write", subject="file:result.txt", digest=ARTIFACT_DIGEST),
        ),
        "expires_at": NOW + timedelta(minutes=10),
        "freshness_seconds": 60,
    }
    values.update(changes)
    return VerificationRequest(**values)


def _receipt(request):
    receipt = {
        **request.to_mapping(),
        "artifact_subjects": [
            ArtifactSubject(subject="file:result.txt", digest=ARTIFACT_DIGEST).to_mapping(),
        ],
        "status": ReceiptStatus.VERIFIED.value,
        "issued_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }
    receipt.pop("freshness_seconds")
    return receipt


def _event(state, kind, source, at=NOW, **kwargs):
    return AttemptEvent(
        session_id=state.session_id,
        attempt_id=state.attempt_id,
        kind=kind,
        source=source,
        occurred_at=at,
        **kwargs,
    )


def _running_state(request=None):
    state = AttemptState.new(request or _request(), now=NOW)
    state = state.apply(_event(state, AttemptEventKind.RESERVE, AttemptEventSource.CONTROLLER), now=NOW)
    return state.apply(
        _event(state, AttemptEventKind.START, AttemptEventSource.CONTROLLER),
        now=NOW,
    )


def _awaiting_state(request=None):
    state = _running_state(request)
    state = state.apply(
        _event(state, AttemptEventKind.EVIDENCE_OBSERVED, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    return state.apply(
        _event(state, AttemptEventKind.AWAIT_VERIFICATION, AttemptEventSource.CONTROLLER),
        now=NOW,
    )


def _proof(request=None, *, trusted_source=True):
    request = request or _request()
    return make_trusted_verification_proof(
        request,
        _receipt(request),
        consumed_nonces=set(),
        trusted_source=trusted_source,
        now=NOW,
    )


def test_full_monotonic_table_reaches_acceptance_only_through_trusted_proof():
    state = AttemptState.new(_request(), now=NOW)
    assert state.status is AttemptStatus.REQUESTED
    state = state.apply(_event(state, AttemptEventKind.RESERVE, AttemptEventSource.CONTROLLER), now=NOW)
    assert state.status is AttemptStatus.RESERVED
    state = state.apply(_event(state, AttemptEventKind.START, AttemptEventSource.CONTROLLER), now=NOW)
    assert state.status is AttemptStatus.RUNNING
    state = state.apply(
        _event(state, AttemptEventKind.EVIDENCE_OBSERVED, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    state = state.apply(
        _event(state, AttemptEventKind.AWAIT_VERIFICATION, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    proof = _proof(state.request)
    state = state.apply(
        _event(
            state,
            AttemptEventKind.TRUSTED_VERIFIED,
            AttemptEventSource.TRUSTED_VERIFIER,
            proof=proof,
        ),
        now=NOW,
    )
    assert state.status is AttemptStatus.VERIFIED_ACCEPTED


@pytest.mark.parametrize(
    "kind, source, expected",
    [
        (AttemptEventKind.RESERVE, AttemptEventSource.WORKER, AttemptStatus.RESERVED),
        (AttemptEventKind.START, AttemptEventSource.WORKER, AttemptStatus.RUNNING),
        (AttemptEventKind.EVIDENCE_OBSERVED, AttemptEventSource.WORKER, AttemptStatus.EVIDENCE_OBSERVED),
        (AttemptEventKind.AWAIT_VERIFICATION, AttemptEventSource.WORKER, AttemptStatus.AWAITING_VERIFICATION),
        (AttemptEventKind.TRUSTED_VERIFIED, AttemptEventSource.WORKER, AttemptStatus.VERIFIED_ACCEPTED),
        (AttemptEventKind.WORKER_SUCCESS, AttemptEventSource.WORKER, AttemptStatus.VERIFIED_ACCEPTED),
    ],
)
def test_worker_cannot_advance_or_self_certify(kind, source, expected):
    state = AttemptState.new(_request(), now=NOW)
    with pytest.raises(AttemptContractError):
        state.apply(_event(state, kind, source), now=NOW)
    assert state.status is AttemptStatus.REQUESTED
    assert expected is not state.status


def test_worker_progress_is_idempotent_but_worker_success_is_not_a_transition():
    state = _running_state()
    duplicate = state.apply(
        _event(state, AttemptEventKind.WORKER_PROGRESS, AttemptEventSource.WORKER),
        now=NOW,
    )
    assert duplicate is state
    with pytest.raises(AttemptContractError):
        state.apply(
            _event(state, AttemptEventKind.WORKER_SUCCESS, AttemptEventSource.WORKER),
            now=NOW,
        )


def test_failed_and_unknown_outcomes_cannot_become_success():
    failed = _running_state().apply(
        _event(_running_state(), AttemptEventKind.WORKER_FAILED, AttemptEventSource.WORKER),
        now=NOW,
    )
    assert failed.status is AttemptStatus.REJECTED_FAILED
    with pytest.raises(AttemptContractError):
        failed.apply(
            _event(failed, AttemptEventKind.TRUSTED_VERIFIED, AttemptEventSource.TRUSTED_VERIFIER, proof=_proof()),
            now=NOW,
        )

    unknown = _running_state().apply(
        _event(_running_state(), AttemptEventKind.WORKER_UNKNOWN, AttemptEventSource.WORKER),
        now=NOW,
    )
    assert unknown.status is AttemptStatus.UNKNOWN_INCOMPLETE
    assert unknown.apply(
        _event(unknown, AttemptEventKind.WORKER_UNKNOWN, AttemptEventSource.WORKER),
        now=NOW,
    ) is unknown
    with pytest.raises(AttemptContractError):
        unknown.apply(
            _event(unknown, AttemptEventKind.WORKER_PROGRESS, AttemptEventSource.WORKER),
            now=NOW,
        )


def test_verifier_unavailable_preserves_manual_resolution_wait():
    state = _awaiting_state()
    state = state.apply(
        _event(state, AttemptEventKind.VERIFIER_UNAVAILABLE, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    state = state.apply(
        _event(state, AttemptEventKind.AWAIT_MANUAL_OR_EXTERNAL, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    assert state.status is AttemptStatus.AWAITING_MANUAL_OR_EXTERNAL_RESOLVER
    with pytest.raises(AttemptContractError):
        state.apply(
            _event(state, AttemptEventKind.MANUAL_RESOLVE, AttemptEventSource.CONTROLLER),
            now=NOW,
        )


def test_controller_reject_and_interrupt_are_terminal_fail_closed_branches():
    rejected = AttemptState.new(_request(), now=NOW).apply(
        _event(AttemptState.new(_request(), now=NOW), AttemptEventKind.CONTROLLER_REJECT, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    assert rejected.status is AttemptStatus.REJECTED_FAILED

    interrupted = _running_state().apply(
        _event(_running_state(), AttemptEventKind.INTERRUPT_CANCEL, AttemptEventSource.CONTROLLER),
        now=NOW,
    )
    assert interrupted.status is AttemptStatus.INTERRUPTED_CANCELLED
    with pytest.raises(AttemptContractError):
        interrupted.apply(
            _event(interrupted, AttemptEventKind.START, AttemptEventSource.CONTROLLER),
            now=NOW,
        )


def test_trusted_proof_requires_validator_and_zero_effects_never_verify():
    request = _request()
    assert _proof(request, trusted_source=False) is None
    with pytest.raises(AttemptContractError):
        from agent.trusted_verifier_attempt import TrustedVerificationProof

        TrustedVerificationProof(request=request, validation=object())

    no_effects = _request(expected_effects=())
    assert _proof(no_effects) is None


def test_cross_attempt_events_and_bad_times_fail_closed():
    state = _running_state()
    foreign = AttemptEvent(
        session_id="other-session",
        attempt_id=state.attempt_id,
        kind=AttemptEventKind.WORKER_PROGRESS,
        source=AttemptEventSource.WORKER,
        occurred_at=NOW,
    )
    with pytest.raises(AttemptContractError):
        state.apply(foreign, now=NOW)
    future = _event(state, AttemptEventKind.WORKER_PROGRESS, AttemptEventSource.WORKER, NOW + timedelta(seconds=1))
    with pytest.raises(AttemptContractError):
        state.apply(future, now=NOW)
    stale = _event(state, AttemptEventKind.WORKER_PROGRESS, AttemptEventSource.WORKER, NOW - timedelta(seconds=1))
    with pytest.raises(AttemptContractError):
        state.apply(stale, now=NOW + timedelta(seconds=1))


def test_trusted_completion_rejects_wrong_source_and_event_binding():
    state = _awaiting_state()
    proof = _proof(state.request)

    with pytest.raises(AttemptContractError, match="trusted verification requires a validator proof"):
        _event(
            state,
            AttemptEventKind.TRUSTED_VERIFIED,
            AttemptEventSource.CONTROLLER,
            proof=proof,
        )

    foreign_event = AttemptEvent(
        session_id=state.session_id,
        attempt_id="foreign-attempt",
        kind=AttemptEventKind.TRUSTED_VERIFIED,
        source=AttemptEventSource.TRUSTED_VERIFIER,
        occurred_at=NOW,
        proof=proof,
    )
    with pytest.raises(AttemptContractError, match="another attempt"):
        state.apply(foreign_event, now=NOW)


def test_terminal_rejection_is_idempotent_but_cannot_change_outcome():
    state = _running_state()
    rejected = state.apply(
        _event(state, AttemptEventKind.WORKER_FAILED, AttemptEventSource.WORKER),
        now=NOW,
    )

    assert rejected.apply(
        _event(rejected, AttemptEventKind.WORKER_FAILED, AttemptEventSource.WORKER),
        now=NOW,
    ) is rejected
    with pytest.raises(AttemptContractError):
        rejected.apply(
            _event(rejected, AttemptEventKind.INTERRUPT_CANCEL, AttemptEventSource.CONTROLLER),
            now=NOW,
        )


def test_reload_turns_uncertain_in_flight_snapshot_into_sticky_unknown_without_replay():
    state = _running_state()
    restored = AttemptState.from_mapping(
        state.to_mapping(), request=state.request, now=NOW + timedelta(minutes=1),
    )
    assert restored.status is AttemptStatus.UNKNOWN_INCOMPLETE
    with pytest.raises(AttemptContractError):
        restored.apply(
            _event(restored, AttemptEventKind.START, AttemptEventSource.CONTROLLER),
            now=NOW + timedelta(minutes=1),
        )


def test_reload_rejects_invalid_or_future_snapshot():
    state = _running_state()
    invalid = state.to_mapping()
    invalid["unexpected"] = True
    with pytest.raises(AttemptContractError):
        AttemptState.from_mapping(invalid, request=state.request, now=NOW)
    future = state.to_mapping()
    future["updated_at"] = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(AttemptContractError):
        AttemptState.from_mapping(future, request=state.request, now=NOW)


def test_event_mapping_rejects_trusted_claim_without_proof():
    with pytest.raises(AttemptContractError):
        AttemptEvent.from_mapping({
            "session_id": "session-1",
            "attempt_id": "attempt-1",
            "kind": AttemptEventKind.TRUSTED_VERIFIED.value,
            "source": AttemptEventSource.TRUSTED_VERIFIER.value,
            "occurred_at": NOW.isoformat().replace("+00:00", "Z"),
        })


def test_untrusted_saved_snapshot_cannot_rehydrate_verified_success():
    state = _running_state()
    saved = state.to_mapping()
    saved["status"] = AttemptStatus.VERIFIED_ACCEPTED.value
    with pytest.raises(AttemptContractError, match="trusted completion cannot be restored"):
        AttemptState.from_mapping(saved, request=state.request, now=NOW)


def test_expired_requested_snapshot_does_not_restart():
    state = AttemptState.new(_request(), now=NOW)
    saved = state.to_mapping()
    with pytest.raises(AttemptContractError, match="expired attempt cannot be resumed"):
        AttemptState.from_mapping(saved, request=state.request, now=state.request.expires_at)


def test_expired_active_state_cannot_advance():
    state = AttemptState.new(_request(), now=NOW)
    with pytest.raises(AttemptContractError, match="expired attempt cannot advance"):
        state.apply(_event(state, AttemptEventKind.RESERVE, AttemptEventSource.CONTROLLER),
                    now=state.request.expires_at)


def test_forged_proof_for_another_attempt_cannot_authorize_completion():
    import agent.trusted_verifier_attempt as attempt_module
    from agent.trusted_verifier_attempt import TrustedVerificationProof
    from agent.trusted_verifier_contract import (
        ValidationResult, ValidationStatus, VerificationReceipt,
    )

    state = _awaiting_state()
    other_request = _request(attempt_id="foreign-attempt", nonce="foreign-nonce")
    foreign_receipt = VerificationReceipt.from_mapping(_receipt(other_request))
    forged_proof = TrustedVerificationProof(
        request=state.request,
        validation=ValidationResult(
            status=ValidationStatus.VERIFIED,
            receipt=foreign_receipt,
        ),
        _capability=attempt_module._PROOF_CAPABILITY,
    )
    with pytest.raises(AttemptContractError, match="trusted proof receipt is foreign"):
        state.apply(
            _event(state, AttemptEventKind.TRUSTED_VERIFIED,
                   AttemptEventSource.TRUSTED_VERIFIER, proof=forged_proof),
            now=NOW,
        )


@pytest.mark.parametrize("phase", [AttemptStatus.EVIDENCE_OBSERVED, AttemptStatus.AWAITING_VERIFICATION])
def test_late_worker_failure_cannot_override_controller_evidence_phase(phase):
    state = _running_state()
    state = state.apply(_event(state, AttemptEventKind.EVIDENCE_OBSERVED,
                               AttemptEventSource.CONTROLLER), now=NOW)
    if phase is AttemptStatus.AWAITING_VERIFICATION:
        state = state.apply(_event(state, AttemptEventKind.AWAIT_VERIFICATION,
                                   AttemptEventSource.CONTROLLER), now=NOW)
    with pytest.raises(AttemptContractError, match="not allowed"):
        state.apply(_event(state, AttemptEventKind.WORKER_FAILED,
                           AttemptEventSource.WORKER), now=NOW)
    assert state.status is phase
