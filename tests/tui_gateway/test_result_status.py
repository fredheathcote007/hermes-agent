"""RED compatibility contracts for strict and advisory assurance consumers."""

from gateway.run import _should_clear_resume_pending_after_turn
from tui_gateway.prompt_turn import _result_status


def test_legacy_strict_verification_unresolved_is_a_tui_error():
    """The historical strict result must remain visibly failed on the TUI."""
    result = {
        "final_response": "Work is incomplete: verification evidence is unavailable.",
        "completed": False,
        "failed": True,
        "verification_unresolved": True,
        "turn_exit_reason": "verification_unresolved",
    }

    assert _result_status(result) == "error"


def test_advisory_unverified_keeps_a_completed_tui_turn():
    """Advisory uncertainty is auxiliary assurance, not an execution failure."""
    result = {
        "final_response": "Useful answer.",
        "completed": True,
        "failed": False,
        "verification_status": "unverified",
    }

    assert _result_status(result) == "complete"


def test_gateway_does_not_clear_resume_pending_for_legacy_strict_failure():
    result = {
        "completed": True,
        "failed": True,
        "verification_unresolved": True,
        "turn_exit_reason": "verification_unresolved",
    }

    assert _should_clear_resume_pending_after_turn(result) is False


def test_gateway_clears_resume_pending_for_advisory_unverified_completion():
    result = {
        "completed": True,
        "failed": False,
        "verification_status": "unverified",
    }

    assert _should_clear_resume_pending_after_turn(result) is True


def test_partial_answer_without_an_error_retains_legacy_complete_status():
    """A partial answer is not independently a failed execution."""
    assert _result_status({"final_response": "answer", "partial": True}) == "complete"
