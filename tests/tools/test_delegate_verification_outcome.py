"""RED contracts for delegated child outcome classification."""

from types import SimpleNamespace

from tools.delegate_tool_child_run import _SchemaOutcome, _build_result_entry


def _child():
    return SimpleNamespace(
        model="child-model",
        session_estimated_cost_usd=0.0,
        session_cost_status="unknown",
        session_prompt_tokens=0,
        session_completion_tokens=0,
        _delegate_role="leaf",
    )


def test_model_done_after_opaque_terminal_effect_is_unverified_not_verified():
    """A child summary and successful tool return are not independent effect proof."""
    result = {
        "final_response": "I ran the command successfully.",
        "completed": True,
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "terminal",
                            "arguments": '{"command":"touch x"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "exit code 0"},
        ],
    }

    entry = _build_result_entry(
        _child(), result, 0, 0.1, _SchemaOutcome(None, None, [], 0)
    )

    assert entry["status"] == "completed"
    assert entry["summary"] == result["final_response"]
    assert entry["verification_status"] == "unverified"
    assert entry["verification_status"] != "corroborated"


def test_noop_child_success_does_not_mint_corroborated_evidence():
    """A child that only returns prose cannot create a corroborated outcome."""
    result = {"final_response": "Done.", "completed": True, "messages": []}

    entry = _build_result_entry(
        _child(), result, 0, 0.1, _SchemaOutcome(None, None, [], 0)
    )

    assert entry["status"] == "completed"
    assert entry.get("verification_status") != "corroborated"


def test_telemetry_failure_resolves_parent_once_and_marks_unobservable_under_lock(
    monkeypatch,
):
    from tools import delegate_verification

    class TrackingLock:
        def __init__(self):
            self.held = False
            self.entered = 0

        def __enter__(self):
            self.held = True
            self.entered += 1
            return self

        def __exit__(self, *_exc):
            self.held = False

    class Parent(SimpleNamespace):
        def __setattr__(self, name, value):
            if name in {
                "_turn_unobservable_delegated_work",
                "_pending_unobservable_delegated_work",
            } and hasattr(self, "_pending_delegated_verification_lock"):
                assert self._pending_delegated_verification_lock.held
            super().__setattr__(name, value)

    lock = TrackingLock()
    parent = Parent(
        _pending_delegated_verification_lock=lock,
        _turn_unobservable_delegated_work=False,
        _pending_unobservable_delegated_work=False,
    )
    lookups = []

    def parent_lookup():
        lookups.append(None)
        return parent

    child = _child()
    child._delegate_verification_owner = None
    child._delegate_parent_ref = parent_lookup
    monkeypatch.setattr(
        delegate_verification,
        "record_child_verification",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("telemetry failed")),
    )

    entry = _build_result_entry(
        child,
        {"final_response": "Done.", "completed": True, "messages": []},
        0,
        0.1,
        _SchemaOutcome(None, None, [], 0),
    )

    assert entry["status"] == "completed"
    assert len(lookups) == 1
    assert lock.entered == 1
    assert parent._turn_unobservable_delegated_work is True
    assert parent._pending_unobservable_delegated_work is True
