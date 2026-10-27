"""The TUI must not render fail-closed run results as successful (#5 / FHM-005)."""

import pytest

from tui_gateway.prompt_turn import _result_status


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"final_response": "done"}, "complete"),
        (
            {
                "interrupted": True,
                "error": "provider error",
                "failed": True,
                "verification_unresolved": True,
                "partial": True,
            },
            "interrupted",
        ),
        ({"error": "provider error"}, "error"),
        ({"failed": True}, "error"),
        ({"verification_unresolved": True}, "error"),
        ({"partial": True}, "error"),
        ({"turn_exit_reason": "verification_unresolved"}, "error"),
        ({"failed": None, "verification_unresolved": False, "partial": 0}, "complete"),
        ({"turn_exit_reason": {"reason": "verification_unresolved"}}, "complete"),
        (None, "complete"),
        ([], "complete"),
        ("not a result dict", "complete"),
    ],
)
def test_result_status_is_deterministic_for_success_and_failure_shapes(result, expected):
    assert _result_status(result) == expected
