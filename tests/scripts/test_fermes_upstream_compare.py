"""Behaviour contracts for the offline Fermes upstream comparison CLI."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fermes_upstream_compare.py"
OFFICIAL_URL = "https://github.com/NousResearch/hermes-agent.git"
FORK_URL = "https://github.com/fredheathcote007/hermes-agent.git"
MODULE_NAME = "fermes_upstream_compare_test_module"
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
COMPARE_TOOL = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = COMPARE_TOOL
MODULE_SPEC.loader.exec_module(COMPARE_TOOL)


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
    assert data["comparison"]["confidence_status"] == "patch-only"
    assert data["comparison"]["equivalent_patch_pairs"]
    assert upstream != fork
    assert markdown.returncode == 0
    assert "# Fermes upstream comparison" in markdown.stdout
    assert "`exact-equivalent`" in markdown.stdout
    assert "patch-only; not deploy safety" in markdown.stdout


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


def test_pinned_history_fixture_is_conservative(tmp_path: Path) -> None:
    repo, base, _upstream, fork = make_repository(
        tmp_path, "upstream.txt", "upstream\n", "fork.txt", "fork\n"
    )
    git(repo, "tag", "v0.22.5", base)
    result = run_compare(repo, base, "v0.22.5", fork)
    data = report(result)

    assert (
        data["refs"]["upstream_base"]["commit"]
        == data["refs"]["upstream_target"]["commit"]
    )
    assert data["refs"]["upstream_target"]["version"].startswith("v0.22.5")
    assert data["comparison"]["review_required"] is True
    assert data["comparison"]["compatibility_status"] == "not-established"


def test_non_ancestor_fails_closed(tmp_path: Path) -> None:
    repo, _base, upstream, fork = make_repository(
        tmp_path, "one.txt", "one\n", "two.txt", "two\n"
    )
    result = run_compare(repo, upstream, fork, fork)

    assert result.returncode != 0
    assert json.loads(result.stdout)["error"]["code"] == "ref_relationship"


def test_missing_patch_id_is_not_classified_as_equivalent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "shared.txt", "upstream\n", "shared.txt", "fork\n"
    )
    monkeypatch.setattr(
        COMPARE_TOOL, "_aggregate_patch_id", lambda *args, **kwargs: None
    )

    data = COMPARE_TOOL.compare(repo, base, upstream, fork)

    assert data["comparison"]["classification"] == "unknown/non-equivalent"
    assert data["comparison"]["confidence_status"] == "low"


def test_commit_history_has_a_real_count_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commits = [f"{index:040x}" for index in range(COMPARE_TOOL.MAX_COMMIT_COUNT + 1)]
    calls: list[list[str]] = []

    def fake_git(_repo: Path, args: list[str], **_kwargs: object) -> bytes:
        calls.append(args)
        return ("\n".join(commits) + "\n").encode()

    monkeypatch.setattr(COMPARE_TOOL, "_git", fake_git)

    with pytest.raises(COMPARE_TOOL.CompareError, match="comparison bound") as error:
        COMPARE_TOOL._commit_patch_ids(tmp_path, "base", "target")

    assert error.value.code == "commit_bound"
    assert len(calls) == 1


def test_commit_history_budget_is_monotonic_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def fake_git(_repo: Path, _args: list[str], **_kwargs: object) -> bytes:
        nonlocal calls
        calls += 1
        return b"0" * 40 + b"\n"

    monkeypatch.setattr(COMPARE_TOOL, "_git", fake_git)
    budget = COMPARE_TOOL.ComparisonBudget(time.monotonic() - 1)

    with pytest.raises(COMPARE_TOOL.CompareError) as error:
        COMPARE_TOOL._commit_patch_ids(tmp_path, "base", "target", budget=budget)

    assert error.value.code == "comparison_timeout"
    assert calls == 0


def test_patch_id_rejects_stream_output_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_runner(*_args: object, **_kwargs: object) -> object:
        return COMPARE_TOOL.GitResult(0, b"", b"", truncated=True)

    monkeypatch.setattr(COMPARE_TOOL, "_run_git_bounded", fake_runner)

    with pytest.raises(COMPARE_TOOL.CompareError, match="output bound") as error:
        COMPARE_TOOL._patch_id(tmp_path, b"patch\n")

    assert error.value.code == "bounded_output"


def test_bounded_git_streams_input_and_caps_output(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")
    result = COMPARE_TOOL._run_git_bounded(
        tmp_path,
        ["cat-file", "--batch"],
        input_data=b"missing-object\n" * 128,
        max_output=128,
    )

    assert result.truncated is True
    assert len(result.stdout) + len(result.stderr) <= 128


def test_report_path_lists_are_bounded_and_annotated(tmp_path: Path) -> None:
    repo, base, upstream, fork = make_repository(
        tmp_path, "one.txt", "one\n", "two.txt", "two\n"
    )
    git(repo, "switch", "--detach", upstream)
    for index in range(COMPARE_TOOL.MAX_REPORT_ITEMS + 10):
        path = repo / "upstream" / f"file-{index:03d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{index}\n", encoding="utf-8")
    large_upstream = commit(repo, "many upstream files")
    git(repo, "switch", "--detach", base)

    data = report(run_compare(repo, base, large_upstream, fork))
    comparison = data["comparison"]

    assert comparison["upstream"]["changed_paths_truncated"] is True
    assert len(comparison["upstream"]["changed_paths"]) == COMPARE_TOOL.MAX_REPORT_ITEMS
    assert (
        len(data["comparison"]["upstream"]["changes"]) == COMPARE_TOOL.MAX_REPORT_ITEMS
    )
    assert len(json.dumps(data).encode()) <= COMPARE_TOOL.MAX_REPORT_BYTES
    assert any(
        "upstream changed_paths truncated" in warning for warning in data["warnings"]
    )


def test_equivalent_patch_pairs_are_deterministically_truncated() -> None:
    upstream = {f"{index:040x}": "same" for index in range(32)}
    fork = {f"{index + 100:040x}": "same" for index in range(32)}

    pairs, total, truncated = COMPARE_TOOL._equivalent_patch_pairs(upstream, fork)

    assert len(pairs) == COMPARE_TOOL.MAX_EQUIVALENT_PATCH_PAIRS
    assert total == 32 * 32
    assert truncated is True
    assert pairs[0]["upstream_commit"] == "0" * 40
    assert pairs[0]["fork_commit"] == f"{100:040x}"
