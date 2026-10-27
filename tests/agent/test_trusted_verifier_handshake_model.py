"""Behavior contracts for the non-authoritative in-memory handshake sketch."""

import pytest

from agent.trusted_verifier_handshake_model import (
    HandshakeModel,
    HandshakeRejected,
    ParentResponse,
    PreverifiedTestFixture,
    Role,
)


def _fixtures(*, generation=4, channel="local-test"):
    common = {
        "session_id": "session-a",
        "generation": generation,
        "channel": channel,
        "key": b"fixture shared secret!",
    }
    return (
        PreverifiedTestFixture(role=Role.CONTROLLER, **common),
        PreverifiedTestFixture(role=Role.PARENT, **common),
    )


def _model(**kwargs):
    controller, parent = _fixtures()
    return HandshakeModel(controller=controller, parent=parent, **kwargs)


def test_proof_yields_ephemeral_session_and_generation_bound_capability():
    model = _model(
        nonce_factory=lambda size: b"n" * size,
        capability_factory=lambda size: b"c" * size,
    )
    challenge = model.issue_challenge()
    capability = model.accept_response(model.parent_response(challenge))
    assert (capability.session_id, capability.generation) == ("session-a", 4)
    assert capability.token == b"c" * 32


def test_invalid_untrusted_assertion_cannot_construct_or_replace_fixtures():
    with pytest.raises(HandshakeRejected):
        HandshakeModel(controller=object(), parent=object())
    controller, _ = _fixtures()
    with pytest.raises(HandshakeRejected):
        HandshakeModel(controller=controller, parent=controller)


def test_fixture_role_generation_and_channel_must_match():
    controller, _ = _fixtures()
    _, wrong_generation = _fixtures(generation=5)
    with pytest.raises(HandshakeRejected, match="binding mismatch"):
        HandshakeModel(controller=controller, parent=wrong_generation)
    _, wrong_channel = _fixtures(channel="other")
    with pytest.raises(HandshakeRejected, match="binding mismatch"):
        HandshakeModel(controller=controller, parent=wrong_channel)


def test_response_replay_fails_after_single_use():
    model = _model(nonce_factory=lambda size: b"a" * size)
    challenge = model.issue_challenge()
    response = model.parent_response(challenge)
    model.accept_response(response)
    with pytest.raises(HandshakeRejected, match="no pending"):
        model.accept_response(response)


def test_nonce_replay_fails_closed():
    model = _model(nonce_factory=lambda size: b"r" * size)
    model.issue_challenge()
    with pytest.raises(HandshakeRejected, match="replayed"):
        model.issue_challenge()


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "foreign"),
        ("generation", 5),
        ("channel", "foreign"),
    ],
)
def test_cross_session_generation_or_channel_response_fails(field, value):
    model = _model(nonce_factory=lambda size: b"x" * size)
    challenge = model.issue_challenge()
    response = model.parent_response(challenge)
    altered = {
        "session_id": response.session_id,
        "generation": response.generation,
        "channel": response.channel,
        "nonce": response.nonce,
        "proof": response.proof,
    }
    altered[field] = value
    with pytest.raises(HandshakeRejected, match="mismatch"):
        model.accept_response(ParentResponse(**altered))


def test_expired_challenge_is_consumed():
    now = [10.0]
    model = _model(clock=lambda: now[0], nonce_factory=lambda size: b"e" * size)
    challenge = model.issue_challenge(ttl_seconds=1)
    response = model.parent_response(challenge)
    now[0] = 11.0
    with pytest.raises(HandshakeRejected, match="expired"):
        model.accept_response(response)
    with pytest.raises(HandshakeRejected, match="replayed"):
        model.issue_challenge()


def test_rotation_invalidates_old_challenge_and_nonce_cannot_be_reused():
    counter = iter((b"1" * 32, b"2" * 32))
    model = _model(nonce_factory=lambda size: next(counter))
    old = model.issue_challenge()
    model.issue_challenge()
    with pytest.raises(HandshakeRejected, match="mismatch"):
        model.accept_response(model.parent_response(old))


def test_bad_proof_fails_and_consumes_challenge():
    model = _model(nonce_factory=lambda size: b"f" * size)
    challenge = model.issue_challenge()
    response = model.parent_response(challenge)
    forged = ParentResponse(
        response.session_id,
        response.generation,
        response.channel,
        response.nonce,
        b"z" * 32,
    )
    with pytest.raises(HandshakeRejected, match="mismatch"):
        model.accept_response(forged)
    with pytest.raises(HandshakeRejected, match="no pending"):
        model.accept_response(response)


@pytest.mark.parametrize("ttl", [0, -1, 301, True])
def test_invalid_challenge_lifetime_rejected(ttl):
    with pytest.raises(HandshakeRejected, match="lifetime"):
        _model().issue_challenge(ttl_seconds=ttl)


def test_invalid_nonce_or_capability_factory_fails_closed():
    with pytest.raises(HandshakeRejected, match="nonce"):
        _model(nonce_factory=lambda size: b"short").issue_challenge()
    model = _model(
        nonce_factory=lambda size: b"g" * size, capability_factory=lambda size: b"short"
    )
    challenge = model.issue_challenge()
    with pytest.raises(HandshakeRejected, match="capability"):
        model.accept_response(model.parent_response(challenge))
