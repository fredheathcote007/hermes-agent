"""Behavior tests for the changed-file configuration-integrity scanner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts/ci/config_integrity.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "scanner@example.invalid")
    _git(repo, "config", "user.name", "config scanner")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, files: dict[str, str], message: str = "change") -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _scan(repo: Path, base: str, head: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo", str(repo), "--base", base, "--head", head],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_jsonc_folder_open_task_is_blocked_and_comments_are_supported(git_repo):
    repo, base = git_repo
    head = _commit(
        repo,
        {
            ".vscode/tasks.json": """
            {
              // JSONC comments and trailing commas are supported.
              "version": "2.0.0",
              "tasks": [{
                "label": "prepare",
                "type": "shell",
                "command": "node tools/prepare.js",
                "runOptions": {"runOn": "folderOpen"},
              }],
            }
            """,
        },
    )
    result = _scan(repo, base, head)
    assert result.returncode == 1
    assert "runs automatically on folderOpen" in result.stdout


def test_plain_text_and_non_folder_open_tasks_are_not_false_positives(git_repo):
    repo, base = git_repo
    head = _commit(
        repo,
        {
            ".vscode/tasks.json": '{"tasks": [{"label": "manual", "runOptions": {"runOn": "default"}}]}\n',
            "scripts/build/notes.js": (
                "// eval(Buffer.from(payload, 'base64')) is documentation, not code.\n"
                "const encoded = ['YQ=='].join('');\n"
            ),
            "README with spaces.md": "folderOpen and eval(Buffer.from(payload, 'base64'))\n",
            "scripts/build/strange\nname.js": "const answer = 42;\n",
        },
    )
    result = _scan(repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr


def test_split_encoded_payload_with_dynamic_execution_is_blocked(git_repo):
    repo, base = git_repo
    head = _commit(
        repo,
        {
            "config/loader.js": (
                "const encoded = ['YQ', '=='].join('');\n"
                "const decoded = Buffer.from(encoded, 'base64')\n"
                "  .toString('utf8');\n"
                "eval(decoded);\n"
            ),
        },
    )
    result = _scan(repo, base, head)
    assert result.returncode == 1
    assert "obfuscation with dynamic execution" in result.stdout


def test_padding_and_overlong_added_code_are_blocked_but_minified_file_is_allowed(git_repo):
    repo, base = git_repo
    padded = " " * 128 + "const hidden = require('child_process').exec('whoami');\n"
    head = _commit(
        repo,
        {
            "build/config.js": (
                padded
                + "const rule = '" + ("x" * 1300) + "';\n"
                + "const ready = true;\n"
                + "export {ready};\n"
            ),
            "build/vendor.min.js": "const vendor = '" + ("x" * 1400) + "';\n",
        },
    )
    result = _scan(repo, base, head)
    assert result.returncode == 1
    assert "whitespace padding" in result.stdout
    assert "overlong line" in result.stdout
    assert "vendor.min.js" not in result.stdout


def test_malformed_jsonc_fails_closed_with_clear_diagnostic(git_repo):
    repo, base = git_repo
    head = _commit(repo, {".vscode/tasks.json": '{"tasks": [\n'})
    result = _scan(repo, base, head)
    assert result.returncode == 1
    assert "tasks.json is not valid JSONC" in result.stdout


def test_invalid_tasks_schema_fails_closed(git_repo):
    repo, base = git_repo
    head = _commit(repo, {".vscode/tasks.json": '{"tasks": {"runOn": "folderOpen"}}\n'})
    result = _scan(repo, base, head)
    assert result.returncode == 1
    assert "invalid top-level tasks schema" in result.stdout


def test_missing_base_revision_is_a_scanner_error(git_repo):
    repo, _ = git_repo
    head = _commit(repo, {"build/config.js": "const value = 1;\n"})
    result = _scan(repo, "0000000000000000000000000000000000000000", head)
    assert result.returncode == 2
    assert "ERROR" in result.stderr
