"""RED contracts for Core delegated outcome assurance.

These tests deliberately exercise the existing profile-local verification module and
turn finalizer.  They do not import the historical delegated modules, because their
absence on current main is part of the intended RED evidence.
"""

import logging
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import verification_evidence, verification_stop
from agent.turn_verification_finalize import verification_state_at_finalize
from agent.turn_finalizer import finalize_turn
from tests.agent.test_turn_finalizer_final_response_persistence import FakeAgent


def test_legacy_verify_on_stop_remains_opt_in_and_strict_boolean():
    """The existing coding-verification switch remains off unless explicitly enabled."""
    assert verification_stop.verify_on_stop_enabled({"agent": {}}) is False
    assert (
        verification_stop.verify_on_stop_enabled({"agent": {"verify_on_stop": True}})
        is True
    )


def _delegated_ledger_api():
    arm = getattr(verification_evidence, "arm_delegated_verification", None)
    pending = getattr(verification_evidence, "pending_delegated_verification", None)
    update = getattr(verification_evidence, "update_delegated_verification", None)
    assert callable(arm), "Core must expose a delegated pending arm helper"
    assert callable(pending), "Core must expose a delegated pending read helper"
    assert callable(update), "Core must expose an owner-bound delegated update helper"
    return arm, pending, update


def test_pending_is_durable_before_dispatch_and_foreign_or_duplicate_results_do_not_mint_evidence(
    monkeypatch,
):
    """The exact parent/attempt/task binding is durable before child execution."""
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    arm, pending, update = _delegated_ledger_api()
    binding = {
        "session_id": "session-1",
        "attempt_id": "attempt-1",
        "task_index": 0,
        "authority": "session:session-1",
    }

    assert arm(**binding) is True
    state = pending(session_id=binding["session_id"], authority=binding["authority"])
    assert len(state["rows"]) == 1
    assert state["rows"][0]["state"] == "running"

    assert (
        update(**{**binding, "authority": "foreign:parent"}, state="completed") is False
    )
    assert update(**binding, state="completed") is True
    assert update(**binding, state="completed") is False
    state = pending(session_id=binding["session_id"], authority=binding["authority"])
    assert not any(row["state"] == "completed" for row in state["rows"])


@pytest.mark.parametrize("fault", ["deleted", "corrupt"])
def test_known_active_ledger_loss_after_arm_is_not_first_run_success(
    monkeypatch, fault
):
    """Restart after known ledger loss stays unknown/error; it never verifies or replays."""
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    arm, pending, _update = _delegated_ledger_api()
    binding = {
        "session_id": "session-lost",
        "attempt_id": "attempt-lost",
        "task_index": 0,
        "authority": "session:session-lost",
    }
    assert arm(**binding) is True
    db_path = Path(verification_evidence._db_path())
    if fault == "deleted":
        db_path.unlink()
    else:
        db_path.write_bytes(b"not a sqlite database")

    recovered = pending(
        session_id=binding["session_id"], authority=binding["authority"]
    )
    assert recovered["unknown"] is True
    assert recovered["error"] is True
    assert recovered["rows"] == []


def test_advisory_opaque_effect_keeps_useful_response_without_strict_failure(
    monkeypatch,
):
    """Advisory assurance labels an opaque effect without replacing a real answer."""
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_args, **_kwargs: [])
    agent = FakeAgent()
    agent._verification_mode = "advisory"
    agent._turn_unobservable_delegated_work = True
    messages = [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "terminal", "arguments": "{}"}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "terminal",
            "content": "done",
        },
    ]

    result = finalize_turn(
        agent,
        final_response="Useful answer.",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="run it",
        original_user_message="run it",
        _should_review_memory=False,
        _turn_exit_reason="text_response(final)",
    )

    assert result["final_response"] == "Useful answer."
    assert result["completed"] is True
    assert result["failed"] is False
    assert result.get("verification_unresolved") is not True
    assert result["verification_status"] == "unverified"


