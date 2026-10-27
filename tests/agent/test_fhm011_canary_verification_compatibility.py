"""FHM-011 contract tests for the two upstream canary verifier conflicts.

These tests deliberately exercise the exported phase-one guard and evidence APIs
through a temporary project.  A terminal receipt may be useful diagnostics, but
it is not independent attestation; only fresh full ``hermes verify`` evidence
can clear the approved DEC-004 source guard.
"""

import json
import tempfile
from pathlib import Path

import pytest

from agent.verification_evidence import (
    mark_workspace_edited,
    record_terminal_result,
    record_verify_run,
    verification_status,
)
from agent.verification_stop import (
    build_verify_on_stop_nudge,
    has_verifiable_paths,
    verification_unresolved,
)


@pytest.fixture(autouse=True)
def _ledger_on(monkeypatch):
    """Enable the opt-in ledger without touching the user's Hermes home."""
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    # These fixtures are marker-only projects.  Do not let an unrelated host
    # repository at a temp-dir parent redefine their workspace root.
    monkeypatch.setattr("agent.coding_context._git_root", lambda _cwd: None)


def _node_project(root: Path) -> None:
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")


def _changed(root: Path) -> str:
    return str(root / "src" / "app.ts")


@pytest.mark.parametrize(
    ("receipt", "expected_kind"),
    [("worker", "test"), ("ad_hoc", "ad_hoc")],
)
def test_passed_terminal_receipts_never_clear_independent_stop_gate(
    tmp_path, monkeypatch, receipt, expected_kind
):
    """The conflict must not turn worker or /tmp-script success into attestation."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    if receipt == "worker":
        root = tmp_path / "suite"
        _node_project(root)
        command = "pnpm test"
        script = None
    else:
        root = tmp_path / "no-suite"
        root.mkdir()
        (root / "package.json").write_text("{}", encoding="utf-8")
        script = (
            Path(tempfile.gettempdir()) / f"hermes-ad-hoc-fhm011-{tmp_path.name}.py"
        )
        script.write_text("print('ok')\n", encoding="utf-8")
        command = f"python {script}"

    changed = _changed(root)
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])
    try:
        receipt_row = record_terminal_result(
            command=command,
            cwd=root,
            session_id="owner",
            exit_code=0,
            output="green",
        )
    finally:
        if script is not None:
            script.unlink(missing_ok=True)

    assert receipt_row is not None
    assert receipt_row["kind"] == expected_kind
    assert verification_status(session_id="owner", cwd=root)["status"] == "passed"
    assert verification_unresolved(session_id="owner", changed_paths=[changed])
    assert (
        build_verify_on_stop_nudge(session_id="owner", changed_paths=[changed])
        is not None
    )


@pytest.mark.parametrize(
    "case",
    ["missing", "failed", "zero_work", "targeted", "foreign", "session_mismatch"],
)
def test_only_fresh_full_verifier_evidence_can_clear_edit(tmp_path, monkeypatch, case):
    """Missing, failed, stale, partial, and unbound proof all remain unresolved."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    root = tmp_path / "project"
    _node_project(root)
    changed = _changed(root)

    if case == "zero_work":
        # A verifier pass before the edit did no work against this changed state.
        record_verify_run(root=root, session_id="owner", ok=True, scope="full")
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])

    if case == "failed":
        record_verify_run(root=root, session_id="owner", ok=False, scope="full")
    elif case == "targeted":
        record_verify_run(root=root, session_id="owner", ok=True, scope="targeted")
    elif case == "foreign":
        record_verify_run(root=root, session_id="other", ok=True, scope="full")
    elif case == "session_mismatch":
        record_verify_run(root=root, session_id=None, ok=True, scope="full")

    assert verification_unresolved(session_id="owner", changed_paths=[changed])
    nudge = build_verify_on_stop_nudge(session_id="owner", changed_paths=[changed])
    assert nudge is not None
    assert "fully verified" in nudge


def test_fresh_same_session_full_verify_clears_guard_and_nudge(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    root = tmp_path / "project"
    _node_project(root)
    changed = _changed(root)
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])

    event = record_verify_run(root=root, session_id="owner", ok=True, scope="full")

    assert event is not None
    assert (
        verification_status(session_id="owner", cwd=root)["evidence"]["kind"]
        == "verify"
    )
    assert not verification_unresolved(session_id="owner", changed_paths=[changed])
    assert (
        build_verify_on_stop_nudge(session_id="owner", changed_paths=[changed]) is None
    )


def test_mixed_paths_filter_docs_but_keep_code_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    root = tmp_path / "project"
    _node_project(root)
    code = _changed(root)
    doc = str(root / "README.md")
    mark_workspace_edited(session_id="owner", cwd=root, paths=[code])

    nudge = build_verify_on_stop_nudge(session_id="owner", changed_paths=[doc, code])

    assert nudge is not None
    assert code in nudge
    assert doc not in nudge
    assert has_verifiable_paths([doc, code])
    assert verification_unresolved(session_id="owner", changed_paths=[doc, code])


def test_docs_only_paths_need_no_verifier_or_nudge(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    paths = ["README.md", "docs/guide.rst", "notes.txt"]

    assert not has_verifiable_paths(paths)
    assert not verification_unresolved(session_id="owner", changed_paths=paths)
    assert build_verify_on_stop_nudge(session_id="owner", changed_paths=paths) is None


def test_stop_nudge_retries_are_bounded_and_missing_evidence_stays_visible(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    root = tmp_path / "project"
    _node_project(root)
    changed = _changed(root)
    mark_workspace_edited(session_id="owner", cwd=root, paths=[changed])

    assert verification_unresolved(session_id="owner", changed_paths=[changed])
    assert (
        build_verify_on_stop_nudge(
            session_id="owner", changed_paths=[changed], attempts=0, max_attempts=2
        )
        is not None
    )
    assert (
        build_verify_on_stop_nudge(
            session_id="owner", changed_paths=[changed], attempts=1, max_attempts=2
        )
        is not None
    )
    assert (
        build_verify_on_stop_nudge(
            session_id="owner", changed_paths=[changed], attempts=2, max_attempts=2
        )
        is None
    )
    # Exhaustion suppresses further nudges; it never verifies the edit.
    assert verification_unresolved(session_id="owner", changed_paths=[changed])
