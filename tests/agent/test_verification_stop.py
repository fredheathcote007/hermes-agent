import json
import sys
import tempfile
from pathlib import Path

import pytest

from agent.verification_evidence import (
    mark_workspace_edited,
    record_verify_run,
    record_terminal_result,
)
from agent.verification_stop import (
    build_verify_on_stop_nudge,
    verification_unresolved,
    verify_on_stop_enabled,
)

def _node_project(root: Path) -> None:
    (root / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")

def _make_project(root: Path) -> None:
    root.mkdir()
    _node_project(root)

@pytest.fixture(autouse=True)
def _ledger_on(monkeypatch):
    """The ledger is inert unless verify-on-stop is enabled; ``clear_verify_env`` (requested
    explicitly, so it runs after this) strips it again for the enabled()-logic tests."""
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")

@pytest.fixture
def clear_verify_env(monkeypatch):
    """Clear every env signal verify_on_stop_enabled consults.

    Tests then set only the variable they exercise, mirroring how the CLI/TUI
    set HERMES_SESSION_SOURCE and the gateway sets HERMES_SESSION_PLATFORM.
    """
    for var in (
        "HERMES_VERIFY_ON_STOP",
        "HERMES_PLATFORM",
        "HERMES_SESSION_PLATFORM",
        "HERMES_SESSION_SOURCE",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch

def test_verify_on_stop_env_can_enable(clear_verify_env):
    # Env "1" forces ON regardless of surface (here a messaging platform).
    clear_verify_env.setenv("HERMES_VERIFY_ON_STOP", "1")
    clear_verify_env.setenv("HERMES_SESSION_PLATFORM", "telegram")
    assert verify_on_stop_enabled({"agent": {}}) is True

@pytest.mark.parametrize("source", ["cli", "tui", "desktop", "codex", "local"])
def test_verify_on_stop_auto_on_for_interactive_surfaces(clear_verify_env, source):
    # Under "auto", CLI/TUI/desktop coding surfaces resolve ON.
    clear_verify_env.setenv("HERMES_SESSION_SOURCE", source)
    assert verify_on_stop_enabled({"agent": {"verify_on_stop": "auto"}}) is True

def test_verify_on_stop_missing_value_defaults_off(clear_verify_env):
    # A missing/unrecognized config value falls back OFF on every surface,
    # matching the opt-in DEFAULT_CONFIG default — only an explicit "auto"
    # opts into the legacy surface-aware behavior.
    clear_verify_env.setenv("HERMES_SESSION_SOURCE", "cli")
    assert verify_on_stop_enabled({"agent": {}}) is False
    assert verify_on_stop_enabled({"agent": {"verify_on_stop": "bogus"}}) is False
    assert verify_on_stop_enabled({}) is False

def test_nudge_checks_all_edited_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    _make_project(project_a)
    _make_project(project_b)
    changed_a = str(project_a / "src" / "app.ts")
    changed_b = str(project_b / "src" / "app.ts")

    record_terminal_result(
        command="pnpm test",
        cwd=project_a,
        session_id="s1",
        exit_code=0,
        output="green",
    )
    mark_workspace_edited(session_id="s1", cwd=project_b, paths=[changed_b])

    nudge = build_verify_on_stop_nudge(
        session_id="s1",
        changed_paths=[changed_a, changed_b],
    )

    assert nudge is not None
    assert changed_b in nudge

@pytest.mark.platforms("posix")  # Symlinks require elevated privileges on Windows
def test_no_suite_nudge_uses_canonical_temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text("{}", encoding="utf-8")
    real_temp = tmp_path / "real-temp"
    real_temp.mkdir()
    linked_temp = tmp_path / "linked-temp"
    linked_temp.symlink_to(real_temp, target_is_directory=True)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(linked_temp))

    nudge = build_verify_on_stop_nudge(
        session_id="s1",
        changed_paths=[str(project / "src" / "app.ts")],
    )

    assert nudge is not None
    # Without a canonical verifier, fail closed instead of suggesting an
    # arbitrary temporary script as independent evidence.
    assert "No independent Hermes verification recipe is available" in nudge
    assert "hermes-verify-" not in nudge

def test_ad_hoc_worker_pass_does_not_satisfy_independent_stop_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    changed = str(tmp_path / "src" / "app.ts")
    script = Path(tempfile.gettempdir()) / f"hermes-ad-hoc-stop-{tmp_path.name}.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    try:
        record_terminal_result(
            command=f"python {script}",
            cwd=tmp_path,
            session_id="s1",
            exit_code=0,
            output="ok",
        )
    finally:
        script.unlink(missing_ok=True)

    assert build_verify_on_stop_nudge(session_id="s1", changed_paths=[changed]) is not None

def test_nudge_attempts_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _node_project(tmp_path)
    changed = str(tmp_path / "src" / "app.ts")
    mark_workspace_edited(session_id="s1", cwd=tmp_path, paths=[changed])

    assert build_verify_on_stop_nudge(
        session_id="s1",
        changed_paths=[changed],
        attempts=2,
        max_attempts=2,
    ) is None


def test_worker_command_receipt_is_not_independent_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _node_project(tmp_path)
    changed = str(tmp_path / "src" / "app.ts")
    mark_workspace_edited(session_id="owner", cwd=tmp_path, paths=[changed])
    # A worker can run or claim a passing test command; it is not the independent verifier.
    record_terminal_result(command="pnpm test", cwd=tmp_path, session_id="owner", exit_code=0, output="green")
    assert verification_unresolved(session_id="owner", changed_paths=[changed])


@pytest.mark.parametrize("case", ["missing", "stale", "foreign", "failed"])
def test_verifier_evidence_must_be_current_and_session_bound(tmp_path, monkeypatch, case):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _node_project(tmp_path)
    changed = str(tmp_path / "src" / "app.ts")
    mark_workspace_edited(session_id="owner", cwd=tmp_path, paths=[changed])
    if case == "stale":
        record_verify_run(root=tmp_path, session_id="owner", ok=True)
        mark_workspace_edited(session_id="owner", cwd=tmp_path, paths=[changed])
    elif case == "foreign":
        record_verify_run(root=tmp_path, session_id="other", ok=True)
    elif case == "failed":
        record_verify_run(root=tmp_path, session_id="owner", ok=False)
    assert verification_unresolved(session_id="owner", changed_paths=[changed])


def test_current_full_verifier_evidence_allows_completion_after_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _node_project(tmp_path)
    changed = str(tmp_path / "src" / "app.ts")
    mark_workspace_edited(session_id="owner", cwd=tmp_path, paths=[changed])
    record_verify_run(root=tmp_path, session_id="owner", ok=True, scope="full")
    assert not verification_unresolved(session_id="owner", changed_paths=[changed])


def test_cross_session_full_verify_does_not_clear_editers_pending_work(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _node_project(tmp_path)
    changed = str(tmp_path / "src" / "app.ts")
    mark_workspace_edited(session_id="editor", cwd=tmp_path, paths=[changed])
    record_verify_run(root=tmp_path, session_id="other", ok=True, scope="full")
    assert verification_unresolved(session_id="editor", changed_paths=[changed])


def test_docs_only_paths_are_not_unresolved_when_evidence_lookup_fails(monkeypatch):
    from agent.verification_stop import has_verifiable_paths

    assert not has_verifiable_paths(["README.md", "docs/guide.md"])
    assert has_verifiable_paths(["README.md", "src/app.py"])

# ---------------------------------------------------------------------------
# Fix C: documentation/prose edits carry no verifiable behavior and must never
# trip the nudge, even on an unverified workspace.
# ---------------------------------------------------------------------------

def test_mixed_doc_and_code_edit_still_nudges(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _node_project(tmp_path)
    doc = str(tmp_path / "README.md")
    code = str(tmp_path / "src" / "app.ts")
    mark_workspace_edited(session_id="s1", cwd=tmp_path, paths=[code])

    nudge = build_verify_on_stop_nudge(
        session_id="s1", changed_paths=[doc, code]
    )
    assert nudge is not None
    # The doc path is filtered out of the reported set; the code path remains.
    assert code in nudge
    assert doc not in nudge
