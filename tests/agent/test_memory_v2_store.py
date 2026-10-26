"""FHM-007 proof-of-architecture tests for the isolated memory-v2 ledger."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context

import pytest

from agent.memory_v2_store import (
    MemoryV2ConflictError,
    MemoryV2OwnershipError,
    MemoryV2Store,
)


def _process_write(args):
    home, index = args
    store = MemoryV2Store(home, "agent")
    try:
        return store.add(
            kind="procedural", content=f"process step {index}"
        ).record.memory_id
    finally:
        store.close()


def test_restart_provenance_and_agent_isolation(tmp_path):
    home = tmp_path / "profile"
    store = MemoryV2Store(home, "primary")
    write = store.add(
        kind="semantic",
        content="Hermes uses local evidence",
        confidence=0.82,
        source_id="session-1",
        source_hash="sha256:abc",
        source_quote="local evidence",
        metadata={"untrusted": True, "origin": "test"},
    )
    assert write.created is True
    store.close()

    reopened = MemoryV2Store(home, "primary")
    record = reopened.get(write.record.memory_id)
    assert record is not None
    assert record.source_id == "session-1"
    assert record.source_hash == "sha256:abc"
    assert record.source_quote == "local evidence"
    assert record.metadata["untrusted"] is True
    secondary = MemoryV2Store(home, "secondary")
    assert secondary.search("local evidence") == []
    secondary.close()
    reopened.close()


def test_dedupe_revision_history_and_stale_write(tmp_path):
    store = MemoryV2Store(tmp_path / "profile", "agent")
    first = store.add(kind="lesson", content="Check the lock first", confidence=0.4)
    duplicate = store.add(
        kind="lesson", content="  CHECK   THE lock first ", confidence=0.9
    )
    assert duplicate.created is False
    assert duplicate.record.memory_id == first.record.memory_id

    second = store.revise(
        first.record.memory_id,
        expected_revision=1,
        content="Check WAL first",
        confidence=0.8,
    )
    assert second.record.revision == 2
    assert store.get(first.record.memory_id).content == "Check WAL first"
    assert store.history(first.record.memory_id)[0].content == "Check the lock first"
    assert any(
        edge.relation == "supersedes" for edge in store.edges(first.record.memory_id)
    )
    with pytest.raises(MemoryV2ConflictError):
        store.revise(first.record.memory_id, expected_revision=1, content="stale")
    store.close()


def test_contradiction_is_explicit_and_not_automatic(tmp_path):
    store = MemoryV2Store(tmp_path / "profile", "agent")
    left = store.add(kind="semantic", content="The deployment is local")
    right = store.add(kind="semantic", content="The deployment is remote")
    assert store.edges(left.record.memory_id) == []
    edge = store.add_edge(
        from_memory_id=left.record.memory_id,
        from_revision=1,
        to_memory_id=right.record.memory_id,
        to_revision=1,
        relation="contradicts",
        metadata={"evidence": "operator review"},
    )
    assert edge.relation == "contradicts"
    assert edge.metadata["evidence"] == "operator review"
    store.close()


def test_fts_recall_is_scoped_and_indexed_transactionally(tmp_path):
    home = tmp_path / "profile"
    store = MemoryV2Store(home, "agent")
    write = store.add(
        kind="episodic", content="The Zanzibar migration completed safely"
    )
    assert [item.memory_id for item in store.search("Zanzibar migration")] == [
        write.record.memory_id
    ]
    other = MemoryV2Store(home, "other-agent")
    assert other.search("Zanzibar migration") == []
    other.close()
    store.close()


def test_concurrent_process_like_writers_and_backup_roundtrip(tmp_path):
    home = tmp_path / "profile"
    stores = [MemoryV2Store(home, "agent") for _ in range(2)]

    def write(index: int):
        return (
            stores[index % 2]
            .add(kind="procedural", content=f"runbook step {index}")
            .record.memory_id
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(write, range(24)))
    assert len(set(ids)) == 24
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context("spawn")) as pool:
        process_ids = list(
            pool.map(_process_write, [(str(home), index) for index in range(8)])
        )
    assert len(set(process_ids)) == 8
    backup = tmp_path / "ledger-backup.sqlite3"
    stores[0].backup_to(backup)
    for store in stores:
        store.close()
    restored = MemoryV2Store.restore_from(
        backup, home, "agent", filename="restored.sqlite3"
    )
    assert len(restored.search("runbook step", limit=30)) == 24
    assert len(restored.search("process step", limit=30)) == 8
    restored.close()


def test_corruption_and_ownership_fail_closed(tmp_path):
    home = tmp_path / "profile"
    store = MemoryV2Store(home, "agent")
    store.close()
    with sqlite3.connect(home / "memory-v2" / "ledger.sqlite3") as conn:
        conn.execute("UPDATE store_meta SET value = 'wrong' WHERE key = 'profile_key'")
    with pytest.raises(MemoryV2OwnershipError):
        MemoryV2Store(home, "agent")
    with pytest.raises(MemoryV2OwnershipError):
        MemoryV2Store(home, "agent", filename="../outside.sqlite3")
