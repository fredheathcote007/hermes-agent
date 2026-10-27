"""Non-authoritative SQLite candidate receipt model for FHM-005.

This module is deliberately not a verifier, controller, receipt authority, or
trusted proof store.  It models the durable state and compare-and-swap edges a
future protected controller would need.  A row only records opaque request
identity, scope identifiers, digests, and lifecycle state; it never stores a
receipt payload, command, output, credential, or provenance flag.

The database is suitable for local POSIX/NTFS experiments when its directory
is protected by the eventual controller.  SQLite cannot provide the same
durability or locking claim on an arbitrary remote filesystem, so this module
does not make that claim.  A successful consume result is only a candidate
store transition and must never be used as trusted completion.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Self

from agent.trusted_verifier_contract import VerificationRequest


CANDIDATE_STORE_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_GENERATION = 2**63 - 1
_EXPECTED_TABLES = frozenset({"candidate_receipts"})
_EXPECTED_COLUMNS = frozenset({
    "row_id", "schema_version", "root", "root_version", "root_digest", "session_id",
    "attempt_id", "authority", "scope_json", "scope_digest", "policy_digest", "nonce",
    "correlation_id", "request_digest", "generation", "issued_at", "expires_at", "state",
    "consumed_at", "reconciled_at",
})


class CandidateReceiptStoreError(RuntimeError):
    """The candidate store could not give a definitive successful outcome."""


class CandidateReceiptStoreClosed(CandidateReceiptStoreError):
    """The candidate store has already been closed or invalidated."""


class CandidateReceiptStoreSchemaError(CandidateReceiptStoreError):
    """The database schema is absent, unsupported, or ambiguous."""


class CandidateReceiptStoreBusy(CandidateReceiptStoreError):
    """The bounded SQLite writer wait expired without acquiring the write lock."""


class CandidateReceiptStoreInputError(CandidateReceiptStoreError, ValueError):
    """An invalid or incomplete candidate input was rejected."""


class CandidateReceiptStoreConflict(CandidateReceiptStoreError):
    """An exact candidate identity has already been issued."""


class CandidateState(str, Enum):
    """Durable states; only ISSUED may move to CONSUMED."""

    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    UNKNOWN_INCOMPLETE = "unknown_incomplete"


class CandidateConsumeStatus(str, Enum):
    """Safe result of a candidate consume attempt."""

    CONSUMED = "consumed"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, kw_only=True)
class CandidateReceipt:
    """An in-memory candidate handle, not an attestation or trusted proof."""

    request: VerificationRequest
    root_digest: str
    generation: int
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _validate_digest(self.root_digest, "root_digest")
        _validate_generation(self.generation)
        if not isinstance(self.request, VerificationRequest):
            raise CandidateReceiptStoreInputError("candidate request is invalid")
        issued = _utc(self.issued_at, "issued_at")
        expires = _utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise CandidateReceiptStoreInputError("candidate expiry must be after issue time")
        if expires > self.request.expires_at:
            raise CandidateReceiptStoreInputError("candidate expiry exceeds request expiry")


@dataclass(frozen=True, kw_only=True)
class CandidateConsumeResult:
    """A fail-closed store result; ``consumed`` is not trusted verification."""

    status: CandidateConsumeStatus
    reason: str
    state: CandidateState | None = None

    @property
    def consumed(self) -> bool:
        return self.status is CandidateConsumeStatus.CONSUMED


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CandidateReceiptStoreInputError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _wire_time(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _validate_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise CandidateReceiptStoreInputError(f"{field} must be a lowercase sha256 digest")
    return value


def _validate_generation(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_GENERATION:
        raise CandidateReceiptStoreInputError("generation must be a positive 64-bit integer")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _digest_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _request_digest(request: VerificationRequest) -> str:
    return _digest_json(request.to_mapping())


def _scope_json(request: VerificationRequest) -> str:
    return _canonical_json(list(request.scope))


def _scope_digest(request: VerificationRequest) -> str:
    return _digest_json(list(request.scope))


def _validate_request(request: object) -> VerificationRequest:
    if not isinstance(request, VerificationRequest):
        raise CandidateReceiptStoreInputError("request must be a VerificationRequest")
    return request


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Run one bounded writer transaction and roll back every failed body."""

    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise CandidateReceiptStoreBusy("candidate store writer lock was not acquired") from exc
        raise CandidateReceiptStoreError("candidate store transaction could not begin") from exc
    try:
        yield
    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error as rollback_error:
            raise CandidateReceiptStoreError("candidate store rollback failed") from rollback_error
        raise
    try:
        connection.commit()
    except BaseException as exc:
        # The commit outcome is not safely knowable to a caller.  Close this
        # connection so a caller cannot accidentally retry on a stale handle.
        try:
            connection.close()
        finally:
            raise CandidateReceiptStoreError("candidate store commit outcome is ambiguous") from exc