def test_finalize_logs_verification_exception_with_full_traceback(monkeypatch, caplog):
    monkeypatch.setattr(
        verification_stop,
        "outcome_verification_mode",
        lambda agent=None: "strict",
    )

    def fail_pending(**_kwargs):
        raise RuntimeError("ledger read failed")

    monkeypatch.setattr(
        verification_evidence,
        "pending_delegated_verification",
        fail_pending,
    )

    with caplog.at_level(logging.DEBUG, logger="agent.turn_verification_finalize"):
        assert verification_state_at_finalize(SimpleNamespace(session_id="s1")) == (
            True,
            None,
        )

    record = next(
        record
        for record in caplog.records
        if "delegated verification finalization failed" in record.message
    )
    assert record.exc_info is not None


def test_parent_lock_initialization_is_shared_under_simultaneous_creation(monkeypatch):
    from agent.turn_verification_finalize import _get_parent_verification_lock as finalize_lock
    from tools.delegate_verification import _get_parent_verification_lock as delegate_lock

    parent = SimpleNamespace()
    real_rlock = threading.RLock
    factory_entered = threading.Event()
    second_call_started = threading.Event()
    release_factory = threading.Event()
    locks = []

    def gated_rlock():
        factory_entered.set()
        assert release_factory.wait(2)
        lock = real_rlock()
        locks.append(lock)
        return lock

    monkeypatch.setattr(threading, "RLock", gated_rlock)
    results = []

    first = threading.Thread(
        target=lambda: results.append(finalize_lock(parent)), daemon=True
    )

    def call_delegate():
        second_call_started.set()
        results.append(delegate_lock(parent))

    second = threading.Thread(target=call_delegate, daemon=True)
    first.start()
    assert factory_entered.wait(2)
    second.start()
    assert second_call_started.wait(2)
    release_factory.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(locks) == 1
    assert results[0] is results[1] is locks[0]


def test_parent_mutations_wait_for_finalizer_snapshot(monkeypatch):
    from tools.delegate_verification import record_child_verification

    class BlockingLock:
        def __init__(self):
            self.entered = threading.Event()
            self.release = threading.Event()
            self.held = False

        def __enter__(self):
            self.held = True
            self.entered.set()
            assert self.release.wait(2)
            return self

        def __exit__(self, *_exc):
            self.held = False

    lock = BlockingLock()
    parent = SimpleNamespace(
        session_id="parent",
        _pending_delegated_verification_lock=lock,
        _turn_file_mutation_paths=set(),
    )
    monkeypatch.setattr(
        verification_stop,
        "outcome_verification_mode",
        lambda agent=None: "advisory",
    )
    monkeypatch.setattr(
        verification_stop,
        "verification_unresolved",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        verification_evidence,
        "pending_delegated_verification",
        lambda **_kwargs: {"paths": set(), "unknown": False, "error": False},
    )
    monkeypatch.setattr(
        verification_evidence,
        "verification_authority",
        lambda _agent: "session:parent",
    )
    monkeypatch.setattr("agent.coding_context.project_facts_for", lambda _path: None)
    monkeypatch.setattr(
        "agent.verification_evidence.mark_workspace_edited",
        lambda **_kwargs: None,
    )

    finalizer_done = threading.Event()

    def finalize():
        try:
            verification_state_at_finalize(parent)
        finally:
            finalizer_done.set()

    finalizer = threading.Thread(target=finalize, daemon=True)
    finalizer.start()
    assert lock.entered.wait(2)

    child_done = threading.Event()

    def record():
        try:
            record_child_verification(
                child=SimpleNamespace(),
                result={"completed": True, "messages": []},
                task_index=0,
                parent=parent,
                child_paths={"child.py"},
            )
        finally:
            child_done.set()

    child = threading.Thread(target=record, daemon=True)
    child.start()
    assert child_done.wait(0.2) is False
    assert finalizer_done.is_set() is False
    lock.release.set()
    finalizer.join(2)
    child.join(2)

    assert not finalizer.is_alive()
    assert not child.is_alive()
    assert parent._turn_file_mutation_paths == {"child.py"}


