"""Source-only IPC contract for a future paired FHM-005 controller.

This module defines strict request/status data and a fail-closed authorization
decision boundary. It is not imported by runtime completion and provides no
socket, service, verifier, persistence, OS authentication, installation, or
deployment. A future protected parent-authority and verifier-controller pair
must obtain peer evidence from a separate independently protected native
adapter. Linux and Windows qualification, including same-user isolation,
replay durability, restart fencing, process containment, and service ACLs, is
required before either service may use this contract. Python objects and tests
here are not a security boundary or native security qualification.

An authorized decision means only that a bound request may be submitted for
verification. It never means an effect was verified or an attempt succeeded.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from agent.trusted_verifier_contract import (
    ExpectedEffect,
    VerificationRequest,
)


CONTROLLER_PROTOCOL_ROOT = "hermes.trusted_verifier_controller"
CONTROLLER_PROTOCOL_VERSION = 1
MAX_CONTROLLER_MESSAGE_BYTES = 16_384
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_IDENTIFIER_LENGTH = 512
_PEER_EVIDENCE_SEAL = object()


class ControllerProtocolError(ValueError):
    """A wire message or immutable controller binding is malformed."""


class ServiceRole(str, Enum):
    """Roles in the future protected service pair and untrusted worker."""

    PARENT_AUTHORITY = "parent_authority"
    VERIFIER_CONTROLLER = "verifier_controller"
    WORKER = "worker"


class MessageKind(str, Enum):
    REQUEST = "request"
    STATUS = "status"


class ControllerStatus(str, Enum):
    """Transport status only; no status value represents verified success."""

    ACCEPTED_FOR_VERIFICATION = "accepted_for_verification"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


class AuthorizationResult(str, Enum):
    """Fail-closed protocol decision, distinct from verification outcome."""

    AUTHORIZED_FOR_VERIFICATION = "authorized_for_verification"
    INCOMPLETE = "incomplete"
    REJECTED = "rejected"


def _identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or value != value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise ControllerProtocolError(f"{name} is not a canonical identifier")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ControllerProtocolError(f"{name} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True, kw_only=True)
class ControllerBinding:
    """Existing immutable verification request plus protected root/generation."""

    request: VerificationRequest
    root_digest: str
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, VerificationRequest):
            raise ControllerProtocolError("verification request is invalid")
        _digest(self.root_digest, "root_digest")
        if type(self.generation) is not int or not 0 < self.generation < 2**63:
            raise ControllerProtocolError(
                "generation must be a positive 63-bit integer"
            )

    @property
    def session_id(self) -> str:
        return self.request.session_id

    @property
    def attempt_id(self) -> str:
        return self.request.attempt_id

    @property
    def nonce(self) -> str:
        return self.request.nonce

    def to_mapping(self) -> dict[str, object]:
        return {
            "request": self.request.to_mapping(),
            "root_digest": self.root_digest,
            "generation": self.generation,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ControllerBinding:
        fields = {"request", "root_digest", "generation"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ControllerProtocolError("binding fields are not exact")
        request = _verification_request_from_mapping(value["request"])
        return cls(
            request=request,
            root_digest=value["root_digest"],
            generation=value["generation"],
        )


def _verification_request_from_mapping(value: object) -> VerificationRequest:
    fields = {
        "root",
        "version",
        "session_id",
        "attempt_id",
        "authority",
        "scope",
        "policy_digest",
        "nonce",
        "correlation_id",
        "expected_effects",
        "expires_at",
        "freshness_seconds",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ControllerProtocolError("verification request fields are not exact")
    if value["root"] != "hermes.trusted_verification":
        raise ControllerProtocolError("verification request root is unsupported")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ControllerProtocolError("verification request version is unsupported")
    if type(value["freshness_seconds"]) is not int:
        raise ControllerProtocolError("request freshness must be an integer")
    scope = value["scope"]
    effects = value["expected_effects"]
    if not isinstance(scope, list) or not isinstance(effects, list):
        raise ControllerProtocolError("request scope and effects must be arrays")
    expires_at = value["expires_at"]
    if not isinstance(expires_at, str):
        raise ControllerProtocolError("request expiry must be an ISO-8601 string")
    try:
        parsed_expiry = datetime.fromisoformat(expires_at)
        return VerificationRequest(
            root=value["root"],
            version=value["version"],
            session_id=value["session_id"],
            attempt_id=value["attempt_id"],
            authority=value["authority"],
            scope=tuple(scope),
            policy_digest=value["policy_digest"],
            nonce=value["nonce"],
            correlation_id=value["correlation_id"],
            expected_effects=tuple(
                ExpectedEffect.from_mapping(effect) for effect in effects
            ),
            expires_at=parsed_expiry,
            freshness_seconds=value["freshness_seconds"],
        )
    except (TypeError, ValueError) as exc:
        raise ControllerProtocolError("verification request is malformed") from exc


@dataclass(frozen=True, kw_only=True)
class ControllerMessage:
    """Strict, bounded request or status envelope with exact binding echo."""

    kind: MessageKind
    binding: ControllerBinding
    status: ControllerStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MessageKind) or not isinstance(
            self.binding, ControllerBinding
        ):
            raise ControllerProtocolError("message kind or binding is invalid")
        if self.kind is MessageKind.REQUEST and self.status is not None:
            raise ControllerProtocolError("request must not contain status")
        if self.kind is MessageKind.STATUS and not isinstance(
            self.status, ControllerStatus
        ):
            raise ControllerProtocolError("status message requires a known status")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "root": CONTROLLER_PROTOCOL_ROOT,
            "version": CONTROLLER_PROTOCOL_VERSION,
            "kind": self.kind.value,
            "binding": self.binding.to_mapping(),
        }
        if self.status is not None:
            result["status"] = self.status.value
        return result

    def to_wire(self) -> bytes:
        encoded = json.dumps(
            self.to_mapping(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > MAX_CONTROLLER_MESSAGE_BYTES:
            raise ControllerProtocolError("message exceeds the byte limit")
        return encoded

    @classmethod
    def from_wire(cls, payload: bytes) -> ControllerMessage:
        if (
            not isinstance(payload, bytes)
            or len(payload) > MAX_CONTROLLER_MESSAGE_BYTES
        ):
            raise ControllerProtocolError(
                "message is not bytes or exceeds the byte limit"
            )
        try:
            decoded = json.loads(
                payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ControllerProtocolError,
        ) as exc:
            raise ControllerProtocolError("message is not strict UTF-8 JSON") from exc
        if not isinstance(decoded, dict):
            raise ControllerProtocolError("message must be an object")
        common = {"root", "version", "kind", "binding"}
        if decoded.get("root") != CONTROLLER_PROTOCOL_ROOT:
            raise ControllerProtocolError("message root is unsupported")
        if (
            type(decoded.get("version")) is not int
            or decoded["version"] != CONTROLLER_PROTOCOL_VERSION
        ):
            raise ControllerProtocolError("message version is unsupported")
        try:
            kind = MessageKind(decoded.get("kind"))
        except (TypeError, ValueError) as exc:
            raise ControllerProtocolError("message kind is unknown") from exc
        expected = common if kind is MessageKind.REQUEST else common | {"status"}
        if set(decoded) != expected:
            raise ControllerProtocolError("message fields are not exact")
        binding = ControllerBinding.from_mapping(decoded["binding"])
        try:
            status = (
                ControllerStatus(decoded["status"])
                if kind is MessageKind.STATUS
                else None
            )
        except (TypeError, ValueError) as exc:
            raise ControllerProtocolError("message status is unknown") from exc
        return cls(kind=kind, binding=binding, status=status)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ControllerProtocolError("duplicate JSON object key")
        result[key] = value
    return result


@dataclass(frozen=True, kw_only=True, init=False)
class PeerAuthentication:
    """Opaque DTO shape for native-adapter evidence; not authentication itself."""

    role: ServiceRole
    principal_id: str
    process_id: int
    generation: int
    _seal: object = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        role: ServiceRole,
        principal_id: str,
        process_id: int,
        generation: int,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _PEER_EVIDENCE_SEAL:
            raise ControllerProtocolError(
                "peer evidence must come from the native adapter"
            )
        if not isinstance(role, ServiceRole):
            raise ControllerProtocolError("peer role is invalid")
        _identifier(principal_id, "principal_id")
        if type(process_id) is not int or process_id <= 0:
            raise ControllerProtocolError("process_id must be positive")
        if type(generation) is not int or generation <= 0:
            raise ControllerProtocolError("peer generation must be positive")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "principal_id", principal_id)
        object.__setattr__(self, "process_id", process_id)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "_seal", _seal)


def _peer_evidence_from_native_adapter(
    *,
    role: ServiceRole,
    principal_id: str,
    process_id: int,
    generation: int,
) -> PeerAuthentication:
    """Private construction seam for a future independently protected adapter."""
    return PeerAuthentication(
        role=role,
        principal_id=principal_id,
        process_id=process_id,
        generation=generation,
        _seal=_PEER_EVIDENCE_SEAL,
    )


class PeerAuthenticator(Protocol):
    """Future OS adapter API; implementations must verify live peer credentials."""

    def authenticate_peer(self, transport_peer: object) -> PeerAuthentication | None:
        """Return OS-verified evidence or ``None``; never infer from caller claims."""


@dataclass(frozen=True, kw_only=True)
class AuthorizationDecision:
    """Authorization result for IPC submission, never an outcome proof."""

    result: AuthorizationResult
    reason: str


class ControllerAuthority:
    """Pure policy gate against controller-owned immutable bindings.

    The expected binding is supplied by controller-owned state; a request's
    generation is only compared to it and is never used to join live state.
    This model's in-memory nonce set is neither durable nor protected.
    """

    def __init__(self, *, binding: ControllerBinding, consumed_nonces: set[str]):
        if not isinstance(binding, ControllerBinding) or not isinstance(
            consumed_nonces, set
        ):
            raise ControllerProtocolError("controller authority inputs are invalid")
        self._binding = binding
        self._consumed_nonces = consumed_nonces

    def authorize_request(
        self,
        message: ControllerMessage,
        peer: object | None,
    ) -> AuthorizationDecision:
        if not isinstance(message, ControllerMessage):
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="message_invalid"
            )
        if message.kind is not MessageKind.REQUEST:
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="request_required"
            )
        if not _is_authenticated_peer(
            peer,
            ServiceRole.PARENT_AUTHORITY,
            message.binding.generation,
        ):
            return AuthorizationDecision(
                result=AuthorizationResult.INCOMPLETE, reason="peer_unverified"
            )
        if message.binding != self._binding:
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="binding_mismatch"
            )
        if message.binding.nonce in self._consumed_nonces:
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="replay"
            )
        self._consumed_nonces.add(message.binding.nonce)
        return AuthorizationDecision(
            result=AuthorizationResult.AUTHORIZED_FOR_VERIFICATION,
            reason="request_authorized_only",
        )

    def accept_status(
        self,
        message: ControllerMessage,
        peer: object | None,
    ) -> AuthorizationDecision:
        if not isinstance(message, ControllerMessage):
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="message_invalid"
            )
        if message.kind is not MessageKind.STATUS:
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="status_required"
            )
        if not _is_authenticated_peer(
            peer,
            ServiceRole.VERIFIER_CONTROLLER,
            message.binding.generation,
        ):
            return AuthorizationDecision(
                result=AuthorizationResult.INCOMPLETE, reason="peer_unverified"
            )
        if message.binding != self._binding:
            return AuthorizationDecision(
                result=AuthorizationResult.REJECTED, reason="binding_mismatch"
            )
        if message.status is not ControllerStatus.ACCEPTED_FOR_VERIFICATION:
            return AuthorizationDecision(
                result=AuthorizationResult.INCOMPLETE, reason=message.status.value
            )
        return AuthorizationDecision(
            result=AuthorizationResult.AUTHORIZED_FOR_VERIFICATION,
            reason="request_accepted_only",
        )


def _is_authenticated_peer(
    peer: object, expected_role: ServiceRole, generation: int
) -> bool:
    if not isinstance(peer, PeerAuthentication):
        return False
    try:
        return (
            peer._seal is _PEER_EVIDENCE_SEAL
            and peer.role is expected_role
            and peer.generation == generation
        )
    except AttributeError:
        return False
