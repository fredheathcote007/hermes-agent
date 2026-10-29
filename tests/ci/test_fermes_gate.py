"""Behavior contracts for the trusted, fail-closed required-check gate."""

import subprocess

from scripts.ci.fermes_gate import (
    ChangedPath,
    aggregate,
    inspect_environment,
    parse_name_status,
    source_change,
    validate_files,
)


def test_aggregate_requires_trusted_inspect_and_expected_source_result():
    needs = {"inspect": {"result": "success"}, "source-test": {"result": "success"}}
    assert aggregate(needs, "true") == []
    assert aggregate({"inspect": {"result": "success"}, "source-test": {"result": "skipped"}}, "true")
    assert aggregate({"inspect": {"result": "success"}, "source-test": {"result": "skipped"}}, "false") == []
    assert aggregate({"inspect": {"result": "failure"}, "source-test": {"result": "skipped"}}, "false")
    assert aggregate(needs, "") == ["inspect.source=missing-or-invalid"]


def test_unknown_categories_require_source_tests():
    assert not source_change(["README.md", ".github/workflows/fermes-pr-checks.yml"])
    assert source_change(["website/docs/guide.txt"])
    assert source_change([".github/workflows/docker.yml"])


def test_name_status_handles_deletions_renames_and_non_utf8_paths():
    entries = parse_name_status(b"D\0old.bin\0R100\0old.md\0new.md\0A\0image.png\xff\0")
    assert entries[0] == ChangedPath("D", "old.bin")
    assert entries[1] == ChangedPath("R", "new.md", "old.md")
    assert entries[2].path.endswith("\udcff")


def test_deleted_and_binary_files_are_not_decoded(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00\xff")
    assert validate_files([ChangedPath("D", "gone.png"), ChangedPath("A", "image.png")], tmp_path) == []


def test_selected_metadata_is_checked_and_missing_metadata_fails(tmp_path):
    (tmp_path / "README.md").write_text("```\n", encoding="utf-8")
    assert validate_files([ChangedPath("A", "README.md")], tmp_path)
    assert validate_files([ChangedPath("A", ".github/workflows/new.yml")], tmp_path)


def test_inspection_uses_trusted_helper_even_when_candidate_replaces_it(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    (tmp_path / "trusted.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "checkout", "-qb", "pr"], cwd=tmp_path, check=True)
    helper = tmp_path / "scripts/ci"
    helper.mkdir(parents=True)
    (helper / "fermes_gate.py").write_text("raise SystemExit('PR code executed')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "checkout", "-q", "-B", "main", base], cwd=tmp_path, check=True)
    subprocess.run(["git", "merge", "--no-ff", "-qm", "synthetic", head], cwd=tmp_path, check=True)
    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CANDIDATE_DIR", str(tmp_path))
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("PR_HEAD_SHA", head)
    entries, checked_head, _ = inspect_environment()
    assert checked_head == head
    assert any(entry.path == "scripts/ci/fermes_gate.py" for entry in entries)


def test_diff_check_is_a_real_git_check(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "file.txt").write_bytes(b"bad trailing space \n")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=tmp_path, check=True)
    result = subprocess.run(["git", "diff", "--check", base, "HEAD"], cwd=tmp_path, check=False)
    assert result.returncode != 0
