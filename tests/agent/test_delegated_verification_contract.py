"""RED contracts for Core delegated outcome assurance.

These tests deliberately exercise the existing profile-local verification module and
turn finalizer.  They do not import the historical delegated modules, because their
absence on current main is part of the intended RED evidence.
"""

from pathlib import Path

import pytest

from agent import verification_evidence, verification_stop
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
