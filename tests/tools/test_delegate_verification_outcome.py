"""Delegated mutation provenance must outlive the parent turn that spawned a child."""

from __future__ import annotations

import json
import threading
import weakref
from types import SimpleNamespace

import pytest

from agent.verification_evidence import (
    arm_delegated_verification,
    pending_delegated_verification,
    update_delegated_verification,
    verification_authority,
)
from agent.turn_verification_finalize import apply_verification_outcome, verification_unresolved_at_finalize
from tools.delegate_tool_child_run import _SchemaOutcome, _build_result_entry


class Parent(SimpleNamespace):
    """Real AIAgent objects support weakref; SimpleNamespace does not."""


def _child_result(parent, tool_name=None, tool_content="ok"):
    child = SimpleNamespace(
        _delegate_parent_ref=weakref.ref(parent),
        _turn_file_mutation_paths=set(),
        model="test",
    )
    messages = []
    if tool_name:
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {"name": tool_name, "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": tool_content},
        ]
    return child, {"final_response": "done", "completed": True, "messages": messages}


def _entry(child, result):
    return _build_result_entry(child, result, 0, 0.1, _SchemaOutcome(None, None, [], 0))


def test_sync_child_landed_paths_are_propagated_to_parent_pending_owner():
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent)
    child._turn_file_mutation_paths = {"/workspace/src/change.py"}

    _entry(child, result)

    assert parent._turn_file_mutation_paths == {"/workspace/src/change.py"}
    assert parent._pending_delegated_verification_paths == {"/workspace/src/change.py"}


def test_late_child_completion_survives_new_parent_turn_reset():
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    parent._pending_delegated_verification_lock = threading.RLock()
    parent._pending_delegated_verification_paths = set()
    parent._pending_unobservable_delegated_work = False
    child, result = _child_result(parent, "write_file")
    child._turn_file_mutation_paths = {"/workspace/src/late.py"}

    _entry(child, result)  # child completes after its spawning parent turn
    parent._turn_file_mutation_paths = set()  # next parent turn reset
    parent._turn_unobservable_delegated_work = False

    assert parent._turn_file_mutation_paths == set()
    assert "/workspace/src/late.py" in parent._pending_delegated_verification_paths


@pytest.mark.parametrize("tool_name", ["terminal", "execute_code"])
def test_command_child_without_landed_paths_marks_unknown_side_effects(tool_name):
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent, tool_name)

    _entry(child, result)

    assert parent._pending_unobservable_delegated_work is True
    assert parent._turn_unobservable_delegated_work is True


@pytest.mark.parametrize("tool_name", ["write_file", "patch", "plugin_mutation"])
def test_mutating_or_unknown_child_without_landed_paths_stays_pending(tool_name):
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent, tool_name)

    _entry(child, result)

    assert parent._pending_unobservable_delegated_work is True
    assert parent._turn_unobservable_delegated_work is True


@pytest.mark.parametrize("command", ["ls -la", "git status --short"])
def test_successful_incidental_read_only_terminal_does_not_stay_pending(command):
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent, "terminal")
    result["messages"][0]["tool_calls"][0]["function"]["arguments"] = json.dumps({"command": command})

    _entry(child, result)

    assert not getattr(parent, "_pending_unobservable_delegated_work", False)
    assert not getattr(parent, "_turn_unobservable_delegated_work", False)


@pytest.mark.parametrize("command", ["rm -f generated.py", "command rm -f generated.py"])
def test_mutating_terminal_command_without_landed_paths_stays_pending(command):
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent, "terminal")
    result["messages"][0]["tool_calls"][0]["function"]["arguments"] = json.dumps({"command": command})

    _entry(child, result)

    assert parent._pending_unobservable_delegated_work is True
    assert parent._turn_unobservable_delegated_work is True


def test_failed_read_only_tool_result_stays_pending():
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent, "read_file", "Error: unavailable")

    _entry(child, result)

    assert parent._pending_unobservable_delegated_work is True
    assert parent._turn_unobservable_delegated_work is True


def test_prose_only_child_does_not_mark_unknown_side_effects():
    parent = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    child, result = _child_result(parent)

    _entry(child, result)

    assert not getattr(parent, "_pending_unobservable_delegated_work", False)
    assert not getattr(parent, "_turn_unobservable_delegated_work", False)


def test_child_result_attribution_releases_owner_after_merging_late_paths():
    parent = Parent(session_id="parent-session")
    child, result = _child_result(parent)
    child._delegate_verification_owner = parent
    child._turn_file_mutation_paths = {"/workspace/src/late.py"}

    _entry(child, result)

    assert parent._pending_delegated_verification_paths == {"/workspace/src/late.py"}
    assert child._delegate_verification_owner is None


def test_pending_marker_rehydrates_after_parent_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert arm_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
    )

    restored = pending_delegated_verification(session_id="parent-session", authority="ui:owner")

    assert restored["error"] is False
    assert restored["unknown"] is True  # crash before verification is unresolved
    assert restored["paths"] == set()


def test_dispatch_only_marker_blocks_parent_finalization_after_rehydration(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert arm_delegated_verification(
        session_id="parent-session", attempt_id="attempt-dispatch-only", task_index=0, authority="session:parent-session",
    )

    replacement = Parent(session_id="parent-session", _turn_file_mutation_paths=set())
    assert verification_unresolved_at_finalize(replacement)
    failed, reason, response = apply_verification_outcome(
        verification_unresolved=True, interrupted=False, failed=False, exit_reason="completed", final_response="done",
    )

    assert failed is True
    assert reason == "verification_unresolved"
    assert "incomplete" in response


def test_late_telemetry_requires_exact_session_attempt_and_authority(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert arm_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
    )

    assert not update_delegated_verification(
        session_id="foreign-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
        state="completed", paths=["/workspace/foreign.py"],
    )
    assert not update_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:other",
        state="completed", paths=["/workspace/foreign.py"],
    )
    assert update_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
        state="completed", paths=["/workspace/owned.py"],
    )

    restored = pending_delegated_verification(session_id="parent-session", authority="ui:owner")
    assert restored["paths"] == {"/workspace/owned.py"}
    assert restored["unknown"] is False


def test_rehydration_does_not_hide_same_session_foreign_authority(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert arm_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:old-owner",
    )

    restored = pending_delegated_verification(session_id="parent-session", authority="ui:new-owner")

    assert restored["unknown"] is True
    assert restored["rows"][0]["authority"] == "ui:old-owner"


def test_completed_prose_child_retires_only_its_exact_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert arm_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
    )
    assert update_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
        state="completed",
    )
    assert pending_delegated_verification(session_id="parent-session", authority="ui:owner")["rows"] == []
    # A late result cannot resurrect the row after its owner retired it.
    assert not update_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
        state="completed", paths=["/workspace/stale.py"],
    )


def test_failed_or_unobservable_child_cannot_retire_pending_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert arm_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
    )
    assert update_delegated_verification(
        session_id="parent-session", attempt_id="attempt-1", task_index=0, authority="ui:owner",
        state="failed", paths=["/workspace/partial.py"],
    )

    pending = pending_delegated_verification(session_id="parent-session", authority="ui:owner")
    assert pending["unknown"] is True
    assert pending["paths"] == {"/workspace/partial.py"}


def test_verification_authority_is_stable_without_ui_binding(monkeypatch):
    monkeypatch.delenv("HERMES_UI_SESSION_ID", raising=False)
    assert verification_authority(SimpleNamespace(session_id="parent-session")) == "session:parent-session"
