"""FHM-005 fail-closed finalisation regressions."""

from types import SimpleNamespace
from unittest.mock import patch

from agent.verification_evidence import arm_delegated_verification, pending_delegated_verification
from agent.turn_verification_finalize import verification_unresolved_at_finalize


def test_verifier_exception_cannot_lose_durable_only_pending_after_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    session_id = "fhm005-exception-guard-session"
    assert arm_delegated_verification(
        session_id=session_id, attempt_id="attempt-01", task_index=0,
        authority=f"session:{session_id}",
    )
    agent = SimpleNamespace(session_id=session_id)  # restarted: no in-memory markers
    pending = pending_delegated_verification(
        session_id=session_id, authority=f"session:{session_id}",
    )
    assert pending["unknown"] is True
    with patch("agent.verification_stop.verification_unresolved",
               side_effect=RuntimeError("verifier crashed")):
        assert verification_unresolved_at_finalize(agent) is True
    assert pending_delegated_verification(
        session_id=session_id, authority=f"session:{session_id}",
    )["unknown"] is True


def test_interrupted_verification_unresolved_marks_failed_without_rewriting_interruption():
    from agent.turn_verification_finalize import apply_verification_outcome

    failed, reason, text = apply_verification_outcome(
        verification_unresolved=True, interrupted=True, failed=False,
        exit_reason="interrupted_by_user", final_response="partial streamed text",
    )
    assert failed is True
    assert reason == "interrupted_by_user"
    assert text == "partial streamed text"
