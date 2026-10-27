"""Pure monotonic attempt state contract for the unpromoted FHM-005 design.

This module records an attempt's facts and untrusted worker telemetry.  It does
not execute work, persist state, provide CAS/atomicity, or establish a trusted
transport.  A future controller must own those properties before this contract
can be used as security authority.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableSet
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from agent.trusted_verifier_contract import (
    ValidationResult,
    ValidationStatus,
    VerificationRequest,
    validate_receipt,
)


ATTEMPT_CONTRACT_VERSION = 1


class AttemptContractError(ValueError):
    """The attempt value or event cannot be accepted by this contract."""


class AttemptStatus(str, Enum):
    """Monotonic attempt phases; aliases preserve the paired terminology."""

    REQUESTED = "requested"
    RESERVED = "reserved"
    RUNNING = "running"
    EVIDENCE_OBSERVED = "evidence_observed"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED_ACCEPTED = "verified_accepted"
    UNKNOWN_INCOMPLETE = "unknown_incomplete"
    REJECTED_FAILED = "rejected_failed"
    INTERRUPTED_CANCELLED = "interrupted_cancelled"
    VERIFIER_UNAVAILABLE = "verifier_unavailable"
    AWAITING_MANUAL_OR_EXTERNAL_RESOLVER = "awaiting_manual_or_external_resolver"


class AttemptEventKind(str, Enum):
    """Events accepted by the transition table."""

    RESERVE = "reserve"
    START = "start"
    WORKER_PROGRESS = "worker_progress"
    EVIDENCE_OBSERVED = "evidence_observed"
    AWAIT_VERIFICATION = "await_verification"
    TRUSTED_VERIFIED = "trusted_verified"
    WORKER_FAILED = "worker_failed"
    CONTROLLER_REJECT = "controller_reject"
    WORKER_UNKNOWN = "worker_unknown"
    INTERRUPT_CANCEL = "interrupt_cancel"
    VERIFIER_UNAVAILABLE = "verifier_unavailable"
    AWAIT_MANUAL_OR_EXTERNAL = "await_manual_or_external"
    WORKER_SUCCESS = "worker_success"
    MANUAL_RESOLVE = "manual_resolve"


class AttemptEventSource(str, Enum):
    """The only event origins understood by the pure contract."""

    CONTROLLER = "controller"
    WORKER = "worker"
    TRUSTED_VERIFIER = "trusted_verifier"


_ACTIVE = frozenset({
    AttemptStatus.REQUESTED,
    AttemptStatus.RESERVED,
    AttemptStatus.RUNNING,
    AttemptStatus.EVIDENCE_OBSERVED,
    AttemptStatus.AWAITING_VERIFICATION,
    AttemptStatus.VERIFIER_UNAVAILABLE,
})
_RELOAD_UNCERTAIN = frozenset(_ACTIVE - {AttemptStatus.REQUESTED})
_PROOF_CAPABILITY = object()


def _strict_keys(value: Mapping[str, object], expected: frozenset[str], field: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise AttemptContractError(f"{field} fields are not exact")


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AttemptContractError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, kw_only=True, init=False)
class TrustedVerificationProof:
    """Opaque-in-this-module result of ``validate_receipt``.

    The capability is deliberately only a test/future-adapter seam.  It is not
    authentication: Python callers and storage are not protected by this class.
    """

    request: VerificationRequest
    validation: ValidationResult

    def __init__(
        self,
        *,
        request: VerificationRequest,
        validation: ValidationResult,
        _capability: object | None = None,
    ) -> None:
        if _capability is not _PROOF_CAPABILITY:
            raise AttemptContractError("trusted proof must come from validate_receipt")
        if not isinstance(request, VerificationRequest):
            raise AttemptContractError("trusted proof request is invalid")
        if not isinstance(validation, ValidationResult) or validation.status is not ValidationStatus.VERIFIED:
            raise AttemptContractError("trusted proof is not a verified validation result")
        if validation.receipt is None:
            raise AttemptContractError("trusted proof has no validated receipt")
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "validation", validation)

    @property
    def receipt(self):
        """The receipt already accepted by the fail-closed validator."""

        return self.validation.receipt


def make_trusted_verification_proof(
    request: VerificationRequest,
    payload: Mapping[str, object] | str | bytes,
    *,
    consumed_nonces: MutableSet[str],
    trusted_source: bool = False,
    now: datetime | None = None,
) -> TrustedVerificationProof | None:
    """Return a proof only when the existing validator reaches ``VERIFIED``.

    ``trusted_source`` is an out-of-band future-adapter test seam.  There is no
    trusted transport in Hermes today, so this function must not be treated as
    real authority.  Failed validation returns ``None`` and never authorizes a
    state transition.
    """

    validation = validate_receipt(
        request,
        payload,
        consumed_nonces=consumed_nonces,
        trusted_source=trusted_source,
        now=now,
    )
    if not validation.verified:
        return None
    return TrustedVerificationProof(
        request=request,
        validation=validation,
        _capability=_PROOF_CAPABILITY,
    )


@dataclass(frozen=True, kw_only=True)
class AttemptEvent:
    """A bound, timestamped event; receipt text is never an event proof."""

    session_id: str
    attempt_id: str
    kind: AttemptEventKind
    source: AttemptEventSource
    occurred_at: datetime
    proof: TrustedVerificationProof | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise AttemptContractError("event.session_id is invalid")
        if not isinstance(self.attempt_id, str) or not self.attempt_id:
            raise AttemptContractError("event.attempt_id is invalid")
        if not isinstance(self.kind, AttemptEventKind):
            raise AttemptContractError("event.kind is invalid")
        if not isinstance(self.source, AttemptEventSource):
            raise AttemptContractError("event.source is invalid")
        _timestamp(self.occurred_at, "event.occurred_at")
        if self.kind is AttemptEventKind.TRUSTED_VERIFIED:
            if self.source is not AttemptEventSource.TRUSTED_VERIFIER or not isinstance(
                self.proof, TrustedVerificationProof,
            ):
                raise AttemptContractError("trusted verification requires a validator proof")
        elif self.proof is not None:
            raise AttemptContractError("proof is only valid on trusted verification")

    @classmethod
    def from_mapping(cls, value: object) -> AttemptEvent:
        if not isinstance(value, Mapping):
            raise AttemptContractError("event must be an object")
        _strict_keys(value, frozenset({"session_id", "attempt_id", "kind", "source", "occurred_at"}), "event")
        try:
            kind = AttemptEventKind(value["kind"])
            source = AttemptEventSource(value["source"])
        except (TypeError, ValueError) as exc:
            raise AttemptContractError("event kind or source is unknown") from exc
        if kind is AttemptEventKind.TRUSTED_VERIFIED:
            raise AttemptContractError("trusted proof cannot be reconstructed from a mapping")
        if not isinstance(value["occurred_at"], str):
            raise AttemptContractError("event.occurred_at must be an ISO-8601 string")
        try:
            occurred_at = datetime.fromisoformat(value["occurred_at"])
        except ValueError as exc:
            raise AttemptContractError("event.occurred_at is not parseable") from exc
        return cls(
            session_id=value["session_id"],
            attempt_id=value["attempt_id"],
            kind=kind,
            source=source,
            occurred_at=occurred_at,
        )


@dataclass(frozen=True, kw_only=True)
class AttemptState:
    """An immutable snapshot whose transitions only move forward."""

    request: VerificationRequest
    status: AttemptStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, request: VerificationRequest, *, now: datetime) -> AttemptState:
        if not isinstance(request, VerificationRequest):
            raise AttemptContractError("attempt request is invalid")
        current = _timestamp(now, "now")
        if current >= request.expires_at:
            raise AttemptContractError("attempt request is expired")
        return cls(request=request, status=AttemptStatus.REQUESTED, created_at=current, updated_at=current)

    def __post_init__(self) -> None:
        if not isinstance(self.request, VerificationRequest):
            raise AttemptContractError("attempt request is invalid")
        if not isinstance(self.status, AttemptStatus):
            raise AttemptContractError("attempt status is invalid")
        created = _timestamp(self.created_at, "created_at")
        updated = _timestamp(self.updated_at, "updated_at")
        if created > updated:
            raise AttemptContractError("attempt timestamps regress")
        if updated >= self.request.expires_at and self.status is AttemptStatus.REQUESTED:
            raise AttemptContractError("requested attempt is expired")

    @property
    def session_id(self) -> str:
        return self.request.session_id

    @property
    def attempt_id(self) -> str:
        return self.request.attempt_id

    @property
    def authority(self) -> str:
        return self.request.authority

    def to_mapping(self) -> dict[str, object]:
        return {
            "version": ATTEMPT_CONTRACT_VERSION,
            "request": self.request.to_mapping(),
            "status": self.status.value,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        request: VerificationRequest,
        now: datetime,
    ) -> AttemptState:
        """Reload a snapshot, converting uncertain in-flight work to unknown."""

        if not isinstance(value, Mapping):
            raise AttemptContractError("attempt state must be an object")
        _strict_keys(value, frozenset({"version", "request", "status", "created_at", "updated_at"}), "attempt state")
        if not isinstance(request, VerificationRequest):
            raise AttemptContractError("attempt request is invalid")
        if (not isinstance(value["version"], int) or isinstance(value["version"], bool)
                or value["version"] != ATTEMPT_CONTRACT_VERSION
                or value["request"] != request.to_mapping()):
            raise AttemptContractError("attempt snapshot does not match its request")
        try:
            status = AttemptStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise AttemptContractError("attempt status is unknown") from exc
        created = _parse_wire_timestamp(value["created_at"], "created_at")
        updated = _parse_wire_timestamp(value["updated_at"], "updated_at")
        current = _timestamp(now, "now")
        if updated > current:
            raise AttemptContractError("attempt snapshot is from the future")
        # A plain mapping is untrusted, even if it claims a verified terminal state.
        # Rehydrating trusted completion requires a future protected controller store
        # with independently authenticated provenance, not this convenience loader.
        if status is AttemptStatus.VERIFIED_ACCEPTED:
            raise AttemptContractError("trusted completion cannot be restored from untrusted state")
        if status is AttemptStatus.REQUESTED and current >= request.expires_at:
            raise AttemptContractError("expired attempt cannot be resumed")
        state = cls(request=request, status=status, created_at=created, updated_at=updated)
        if status in _RELOAD_UNCERTAIN:
            return cls(request=request, status=AttemptStatus.UNKNOWN_INCOMPLETE,
                       created_at=created, updated_at=current)
        return state

    def apply(self, event: AttemptEvent, *, now: datetime) -> AttemptState:
        """Apply one event and return a new snapshot, or reject it."""

        if not isinstance(event, AttemptEvent):
            raise AttemptContractError("event is invalid")
        current = _timestamp(now, "now")
        occurred = _timestamp(event.occurred_at, "event.occurred_at")
        if current < self.updated_at:
            raise AttemptContractError("validation clock moved backwards")
        if occurred > current:
            raise AttemptContractError("event is from the future")
        if occurred < self.created_at:
            raise AttemptContractError("event predates the attempt")
        if event.session_id != self.session_id or event.attempt_id != self.attempt_id:
            raise AttemptContractError("event is bound to another attempt")
        target = self._target(event)
        # No active or accepting transition is allowed after the request's
        # deadline, including replaying a previously requested/reserved attempt.
        if current >= self.request.expires_at and target in _ACTIVE | {AttemptStatus.VERIFIED_ACCEPTED}:
            raise AttemptContractError("expired attempt cannot advance")
        if target is self.status:
            return self
        if occurred < self.updated_at:
            raise AttemptContractError("event is stale")
        if current >= self.request.expires_at and target is AttemptStatus.VERIFIED_ACCEPTED:
            raise AttemptContractError("verification request is expired")
        if target is AttemptStatus.VERIFIED_ACCEPTED:
            self._require_proof(event)
        return AttemptState(
            request=self.request,
            status=target,
            created_at=self.created_at,
            updated_at=current,
        )

    def _target(self, event: AttemptEvent) -> AttemptStatus:
        allowed: dict[AttemptEventKind, tuple[frozenset[AttemptStatus], AttemptStatus, AttemptEventSource]] = {
            AttemptEventKind.RESERVE: (frozenset({AttemptStatus.REQUESTED, AttemptStatus.RESERVED}), AttemptStatus.RESERVED, AttemptEventSource.CONTROLLER),
            AttemptEventKind.START: (frozenset({AttemptStatus.RESERVED, AttemptStatus.RUNNING}), AttemptStatus.RUNNING, AttemptEventSource.CONTROLLER),
            AttemptEventKind.WORKER_PROGRESS: (frozenset({AttemptStatus.RUNNING}), AttemptStatus.RUNNING, AttemptEventSource.WORKER),
            AttemptEventKind.EVIDENCE_OBSERVED: (frozenset({AttemptStatus.RUNNING, AttemptStatus.EVIDENCE_OBSERVED}), AttemptStatus.EVIDENCE_OBSERVED, AttemptEventSource.CONTROLLER),
            AttemptEventKind.AWAIT_VERIFICATION: (frozenset({AttemptStatus.RUNNING, AttemptStatus.EVIDENCE_OBSERVED, AttemptStatus.AWAITING_VERIFICATION}), AttemptStatus.AWAITING_VERIFICATION, AttemptEventSource.CONTROLLER),
            AttemptEventKind.TRUSTED_VERIFIED: (frozenset({AttemptStatus.AWAITING_VERIFICATION, AttemptStatus.VERIFIED_ACCEPTED}), AttemptStatus.VERIFIED_ACCEPTED, AttemptEventSource.TRUSTED_VERIFIER),
            AttemptEventKind.WORKER_FAILED: (frozenset(_ACTIVE - {AttemptStatus.REQUESTED, AttemptStatus.UNKNOWN_INCOMPLETE}), AttemptStatus.REJECTED_FAILED, AttemptEventSource.WORKER),
            AttemptEventKind.CONTROLLER_REJECT: (_ACTIVE | {AttemptStatus.REJECTED_FAILED}, AttemptStatus.REJECTED_FAILED, AttemptEventSource.CONTROLLER),
            AttemptEventKind.WORKER_UNKNOWN: (frozenset({*(_ACTIVE - {AttemptStatus.REQUESTED}), AttemptStatus.UNKNOWN_INCOMPLETE}), AttemptStatus.UNKNOWN_INCOMPLETE, AttemptEventSource.WORKER),
            AttemptEventKind.INTERRUPT_CANCEL: (_ACTIVE | {AttemptStatus.INTERRUPTED_CANCELLED}, AttemptStatus.INTERRUPTED_CANCELLED, AttemptEventSource.CONTROLLER),
            AttemptEventKind.VERIFIER_UNAVAILABLE: (frozenset({AttemptStatus.AWAITING_VERIFICATION, AttemptStatus.VERIFIER_UNAVAILABLE}), AttemptStatus.VERIFIER_UNAVAILABLE, AttemptEventSource.CONTROLLER),
            AttemptEventKind.AWAIT_MANUAL_OR_EXTERNAL: (frozenset({AttemptStatus.VERIFIER_UNAVAILABLE, AttemptStatus.AWAITING_MANUAL_OR_EXTERNAL_RESOLVER}), AttemptStatus.AWAITING_MANUAL_OR_EXTERNAL_RESOLVER, AttemptEventSource.CONTROLLER),
        }
        if event.kind in {AttemptEventKind.WORKER_SUCCESS, AttemptEventKind.MANUAL_RESOLVE}:
            raise AttemptContractError("worker success and manual resolution cannot authorize acceptance")
        transition = allowed.get(event.kind)
        if transition is None:
            raise AttemptContractError("event kind is not allowed")
        sources, target, source = transition
        if event.source is not source:
            raise AttemptContractError("event source is not trusted for this transition")
        if self.status not in sources:
            raise AttemptContractError(f"transition {self.status.value} -> {target.value} is not allowed")
        if target is AttemptStatus.VERIFIED_ACCEPTED:
            self._require_proof(event)
        return target

    def _require_proof(self, event: AttemptEvent) -> None:
        proof = event.proof
        if not isinstance(proof, TrustedVerificationProof) or proof.request != self.request:
            raise AttemptContractError("acceptance requires a bound trusted validator proof")
        if not proof.validation.verified or proof.receipt is None:
            raise AttemptContractError("acceptance requires successful receipt validation")
        # Do not accept a manually constructed proof whose validation/receipt
        # belongs to another attempt. The future controller must still supply
        # genuine authenticated provenance and durable one-use CAS.
        receipt = proof.receipt
        for field in ("root", "version", "session_id", "attempt_id", "authority", "scope",
                      "policy_digest", "nonce", "correlation_id", "expected_effects"):
            if getattr(receipt, field) != getattr(self.request, field):
                raise AttemptContractError("trusted proof receipt is foreign")
        if not self.request.expected_effects:
            raise AttemptContractError("zero expected effects cannot be verified")


def _parse_wire_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise AttemptContractError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AttemptContractError(f"{field} is not parseable") from exc
    return _timestamp(parsed, field)


__all__ = [
    "ATTEMPT_CONTRACT_VERSION",
    "AttemptContractError",
    "AttemptEvent",
    "AttemptEventKind",
    "AttemptEventSource",
    "AttemptState",
    "AttemptStatus",
    "TrustedVerificationProof",
    "make_trusted_verification_proof",
]
