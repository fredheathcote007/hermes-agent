"""Pure, versioned data contract for a future trusted-verifier boundary.

This module is deliberately a contract and validator, not a verifier.  It does
not execute commands, inspect a workspace, establish provenance, authenticate a
transport, persist replay state, or make a receipt trustworthy.  A future
independently verified transport adapter must supply ``trusted_source=True`` to
``validate_receipt``; that value is never read from receipt data.

Validation is fail-closed: only a current, fresh, session/attempt/authority/
scope/policy/nonce/correlation-bound ``VERIFIED`` receipt whose exact expected
effects are observable and whose nonce is not in the caller-owned consumed set
gets the ``VERIFIED`` outcome.  Everything else is ``INCOMPLETE``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, MutableSet
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


CONTRACT_ROOT = "hermes.trusted_verification"
CONTRACT_VERSION = 1

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_MAX_LENGTH = 512


class ReceiptStatus(str, Enum):
    """Status a receipt reports; only ``VERIFIED`` can pass validation."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_VERIFIED = "NOT_VERIFIED"


class ValidationStatus(str, Enum):
    """Safe result exposed to a caller of the fail-closed validator."""

    VERIFIED = "VERIFIED"
    INCOMPLETE = "INCOMPLETE"


class ContractParseError(ValueError):
    """The untrusted payload is not a valid current contract value."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _IDENTIFIER_MAX_LENGTH:
        raise ContractParseError(f"{field} must be a non-empty string")
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise ContractParseError(f"{field} is not a canonical identifier")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ContractParseError(f"{field} must be a lowercase sha256 digest")
    return value


def _utc_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ContractParseError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractParseError(f"{field} is not parseable") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractParseError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _strict_keys(value: Mapping[str, object], expected: frozenset[str], field: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if unknown:
            detail.append(f"unknown={unknown}")
        raise ContractParseError(f"{field} fields are not exact ({', '.join(detail)})")


@dataclass(frozen=True, kw_only=True)
class ArtifactSubject:
    """An independently observed subject and its content/state digest."""

    subject: str
    digest: str

    def __post_init__(self) -> None:
        _identifier(self.subject, "artifact.subject")
        _digest(self.digest, "artifact.digest")

    def to_mapping(self) -> dict[str, str]:
        return {"subject": self.subject, "digest": self.digest}

    @classmethod
    def from_mapping(cls, value: object) -> ArtifactSubject:
        if not isinstance(value, Mapping):
            raise ContractParseError("artifact must be an object")
        _strict_keys(value, frozenset({"subject", "digest"}), "artifact")
        return cls(subject=_identifier(value["subject"], "artifact.subject"),
                   digest=_digest(value["digest"], "artifact.digest"))


@dataclass(frozen=True, kw_only=True)
class ExpectedEffect:
    """The exact effect and artifact digest the request requires evidence for."""

    effect: str
    subject: str
    digest: str

    def __post_init__(self) -> None:
        _identifier(self.effect, "effect.effect")
        _identifier(self.subject, "effect.subject")
        _digest(self.digest, "effect.digest")

    def to_mapping(self) -> dict[str, str]:
        return {"effect": self.effect, "subject": self.subject, "digest": self.digest}

    @classmethod
    def from_mapping(cls, value: object) -> ExpectedEffect:
        if not isinstance(value, Mapping):
            raise ContractParseError("expected effect must be an object")
        _strict_keys(value, frozenset({"effect", "subject", "digest"}), "expected effect")
        return cls(
            effect=_identifier(value["effect"], "effect.effect"),
            subject=_identifier(value["subject"], "effect.subject"),
            digest=_digest(value["digest"], "effect.digest"),
        )


def _immutable_sequence(values: object, field: str, parser: Any) -> tuple[Any, ...]:
    if not isinstance(values, (list, tuple)):
        raise ContractParseError(f"{field} must be an array")
    parsed = tuple(parser(value) for value in values)
    if len({value for value in parsed}) != len(parsed):
        raise ContractParseError(f"{field} must not contain duplicates")
    return parsed


@dataclass(frozen=True, kw_only=True)
class VerificationRequest:
    """Immutable request identity and the effects a receipt must account for."""

    root: str
    version: int
    session_id: str
    attempt_id: str
    authority: str
    scope: tuple[str, ...]
    policy_digest: str
    nonce: str
    correlation_id: str
    expected_effects: tuple[ExpectedEffect, ...]
    expires_at: datetime
    freshness_seconds: int

    def __post_init__(self) -> None:
        if self.root != CONTRACT_ROOT or self.version != CONTRACT_VERSION:
            raise ContractParseError("request schema root/version is unsupported")
        for field in ("session_id", "attempt_id", "authority", "nonce", "correlation_id"):
            _identifier(getattr(self, field), f"request.{field}")
        if not isinstance(self.scope, tuple) or not self.scope:
            raise ContractParseError("request.scope must be a non-empty tuple")
        if len(set(self.scope)) != len(self.scope):
            raise ContractParseError("request.scope must not contain duplicates")
        for item in self.scope:
            _identifier(item, "request.scope item")
        _digest(self.policy_digest, "request.policy_digest")
        if not isinstance(self.expected_effects, tuple):
            raise ContractParseError("request.expected_effects must be a tuple")
        if len(set(self.expected_effects)) != len(self.expected_effects):
            raise ContractParseError("request.expected_effects must not contain duplicates")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise ContractParseError("request.expires_at must include a timezone")
        if not isinstance(self.freshness_seconds, int) or isinstance(self.freshness_seconds, bool) \
                or self.freshness_seconds <= 0:
            raise ContractParseError("request.freshness_seconds must be positive")

    def to_mapping(self) -> dict[str, object]:
        return {
            "root": self.root,
            "version": self.version,
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "authority": self.authority,
            "scope": list(self.scope),
            "policy_digest": self.policy_digest,
            "nonce": self.nonce,
            "correlation_id": self.correlation_id,
            "expected_effects": [effect.to_mapping() for effect in self.expected_effects],
            "expires_at": _wire_datetime(self.expires_at),
            "freshness_seconds": self.freshness_seconds,
        }


_RECEIPT_FIELDS = frozenset({
    "root", "version", "session_id", "attempt_id", "authority", "scope", "policy_digest",
    "nonce", "correlation_id", "expected_effects", "artifact_subjects", "status", "issued_at",
    "expires_at",
})


@dataclass(frozen=True, kw_only=True)
class VerificationReceipt:
    """Untrusted receipt data; provenance is intentionally not a receipt field."""

    root: str
    version: int
    session_id: str
    attempt_id: str
    authority: str
    scope: tuple[str, ...]
    policy_digest: str
    nonce: str
    correlation_id: str
    expected_effects: tuple[ExpectedEffect, ...]
    artifact_subjects: tuple[ArtifactSubject, ...]
    status: ReceiptStatus
    issued_at: datetime
    expires_at: datetime

    def to_mapping(self) -> dict[str, object]:
        return {
            "root": self.root,
            "version": self.version,
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "authority": self.authority,
            "scope": list(self.scope),
            "policy_digest": self.policy_digest,
            "nonce": self.nonce,
            "correlation_id": self.correlation_id,
            "expected_effects": [effect.to_mapping() for effect in self.expected_effects],
            "artifact_subjects": [artifact.to_mapping() for artifact in self.artifact_subjects],
            "status": self.status.value,
            "issued_at": _wire_datetime(self.issued_at),
            "expires_at": _wire_datetime(self.expires_at),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> VerificationReceipt:
        _strict_keys(value, _RECEIPT_FIELDS, "receipt")
        if value["root"] != CONTRACT_ROOT or value["version"] != CONTRACT_VERSION:
            raise ContractParseError("receipt schema root/version is unsupported")
        status_value = value["status"]
        try:
            status = ReceiptStatus(status_value)
        except (TypeError, ValueError) as exc:
            raise ContractParseError("receipt.status is unknown") from exc
        scope = _immutable_sequence(value["scope"], "receipt.scope", lambda item: _identifier(item, "scope item"))
        return cls(
            root=CONTRACT_ROOT,
            version=CONTRACT_VERSION,
            session_id=_identifier(value["session_id"], "receipt.session_id"),
            attempt_id=_identifier(value["attempt_id"], "receipt.attempt_id"),
            authority=_identifier(value["authority"], "receipt.authority"),
            scope=scope,
            policy_digest=_digest(value["policy_digest"], "receipt.policy_digest"),
            nonce=_identifier(value["nonce"], "receipt.nonce"),
            correlation_id=_identifier(value["correlation_id"], "receipt.correlation_id"),
            expected_effects=_immutable_sequence(
                value["expected_effects"], "receipt.expected_effects", ExpectedEffect.from_mapping,
            ),
            artifact_subjects=_immutable_sequence(
                value["artifact_subjects"], "receipt.artifact_subjects", ArtifactSubject.from_mapping,
            ),
            status=status,
            issued_at=_utc_datetime(value["issued_at"], "receipt.issued_at"),
            expires_at=_utc_datetime(value["expires_at"], "receipt.expires_at"),
        )


@dataclass(frozen=True, kw_only=True)
class ValidationResult:
    """Validation outcome and non-authoritative diagnostics for an operator."""

    status: ValidationStatus
    reasons: tuple[str, ...] = ()
    receipt: VerificationReceipt | None = None

    @property
    def verified(self) -> bool:
        return self.status is ValidationStatus.VERIFIED


def _wire_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _payload_mapping(payload: Mapping[str, object] | str | bytes) -> Mapping[str, object]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractParseError("receipt is not UTF-8") from exc
    if not isinstance(payload, str):
        raise ContractParseError("receipt must be a mapping, JSON string, or UTF-8 bytes")
    try:
        decoded = json.loads(payload, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant {value}"),
        ))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractParseError("receipt JSON is not parseable") from exc
    if not isinstance(decoded, Mapping):
        raise ContractParseError("receipt JSON must contain an object")
    return decoded


def _incomplete(*reasons: str, receipt: VerificationReceipt | None = None) -> ValidationResult:
    return ValidationResult(status=ValidationStatus.INCOMPLETE, reasons=tuple(reasons), receipt=receipt)


def validate_receipt(
    request: VerificationRequest,
    payload: Mapping[str, object] | str | bytes,
    *,
    consumed_nonces: MutableSet[str],
    trusted_source: bool = False,
    now: datetime | None = None,
) -> ValidationResult:
    """Validate one untrusted receipt against a request.

    ``trusted_source`` is an out-of-band fact supplied by a future independently
    verified transport adapter.  It is false by default and a receipt field with
    that name is rejected as an unknown field.  ``consumed_nonces`` belongs to
    the caller: the caller must provide its synchronization and durable storage
    if validation crosses threads or process restarts.  This function adds the
    nonce only after all checks pass; it never removes or globally tracks one.
    """
    if not isinstance(request, VerificationRequest):
        return _incomplete("invalid_request")
    if trusted_source is not True:
        return _incomplete("untrusted_provenance")
    if not isinstance(consumed_nonces, MutableSet):
        return _incomplete("caller_nonce_set_required")
    current_time = now if now is not None else datetime.now(UTC)
    if not isinstance(current_time, datetime) or current_time.tzinfo is None:
        return _incomplete("invalid_validation_time")
    current_time = current_time.astimezone(UTC)
    try:
        receipt = VerificationReceipt.from_mapping(_payload_mapping(payload))
    except ContractParseError as exc:
        return _incomplete(f"unparseable_receipt:{exc}")

    reasons: list[str] = []
    for field in ("root", "version", "session_id", "attempt_id", "authority", "scope",
                  "policy_digest", "nonce", "correlation_id", "expected_effects"):
        if getattr(receipt, field) != getattr(request, field):
            reasons.append(f"request_mismatch:{field}")
    if receipt.status is not ReceiptStatus.VERIFIED:
        reasons.append(f"receipt_status:{receipt.status.value}")
    if current_time >= request.expires_at:
        reasons.append("request_expired")
    if receipt.issued_at > current_time:
        reasons.append("receipt_from_future")
    if receipt.expires_at <= current_time:
        reasons.append("receipt_expired")
    if receipt.expires_at > request.expires_at:
        reasons.append("receipt_expiry_exceeds_request")
    if (current_time - receipt.issued_at).total_seconds() > request.freshness_seconds:
        reasons.append("receipt_stale")

    expected_artifacts = tuple(
        ArtifactSubject(subject=effect.subject, digest=effect.digest)
        for effect in request.expected_effects
    )
    if receipt.artifact_subjects != expected_artifacts:
        reasons.append("effects_unobservable_or_mismatched")
    if reasons:
        return _incomplete(*reasons, receipt=receipt)
    try:
        if receipt.nonce in consumed_nonces:
            return _incomplete("nonce_replay", receipt=receipt)
        consumed_nonces.add(receipt.nonce)
    except (KeyError, TypeError, ValueError):
        return _incomplete("caller_nonce_set_unavailable", receipt=receipt)
    return ValidationResult(status=ValidationStatus.VERIFIED, receipt=receipt)


__all__ = [
    "CONTRACT_ROOT",
    "CONTRACT_VERSION",
    "ArtifactSubject",
    "ContractParseError",
    "ExpectedEffect",
    "ReceiptStatus",
    "ValidationResult",
    "ValidationStatus",
    "VerificationReceipt",
    "VerificationRequest",
    "validate_receipt",
]
