"""Adversarial tests for the non-authoritative FHM-005 receipt CAS model."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import multiprocessing
from pathlib import Path
import sqlite3
import time

import pytest

from agent.trusted_verifier_contract import (
    CONTRACT_ROOT,
    CONTRACT_VERSION,
    ExpectedEffect,
    VerificationRequest,
)
from agent.trusted_verifier_receipt_store import (
    CandidateConsumeStatus,
    CandidateReceipt,
    CandidateReceiptStore,
    CandidateReceiptStoreBusy,
    CandidateReceiptStoreClosed,
    CandidateReceiptStoreConflict,
    CandidateReceiptStoreError,
    CandidateReceiptStoreInputError,
    CandidateReceiptStoreNotReady,
    CandidateReceiptStoreSchemaError,
    CandidateState,
)


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
POLICY_DIGEST = "sha256:" + "1" * 64
ROOT_DIGEST = "sha256:" + "3" * 64
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


def _issue(store, request=None, **changes):
    return store.issue(
        request or _request(), root_digest=changes.pop("root_digest", ROOT_DIGEST),
        generation=changes.pop("generation", 7), now=changes.pop("now", NOW),
    )


def _consume_child(db_path: str, barrier, output) -> None:
    request = _request()
    store = CandidateReceiptStore.open_for_live_generation(
        db_path, generation=7, busy_timeout_ms=1000,
    )
    candidate = CandidateReceipt(
        request=request,
        root_digest=ROOT_DIGEST,
        generation=7,
        issued_at=NOW,
        expires_at=request.expires_at,
    )
    try:
        barrier.wait(timeout=5)
        result = store.consume(candidate, now=NOW + timedelta(seconds=1))
        output.put((result.status.value, result.reason))
    except Exception as exc:  # child reports failure to the parent assertion
        output.put(("exception", type(exc).__name__, str(exc)))
    finally:
        store.close()


def test_issue_persists_only_opaque_identity_and_consumption_is_one_use(tmp_path):
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path) as store:
        candidate = _issue(store)
        row = sqlite3.connect(db_path).execute(
            "SELECT root, root_digest, session_id, attempt_id, authority, scope_json, "
            "policy_digest, nonce, generation, state FROM candidate_receipts",
        ).fetchone()
        assert row[-1] == CandidateState.ISSUED.value
        assert "result.txt" not in repr(row)
        assert "secret" not in repr(row)

        consumed = store.consume(candidate, now=NOW + timedelta(seconds=1))
        assert consumed.status is CandidateConsumeStatus.CONSUMED
        assert consumed.state is CandidateState.CONSUMED
        replay = store.consume(candidate, now=NOW + timedelta(seconds=2))
        assert replay.status is CandidateConsumeStatus.INCOMPLETE
        assert replay.reason == "replay"


def test_unique_identity_conflict_rolls_back_and_does_not_create_a_second_row(tmp_path):
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path) as store:
        _issue(store)
        with pytest.raises(CandidateReceiptStoreConflict):
            _issue(store)
        count = sqlite3.connect(db_path).execute(
            "SELECT count(*) FROM candidate_receipts",
        ).fetchone()[0]
        assert count == 1


@pytest.mark.parametrize(
    "change, reason",
    [
        (lambda request: replace(request, attempt_id="other-attempt"), "foreign_or_mismatched_identity"),
        (lambda request: replace(request, nonce="other-nonce"), "foreign_or_mismatched_identity"),
        (lambda request: replace(request, session_id="other-session"), "foreign_or_mismatched_identity"),
        (lambda request: replace(request, policy_digest="sha256:" + "4" * 64), "foreign_or_mismatched_identity"),
        (lambda request: replace(request, scope=("workspace:other",)), "scope_mismatch"),
    ],
)
def test_foreign_scope_attempt_nonce_and_session_never_consume(tmp_path, change, reason):
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path) as store:
        candidate = _issue(store)
        altered = replace(candidate, request=change(candidate.request))
        result = store.consume(altered, now=NOW + timedelta(seconds=1))
        assert result.status is CandidateConsumeStatus.INCOMPLETE
        assert result.reason == reason


def test_stale_generation_and_root_digest_are_foreign_not_replay(tmp_path):
    with CandidateReceiptStore(tmp_path / "candidate.db") as store:
        candidate = _issue(store)
        assert store.consume(
            replace(candidate, generation=8), now=NOW,
        ).reason == "foreign_or_mismatched_identity"
        assert store.consume(
            replace(candidate, root_digest="sha256:" + "5" * 64), now=NOW,
        ).reason == "foreign_or_mismatched_identity"
        assert store.consume(candidate, now=NOW).consumed


def test_expired_candidate_is_fenced_and_never_consumed(tmp_path):
    request = _request(expires_at=NOW + timedelta(seconds=5))
    with CandidateReceiptStore(tmp_path / "candidate.db") as store:
        candidate = _issue(store, request)
        result = store.consume(candidate, now=request.expires_at)
        assert result.status is CandidateConsumeStatus.INCOMPLETE
        assert result.reason == "expired"
        row = sqlite3.connect(store.db_path).execute(
            "SELECT state FROM candidate_receipts",
        ).fetchone()
        assert row[0] == CandidateState.EXPIRED.value


def test_restart_reconciliation_marks_uncertain_work_unknown_without_auto_resume(tmp_path):
    db_path = tmp_path / "candidate.db"
    first = CandidateReceiptStore(db_path)
    candidate = _issue(first)
    first.close()

    with CandidateReceiptStore(db_path) as restarted:
        assert restarted.reconcile_required
        with pytest.raises(CandidateReceiptStoreNotReady):
            _issue(restarted, request=_request(attempt_id="attempt-after-restart"))
        with pytest.raises(CandidateReceiptStoreNotReady):
            restarted.consume(candidate, now=NOW + timedelta(seconds=1))
        assert restarted.reconcile_after_restart(now=NOW + timedelta(seconds=1)) == 1
        assert not restarted.reconcile_required
        result = restarted.consume(candidate, now=NOW + timedelta(seconds=2))
        assert result.status is CandidateConsumeStatus.INCOMPLETE
        assert result.reason == "unknown_after_restart_reconciliation"
        assert result.state is CandidateState.UNKNOWN_INCOMPLETE
        state = sqlite3.connect(db_path).execute(
            "SELECT state FROM candidate_receipts",
        ).fetchone()[0]
        assert state == CandidateState.UNKNOWN_INCOMPLETE.value


def test_restart_preserves_consumed_terminal_state_and_rejects_replay(tmp_path):
    db_path = tmp_path / "candidate.db"
    first = CandidateReceiptStore(db_path)
    candidate = _issue(first)
    assert first.consume(candidate, now=NOW + timedelta(seconds=1)).consumed
    first.close()

    with CandidateReceiptStore(db_path) as restarted:
        assert restarted.reconcile_required
        assert restarted.reconcile_after_restart(now=NOW + timedelta(seconds=2)) == 0
        replay = restarted.consume(candidate, now=NOW + timedelta(seconds=3))

    assert replay.status is CandidateConsumeStatus.INCOMPLETE
    assert replay.reason == "replay"
    assert replay.state is CandidateState.CONSUMED


def test_same_user_sqlite_mutation_can_bypass_cas_but_is_not_authority(tmp_path):
    """Expose the remaining protected-controller gate without treating it as fixed."""
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path) as store:
        candidate = _issue(store)
        assert store.consume(candidate, now=NOW + timedelta(seconds=1)).consumed

    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE candidate_receipts SET state='issued', consumed_at=NULL WHERE row_id=1",
    )
    connection.commit()
    connection.close()

    with CandidateReceiptStore.open_for_live_generation(db_path, generation=7) as reopened:
        result = reopened.consume(candidate, now=NOW + timedelta(seconds=2))

    assert result.status is CandidateConsumeStatus.CONSUMED
    # The result remains only a candidate-store transition; no trusted proof exists.


def test_live_generation_join_rejects_issue_and_consume_from_other_generation(tmp_path):
    db_path = tmp_path / "candidate.db"
    first = CandidateReceiptStore(db_path)
    candidate = _issue(first, generation=7)
    first.close()

    with CandidateReceiptStore.open_for_live_generation(db_path, generation=8) as joined:
        with pytest.raises(CandidateReceiptStoreInputError, match="joined live generation"):
            _issue(
                joined,
                request=_request(attempt_id="attempt-generation-mismatch"),
                generation=7,
            )
        with pytest.raises(CandidateReceiptStoreInputError, match="joined live generation"):
            joined.consume(candidate, now=NOW + timedelta(seconds=1))


def test_live_generation_join_can_unsafe_bypass_restart_fence(tmp_path):
    """Document the caller-controlled bypass; never expose it to routine workers."""
    db_path = tmp_path / "candidate.db"
    first = CandidateReceiptStore(db_path)
    candidate = _issue(first)
    first.close()

    # This deliberately skips reconciliation for an existing issued row. It is
    # unsafe unless a future protected controller authenticates live generation
    # out of band; otherwise the controller must remove this API and reconcile.
    with CandidateReceiptStore.open_for_live_generation(db_path, generation=7) as joined:
        assert not joined.reconcile_required
        assert joined.consume(candidate, now=NOW + timedelta(seconds=1)).consumed


def test_simultaneous_process_consumption_has_at_most_one_winner(tmp_path):
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path) as store:
        _issue(store)

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    output = context.Queue()
    processes = [context.Process(target=_consume_child, args=(str(db_path), barrier, output)) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
    assert all(process.exitcode == 0 for process in processes)
    results = [output.get(timeout=2) for _ in processes]
    winners = [result for result in results if result[0] == CandidateConsumeStatus.CONSUMED.value]
    assert len(winners) == 1
    assert sum(result[0] == CandidateConsumeStatus.CONSUMED.value for result in results) <= 1


def test_begin_immediate_contention_is_bounded_and_fails_closed(tmp_path):
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path, busy_timeout_ms=100) as store:
        locker = sqlite3.connect(db_path, timeout=0)
        locker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(CandidateReceiptStoreBusy):
            _issue(store)
        assert time.monotonic() - started < 1.5
        locker.rollback()
        locker.close()
        _issue(store)


def test_sqlite_error_rolls_back_and_close_is_complete(tmp_path):
    db_path = tmp_path / "candidate.db"
    store = CandidateReceiptStore(db_path)
    store._connection.execute(
        "CREATE TRIGGER reject_candidate BEFORE INSERT ON candidate_receipts "
        "BEGIN SELECT RAISE(ABORT, 'interrupted'); END",
    )
    with pytest.raises(CandidateReceiptStoreError):
        _issue(store)
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM candidate_receipts",
    ).fetchone()[0] == 0
    store._connection.execute("DROP TRIGGER reject_candidate")
    candidate = _issue(store)
    store.close()
    store.close()
    with pytest.raises(CandidateReceiptStoreClosed):
        store.consume(candidate)


def test_ambiguous_commit_invalidates_instance_and_does_not_reuse_handle(tmp_path, monkeypatch):
    db_path = tmp_path / "candidate.db"
    store = CandidateReceiptStore(db_path)

    def fail_commit(_connection):
        raise sqlite3.OperationalError("injected ambiguous commit failure")

    monkeypatch.setattr("agent.trusted_verifier_receipt_store._commit", fail_commit)
    with pytest.raises(CandidateReceiptStoreError, match="ambiguous"):
        _issue(store)
    assert store._connection is None
    with pytest.raises(CandidateReceiptStoreClosed):
        _issue(store, request=_request(attempt_id="retry"))
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM candidate_receipts",
    ).fetchone()[0] == 0


def test_ambiguous_consume_commit_closes_store(tmp_path, monkeypatch):
    db_path = tmp_path / "candidate.db"
    store = CandidateReceiptStore(db_path)
    candidate = _issue(store)

    def fail_commit(_connection):
        raise sqlite3.OperationalError("injected ambiguous commit failure")

    monkeypatch.setattr("agent.trusted_verifier_receipt_store._commit", fail_commit)
    with pytest.raises(CandidateReceiptStoreError, match="ambiguous"):
        store.consume(candidate, now=NOW + timedelta(seconds=1))
    with pytest.raises(CandidateReceiptStoreClosed):
        store.consume(candidate, now=NOW + timedelta(seconds=2))


def test_clock_rollback_never_consumes_an_issued_candidate(tmp_path):
    with CandidateReceiptStore(tmp_path / "candidate.db") as store:
        candidate = _issue(store)
        result = store.consume(candidate, now=NOW - timedelta(seconds=1))
        assert result.status is CandidateConsumeStatus.INCOMPLETE
        assert result.reason == "clock_rollback"
        assert store.consume(candidate, now=NOW + timedelta(seconds=1)).consumed


def test_corrupted_row_state_fails_closed_without_raw_value_error(tmp_path):
    db_path = tmp_path / "candidate.db"
    with CandidateReceiptStore(db_path) as store:
        candidate = _issue(store)
        connection = sqlite3.connect(db_path)
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE candidate_receipts SET state='corrupt'")
        connection.commit()
        connection.close()
        with pytest.raises(CandidateReceiptStoreError, match="invalid row state"):
            store.consume(candidate, now=NOW + timedelta(seconds=1))


def test_parent_symlink_is_rejected(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    symlink_parent = tmp_path / "linked"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(CandidateReceiptStoreInputError, match="parent"):
        CandidateReceiptStore(symlink_parent / "candidate.db")


def test_schema_version_is_explicit_and_unknown_schema_fails_closed(tmp_path):
    db_path = tmp_path / "candidate.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA user_version=99")
    connection.close()
    with pytest.raises(CandidateReceiptStoreSchemaError):
        CandidateReceiptStore(db_path)


def test_malformed_schema_columns_fail_closed(tmp_path):
    db_path = tmp_path / "candidate.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE candidate_receipts (row_id INTEGER PRIMARY KEY)")
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()
    with pytest.raises(CandidateReceiptStoreSchemaError):
        CandidateReceiptStore(db_path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"root_digest": "not-a-digest", "generation": 1},
        {"root_digest": ROOT_DIGEST, "generation": 0},
        {"root_digest": ROOT_DIGEST, "generation": True},
    ],
)
def test_invalid_candidate_identity_is_rejected_without_a_row(tmp_path, kwargs):
    with CandidateReceiptStore(tmp_path / "candidate.db") as store:
        with pytest.raises(CandidateReceiptStoreInputError):
            store.issue(_request(), now=NOW, **kwargs)
        assert sqlite3.connect(store.db_path).execute(
            "SELECT count(*) FROM candidate_receipts",
        ).fetchone()[0] == 0


def test_duplicate_nonce_scope_with_different_correlation_is_rejected(tmp_path):
    """The UNIQUE key deliberately omits correlation: it cannot loosen nonce identity."""
    with CandidateReceiptStore(tmp_path / "candidate.db") as store:
        initial = _issue(store)
        with pytest.raises(CandidateReceiptStoreConflict):
            _issue(store, replace(initial.request, correlation_id="corr-2"))
        with pytest.raises(CandidateReceiptStoreConflict):
            _issue(store, replace(initial.request, freshness_seconds=30))
        count = sqlite3.connect(store.db_path).execute(
            "SELECT count(*) FROM candidate_receipts",
        ).fetchone()[0]
        assert count == 1
        assert store.consume(initial, now=NOW + timedelta(seconds=1)).consumed


def test_existing_nonce_cannot_consume_modified_expected_effects(tmp_path):
    with CandidateReceiptStore(tmp_path / "candidate.db") as store:
        candidate = _issue(store)
        forged_request = replace(candidate.request, expected_effects=(
            ExpectedEffect(effect="write", subject="file:elsewhere.txt", digest=ARTIFACT_DIGEST),
        ))
        result = store.consume(replace(candidate, request=forged_request), now=NOW)
        assert result.status is CandidateConsumeStatus.INCOMPLETE
        assert result.reason == "request_mismatch"
        assert store.consume(candidate, now=NOW).consumed
