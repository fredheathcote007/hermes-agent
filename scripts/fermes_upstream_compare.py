#!/usr/bin/env python3
"""Compare two local upstream refs with a maintained fork ref.

The command is deliberately read-only.  It never fetches, changes refs or
creates a report file; reports are written to stdout only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlparse


TOOL_NAME = "fermes-upstream-compare"
SCHEMA_VERSION = 1
DEFAULT_TIMEOUT = 10.0
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_PATCH_INPUT_BYTES = 4 * 1024 * 1024
COMPARISON_BUDGET_SECONDS = 30.0
MAX_COMMIT_COUNT = 256
MAX_EQUIVALENT_PATCH_PAIRS = 256
MAX_REPORT_ITEMS = 256
MAX_REPORT_BYTES = 1024 * 1024
OFFICIAL_IDENTITY = "github.com/nousresearch/hermes-agent"
FORK_IDENTITY = "github.com/fredheathcote007/hermes-agent"
T = TypeVar("T")


class CompareError(RuntimeError):
    """A fail-closed comparison error."""

    def __init__(self, code: str, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class ComparisonBudget:
    """Monotonic deadline shared by all work in one comparison."""

    deadline: float

    @classmethod
    def start(cls, seconds: float = COMPARISON_BUDGET_SECONDS) -> ComparisonBudget:
        return cls(time.monotonic() + seconds)

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CompareError("comparison_timeout", "comparison budget exhausted")
        return remaining


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    """Terminate a child and collect it without buffering either pipe."""

    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired as reap_exc:
            raise CompareError(
                "git_execution", "Git process could not be killed and reaped"
            ) from reap_exc
        raise CompareError(
            "git_execution", "Git process exceeded reap grace period"
        ) from exc


def _run_git_bounded(
    repo: Path,
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_output: int = MAX_OUTPUT_BYTES,
    input_data: bytes | None = None,
    max_input: int = MAX_PATCH_INPUT_BYTES,
) -> GitResult:
    """Run Git with bounded pipes and selector-driven input/output."""

    if input_data is not None and len(input_data) > max_input:
        raise CompareError("bounded_input", "Git input exceeded the input bound")

    argv = ["git", "-C", str(repo), *args]
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise CompareError("git_unavailable", f"could not run Git: {exc}") from exc

    assert process.stdout is not None and process.stderr is not None
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    buffers = {stdout_fd: bytearray(), stderr_fd: bytearray()}
    streams = {stdout_fd: process.stdout, stderr_fd: process.stderr}
    selector = selectors.DefaultSelector()
    for stream in streams.values():
        selector.register(stream, selectors.EVENT_READ)
    input_stream = process.stdin if input_data is not None else None
    input_fd = input_stream.fileno() if input_stream is not None else None
    input_offset = 0
    if input_stream is not None:
        os.set_blocking(input_fd, False)
        selector.register(input_stream, selectors.EVENT_WRITE)
    captured = 0
    killed = False
    truncated = False
    timed_out = False
    started = time.monotonic()
    kill_deadline: float | None = None
    try:
        while streams or input_stream is not None:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                timed_out = True
                if not killed:
                    _kill_and_reap(process)
                    killed = True
                    kill_deadline = time.monotonic()
                if input_stream is not None:
                    selector.unregister(input_stream)
                    input_stream.close()
                    input_stream = None
            if (
                killed
                and kill_deadline is not None
                and time.monotonic() >= kill_deadline
            ):
                break
            for key, _ in selector.select(min(0.1, max(0.0, remaining))):
                stream = key.fileobj
                if stream is input_stream:
                    try:
                        chunk = input_data[input_offset : input_offset + 65536]
                        if chunk:
                            input_offset += os.write(input_fd, chunk)
                        if input_offset == len(input_data):
                            selector.unregister(stream)
                            stream.close()
                            input_stream = None
                    except BrokenPipeError:
                        selector.unregister(stream)
                        stream.close()
                        input_stream = None
                    continue
                fd = stream.fileno()
                data = os.read(fd, 65536)
                if not data:
                    selector.unregister(stream)
                    streams.pop(fd, None)
                    stream.close()
                    continue
                if not killed and not truncated:
                    room = max_output - captured
                    buffers[fd].extend(data[:room])
                    captured += min(room, len(data))
                    if len(data) > room:
                        truncated = True
                        _kill_and_reap(process)
                        killed = True
                        kill_deadline = time.monotonic()
                        if input_stream is not None:
                            selector.unregister(input_stream)
                            input_stream.close()
                            input_stream = None
        if process.poll() is None:
            _kill_and_reap(process)
        else:
            process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _kill_and_reap(process)
        raise CompareError(
            "git_execution", f"Git process could not be collected: {exc}"
        ) from exc
    finally:
        if input_stream is not None:
            input_stream.close()
        for stream in streams.values():
            stream.close()
        selector.close()

    return GitResult(
        process.returncode if process.returncode is not None else 1,
        bytes(buffers[stdout_fd]),
        bytes(buffers[stderr_fd]),
        timed_out,
        truncated,
    )


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _path_text(data: bytes) -> str:
    """Decode a Git path without losing bytes that are not UTF-8."""

    return data.decode("utf-8", errors="surrogateescape")


def _path_sort_key(path: str) -> bytes:
    return os.fsencode(path)


def _markdown_path(path: str) -> str:
    """Make arbitrary Git path bytes printable without raising on stdout."""

    return (
        path.encode("utf-8", errors="backslashreplace")
        .decode("ascii")
        .replace("`", "\\`")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _stage(stage: str, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except CompareError as exc:
        if exc.stage is None:
            exc.stage = stage
        raise


def _require_ok(result: GitResult, action: str) -> bytes:
    if result.timed_out:
        raise CompareError("git_timeout", f"Git {action} exceeded the timeout")
    if result.truncated:
        raise CompareError("bounded_output", f"Git {action} exceeded the output bound")
    if result.returncode != 0:
        detail = _text(result.stderr).strip()[:500]
        suffix = f": {detail}" if detail else ""
        raise CompareError("git_data", f"Git {action} failed{suffix}")
    return result.stdout


def _git(
    repo: Path,
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    budget: ComparisonBudget | None = None,
) -> bytes:
    if budget is not None:
        timeout = min(timeout, budget.remaining())
    return _require_ok(_run_git_bounded(repo, args, timeout=timeout), " ".join(args))


def _canonical_identity(url: str) -> str | None:
    value = url.strip()
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "ssh", "git"}:
            return None
        if (parsed.hostname or "").lower() != "github.com":
            return None
        path = parsed.path.lstrip("/")
    path = path.removesuffix("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return f"github.com/{parts[0].lower()}/{parts[1].lower()}"


def _verify_worktree(repo: Path, *, budget: ComparisonBudget | None = None) -> str:
    inside = _text(
        _git(repo, ["rev-parse", "--is-inside-work-tree"], budget=budget)
    ).strip()
    if inside != "true":
        raise CompareError("worktree", "the supplied repository is not a Git worktree")
    top = Path(
        _text(_git(repo, ["rev-parse", "--show-toplevel"], budget=budget)).strip()
    ).resolve()
    if not top.is_dir():
        raise CompareError(
            "worktree", "Git reported a worktree that is not a directory"
        )
    status = _git(
        repo,
        [
            "--no-optional-locks",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        budget=budget,
    )
    if status:
        detail = _text(status).splitlines()[0][:200]
        raise CompareError("dirty_worktree", f"worktree is dirty ({detail})")
    return _text(_git(repo, ["rev-parse", "HEAD"], budget=budget)).strip()


def _verify_remotes(
    repo: Path, *, budget: ComparisonBudget | None = None
) -> dict[str, object]:
    names = sorted(
        filter(None, _text(_git(repo, ["remote"], budget=budget)).splitlines())
    )
    records: list[dict[str, str]] = []
    by_role: dict[str, set[str]] = {"official_upstream": set(), "fork": set()}
    for name in names:
        urls = _text(
            _git(repo, ["remote", "get-url", "--all", name], budget=budget)
        ).splitlines()
        for url in urls:
            identity = _canonical_identity(url)
            if identity == OFFICIAL_IDENTITY:
                role = "official_upstream"
            elif identity == FORK_IDENTITY:
                role = "fork"
            else:
                continue
            records.append({"name": name, "role": role, "identity": identity})
            by_role[role].add(name)
    if not by_role["official_upstream"] or not by_role["fork"]:
        raise CompareError(
            "remote_identity",
            "could not verify both canonical remotes: "
            f"official={bool(by_role['official_upstream'])}, fork={bool(by_role['fork'])}",
        )
    if by_role["official_upstream"] & by_role["fork"]:
        raise CompareError(
            "remote_identity", "one remote name resolves to both required identities"
        )
    records.sort(key=lambda record: (record["role"], record["name"]))
    return {
        "verified": True,
        "official_upstream": records_for(records, "official_upstream"),
        "fork": records_for(records, "fork"),
    }


def records_for(records: list[dict[str, str]], role: str) -> list[dict[str, str]]:
    return [record for record in records if record["role"] == role]


def _resolve_ref(
    repo: Path,
    label: str,
    value: str,
    *,
    budget: ComparisonBudget | None = None,
) -> dict[str, str]:
    if not value.strip():
        raise CompareError("ref", f"{label} ref is empty")
    try:
        resolved = _git(
            repo,
            [
                "rev-parse",
                "--verify",
                "--quiet",
                "--end-of-options",
                f"{value}^{{commit}}",
            ],
            budget=budget,
        )
    except CompareError as exc:
        if exc.code != "git_data":
            raise
        raise CompareError("ref", f"{label} did not resolve to a commit") from exc
    commit = _text(resolved).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CompareError("ref", f"{label} did not resolve to a commit")
    metadata = _git(
        repo,
        ["show", "-s", "--format=%H%x00%h%x00%cs%x00%s", commit],
        budget=budget,
    )
    fields = _text(metadata).rstrip("\n").split("\x00", 3)
    if len(fields) != 4:
        raise CompareError("ref", f"could not read metadata for {label}")
    described = _text(
        _git(repo, ["describe", "--tags", "--always", commit], budget=budget)
    ).strip()
    return {
        "input": value,
        "commit": fields[0],
        "short": fields[1],
        "date": fields[2],
        "subject": fields[3],
        "version": described,
    }


def _is_ancestor(
    repo: Path,
    older: str,
    newer: str,
    *,
    budget: ComparisonBudget | None = None,
) -> bool:
    timeout = budget.remaining() if budget is not None else DEFAULT_TIMEOUT
    result = _run_git_bounded(
        repo, ["merge-base", "--is-ancestor", older, newer], timeout=timeout
    )
    if result.timed_out or result.truncated:
        raise CompareError("git_data", "could not verify ref ancestry")
    if result.returncode not in (0, 1):
        _require_ok(result, "merge-base --is-ancestor")
    return result.returncode == 0


def _parse_name_status(raw: bytes) -> list[dict[str, object]]:
    if not raw:
        return []
    if not raw.endswith(b"\x00"):
        raise CompareError("git_data", "Git returned unterminated name-status output")
    fields = raw[:-1].split(b"\x00")
    entries: list[dict[str, object]] = []
    index = 0
    while index < len(fields):
        if not fields[index]:
            raise CompareError("git_data", "Git returned an empty change status")
        try:
            status = fields[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise CompareError(
                "git_data", "Git returned a non-ASCII change status"
            ) from exc
        index += 1
        if index >= len(fields):
            raise CompareError("git_data", "Git returned malformed name-status output")
        if not fields[index]:
            raise CompareError("git_data", "Git returned an empty changed path")
        paths = [_path_text(fields[index])]
        index += 1
        if status[:1] in {"R", "C"}:
            if index >= len(fields):
                raise CompareError("git_data", "Git returned malformed rename output")
            if not fields[index]:
                raise CompareError("git_data", "Git returned an empty rename path")
            paths.append(_path_text(fields[index]))
            index += 1
        entries.append({"status": status, "paths": paths})
    return entries


def _shortstat(raw: bytes) -> dict[str, int]:
    line = _text(raw).strip()

    def number(pattern: str) -> int:
        match = re.search(pattern, line)
        return int(match.group(1)) if match else 0

    return {
        "files_changed": number(r"(\d+) file(?:s)? changed"),
        "insertions": number(r"(\d+) insertion(?:s)?\(\+\)"),
        "deletions": number(r"(\d+) deletion(?:s)?\(-\)"),
    }


def _change_summary(
    repo: Path,
    older: str,
    newer: str,
    *,
    budget: ComparisonBudget | None = None,
) -> dict[str, object]:
    entries = _parse_name_status(
        _git(
            repo,
            ["diff", "--name-status", "-z", "--find-renames=50%", older, newer],
            budget=budget,
        )
    )
    stats = _shortstat(_git(repo, ["diff", "--shortstat", older, newer], budget=budget))
    paths = sorted(
        {path for entry in entries for path in entry["paths"]}, key=_path_sort_key
    )
    stats["files_changed"] = len(entries)
    return {
        "counts": stats,
        "changed_paths": paths,
        "changes": sorted(
            entries,
            key=lambda item: tuple(_path_sort_key(path) for path in item["paths"]),
        ),
    }


def _overview_change_summary(
    repo: Path,
    older: str,
    newer: str,
    *,
    budget: ComparisonBudget | None = None,
) -> dict[str, object]:
    """Collect bounded structural change data without reading patch content."""

    entries = _parse_name_status(
        _git(
            repo,
            [
                "diff",
                "--name-status",
                "-z",
                "--find-renames=50%",
                "--no-ext-diff",
                "--no-textconv",
                older,
                newer,
            ],
            budget=budget,
        )
    )
    stats = _shortstat(
        _git(
            repo,
            ["diff", "--shortstat", "--no-ext-diff", "--no-textconv", older, newer],
            budget=budget,
        )
    )
    count_raw = _git(
        repo,
        ["rev-list", "--count", "--no-merges", f"{older}..{newer}"],
        budget=budget,
    )
    count_text = _text(count_raw).strip()
    if not re.fullmatch(r"\d+", count_text):
        raise CompareError("git_data", "Git returned an invalid non-merge commit count")
    paths = sorted(
        {path for entry in entries for path in entry["paths"]}, key=_path_sort_key
    )
    stats["files_changed"] = len(entries)
    stats["non_merge_commits"] = int(count_text)
    return {
        "counts": stats,
        "total_paths": len(paths),
        "changed_paths": paths,
        "changes": sorted(
            entries,
            key=lambda item: tuple(_path_sort_key(path) for path in item["paths"]),
        ),
    }


def _patch_id(
    repo: Path,
    patch: bytes,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    budget: ComparisonBudget | None = None,
) -> str | None:
    if not patch.strip():
        return None
    if budget is not None:
        timeout = min(timeout, budget.remaining())
    result = _run_git_bounded(
        repo,
        ["patch-id", "--stable"],
        timeout=timeout,
        input_data=patch,
    )
    if result.timed_out:
        raise CompareError("git_timeout", "Git patch-id exceeded the timeout")
    if result.truncated:
        raise CompareError("bounded_output", "Git patch-id exceeded the output bound")
    if result.returncode != 0:
        detail = _text(result.stderr).strip()[:500]
        raise CompareError("git_data", f"Git patch-id failed: {detail}")
    match = re.match(r"([0-9a-f]{40})\s", _text(result.stdout))
    return match.group(1) if match else None


def _aggregate_patch_id(
    repo: Path,
    older: str,
    newer: str,
    *,
    budget: ComparisonBudget | None = None,
) -> str | None:
    patch = _git(
        repo, ["diff", "--binary", "--no-ext-diff", older, newer], budget=budget
    )
    return _patch_id(repo, patch, budget=budget)


def _commit_patch_ids(
    repo: Path,
    older: str,
    newer: str,
    *,
    budget: ComparisonBudget | None = None,
) -> dict[str, str]:
    if budget is not None:
        budget.remaining()
    commits = _text(
        _git(
            repo,
            [
                "rev-list",
                "--no-merges",
                "--reverse",
                f"--max-count={MAX_COMMIT_COUNT + 1}",
                f"{older}..{newer}",
            ],
            budget=budget,
        )
    ).splitlines()
    if len(commits) > MAX_COMMIT_COUNT:
        raise CompareError(
            "commit_bound",
            f"commit history exceeded the {MAX_COMMIT_COUNT}-commit comparison bound",
        )
    patch_ids: dict[str, str] = {}
    for commit in commits:
        if budget is not None:
            budget.remaining()
        patch = _git(
            repo,
            ["show", "--format=", "--patch", "--binary", "--no-ext-diff", commit],
            budget=budget,
        )
        patch_id = _patch_id(repo, patch, budget=budget)
        if patch_id is not None:
            patch_ids[commit] = patch_id
    return patch_ids


def _risk_hints(paths: list[str]) -> dict[str, list[str]]:
    patterns = {
        "agent_execution": (
            "agent/",
            "run_agent.py",
            "gateway/",
            "tui_gateway/",
            "ui-tui/",
        ),
        "tool_use": ("tools/", "model_tools.py", "toolsets.py"),
        "memory": ("memory", "hermes_state", "plugins/memory/"),
        "tests": ("tests/",),
        "ci": (".github/", "scripts/ci/", "AGENTS.md"),
        "security": ("security", "auth", "credential", "verify", "SECURITY.md"),
        "dependencies": (
            "pyproject.toml",
            "uv.lock",
            "requirements",
            "package.json",
            "Dockerfile",
        ),
    }
    hints: dict[str, list[str]] = {}
    for category, needles in patterns.items():
        matched = sorted(
            {
                path
                for path in paths
                if any(needle.lower() in path.lower() for needle in needles)
            }
        )
        if matched:
            hints[category] = matched
    return hints


def _bounded_items(
    items: list[object], limit: int = MAX_REPORT_ITEMS
) -> tuple[list[object], bool]:
    return items[:limit], len(items) > limit


def _bound_change_summary(
    summary: dict[str, object], side: str, warnings: list[str]
) -> None:
    for field in ("changed_paths", "changes"):
        items = summary[field]
        assert isinstance(items, list)
        visible, truncated = _bounded_items(items)
        summary[field] = visible
        if truncated:
            summary[f"{field}_total"] = len(items)
            summary[f"{field}_truncated"] = True
            warnings.append(
                f"{side} {field} truncated to {MAX_REPORT_ITEMS} items in the report."
            )


def _equivalent_patch_pairs(
    upstream_commits: dict[str, str], fork_commits: dict[str, str]
) -> tuple[list[dict[str, str]], int, bool]:
    upstream_by_patch: dict[str, list[str]] = {}
    fork_by_patch: dict[str, list[str]] = {}
    for commit, patch_id in upstream_commits.items():
        upstream_by_patch.setdefault(patch_id, []).append(commit)
    for commit, patch_id in fork_commits.items():
        fork_by_patch.setdefault(patch_id, []).append(commit)

    pairs: list[dict[str, str]] = []
    total = 0
    for patch_id in sorted(upstream_by_patch.keys() & fork_by_patch.keys()):
        upstream_matches = sorted(upstream_by_patch[patch_id])
        fork_matches = sorted(fork_by_patch[patch_id])
        total += len(upstream_matches) * len(fork_matches)
        if len(pairs) >= MAX_EQUIVALENT_PATCH_PAIRS:
            continue
        for upstream_commit in upstream_matches:
            for fork_commit in fork_matches:
                pairs.append(
                    {
                        "upstream_commit": upstream_commit,
                        "fork_commit": fork_commit,
                        "patch_id": patch_id,
                    }
                )
                if len(pairs) == MAX_EQUIVALENT_PATCH_PAIRS:
                    break
            if len(pairs) == MAX_EQUIVALENT_PATCH_PAIRS:
                break
    return pairs, total, total > MAX_EQUIVALENT_PATCH_PAIRS


def _overview_report(
    repo: Path,
    worktree_head: str,
    remotes: dict[str, object],
    base: dict[str, str],
    target: dict[str, str],
    fork_ref: dict[str, str],
    *,
    budget: ComparisonBudget,
) -> dict[str, object]:
    upstream_changes = _stage(
        "overview-upstream-diff",
        lambda: _overview_change_summary(
            repo, base["commit"], target["commit"], budget=budget
        ),
    )
    fork_changes = _stage(
        "overview-fork-diff",
        lambda: _overview_change_summary(
            repo, base["commit"], fork_ref["commit"], budget=budget
        ),
    )
    upstream_paths = set(upstream_changes["changed_paths"])
    fork_paths = set(fork_changes["changed_paths"])
    overlap = sorted(upstream_paths & fork_paths, key=_path_sort_key)
    all_paths = sorted(upstream_paths | fork_paths, key=_path_sort_key)
    warnings: list[str] = []
    _bound_change_summary(upstream_changes, "upstream", warnings)
    _bound_change_summary(fork_changes, "fork", warnings)
    overlap_visible, overlap_truncated = _bounded_items(overlap)
    if overlap_truncated:
        warnings.append(
            f"path_overlap truncated to {MAX_REPORT_ITEMS} items in the report."
        )
    risk_hints = _risk_hints(all_paths)
    for category, paths in risk_hints.items():
        visible, truncated = _bounded_items(paths)
        risk_hints[category] = visible
        if truncated:
            warnings.append(
                f"risk hint {category} truncated to {MAX_REPORT_ITEMS} items in the report."
            )
    warnings.append(
        "Overview is static path-overlap triage only; compatibility and adoption safety are not established."
    )
    if not overlap:
        warnings.append(
            "No path overlap was observed; that is not evidence of compatibility or safety."
        )
    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "mode": "overview",
        "status": "ok",
        "repository": str(repo),
        "worktree_head": worktree_head,
        "remotes": remotes,
        "refs": {"upstream_base": base, "upstream_target": target, "fork": fork_ref},
        "comparison": {
            "classification": "possible-overlap-by-path" if overlap else "no-overlap",
            "confidence_status": "static-overlap-only",
            "compatibility_status": "not-established",
            "review_required": True,
            "patch_equivalence": "not-evaluated",
            "merge_conflict_status": "not-tested",
            "path_overlap": overlap_visible,
            "path_overlap_total": len(overlap),
            "path_overlap_truncated": overlap_truncated,
            "upstream": upstream_changes,
            "fork": fork_changes,
        },
        "risk_hints": risk_hints,
        "warnings": sorted(set(warnings)),
    }


def compare(
    repo: Path,
    upstream_base: str,
    upstream_target: str,
    fork: str,
    *,
    mode: str = "full",
) -> dict[str, object]:
    if mode not in {"full", "overview"}:
        raise CompareError("mode", f"unsupported comparison mode: {mode}")
    budget = ComparisonBudget.start()
    worktree_head = _stage(
        "verify-worktree", lambda: _verify_worktree(repo, budget=budget)
    )
    remotes = _stage("verify-remotes", lambda: _verify_remotes(repo, budget=budget))
    base = _stage(
        "resolve-upstream-base",
        lambda: _resolve_ref(repo, "upstream-base", upstream_base, budget=budget),
    )
    target = _stage(
        "resolve-upstream-target",
        lambda: _resolve_ref(repo, "upstream-target", upstream_target, budget=budget),
    )
    fork_ref = _stage(
        "resolve-fork", lambda: _resolve_ref(repo, "fork", fork, budget=budget)
    )
    if not _stage(
        "verify-upstream-target-ancestry",
        lambda: _is_ancestor(repo, base["commit"], target["commit"], budget=budget),
    ):
        raise CompareError(
            "ref_relationship",
            "upstream-base is not an ancestor of upstream-target",
            stage="verify-upstream-target-ancestry",
        )
    if not _stage(
        "verify-fork-ancestry",
        lambda: _is_ancestor(repo, base["commit"], fork_ref["commit"], budget=budget),
    ):
        raise CompareError(
            "ref_relationship",
            "upstream-base is not an ancestor of fork",
            stage="verify-fork-ancestry",
        )

    if mode == "overview":
        return _overview_report(
            repo,
            worktree_head,
            remotes,
            base,
            target,
            fork_ref,
            budget=budget,
        )

    upstream_changes = _stage(
        "full-upstream-diff",
        lambda: _change_summary(repo, base["commit"], target["commit"], budget=budget),
    )
    fork_changes = _stage(
        "full-fork-diff",
        lambda: _change_summary(
            repo, base["commit"], fork_ref["commit"], budget=budget
        ),
    )
    upstream_patch = _stage(
        "full-upstream-patch-id",
        lambda: _aggregate_patch_id(
            repo, base["commit"], target["commit"], budget=budget
        ),
    )
    fork_patch = _stage(
        "full-fork-patch-id",
        lambda: _aggregate_patch_id(
            repo, base["commit"], fork_ref["commit"], budget=budget
        ),
    )
    upstream_commits = _stage(
        "full-upstream-commit-patch-ids",
        lambda: _commit_patch_ids(
            repo, base["commit"], target["commit"], budget=budget
        ),
    )
    fork_commits = _stage(
        "full-fork-commit-patch-ids",
        lambda: _commit_patch_ids(
            repo, base["commit"], fork_ref["commit"], budget=budget
        ),
    )
    upstream_paths = set(upstream_changes["changed_paths"])
    fork_paths = set(fork_changes["changed_paths"])
    overlap = sorted(upstream_paths & fork_paths)
    equivalent_pairs, equivalent_pair_total, equivalent_pairs_truncated = (
        _equivalent_patch_pairs(upstream_commits, fork_commits)
    )
    warnings: list[str] = []
    patch_id_unknown = (bool(upstream_paths) and upstream_patch is None) or (
        bool(fork_paths) and fork_patch is None
    )
    if not upstream_paths and not fork_paths:
        classification = "no-overlap"
        confidence = "high"
    elif upstream_patch is not None and upstream_patch == fork_patch:
        classification = "exact-equivalent"
        confidence = "patch-only"
    elif patch_id_unknown and overlap:
        classification = "unknown/non-equivalent"
        confidence = "low"
        warnings.append(
            "Git could not produce a patch ID for an overlapping side; equivalence is unknown."
        )
    elif overlap:
        classification = "possible-overlap-by-path"
        confidence = "medium" if upstream_patch and fork_patch else "low"
    else:
        classification = "no-overlap"
        confidence = "medium" if patch_id_unknown else "high"
        if patch_id_unknown:
            warnings.append(
                "Git could not produce a patch ID for one disjoint side; path overlap is known absent, but patch equivalence is unknown."
            )

    all_paths = sorted(upstream_paths | fork_paths)
    _bound_change_summary(upstream_changes, "upstream", warnings)
    _bound_change_summary(fork_changes, "fork", warnings)
    overlap_visible, overlap_truncated = _bounded_items(overlap)
    if overlap_truncated:
        warnings.append(
            f"path_overlap truncated to {MAX_REPORT_ITEMS} items in the report."
        )
    risk_hints = _risk_hints(all_paths)
    for category, paths in risk_hints.items():
        visible, truncated = _bounded_items(paths)
        risk_hints[category] = visible
        if truncated:
            warnings.append(
                f"risk hint {category} truncated to {MAX_REPORT_ITEMS} items in the report."
            )
    if equivalent_pairs_truncated:
        warnings.append(
            "Equivalent patch-pair evidence was deterministically truncated; "
            "classification remains patch-only evidence and does not establish compatibility."
        )
    warnings.append(
        "Risk categories are review hints only; this report does not establish compatibility or adoption safety."
    )
    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "mode": "full",
        "status": "ok",
        "repository": str(repo),
        "worktree_head": worktree_head,
        "remotes": remotes,
        "refs": {"upstream_base": base, "upstream_target": target, "fork": fork_ref},
        "comparison": {
            "classification": classification,
            "confidence_status": confidence,
            "compatibility_status": "not-established",
            "review_required": True,
            "equivalent_patch_pairs": equivalent_pairs,
            "equivalent_patch_pair_total": equivalent_pair_total,
            "equivalent_patch_pairs_truncated": equivalent_pairs_truncated,
            "aggregate_patch_ids": {"upstream": upstream_patch, "fork": fork_patch},
            "path_overlap": overlap_visible,
            "path_overlap_total": len(overlap),
            "path_overlap_truncated": overlap_truncated,
            "upstream": upstream_changes,
            "fork": fork_changes,
        },
        "risk_hints": risk_hints,
        "warnings": sorted(set(warnings)),
    }


def _markdown(report: dict[str, object]) -> str:
    if report.get("status") != "ok":
        error = report["error"]
        mode = report.get("mode", "full")
        return (
            "# Fermes upstream comparison\n\n"
            f"**Schema version:** `{report['schema_version']}`  \n"
            f"**Mode:** `{mode}`  \n"
            "**Status:** ERROR  \n"
            f"**Stage:** `{error.get('stage', 'unknown')}`  \n"
            f"**Code:** `{error['code']}`  \n"
            f"**Message:** {error['message']}\n"
        )
    refs = report["refs"]
    comparison = report["comparison"]
    mode = report["mode"]
    confidence_detail = (
        "static path-overlap triage only"
        if mode == "overview"
        else (
            "patch-only; not deploy safety"
            if comparison["classification"] == "exact-equivalent"
            else "review confidence only"
        )
    )
    lines = [
        "# Fermes upstream comparison",
        "",
        f"**Schema version:** `{report['schema_version']}`  ",
        f"**Mode:** `{mode}`  ",
        "**Status:** OK  ",
        f"**Repository:** `{report['repository']}`  ",
        f"**Classification:** `{comparison['classification']}`  ",
        f"**Confidence:** `{comparison['confidence_status']}` ({confidence_detail})  ",
        "**Review required:** YES  ",
        "**Compatibility/adoption:** not established",
        f"**Patch equivalence:** {comparison.get('patch_equivalence', 'evaluated in full mode')}  ",
        f"**Merge conflicts:** {comparison.get('merge_conflict_status', 'not reported in full mode')}",
        "",
        "## Canonical repository identities",
        "",
        f"- **Official upstream:** `{OFFICIAL_IDENTITY}`",
        f"- **Maintained fork:** `{FORK_IDENTITY}`",
        "",
        "## Refs",
        "",
        "| Role | Input | Commit | Version |",
        "| --- | --- | --- | --- |",
    ]
    for role in ("upstream_base", "upstream_target", "fork"):
        ref = refs[role]
        lines.append(
            f"| {role} | `{ref['input']}` | `{ref['commit']}` | `{ref['version']}` |"
        )
    if mode == "overview":
        lines += [
            "",
            "## Changed paths",
            "",
            "| Side | Files | Paths | Non-merge commits | Insertions | Deletions |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    else:
        lines += [
            "",
            "## Changed paths",
            "",
            "| Side | Files | Insertions | Deletions |",
            "| --- | ---: | ---: | ---: |",
        ]
    for side in ("upstream", "fork"):
        counts = comparison[side]["counts"]
        if mode == "overview":
            lines.append(
                f"| {side} | {counts['files_changed']} | "
                f"{comparison[side]['total_paths']} | {counts['non_merge_commits']} | "
                f"{counts['insertions']} | {counts['deletions']} |"
            )
        else:
            lines.append(
                f"| {side} | {counts['files_changed']} | {counts['insertions']} | {counts['deletions']} |"
            )
    lines += ["", "### Path lists", ""]
    for side in ("upstream", "fork"):
        paths = comparison[side]["changed_paths"]
        lines.append(
            f"- **{side}:** "
            f"{', '.join(f'`{_markdown_path(path)}`' for path in paths) if paths else '(none)'}"
        )
    if mode == "overview":
        lines += ["", "### Change samples", ""]
        for side in ("upstream", "fork"):
            changes = comparison[side]["changes"]
            for change in changes:
                paths = " → ".join(
                    f"`{_markdown_path(path)}`" for path in change["paths"]
                )
                lines.append(f"- **{side} {change['status']}:** {paths}")
    lines += [
        f"- **Overlap:** {', '.join(f'`{_markdown_path(path)}`' for path in comparison['path_overlap']) if comparison['path_overlap'] else '(none)'}",
        "",
        "## Risk review hints",
        "",
    ]
    hints = report["risk_hints"]
    lines.extend(
        f"- **{category}:** {', '.join(f'`{_markdown_path(path)}`' for path in paths)}"
        for category, paths in hints.items()
    )
    if not hints:
        lines.append("- None detected by the configured path hints.")
    lines += ["", "## Warnings", ""]
    lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def _render_report(report: dict[str, object], output_format: str) -> str:
    if output_format == "json":
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    else:
        rendered = _markdown(report)
    if len(rendered.encode("utf-8")) > MAX_REPORT_BYTES:
        raise CompareError(
            "report_output",
            f"rendered report exceeded the {MAX_REPORT_BYTES}-byte output bound",
        )
    return rendered


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", required=True, help="explicit local Git worktree to inspect"
    )
    parser.add_argument(
        "--upstream-base",
        required=True,
        help="verified local upstream baseline SHA or ref",
    )
    parser.add_argument(
        "--upstream-target",
        required=True,
        help="verified local upstream target SHA or ref",
    )
    parser.add_argument(
        "--fork", required=True, help="verified local maintained-fork SHA or ref"
    )
    parser.add_argument(
        "--mode",
        choices=("full", "overview"),
        default="full",
        help="full patch-equivalence comparison or bounded structural overview",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    try:
        if not repo.exists() or not repo.is_dir():
            raise CompareError(
                "repository", f"repository directory does not exist: {repo}"
            )
        report = compare(
            repo,
            args.upstream_base,
            args.upstream_target,
            args.fork,
            mode=args.mode,
        )
        exit_code = 0
    except CompareError as exc:
        report = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "mode": args.mode,
            "status": "error",
            "repository": str(repo),
            "error": {
                "code": exc.code,
                "message": str(exc),
                "stage": exc.stage or "initialization",
            },
            "review_required": True,
        }
        exit_code = 2
    try:
        rendered = _render_report(report, args.format)
    except CompareError as exc:
        report = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "mode": args.mode,
            "status": "error",
            "repository": str(repo),
            "error": {
                "code": exc.code,
                "message": str(exc),
                "stage": exc.stage or "render-report",
            },
            "review_required": True,
        }
        exit_code = 2
        rendered = _render_report(report, args.format)
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
