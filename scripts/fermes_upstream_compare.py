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
from urllib.parse import urlparse


TOOL_NAME = "fermes-upstream-compare"
SCHEMA_VERSION = 1
DEFAULT_TIMEOUT = 10.0
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
OFFICIAL_IDENTITY = "github.com/nousresearch/hermes-agent"
FORK_IDENTITY = "github.com/fredheathcote007/hermes-agent"


class CompareError(RuntimeError):
    """A fail-closed comparison error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    truncated: bool = False


def _run_git_bounded(
    repo: Path,
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_output: int = MAX_OUTPUT_BYTES,
) -> GitResult:
    """Run Git while retaining bounded stdout/stderr buffers."""

    argv = ["git", "-C", str(repo), *args]
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
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
    captured = 0
    killed = False
    truncated = False
    timed_out = False
    started = time.monotonic()
    try:
        while streams:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                timed_out = True
                if not killed:
                    process.kill()
                    killed = True
            for key, _ in selector.select(min(0.1, max(0.0, remaining))):
                stream = key.fileobj
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
                        process.kill()
                        killed = True
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
        raise CompareError(
            "git_execution", f"Git process could not be collected: {exc}"
        ) from exc
    finally:
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


def _git(repo: Path, args: list[str], *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
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


def _verify_worktree(repo: Path) -> str:
    inside = _text(_git(repo, ["rev-parse", "--is-inside-work-tree"])).strip()
    if inside != "true":
        raise CompareError("worktree", "the supplied repository is not a Git worktree")
    top = Path(_text(_git(repo, ["rev-parse", "--show-toplevel"])).strip()).resolve()
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
    )
    if status:
        detail = _text(status).splitlines()[0][:200]
        raise CompareError("dirty_worktree", f"worktree is dirty ({detail})")
    return _text(_git(repo, ["rev-parse", "HEAD"])).strip()


def _verify_remotes(repo: Path) -> dict[str, object]:
    names = sorted(filter(None, _text(_git(repo, ["remote"])).splitlines()))
    records: list[dict[str, str]] = []
    by_role: dict[str, set[str]] = {"official_upstream": set(), "fork": set()}
    for name in names:
        urls = _text(_git(repo, ["remote", "get-url", "--all", name])).splitlines()
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


def _resolve_ref(repo: Path, label: str, value: str) -> dict[str, str]:
    if not value.strip():
        raise CompareError("ref", f"{label} ref is empty")
    resolved = _git(
        repo,
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{value}^{{commit}}"],
    )
    commit = _text(resolved).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CompareError("ref", f"{label} did not resolve to a commit")
    metadata = _git(repo, ["show", "-s", "--format=%H%x00%h%x00%cs%x00%s", commit])
    fields = _text(metadata).rstrip("\n").split("\x00", 3)
    if len(fields) != 4:
        raise CompareError("ref", f"could not read metadata for {label}")
    described = _text(_git(repo, ["describe", "--tags", "--always", commit])).strip()
    return {
        "input": value,
        "commit": fields[0],
        "short": fields[1],
        "date": fields[2],
        "subject": fields[3],
        "version": described,
    }


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    result = _run_git_bounded(repo, ["merge-base", "--is-ancestor", older, newer])
    if result.timed_out or result.truncated:
        raise CompareError("git_data", "could not verify ref ancestry")
    if result.returncode not in (0, 1):
        _require_ok(result, "merge-base --is-ancestor")
    return result.returncode == 0


def _parse_name_status(raw: bytes) -> list[dict[str, object]]:
    fields = _text(raw).split("\x00")
    entries: list[dict[str, object]] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        index += 1
        if index >= len(fields):
            raise CompareError("git_data", "Git returned malformed name-status output")
        paths = [fields[index]]
        index += 1
        if status[:1] in {"R", "C"}:
            if index >= len(fields):
                raise CompareError("git_data", "Git returned malformed rename output")
            paths.append(fields[index])
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


def _change_summary(repo: Path, older: str, newer: str) -> dict[str, object]:
    entries = _parse_name_status(
        _git(repo, ["diff", "--name-status", "-z", "--find-renames=50%", older, newer])
    )
    stats = _shortstat(_git(repo, ["diff", "--shortstat", older, newer]))
    paths = sorted({path for entry in entries for path in entry["paths"]})
    stats["files_changed"] = len(entries)
    return {
        "counts": stats,
        "changed_paths": paths,
        "changes": sorted(entries, key=lambda item: tuple(item["paths"])),
    }


def _patch_id(
    repo: Path, patch: bytes, *, timeout: float = DEFAULT_TIMEOUT
) -> str | None:
    if not patch.strip():
        return None
    try:
        process = subprocess.Popen(
            ["git", "-C", str(repo), "patch-id", "--stable"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(input=patch, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CompareError("git_timeout", "Git patch-id exceeded the timeout") from exc
    if len(stdout) + len(stderr) > MAX_OUTPUT_BYTES:
        raise CompareError("bounded_output", "Git patch-id exceeded the output bound")
    if process.returncode != 0:
        detail = _text(stderr).strip()[:500]
        raise CompareError("git_data", f"Git patch-id failed: {detail}")
    match = re.match(r"([0-9a-f]{40})\s", _text(stdout))
    return match.group(1) if match else None


def _aggregate_patch_id(repo: Path, older: str, newer: str) -> str | None:
    patch = _git(repo, ["diff", "--binary", "--no-ext-diff", older, newer])
    return _patch_id(repo, patch)


def _commit_patch_ids(repo: Path, older: str, newer: str) -> dict[str, str]:
    commits = _text(
        _git(
            repo,
            [
                "rev-list",
                "--no-merges",
                "--reverse",
                "--max-count=10001",
                f"{older}..{newer}",
            ],
        )
    ).splitlines()
    if len(commits) > 10000:
        raise CompareError(
            "bounded_output", "commit history exceeded the comparison bound"
        )
    patch_ids: dict[str, str] = {}
    for commit in commits:
        patch = _git(
            repo, ["show", "--format=", "--patch", "--binary", "--no-ext-diff", commit]
        )
        patch_id = _patch_id(repo, patch)
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


def compare(
    repo: Path, upstream_base: str, upstream_target: str, fork: str
) -> dict[str, object]:
    worktree_head = _verify_worktree(repo)
    remotes = _verify_remotes(repo)
    base = _resolve_ref(repo, "upstream-base", upstream_base)
    target = _resolve_ref(repo, "upstream-target", upstream_target)
    fork_ref = _resolve_ref(repo, "fork", fork)
    if not _is_ancestor(repo, base["commit"], target["commit"]):
        raise CompareError(
            "ref_relationship", "upstream-base is not an ancestor of upstream-target"
        )
    if not _is_ancestor(repo, base["commit"], fork_ref["commit"]):
        raise CompareError(
            "ref_relationship", "upstream-base is not an ancestor of fork"
        )

    upstream_changes = _change_summary(repo, base["commit"], target["commit"])
    fork_changes = _change_summary(repo, base["commit"], fork_ref["commit"])
    upstream_patch = _aggregate_patch_id(repo, base["commit"], target["commit"])
    fork_patch = _aggregate_patch_id(repo, base["commit"], fork_ref["commit"])
    upstream_commits = _commit_patch_ids(repo, base["commit"], target["commit"])
    fork_commits = _commit_patch_ids(repo, base["commit"], fork_ref["commit"])
    upstream_paths = set(upstream_changes["changed_paths"])
    fork_paths = set(fork_changes["changed_paths"])
    overlap = sorted(upstream_paths & fork_paths)
    equivalent_pairs = sorted(
        [
            {
                "upstream_commit": upstream_commit,
                "fork_commit": fork_commit,
                "patch_id": patch_id,
            }
            for upstream_commit, patch_id in upstream_commits.items()
            for fork_commit, fork_patch_id in fork_commits.items()
            if patch_id == fork_patch_id
        ],
        key=lambda pair: (pair["upstream_commit"], pair["fork_commit"]),
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
        confidence = "high"
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
    warnings.append(
        "Risk categories are review hints only; this report does not establish compatibility or adoption safety."
    )
    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
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
            "aggregate_patch_ids": {"upstream": upstream_patch, "fork": fork_patch},
            "path_overlap": overlap,
            "upstream": upstream_changes,
            "fork": fork_changes,
        },
        "risk_hints": _risk_hints(all_paths),
        "warnings": sorted(set(warnings)),
    }


def _markdown(report: dict[str, object]) -> str:
    if report.get("status") != "ok":
        error = report["error"]
        return f"# Fermes upstream comparison\n\n**Status:** ERROR  \n**Code:** `{error['code']}`  \n**Message:** {error['message']}\n"
    refs = report["refs"]
    comparison = report["comparison"]
    lines = [
        "# Fermes upstream comparison",
        "",
        "**Status:** OK  ",
        f"**Repository:** `{report['repository']}`  ",
        f"**Classification:** `{comparison['classification']}`  ",
        f"**Confidence:** `{comparison['confidence_status']}`  ",
        "**Review required:** YES  ",
        "**Compatibility/adoption:** not established",
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
    lines += [
        "",
        "## Changed paths",
        "",
        "| Side | Files | Insertions | Deletions |",
        "| --- | ---: | ---: | ---: |",
    ]
    for side in ("upstream", "fork"):
        counts = comparison[side]["counts"]
        lines.append(
            f"| {side} | {counts['files_changed']} | {counts['insertions']} | {counts['deletions']} |"
        )
    lines += ["", "### Path lists", ""]
    for side in ("upstream", "fork"):
        paths = comparison[side]["changed_paths"]
        lines.append(
            f"- **{side}:** {', '.join(f'`{path}`' for path in paths) if paths else '(none)'}"
        )
    lines += [
        f"- **Overlap:** {', '.join(f'`{path}`' for path in comparison['path_overlap']) if comparison['path_overlap'] else '(none)'}",
        "",
        "## Risk review hints",
        "",
    ]
    hints = report["risk_hints"]
    lines.extend(
        f"- **{category}:** {', '.join(f'`{path}`' for path in paths)}"
        for category, paths in hints.items()
    )
    if not hints:
        lines.append("- None detected by the configured path hints.")
    lines += ["", "## Warnings", ""]
    lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


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
        report = compare(repo, args.upstream_base, args.upstream_target, args.fork)
        exit_code = 0
    except CompareError as exc:
        report = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "repository": str(repo),
            "error": {"code": exc.code, "message": str(exc)},
            "review_required": True,
        }
        exit_code = 2
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True) + "\n", end="")
    else:
        print(_markdown(report), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
