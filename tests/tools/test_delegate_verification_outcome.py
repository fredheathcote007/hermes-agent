"""Delegated mutation provenance must outlive the parent turn that spawned a child."""

from __future__ import annotations

import threading
import weakref
from types import SimpleNamespace

import pytest

from tools.delegate_tool_child_run import _SchemaOutcome, _build_result_entry


class Parent(SimpleNamespace):
    """Real AIAgent objects support weakref; SimpleNamespace does not."""


def _child_result(parent, tool_name=None):
    child = SimpleNamespace(
        _delegate_parent_ref=weakref.ref(parent),
        _turn_file_mutation_paths=set(),
        model="test",
    )
    messages = []
    if tool_name:
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {"name": tool_name, "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
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