class CandidateReceiptStore:
    """Local SQLite model for durable candidate issue/consume state.

    ``busy_timeout_ms`` is intentionally short and bounded.  The future
    protected controller must own the database path and enforce its OS-level
    scope/permissions; this model only refuses missing parent directories and
    symlinked database files.  Call ``reconcile_after_restart`` before using
    an existing store after a crash: every still-issued row becomes
    ``UNKNOWN_INCOMPLETE`` and can never be resumed or consumed.
    """

    def __init__(self, db_path: str | Path, *, busy_timeout_ms: int = 250) -> None:
        if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 30_000:
            raise CandidateReceiptStoreInputError("busy_timeout_ms is outside its bounded range")
        self.db_path = self._validate_db_path(db_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._connection: sqlite3.Connection | None = None
        try:
            self._connection = sqlite3.connect(
                str(self.db_path), timeout=busy_timeout_ms / 1000, isolation_level=None,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            journal_mode = self._connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise CandidateReceiptStoreSchemaError("candidate store requires SQLite WAL mode")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._initialize_schema()
        except CandidateReceiptStoreError:
            self.close()
            raise
        except sqlite3.Error as exc:
            self.close()
            raise CandidateReceiptStoreSchemaError("candidate store schema setup failed") from exc

    @staticmethod
    def _validate_db_path(db_path: str | Path) -> Path:
        if not isinstance(db_path, (str, Path)) or not str(db_path):
            raise CandidateReceiptStoreInputError("db_path is required")
        path = Path(db_path)
        if not path.is_absolute():
            raise CandidateReceiptStoreInputError("db_path must be absolute")
        if path.exists() and path.is_symlink():
            raise CandidateReceiptStoreInputError("db_path must not be a symlink")
        if not path.parent.is_dir():
            raise CandidateReceiptStoreInputError("db_path parent directory must already exist")
        if path.exists() and not path.is_file():
            raise CandidateReceiptStoreInputError("db_path must name a regular file")
        return path

    def _initialize_schema(self) -> None:
        connection = self._connection_or_raise()
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = frozenset(
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            )
        )
        if user_version not in (0, CANDIDATE_STORE_SCHEMA_VERSION):
            raise CandidateReceiptStoreSchemaError("candidate store schema version is unsupported")
        if user_version == 0 and tables:
            raise CandidateReceiptStoreSchemaError("unversioned candidate store schema is ambiguous")
        if user_version == CANDIDATE_STORE_SCHEMA_VERSION:
            if tables != _EXPECTED_TABLES:
                raise CandidateReceiptStoreSchemaError("candidate store tables are unsupported")
            columns = frozenset(row[1] for row in connection.execute(
                "PRAGMA table_info(candidate_receipts)",
            ))
            if columns != _EXPECTED_COLUMNS:
                raise CandidateReceiptStoreSchemaError("candidate store columns are unsupported")
            return
        with _transaction(connection):
            connection.execute(
                """CREATE TABLE candidate_receipts (
                    row_id INTEGER PRIMARY KEY,
                    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
                    root TEXT NOT NULL,
                    root_version INTEGER NOT NULL,
                    root_digest TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    scope_digest TEXT NOT NULL,
                    policy_digest TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK (generation > 0),
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('issued', 'consumed', 'expired', 'unknown_incomplete')),
                    consumed_at TEXT,
                    reconciled_at TEXT,
                    UNIQUE (attempt_id, nonce, authority, session_id, policy_digest, root_digest, generation)
                )""",
            )
            connection.execute(
                "CREATE INDEX candidate_receipts_state_expiry "
                "ON candidate_receipts (state, expires_at)",
            )
            connection.execute("PRAGMA user_version=1")

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise CandidateReceiptStoreClosed("candidate store is closed")
        return self._connection

    def issue(
        self,
        request: VerificationRequest,
        *,
        root_digest: str,
        generation: int,
        now: datetime | None = None,
    ) -> CandidateReceipt:
        """Atomically issue one candidate row, rejecting duplicate identity."""

        request = _validate_request(request)
        root_digest = _validate_digest(root_digest, "root_digest")
        generation = _validate_generation(generation)
        current = _utc(now if now is not None else datetime.now(UTC), "now")
        if current >= request.expires_at:
            raise CandidateReceiptStoreInputError("cannot issue an expired request")
        candidate = CandidateReceipt(
            request=request, root_digest=root_digest, generation=generation,
            issued_at=current, expires_at=request.expires_at,
        )
        connection = self._connection_or_raise()
        try:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO candidate_receipts (
                        schema_version, root, root_version, root_digest, session_id, attempt_id,
                        authority, scope_json, scope_digest, policy_digest, nonce, correlation_id,
                        request_digest, generation, issued_at, expires_at, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued')
                    """,
                    (
                        CANDIDATE_STORE_SCHEMA_VERSION, request.root, request.version, root_digest,
                        request.session_id, request.attempt_id, request.authority, _scope_json(request),
                        _scope_digest(request), request.policy_digest, request.nonce,
                        request.correlation_id, _request_digest(request), generation,
                        _wire_time(current), _wire_time(request.expires_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise CandidateReceiptStoreConflict("candidate identity is already issued") from exc
            raise CandidateReceiptStoreError("candidate store issue was rejected") from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise CandidateReceiptStoreBusy("candidate store issue lock wait expired") from exc
            raise CandidateReceiptStoreError("candidate store issue failed") from exc
        except sqlite3.Error as exc:
            raise CandidateReceiptStoreError("candidate store issue failed") from exc
        return candidate

    def consume(
        self,
        candidate: CandidateReceipt,
        *,
        now: datetime | None = None,
    ) -> CandidateConsumeResult:
        """Conditionally consume a candidate once, never returning trusted proof."""

        if not isinstance(candidate, CandidateReceipt):
            raise CandidateReceiptStoreInputError("candidate is invalid")
        current = _utc(now if now is not None else datetime.now(UTC), "now")
        request = candidate.request
        connection = self._connection_or_raise()
        try:
            with _transaction(connection):
                self._expire_rows(connection, current)
                cursor = connection.execute(
                    """
                    UPDATE candidate_receipts
                       SET state='consumed', consumed_at=?
                     WHERE state='issued'
                       AND root=? AND root_version=? AND root_digest=?
                       AND session_id=? AND attempt_id=? AND authority=?
                       AND scope_json=? AND scope_digest=? AND policy_digest=?
                       AND nonce=? AND correlation_id=? AND request_digest=?
                       AND generation=? AND issued_at=? AND expires_at=?
                       AND expires_at>?
                    """,
                    (
                        _wire_time(current), request.root, request.version, candidate.root_digest,
                        request.session_id, request.attempt_id, request.authority, _scope_json(request),
                        _scope_digest(request), request.policy_digest, request.nonce,
                        request.correlation_id, _request_digest(request), candidate.generation,
                        _wire_time(candidate.issued_at), _wire_time(candidate.expires_at),
                        _wire_time(current),
                    ),
                )
                if cursor.rowcount == 1:
                    result = CandidateConsumeResult(
                        status=CandidateConsumeStatus.CONSUMED, reason="consumed",
                        state=CandidateState.CONSUMED,
                    )
                else:
                    result = self._incomplete_reason(connection, candidate)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise CandidateReceiptStoreBusy("candidate store consume lock wait expired") from exc
            raise CandidateReceiptStoreError("candidate store consume failed") from exc
        except sqlite3.Error as exc:
            raise CandidateReceiptStoreError("candidate store consume failed") from exc
        return result

    @staticmethod
    def _expire_rows(connection: sqlite3.Connection, now: datetime) -> None:
        connection.execute(
            """
            UPDATE candidate_receipts SET state='expired', reconciled_at=?
             WHERE state='issued' AND expires_at<=?
            """,
            (_wire_time(now), _wire_time(now)),
        )

    @staticmethod
    def _incomplete_reason(
        connection: sqlite3.Connection, candidate: CandidateReceipt,
    ) -> CandidateConsumeResult:
        request = candidate.request
        row = connection.execute(
            """
            SELECT state, request_digest, scope_digest, scope_json, issued_at, expires_at
              FROM candidate_receipts
             WHERE attempt_id=? AND nonce=? AND authority=? AND session_id=?
                   AND policy_digest=? AND root_digest=? AND generation=?
            """,
            (
                request.attempt_id, request.nonce, request.authority, request.session_id,
                request.policy_digest, candidate.root_digest, candidate.generation,
            ),
        ).fetchone()
        if row is None:
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.INCOMPLETE,
                reason="foreign_or_mismatched_identity",
            )
        state = CandidateState(row["state"])
        if state is CandidateState.CONSUMED:
            reason = "replay"
        elif state is CandidateState.EXPIRED:
            reason = "expired"
        elif state is CandidateState.UNKNOWN_INCOMPLETE:
            reason = "unknown_after_restart_reconciliation"
        else:
            reason = "candidate_fields_mismatch"
            if row["scope_digest"] != _scope_digest(request) or row["scope_json"] != _scope_json(request):
                reason = "scope_mismatch"
            elif row["request_digest"] != _request_digest(request):
                reason = "request_mismatch"
            elif row["issued_at"] != _wire_time(candidate.issued_at) or row["expires_at"] != _wire_time(candidate.expires_at):
                reason = "candidate_time_mismatch"
        return CandidateConsumeResult(
            status=CandidateConsumeStatus.INCOMPLETE, reason=reason, state=state,
        )

    def reconcile_after_restart(self, *, now: datetime | None = None) -> int:
        """Fence pending rows after a crash; never resumes unknown work."""

        current = _utc(now if now is not None else datetime.now(UTC), "now")
        connection = self._connection_or_raise()
        try:
            with _transaction(connection):
                self._expire_rows(connection, current)
                cursor = connection.execute(
                    """
                    UPDATE candidate_receipts SET state='unknown_incomplete', reconciled_at=?
                     WHERE state='issued'
                    """,
                    (_wire_time(current),),
                )
                count = cursor.rowcount
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise CandidateReceiptStoreBusy("candidate store reconciliation lock wait expired") from exc
            raise CandidateReceiptStoreError("candidate store reconciliation failed") from exc
        except sqlite3.Error as exc:
            raise CandidateReceiptStoreError("candidate store reconciliation failed") from exc
        return count

    def close(self) -> None:
        """Rollback any open transaction and close the local handle."""

        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            try:
                if connection.in_transaction:
                    connection.rollback()
            except sqlite3.Error:
                # A failed commit may already have invalidated this handle;
                # closing remains the only safe disposition.
                pass
        finally:
            try:
                connection.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> Self:
        self._connection_or_raise()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


__all__ = [
    "CANDIDATE_STORE_SCHEMA_VERSION",
    "CandidateConsumeResult",
    "CandidateConsumeStatus",
    "CandidateReceipt",
    "CandidateReceiptStore",
    "CandidateReceiptStoreBusy",
    "CandidateReceiptStoreClosed",
    "CandidateReceiptStoreConflict",
    "CandidateReceiptStoreError",
    "CandidateReceiptStoreInputError",
    "CandidateReceiptStoreSchemaError",
    "CandidateState",
]
