"""MODEL-ONLY in-memory handshake sketch; never runtime authorization.

The fixture represents evidence already verified by a hypothetical test
adapter. Caller assertions cannot create it via an input message. Real use
requires an independently protected native OS adapter. Python object sealing
is not a security boundary, and this module makes no OS authentication claim.
Nothing here reports trusted success or persists replay/generation state.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Callable

from agent.trusted_verifier_controller_protocol import MAX_CONTROLLER_MESSAGE_BYTES


class HandshakeRejected(ValueError):
    """Malformed, stale, mismatched, expired, replayed, or invalid exchange."""


class Role(str, Enum):
    CONTROLLER = "controller"
    PARENT = "parent"


@dataclass(frozen=True)
class PreverifiedTestFixture:
    """Explicit MODEL-ONLY injected test evidence and shared test secret."""

    role: Role
    session_id: str
    generation: int
    channel: str
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role, Role)
            or not self.session_id
            or len(self.session_id.encode()) > 512
            or self.generation <= 0
            or not self.channel
            or len(self.channel.encode()) > 512
            or not isinstance(self.key, bytes)
            or len(self.key) < 16
        ):
            raise HandshakeRejected("invalid test fixture")


@dataclass(frozen=True)
class Challenge:
    session_id: str
    generation: int
    channel: str
    nonce: bytes
    expires_at: float


@dataclass(frozen=True)
class ParentResponse:
    session_id: str
    generation: int
    channel: str
    nonce: bytes
    proof: bytes


@dataclass(frozen=True)
class SessionCapability:
    """Ephemeral model token, scoped to one session and generation."""

    session_id: str
    generation: int
    token: bytes = field(repr=False)


class HandshakeModel:
    """In-memory challenge verifier. Acceptance is not OS trust or success."""

    def __init__(
        self,
        *,
        controller: PreverifiedTestFixture,
        parent: PreverifiedTestFixture,
        nonce_factory: Callable[[int], bytes] = secrets.token_bytes,
        capability_factory: Callable[[int], bytes] = secrets.token_bytes,
        clock: Callable[[], float] | None = None,
    ):
        if (
            not isinstance(controller, PreverifiedTestFixture)
            or not isinstance(parent, PreverifiedTestFixture)
            or controller.role is not Role.CONTROLLER
            or parent.role is not Role.PARENT
        ):
            raise HandshakeRejected("explicit preverified test fixtures required")
        if (
            controller.session_id != parent.session_id
            or controller.generation != parent.generation
            or controller.channel != parent.channel
            or not hmac.compare_digest(controller.key, parent.key)
        ):
            raise HandshakeRejected("fixture binding mismatch")
        self._controller, self._parent = controller, parent
        self._nonce_factory, self._capability_factory = (
            nonce_factory,
            capability_factory,
        )
        self._clock = clock or (lambda: datetime.now(UTC).timestamp())
        self._pending: Challenge | None = None
        self._consumed: set[bytes] = set()

    def issue_challenge(self, *, ttl_seconds: int = 30) -> Challenge:
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
            raise HandshakeRejected("invalid challenge lifetime")
        nonce = self._nonce_factory(32)
        if not isinstance(nonce, bytes) or len(nonce) != 32 or nonce in self._consumed:
            raise HandshakeRejected("invalid or replayed nonce")
        challenge = Challenge(
            self._controller.session_id,
            self._controller.generation,
            self._controller.channel,
            nonce,
            self._clock() + ttl_seconds,
        )
        self._pending = challenge
        return challenge

    def parent_response(self, challenge: Challenge) -> ParentResponse:
        """Test-fixture parent computes proof; production must use native adapter."""
        if not isinstance(challenge, Challenge):
            raise HandshakeRejected("challenge required")
        proof = hmac.digest(self._parent.key, _transcript(challenge), "sha256")
        return ParentResponse(
            challenge.session_id,
            challenge.generation,
            challenge.channel,
            challenge.nonce,
            proof,
        )

    def accept_response(self, response: ParentResponse) -> SessionCapability:
        challenge = self._pending
        if challenge is None or not isinstance(response, ParentResponse):
            raise HandshakeRejected("no pending challenge")
        if self._clock() >= challenge.expires_at:
            self._pending = None
            self._consumed.add(challenge.nonce)
            raise HandshakeRejected("challenge expired")
        expected = hmac.digest(self._controller.key, _transcript(challenge), "sha256")
        valid = (
            response.session_id == challenge.session_id
            and type(response.generation) is int
            and response.generation == challenge.generation
            and response.channel == challenge.channel
            and response.nonce == challenge.nonce
            and isinstance(response.proof, bytes)
            and hmac.compare_digest(response.proof, expected)
        )
        self._pending = None
        self._consumed.add(challenge.nonce)
        if not valid:
            raise HandshakeRejected("response mismatch")
        token = self._capability_factory(32)
        if not isinstance(token, bytes) or len(token) != 32:
            raise HandshakeRejected("invalid ephemeral capability")
        return SessionCapability(challenge.session_id, challenge.generation, token)


def _transcript(challenge: Challenge) -> bytes:
    fields = (
        challenge.session_id.encode(),
        str(challenge.generation).encode(),
        challenge.channel.encode(),
        challenge.nonce,
    )
    payload = b"hermes.fhm005.model.handshake.v1\0" + b"\0".join(fields)
    if len(payload) > MAX_CONTROLLER_MESSAGE_BYTES:
        raise HandshakeRejected("challenge exceeds protocol limit")
    return payload
