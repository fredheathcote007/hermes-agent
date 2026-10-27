"""Behaviour contracts for the offline Fermes upstream comparison CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fermes_upstream_compare.py"
OFFICIAL_URL = "https://github.com/NousResearch/hermes-agent.git"
FORK_URL = "https://github.com/fredheathcote007/hermes-agent.git"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if check:
        result.check_returncode()
    return result


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def make_repository(
    tmp_path: Path,
    upstream_path: str,
    upstream_value: str,
    fork_path: str,
    fork_value: str,
) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "user.name", "Fermes tests")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    base = commit(repo, "base")
    git(repo, "remote", "add", "official", OFFICIAL_URL)
    git(repo, "remote", "add", "maintained", FORK_URL)

    git(repo, "switch", "-c", "upstream-target", base)
    (repo / upstream_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / upstream_path).write_text(upstream_value, encoding="utf-8")
    upstream = commit(repo, "upstream change")

    git(repo, "switch", "-c", "fork-target", base)
    (repo / fork_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / fork_path).write_text(fork_value, encoding="utf-8")
    fork = commit(repo, "maintained fork change")
    git(repo, "switch", "--detach", base)
    return repo, base, upstream, fork


def run_compare(
    repo: Path, base: str, target: str, fork: str, *, output_format: str = "json"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--upstream-base",
            base,
            "--upstream-target",
            target,
            "--fork",
            fork,
            "--format",
            output_format,
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"GIT_DIR", "GIT_WORK_TREE"}
        },
    )


def report(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_exact_equivalent_patch_uses_patch_id_not_commit_sha(tmp_path: Path) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "shared.txt", "same\n", "shared.txt", "same\n"
    )
    data = report(run_compare(repo, base, upstream, fork))
    markdown = run_compare(repo, base, upstream, fork, output_format="markdown")

    assert data["comparison"]["classification"] == "exact-equivalent"
    assert data["comparison"]["equivalent_patch_pairs"]
    assert upstream != fork
    assert markdown.returncode == 0
    assert "# Fermes upstream comparison" in markdown.stdout
    assert "`exact-equivalent`" in markdown.stdout


def test_overlapping_different_patch_requires_review(tmp_path: Path) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "shared.txt", "upstream\n", "shared.txt", "fork\n"
    )
    data = report(run_compare(repo, base, upstream, fork))

    comparison = data["comparison"]
    assert comparison["classification"] == "possible-overlap-by-path"
    assert comparison["path_overlap"] == ["shared.txt"]
    assert comparison["review_required"] is True
    assert comparison["compatibility_status"] == "not-established"


def test_unrelated_files_are_no_overlap_with_risk_hints(tmp_path: Path) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "tests/upstream.py", "upstream\n", "tools/fork.py", "fork\n"
    )
    data = report(run_compare(repo, base, upstream, fork))

    assert data["comparison"]["classification"] == "no-overlap"
    assert data["comparison"]["path_overlap"] == []
    assert data["risk_hints"]["tests"] == ["tests/upstream.py"]
    assert data["risk_hints"]["tool_use"] == ["tools/fork.py"]


@pytest.mark.parametrize("bad_ref", ["does-not-exist", "HEAD~999"])
def test_bad_ref_fails_closed(tmp_path: Path, bad_ref: str) -> None:
    repo, base, _upstream, fork = make_repository(
        tmp_path, "one.txt", "one\n", "two.txt", "two\n"
    )
    result = run_compare(repo, base, bad_ref, fork)

    assert result.returncode != 0
    assert json.loads(result.stdout)["status"] == "error"


def test_spoofed_remotes_fail_closed(tmp_path: Path) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "one.txt", "one\n", "two.txt", "two\n"
    )
    git(
        repo,
        "remote",
        "set-url",
        "official",
        "https://github.com/attacker/hermes-agent.git",
    )
    result = run_compare(repo, base, upstream, fork)

    assert result.returncode != 0
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "remote_identity"


def test_dirty_checkout_and_read_only_determinism(tmp_path: Path) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "one.txt", "one\n", "two.txt", "two\n"
    )
    before_refs = git(repo, "show-ref").stdout
    first = run_compare(repo, base, upstream, fork)
    after_first_refs = git(repo, "show-ref").stdout
    second = run_compare(repo, base, upstream, fork)

    assert first.stdout == second.stdout
    assert before_refs == after_first_refs
    assert git(repo, "status", "--porcelain=v1").stdout == ""
    (repo / "base.txt").write_text("dirty\n", encoding="utf-8")
    dirty = run_compare(repo, base, upstream, fork)
    assert dirty.returncode != 0
    assert json.loads(dirty.stdout)["error"]["code"] == "dirty_worktree"


def test_real_pinned_history_is_conservative(tmp_path: Path) -> None:
    fork_commit = git(
        ROOT, "rev-parse", "fermes/qwen-lmstudio-v0225-20261026"
    ).stdout.strip()
    worktree = tmp_path / "real-history"
    worktree.mkdir()
    base = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
    subprocess.run(
        ["git", "-C", str(worktree), "init", "-b", "main"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    git(worktree, "remote", "add", "official", OFFICIAL_URL)
    git(worktree, "remote", "add", "maintained", FORK_URL)
    git(worktree, "fetch", "--depth=10000", str(ROOT), base, fork_commit)
    git(worktree, "update-ref", "refs/heads/base", base)
    git(worktree, "update-ref", "refs/heads/fork", fork_commit)
    git(worktree, "update-ref", "refs/tags/v0.22.5", base)
    git(worktree, "switch", "--detach", base)
    result = run_compare(worktree, base, "v0.22.5", fork_commit)
    data = report(result)

    assert (
        data["refs"]["upstream_base"]["commit"]
        == data["refs"]["upstream_target"]["commit"]
    )
    assert data["refs"]["upstream_target"]["version"].startswith("v0.22.5")
    assert data["comparison"]["review_required"] is True
    assert data["comparison"]["compatibility_status"] == "not-established"
