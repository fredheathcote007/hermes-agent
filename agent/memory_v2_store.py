"""An isolated, local-first SQLite ledger for the memory-v2 architecture.

This module is deliberately not wired into the active memory provider or tool surface.  It is a
proof-of-architecture component for FHM-007: all writes are explicit, revisions are immutable,
and the profile/agent scope is checked at the store boundary.  It performs no LLM, embedding,
network, consolidation, or automatic forgetting work.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator, Mapping, Optional


class MemoryV2StoreError(RuntimeError):
    """Base error for the isolated memory-v2 ledger."""


class MemoryV2OwnershipError(MemoryV2StoreError):
    """The database is not owned by the requested profile or agent scope."""


class MemoryV2ConflictError(MemoryV2StoreError):
    """A compare-and-set write did not target the current revision."""


class MemoryV2CorruptionError(MemoryV2StoreError):
    """The SQLite database or its FTS index failed an integrity check."""


@dataclass(frozen=True)
class MemoryV2Record:
    memory_id: str
    revision: int
    agent_id: str
    kind: str
    content: str
    confidence: float
    status: str
    created_at: float
    source_id: Optional[str]
    source_hash: Optional[str]
    source_quote: Optional[str]
    metadata: dict[str, Any]
    supersedes_memory_id: Optional[str]
    supersedes_revision: Optional[int]


@dataclass(frozen=True)
class MemoryV2Write:
    record: MemoryV2Record
    created: bool


@dataclass(frozen=True)
class MemoryV2Edge:
    edge_id: str
    agent_id: str
    from_memory_id: str
    from_revision: int
    to_memory_id: str
    to_revision: int
    relation: str
    metadata: dict[str, Any]
    created_at: float


_KINDS = frozenset({"semantic", "episodic", "procedural", "failure", "lesson"})
_STATUSES = frozenset({"active", "superseded", "contradicted", "archived", "retracted"})
_RELATIONS = frozenset({"supersedes", "contradicts", "supports", "derived_from"})
_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_QUERY_TOKEN_RE = re.compile(r"[\w-]{1,80}", re.UNICODE)
_SCHEMA_VERSION = "1"
_STORE_DIR = "memory-v2"
_DEFAULT_FILENAME = "ledger.sqlite3"
_MAX_CONTENT_CHARS = 1_000_000
_MAX_SOURCE_QUOTE_CHARS = 100_000


def _profile_key(home: Path) -> str:
    return hashlib.sha256(str(home).encode("utf-8")).hexdigest()


def _validate_agent_id(agent_id: str) -> str:
    value = str(agent_id or "").strip()
    if not _AGENT_RE.fullmatch(value):
        raise MemoryV2OwnershipError("agent_id must be a non-empty, safe identifier")
    return value


def _safe_json(value: Mapping[str, Any], label: str) -> str:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} must contain JSON-compatible values") from exc


def _normalise_content(content: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", content).split()).casefold()


def _validate_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if "\x00" in content or len(content) > _MAX_CONTENT_CHARS:
        raise ValueError("content is empty, contains NUL, or exceeds the size limit")
    return content.strip()


def _validate_confidence(confidence: float) -> float:
    value = float(confidence)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be a finite number between 0 and 1")
    return value


class MemoryV2Store:
    """A profile-local, agent-namespaced and revisioned memory ledger.

    ``hermes_home`` is required explicitly so a background caller cannot silently fall back to the
    launch profile.  The database path is always beneath that home, and a persisted profile hash is
    checked on every open.  Different agents share the profile-local file but never share records.
    """

    def __init__(
        self,
        hermes_home: str | os.PathLike[str],
        agent_id: str,
        *,
        filename: str = _DEFAULT_FILENAME,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.home = self._resolve_home(hermes_home)
        self.agent_id = _validate_agent_id(agent_id)
        self.db_path = self._resolve_db_path(filename)
        if int(busy_timeout_ms) <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=int(busy_timeout_ms) / 1000,
                isolation_level=None,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._configure()
            self._initialise_schema()
            self._validate_owner()
        except sqlite3.DatabaseError as exc:
            self._close_connection()
            raise MemoryV2CorruptionError(
                f"cannot open memory-v2 ledger: {exc}"
            ) from exc
        except Exception:
            self._close_connection()
            raise

    @staticmethod
    def _resolve_home(raw_home: str | os.PathLike[str]) -> Path:
        home = Path(raw_home).expanduser()
        if not home.is_absolute():
            raise MemoryV2OwnershipError("hermes_home must be an absolute path")
        home = home.resolve(strict=False)
        home.mkdir(parents=True, exist_ok=True)
        return home

    def _resolve_db_path(self, filename: str) -> Path:
        candidate = Path(filename)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.name:
            raise MemoryV2OwnershipError(
                "ledger filename must stay below hermes_home/memory-v2"
            )
        root = self.home / _STORE_DIR
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink():
            raise MemoryV2OwnershipError("memory-v2 directory must not be a symlink")
        path = (root / candidate).resolve(strict=False)
        if path.parent != root.resolve(strict=False):
            raise MemoryV2OwnershipError(
                "ledger filename escaped the profile memory directory"
            )
        if path.exists() and path.is_symlink():
            raise MemoryV2OwnershipError("ledger database must not be a symlink")
        return path

    def _configure(self) -> None:
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise MemoryV2StoreError(f"memory-v2 requires SQLite WAL, got {mode!r}")
        self._conn.execute("PRAGMA synchronous=FULL")

    def _initialise_schema(self) -> None:
        with self._transaction() as conn:
            statements = (
                """
                CREATE TABLE IF NOT EXISTS store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )""",
                """
                CREATE TABLE IF NOT EXISTS memory_revisions (
                    fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    normalized_content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    source_id TEXT,
                    source_hash TEXT,
                    source_quote TEXT,
                    metadata_json TEXT NOT NULL,
                    supersedes_memory_id TEXT,
                    supersedes_revision INTEGER,
                    UNIQUE(memory_id, revision),
                    CHECK (confidence >= 0 AND confidence <= 1),
                    CHECK (status IN ('active', 'superseded', 'contradicted', 'archived', 'retracted'))
                )""",
                """
                CREATE INDEX IF NOT EXISTS memory_latest_idx
                    ON memory_revisions(agent_id, memory_id, revision DESC);
                """,
                """
                CREATE INDEX IF NOT EXISTS memory_hash_idx
                    ON memory_revisions(agent_id, kind, content_hash, revision DESC);
                """,
                """
                CREATE TABLE IF NOT EXISTS memory_edges (
                    edge_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    from_memory_id TEXT NOT NULL,
                    from_revision INTEGER NOT NULL,
                    to_memory_id TEXT NOT NULL,
                    to_revision INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(agent_id, from_memory_id, from_revision, to_memory_id, to_revision, relation),
                    CHECK (relation IN ('supersedes', 'contradicts', 'supports', 'derived_from'))
                )""",
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    content, memory_id UNINDEXED, revision UNINDEXED,
                    agent_id UNINDEXED, kind UNINDEXED, tokenize='unicode61'
                )""",
            )
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO store_meta(key, value) VALUES ('schema_version', ?)",
                (_SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO store_meta(key, value) VALUES ('profile_key', ?)",
                (_profile_key(self.home),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO store_meta(key, value) VALUES ('store_kind', 'hermes-memory-v2')"
            )

    def _validate_owner(self) -> None:
        rows = dict(self._conn.execute("SELECT key, value FROM store_meta").fetchall())
        expected = {
            "schema_version": _SCHEMA_VERSION,
            "profile_key": _profile_key(self.home),
            "store_kind": "hermes-memory-v2",
        }
        if any(rows.get(key) != value for key, value in expected.items()):
            raise MemoryV2OwnershipError(
                "memory-v2 ledger ownership or schema validation failed"
            )
        self.check_integrity()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise MemoryV2StoreError("memory-v2 ledger is closed")
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryV2Record:
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryV2CorruptionError("invalid memory metadata JSON") from exc
        if not isinstance(metadata, dict):
            raise MemoryV2CorruptionError("memory metadata is not an object")
        return MemoryV2Record(
            memory_id=row["memory_id"],
            revision=row["revision"],
            agent_id=row["agent_id"],
            kind=row["kind"],
            content=row["content"],
            confidence=row["confidence"],
            status=row["status"],
            created_at=row["created_at"],
            source_id=row["source_id"],
            source_hash=row["source_hash"],
            source_quote=row["source_quote"],
            metadata=metadata,
            supersedes_memory_id=row["supersedes_memory_id"],
            supersedes_revision=row["supersedes_revision"],
        )

    def _latest_row(
        self, conn: sqlite3.Connection, memory_id: str
    ) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM memory_revisions WHERE agent_id = ? AND memory_id = ? "
            "ORDER BY revision DESC LIMIT 1",
            (self.agent_id, memory_id),
        ).fetchone()

    def _insert_revision(
        self,
        conn: sqlite3.Connection,
        *,
        memory_id: str,
        revision: int,
        kind: str,
        content: str,
        confidence: float,
        status: str,
        source_id: Optional[str],
        source_hash: Optional[str],
        source_quote: Optional[str],
        metadata_json: str,
        supersedes_memory_id: Optional[str],
        supersedes_revision: Optional[int],
    ) -> MemoryV2Record:
        now = time.time()
        normal = _normalise_content(content)
        content_hash = hashlib.sha256(normal.encode("utf-8")).hexdigest()
        cursor = conn.execute(
            "INSERT INTO memory_revisions(memory_id, revision, agent_id, kind, content, "
            "normalized_content, content_hash, confidence, status, created_at, source_id, "
            "source_hash, source_quote, metadata_json, supersedes_memory_id, supersedes_revision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                revision,
                self.agent_id,
                kind,
                content,
                normal,
                content_hash,
                confidence,
                status,
                now,
                source_id,
                source_hash,
                source_quote,
                metadata_json,
                supersedes_memory_id,
                supersedes_revision,
            ),
        )
        conn.execute(
            "INSERT INTO memory_fts(rowid, content, memory_id, revision, agent_id, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cursor.lastrowid, content, memory_id, revision, self.agent_id, kind),
        )
        row = conn.execute(
            "SELECT * FROM memory_revisions WHERE fts_rowid = ?", (cursor.lastrowid,)
        ).fetchone()
        return self._row_to_record(row)

    def add(
        self,
        *,
        kind: str,
        content: str,
        confidence: float = 0.5,
        source_id: Optional[str] = None,
        source_hash: Optional[str] = None,
        source_quote: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> MemoryV2Write:
        """Add an evidence-bearing record; exact active duplicates return the existing revision."""
        kind = str(kind).strip().lower()
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {sorted(_KINDS)}")
        content = _validate_content(content)
        confidence = _validate_confidence(confidence)
        if source_quote is not None and len(source_quote) > _MAX_SOURCE_QUOTE_CHARS:
            raise ValueError("source_quote exceeds the size limit")
        metadata_json = _safe_json(metadata or {}, "metadata")
        content_hash = hashlib.sha256(
            _normalise_content(content).encode("utf-8")
        ).hexdigest()
        with self._transaction() as conn:
            duplicate = conn.execute(
                "SELECT r.* FROM memory_revisions r JOIN ("
                "SELECT memory_id, MAX(revision) revision FROM memory_revisions "
                "WHERE agent_id = ? GROUP BY memory_id) latest "
                "ON latest.memory_id = r.memory_id AND latest.revision = r.revision "
                "WHERE r.agent_id = ? AND r.kind = ? AND r.status = 'active' AND r.content_hash = ?",
                (self.agent_id, self.agent_id, kind, content_hash),
            ).fetchone()
            if duplicate:
                return MemoryV2Write(self._row_to_record(duplicate), created=False)
            record = self._insert_revision(
                conn,
                memory_id=uuid.uuid4().hex,
                revision=1,
                kind=kind,
                content=content,
                confidence=confidence,
                status="active",
                source_id=source_id,
                source_hash=source_hash,
                source_quote=source_quote,
                metadata_json=metadata_json,
                supersedes_memory_id=None,
                supersedes_revision=None,
            )
            return MemoryV2Write(record, created=True)

    def revise(
        self,
        memory_id: str,
        *,
        expected_revision: int,
        content: str,
        confidence: Optional[float] = None,
        source_id: Optional[str] = None,
        source_hash: Optional[str] = None,
        source_quote: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> MemoryV2Write:
        """Append a new active revision using compare-and-set; no previous row is mutated."""
        content = _validate_content(content)
        with self._transaction() as conn:
            previous = self._latest_row(conn, memory_id)
            if previous is None or previous["revision"] != expected_revision:
                raise MemoryV2ConflictError(
                    "revision is stale or does not belong to this agent"
                )
            value = (
                previous["confidence"]
                if confidence is None
                else _validate_confidence(confidence)
            )
            if source_quote is not None and len(source_quote) > _MAX_SOURCE_QUOTE_CHARS:
                raise ValueError("source_quote exceeds the size limit")
            record = self._insert_revision(
                conn,
                memory_id=memory_id,
                revision=expected_revision + 1,
                kind=previous["kind"],
                content=content,
                confidence=value,
                status="active",
                source_id=source_id,
                source_hash=source_hash,
                source_quote=source_quote,
                metadata_json=_safe_json(metadata or {}, "metadata"),
                supersedes_memory_id=memory_id,
                supersedes_revision=expected_revision,
            )
            self._insert_edge(conn, record, previous, "supersedes", {})
            return MemoryV2Write(record, created=True)

    def transition(
        self,
        memory_id: str,
        *,
        expected_revision: int,
        status: str,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> MemoryV2Write:
        """Record a status transition as a new immutable revision."""
        status = str(status).strip().lower()
        if status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        with self._transaction() as conn:
            previous = self._latest_row(conn, memory_id)
            if previous is None or previous["revision"] != expected_revision:
                raise MemoryV2ConflictError(
                    "revision is stale or does not belong to this agent"
                )
            record = self._insert_revision(
                conn,
                memory_id=memory_id,
                revision=expected_revision + 1,
                kind=previous["kind"],
                content=previous["content"],
                confidence=previous["confidence"],
                status=status,
                source_id=previous["source_id"],
                source_hash=previous["source_hash"],
                source_quote=previous["source_quote"],
                metadata_json=_safe_json(metadata or {}, "metadata"),
                supersedes_memory_id=memory_id,
                supersedes_revision=expected_revision,
            )
            self._insert_edge(
                conn, record, previous, "supersedes", {"status_transition": status}
            )
            return MemoryV2Write(record, created=True)

    def add_edge(
        self,
        *,
        from_memory_id: str,
        from_revision: int,
        to_memory_id: str,
        to_revision: int,
        relation: str,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> MemoryV2Edge:
        """Create an explicit relation; in particular, contradiction is never inferred."""
        relation = str(relation).strip().lower()
        if relation not in _RELATIONS:
            raise ValueError(f"relation must be one of {sorted(_RELATIONS)}")
        with self._transaction() as conn:
            source = self._get_row(conn, from_memory_id, from_revision)
            target = self._get_row(conn, to_memory_id, to_revision)
            if source is None or target is None:
                raise MemoryV2OwnershipError("edge endpoints must belong to this agent")
            return self._insert_edge(
                conn, source, target, relation, dict(metadata or {})
            )

    def _get_row(
        self, conn: sqlite3.Connection, memory_id: str, revision: Optional[int] = None
    ) -> Optional[sqlite3.Row]:
        if revision is None:
            return self._latest_row(conn, memory_id)
        return conn.execute(
            "SELECT * FROM memory_revisions WHERE agent_id = ? AND memory_id = ? AND revision = ?",
            (self.agent_id, memory_id, revision),
        ).fetchone()

    def _insert_edge(
        self,
        conn: sqlite3.Connection,
        source: sqlite3.Row | MemoryV2Record,
        target: sqlite3.Row | MemoryV2Record,
        relation: str,
        metadata: Mapping[str, Any],
    ) -> MemoryV2Edge:
        def field(item: sqlite3.Row | MemoryV2Record, name: str) -> Any:
            return item[name] if isinstance(item, sqlite3.Row) else getattr(item, name)

        source_id, source_rev = field(source, "memory_id"), field(source, "revision")
        target_id, target_rev = field(target, "memory_id"), field(target, "revision")
        edge_id = uuid.uuid4().hex
        metadata_json = _safe_json(metadata, "edge metadata")
        conn.execute(
            "INSERT OR IGNORE INTO memory_edges(edge_id, agent_id, from_memory_id, from_revision, "
            "to_memory_id, to_revision, relation, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                edge_id,
                self.agent_id,
                source_id,
                source_rev,
                target_id,
                target_rev,
                relation,
                metadata_json,
                time.time(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM memory_edges WHERE agent_id = ? AND from_memory_id = ? AND from_revision = ? "
            "AND to_memory_id = ? AND to_revision = ? AND relation = ?",
            (self.agent_id, source_id, source_rev, target_id, target_rev, relation),
        ).fetchone()
        return self._row_to_edge(row)

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> MemoryV2Edge:
        metadata = json.loads(row["metadata_json"])
        if not isinstance(metadata, dict):
            raise MemoryV2CorruptionError("edge metadata is not an object")
        return MemoryV2Edge(
            edge_id=row["edge_id"],
            agent_id=row["agent_id"],
            from_memory_id=row["from_memory_id"],
            from_revision=row["from_revision"],
            to_memory_id=row["to_memory_id"],
            to_revision=row["to_revision"],
            relation=row["relation"],
            metadata=metadata,
            created_at=row["created_at"],
        )

    def get(
        self, memory_id: str, revision: Optional[int] = None
    ) -> Optional[MemoryV2Record]:
        with self._lock:
            row = self._get_row(self._conn, memory_id, revision)
            return self._row_to_record(row) if row else None

    def history(self, memory_id: str) -> list[MemoryV2Record]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory_revisions WHERE agent_id = ? AND memory_id = ? ORDER BY revision",
                (self.agent_id, memory_id),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def edges(self, memory_id: str) -> list[MemoryV2Edge]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory_edges WHERE agent_id = ? AND (from_memory_id = ? OR to_memory_id = ?) "
                "ORDER BY created_at, edge_id",
                (self.agent_id, memory_id, memory_id),
            ).fetchall()
            return [self._row_to_edge(row) for row in rows]

    def search(
        self, query: str, *, limit: int = 10, include_history: bool = False
    ) -> list[MemoryV2Record]:
        """Search the profile/agent FTS index; retrieval never executes or interprets content."""
        if int(limit) <= 0:
            return []
        tokens = _QUERY_TOKEN_RE.findall(unicodedata.normalize("NFKC", str(query)))
        if not tokens:
            return []
        fts_query = " AND ".join(
            '"' + token.replace('"', '""') + '"' for token in tokens[:32]
        )
        with self._lock:
            if include_history:
                predicate = "1 = 1"
            else:
                predicate = (
                    "r.revision = (SELECT MAX(r2.revision) FROM memory_revisions r2 "
                    "WHERE r2.agent_id = r.agent_id AND r2.memory_id = r.memory_id) "
                    "AND r.status = 'active'"
                )
            rows = self._conn.execute(
                f"SELECT r.* FROM memory_fts f JOIN memory_revisions r ON r.fts_rowid = f.rowid "
                f"WHERE memory_fts MATCH ? AND r.agent_id = ? AND {predicate} "
                "ORDER BY bm25(memory_fts), r.created_at DESC LIMIT ?",
                (fts_query, self.agent_id, int(limit)),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def check_integrity(self) -> None:
        with self._lock:
            try:
                result = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise MemoryV2CorruptionError(
                        f"SQLite integrity check failed: {result}"
                    )
                self._conn.execute(
                    "INSERT INTO memory_fts(memory_fts) VALUES ('integrity-check')"
                )
            except sqlite3.DatabaseError as exc:
                raise MemoryV2CorruptionError(
                    f"memory-v2 integrity check failed: {exc}"
                ) from exc

    def backup_to(self, destination: str | os.PathLike[str]) -> Path:
        """Create a durable SQLite backup; the destination is replaced atomically."""
        target = Path(destination).expanduser()
        if not target.is_absolute() or target == self.db_path:
            raise ValueError(
                "backup destination must be an absolute path different from the ledger"
            )
        if target.exists() and target.is_symlink():
            raise MemoryV2OwnershipError("backup destination must not be a symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            with self._lock, sqlite3.connect(str(temp)) as backup_conn:
                self._conn.backup(backup_conn)
                backup_conn.execute("PRAGMA synchronous=FULL")
                backup_conn.commit()
            with temp.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temp, target)
            return target
        finally:
            if temp.exists():
                temp.unlink()

    @classmethod
    def restore_from(
        cls,
        backup: str | os.PathLike[str],
        hermes_home: str | os.PathLike[str],
        agent_id: str,
        *,
        filename: str = _DEFAULT_FILENAME,
    ) -> MemoryV2Store:
        """Restore a backup only into its original profile and into a new ledger path."""
        raw_backup = Path(backup).expanduser()
        if raw_backup.is_symlink():
            raise MemoryV2OwnershipError("backup must not be a symlink")
        backup_path = raw_backup.resolve(strict=True)
        home = cls._resolve_home(hermes_home)
        checked_agent = _validate_agent_id(agent_id)
        probe = object.__new__(cls)
        probe.home = home
        target_path = probe._resolve_db_path(filename)
        if target_path.exists():
            raise MemoryV2OwnershipError("restore target already exists")
        with sqlite3.connect(str(backup_path)) as source:
            source.row_factory = sqlite3.Row
            meta = dict(source.execute("SELECT key, value FROM store_meta").fetchall())
            if meta.get("profile_key") != _profile_key(home):
                raise MemoryV2OwnershipError("backup belongs to a different profile")
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise MemoryV2CorruptionError("backup integrity check failed")
            with sqlite3.connect(str(target_path)) as target:
                source.backup(target)
        return cls(home, checked_agent, filename=filename)

    def _close_connection(self) -> None:
        conn = getattr(self, "_conn", None)
        if conn is not None:
            conn.close()
            self._conn = None

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._close_connection()
                self._closed = True

    def __enter__(self) -> MemoryV2Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