def _clear_known_bindings():
    cache = verification_evidence._KNOWN_DELEGATED_LEDGER_BINDINGS
    lock = getattr(verification_evidence, "_KNOWN_DELEGATED_LEDGER_BINDINGS_LOCK", None)
    if lock is None:
        cache.clear()
    else:
        with lock:
            cache.clear()


def test_fallback_binding_cache_refuses_new_arm_without_dropping_old_keys(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setattr(
        verification_evidence,
        "_MAX_KNOWN_DELEGATED_LEDGER_BINDINGS",
        2,
        raising=False,
    )
    monkeypatch.setattr(
        verification_evidence,
        "_write_ledger_continuity_marker",
        lambda *_args: (True, False),
    )
    _clear_known_bindings()

    def arm(session, attempt):
        return verification_evidence.arm_delegated_verification(
            session_id=session,
            attempt_id=attempt,
            task_index=0,
            authority=f"session:{session}",
        )

    assert arm("session-1", "first") is True
    assert arm("session-2", "second") is True
    assert len(verification_evidence._KNOWN_DELEGATED_LEDGER_BINDINGS) == 2
    assert arm("session-3", "third") is False
    state = verification_evidence.pending_delegated_verification(
        session_id="session-1", authority="session:session-1"
    )
    assert {row["attempt_id"] for row in state["rows"]} == {"first"}

    db_path = Path(verification_evidence._db_path())
    db_path.unlink()
    recovered = verification_evidence.pending_delegated_verification(
        session_id="session-1", authority="session:session-1"
    )
    assert recovered["unknown"] is True
    assert recovered["error"] is True
    _clear_known_bindings()


def test_durable_continuity_marker_does_not_use_fallback_cache(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    monkeypatch.setenv("HERMES_HOME", str(home))
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute("CREATE TABLE state_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    _clear_known_bindings()
    assert verification_evidence.arm_delegated_verification(
        session_id="session",
        attempt_id="attempt",
        task_index=0,
        authority="session:session",
    ) is True
    assert verification_evidence._KNOWN_DELEGATED_LEDGER_BINDINGS == set()



def test_interleaved_same_key_arm_failure_never_forgets_successful_sibling(monkeypatch, tmp_path):
    """A failed reservation must not erase continuity for a concurrently successful arm."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    monkeypatch.setattr(verification_evidence, "_write_ledger_continuity_marker", lambda *_args: (True, False))
    _clear_known_bindings()
    reserved = threading.Event()
    sibling_saw_key = threading.Event()
    real_transaction = verification_evidence._transaction
    key = verification_evidence._delegated_binding_key("s-race", "session:s-race")
    results = {}

    class ObservedKeys(set):
        def __contains__(self, value):
            present = super().__contains__(value)
            if threading.current_thread().name == "sibling" and value == key and present:
                sibling_saw_key.set()
            return present

    monkeypatch.setattr(verification_evidence, "_KNOWN_DELEGATED_LEDGER_BINDINGS", ObservedKeys())
    def forced_transaction():
        if threading.current_thread().name == "failing":
            reserved.set()
            assert sibling_saw_key.wait(5), "Sibling must observe reserved cache key"
            raise sqlite3.OperationalError("simulated failed DB insertion")
        return real_transaction()
    monkeypatch.setattr(verification_evidence, "_transaction", forced_transaction)

    def arm(name, index):
        results[name] = verification_evidence.arm_delegated_verification(
            session_id="s-race", attempt_id=name, task_index=index, authority="session:s-race"
        )

    failing = threading.Thread(target=arm, args=("failing", 0), name="failing")
    sibling = threading.Thread(target=arm, args=("sibling", 1), name="sibling")
    failing.start()
    assert reserved.wait(5)
    sibling.start()
    failing.join(timeout=8)
    sibling.join(timeout=8)
    assert not failing.is_alive() and not sibling.is_alive()
    assert results == {"failing": False, "sibling": True}
    assert verification_evidence._has_ledger_continuity_marker("s-race", "session:s-race") is True
    verification_evidence._db_path().unlink()
    state = verification_evidence.pending_delegated_verification(
        session_id="s-race", authority="session:s-race"
    )
    assert state["unknown"] is True and state["error"] is True
    _clear_known_bindings()
