"""Behavior contracts for the trusted, fail-closed required-check gate."""

import subprocess

from scripts.ci.fermes_gate import (
    GATE_CRITICAL_FILES,
    ChangedPath,
    aggregate,
    inspect_environment,
    parse_name_status,
    source_change,
    validate_gate_integrity,
    validate_ci_path_integrity,
    validate_files,
    _validate_markdown,
)


def test_aggregate_requires_trusted_inspect_success():
    assert aggregate({"inspect": {"result": "success"}}) == []
    assert aggregate({"inspect": {"result": "failure"}})
    assert aggregate({})


def test_unknown_categories_require_source_tests():
    assert not source_change(["README.md"])
    assert source_change(["website/docs/guide.txt"])
    assert source_change([".github/workflows/docker.yml"])
    assert source_change([".github/workflows/fermes-pr-checks.yml"])
    assert source_change(
        ["skills/runtime.md", "agent/prompt.md", "plugins/x.md", "tests/fixture.md"]
    )
    assert not source_change(["docs/fermes/research/FHM-012-ASSESSMENT.md"])
    assert not source_change(["website/docs/index.md", "README.md"])
    assert source_change(["optional-skills/x/SKILL.md", "hermes_cli/AGENTS.md"])
    assert source_change(["plugin-catalog/README.md", ".github/AGENTS.md"])



def test_name_status_handles_deletions_renames_and_non_utf8_paths():
    entries = parse_name_status(b"D\0old.bin\0R100\0old.md\0new.md\0A\0image.png\xff\0")
    assert entries[0] == ChangedPath("D", "old.bin")
    assert entries[1] == ChangedPath("R", "new.md", "old.md")
    assert entries[2].path.endswith("\udcff")
    assert source_change([entries[1]])  # Unclassified root Markdown is source.
    assert source_change([ChangedPath("R", "docs/new.md", "tools/old.py")])
    assert source_change([ChangedPath("D", "tools/removed.py")])


def test_deleted_and_binary_files_are_not_decoded(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00\xff")
    assert (
        validate_files(
            [ChangedPath("D", "gone.png"), ChangedPath("A", "image.png")], tmp_path
        )
        == []
    )


def test_selected_metadata_is_checked_and_missing_metadata_fails(tmp_path):
    (tmp_path / "README.md").write_text("```\n", encoding="utf-8")
    assert validate_files([ChangedPath("A", "README.md")], tmp_path)
    assert validate_files([ChangedPath("A", ".github/workflows/new.yml")], tmp_path)


def test_every_workflow_and_action_path_is_protected():
    entries = [
        ChangedPath("A", ".github/workflows/fake.yml"),
        ChangedPath("D", ".github/actions/setup-pm/action.yml"),
        ChangedPath("R", ".github/workflows/new.yml", ".github/workflows/old.yml"),
    ]
    problems = validate_ci_path_integrity(entries)
    assert len(problems) == 4


def test_gate_workflow_and_helper_forgery_or_deletion_fails_closed(tmp_path):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    for root in (base, candidate):
        for name in GATE_CRITICAL_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"trusted {name}\n".encode())
    assert validate_gate_integrity(base, candidate) == []

    (candidate / GATE_CRITICAL_FILES[0]).write_bytes(b"forged gate\n")
    assert validate_gate_integrity(base, candidate)
    (candidate / GATE_CRITICAL_FILES[0]).write_bytes(
        (base / GATE_CRITICAL_FILES[0]).read_bytes()
    )
    (candidate / GATE_CRITICAL_FILES[-1]).unlink()
    assert validate_gate_integrity(base, candidate)


def test_gate_bootstrap_fails_when_trusted_base_lacks_critical_file(tmp_path):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    candidate.mkdir()
    for name in GATE_CRITICAL_FILES:
        path = candidate / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"candidate\n")
    assert any(
        "trusted base is missing" in problem
        for problem in validate_gate_integrity(base, candidate)
    )


def test_inspection_uses_trusted_helper_even_when_candidate_replaces_it(
    tmp_path, monkeypatch
):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    (tmp_path / "trusted.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    subprocess.run(["git", "checkout", "-qb", "pr"], cwd=tmp_path, check=True)
    helper = tmp_path / "scripts/ci"
    helper.mkdir(parents=True)
    (helper / "fermes_gate.py").write_text(
        "raise SystemExit('PR code executed')\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    subprocess.run(
        ["git", "checkout", "-q", "-B", "main", base], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "merge", "--no-ff", "-qm", "synthetic", head], cwd=tmp_path, check=True
    )
    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CANDIDATE_DIR", str(tmp_path))
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("PR_HEAD_SHA", head)
    entries, checked_head, _ = inspect_environment()
    assert checked_head == head
    assert any(entry.path == "scripts/ci/fermes_gate.py" for entry in entries)


def test_inspection_binds_to_exact_synthetic_merge_head(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True
    )
    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-qm", "base")
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    run("checkout", "-qb", "pr")
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    run("commit", "-am", "head")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    run("checkout", "-q", "--detach", base)
    run("merge", "--no-ff", "-qm", "synthetic", head)
    monkeypatch.setenv("BASE_DIR", str(repo))
    monkeypatch.setenv("CANDIDATE_DIR", str(repo))
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("PR_HEAD_SHA", head)
    _, checked_head, _ = inspect_environment()
    assert checked_head == head
    monkeypatch.setenv("PR_HEAD_SHA", "0" * 40)
    try:
        inspect_environment()
    except ValueError as exc:
        assert "synthetic merge" in str(exc)
    else:
        raise AssertionError("wrong PR head was accepted")


def test_diff_check_is_a_real_git_check(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    (tmp_path / "file.txt").write_bytes(b"bad trailing space \n")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["git", "diff", "--check", base, "HEAD"], cwd=tmp_path, check=False
    )
    assert result.returncode != 0


def test_diff_check_uses_base_attributes(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    (tmp_path / ".gitattributes").write_text("*.txt whitespace\n", encoding="utf-8")
    (tmp_path / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    (tmp_path / ".gitattributes").write_text("*.txt -whitespace\n", encoding="utf-8")
    (tmp_path / "file.txt").write_bytes(b"bad trailing space \n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CANDIDATE_DIR", str(tmp_path))
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("PR_HEAD_SHA", candidate)
    subprocess.run(
        ["git", "checkout", "-q", "-B", "main", base], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "merge", "--no-ff", "-qm", "synthetic", candidate],
        cwd=tmp_path,
        check=True,
    )
    try:
        inspect_environment()
    except ValueError as exc:
        assert "diff --check" in str(exc)
    else:
        raise AssertionError("base whitespace attribute was ignored")


def test_markdown_hardbreak_allowed_but_other_trailing_whitespace_rejected():
    assert _validate_markdown(b"**Date:** 2026-10-28 UTC  \n", "memo.md") == []
    assert _validate_markdown(b"trailing one \n", "memo.md")
    assert _validate_markdown(b"trailing three   \n", "memo.md")
