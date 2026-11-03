"""Regression coverage for FHM-011's passive-verification completion boundary."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.turn_verification_finalize import (
    apply_verification_outcome,
    verification_unresolved_at_finalize,
)
from agent.verification_evidence import (
    arm_delegated_verification,
    mark_workspace_edited,
    pending_delegated_verification,
    record_terminal_result,
    record_verify_run,
    update_delegated_verification,
    verification_status,
)
from agent.verification_stop import build_verify_on_stop_nudge, verification_unresolved


@pytest.fixture(autouse=True)
def _diagnostic_ledger_only(monkeypatch):
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    monkeypatch.setattr("agent.coding_context._git_root", lambda _cwd: None)


def _project(root: Path) -> str:
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    return str(root / "src" / "app.ts")


def test_passed_diagnostic_row_is_labeled_but_cannot_clear_stop_boundary(tmp_path):
    root = tmp_path / "project"
    changed = _project(root)
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])
    record_verify_run(root=root, session_id="owner", ok=True, scope="full", output="model says green")

    status = verification_status(session_id="owner", cwd=root)
    assert status["status"] == "passed"
    assert verification_unresolved(session_id="owner", changed_paths=[changed])
    nudge = build_verify_on_stop_nudge(session_id="owner", changed_paths=[changed])
    assert nudge is not None
    assert "diagnostic" in nudge.lower() or "independent" in nudge.lower()


@pytest.mark.parametrize(
    "record",
    [
        lambda root: record_terminal_result(
            command="pnpm test", cwd=root, session_id="owner", exit_code=0, output="PIPESTATUS=0"
        ),
        lambda root: record_verify_run(root=root, session_id="owner", ok=True, scope="full"),
    ],
)
def test_worker_zero_exit_or_pipestatus_cannot_clear_boundary(tmp_path, record):
    root = tmp_path / "project"
    changed = _project(root)
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])
    assert record(root) is not None
    assert verification_unresolved(session_id="owner", changed_paths=[changed])


def test_finalize_rejects_diagnostic_pass_and_machine_readable_success(tmp_path):
    root = tmp_path / "project"
    changed = _project(root)
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])
    record_verify_run(root=root, session_id="owner", ok=True, scope="full")
    agent = SimpleNamespace(session_id="owner", _turn_file_mutation_paths={changed})

    assert verification_unresolved_at_finalize(agent)
    failed, reason, response = apply_verification_outcome(
        verification_unresolved=True,
        interrupted=False,
        failed=False,
        exit_reason="completed",
        final_response="done",
    )
    assert (failed, reason) == (True, "verification_unresolved")
    assert "incomplete" in response.lower()


def test_completed_delegated_path_stays_pending_without_controller_receipt(tmp_path):
    root = tmp_path / "project"
    changed = _project(root)
    session_id, authority, attempt_id = "owner", "session:owner", "attempt-1"
    mark_workspace_edited(session_id=session_id, cwd=root, paths=[changed])
    assert arm_delegated_verification(
        session_id=session_id, attempt_id=attempt_id, task_index=0, authority=authority,
    )
    assert update_delegated_verification(
        session_id=session_id, attempt_id=attempt_id, task_index=0, authority=authority,
        state="completed", paths=[changed],
    )
    record_verify_run(root=root, session_id=session_id, ok=True, scope="full")
    agent = SimpleNamespace(
        session_id=session_id,
        _turn_file_mutation_paths={changed},
    )

    assert verification_unresolved_at_finalize(agent)
