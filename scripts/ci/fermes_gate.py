#!/usr/bin/env python3
"""Trusted, fail-closed validation for the Fermes required PR check."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_MARKDOWN_SUFFIXES = {".md", ".mdx", ".markdown"}
_WORKFLOW_ROOTS = (".github/workflows/", ".github/actions/")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PINNED_ACTION = re.compile(r"^\s+uses:\s+([^\s]+)@([0-9a-f]{40})(?:\s+#.*)?$")


@dataclass(frozen=True)
class ChangedPath:
    status: str
    path: str
    old_path: str | None = None


def _git(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, check=False, capture_output=True)
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _path(raw: bytes) -> str:
    if b"\n" in raw or b"\r" in raw:
        raise ValueError("git reported a path containing a line break")
    return raw.decode("utf-8", "surrogateescape")


def parse_name_status(raw: bytes) -> list[ChangedPath]:
    """Parse NUL-delimited Git paths without decoding file contents."""
    fields = raw.split(b"\0")
    entries: list[ChangedPath] = []
    index = 0
    while index < len(fields) - 1:
        status = fields[index].decode("ascii")
        index += 1
        if not status:
            continue
        if status[0] in {"R", "C"}:
            if index + 1 >= len(fields):
                raise ValueError("incomplete rename/copy record from git")
            old_path, new_path = _path(fields[index]), _path(fields[index + 1])
            entries.append(ChangedPath(status[0], new_path, old_path))
            index += 2
        else:
            if index >= len(fields):
                raise ValueError("incomplete name-status record from git")
            entries.append(ChangedPath(status[0], _path(fields[index])))
            index += 1
    return entries


def is_workflow(path: str) -> bool:
    return path.startswith(_WORKFLOW_ROOTS) and Path(path).suffix in {".yml", ".yaml"}


def is_markdown(path: str) -> bool:
    return Path(path).suffix.lower() in _MARKDOWN_SUFFIXES


def source_change(paths: Iterable[str | ChangedPath]) -> bool:
    """Unknown and code categories require the substantive source lane."""
    names = (item.path if isinstance(item, ChangedPath) else item for item in paths)
    return any(not is_markdown(name) and name != ".github/workflows/fermes-pr-checks.yml" for name in names)


def _validate_markdown(data: bytes, name: str) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"selected Markdown metadata is not UTF-8: {name}"]
    fence_count = sum(line.lstrip().startswith(("```", "~~~")) for line in text.splitlines())
    problems = [f"unclosed fenced code block: {name}"] if fence_count % 2 else []
    # Exactly two end-of-line spaces are intentional Markdown hard breaks.
    for number, line in enumerate(text.splitlines(), start=1):
        trailing = len(line) - len(line.rstrip(" "))
        if trailing and trailing != 2:
            problems.append(f"invalid trailing whitespace in {name}:{number}")
    return problems


def _validate_workflow(data: bytes, name: str) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"selected workflow metadata is not UTF-8: {name}"]
    # Only this protected gate has the mandatory trusted-event contract.
    # Other workflow changes are source changes and require substantive CI;
    # they must not be judged against this gate's event requirements.
    if name != ".github/workflows/fermes-pr-checks.yml":
        return []
    lines = text.splitlines()
    problems: list[str] = []
    if "pull_request_target" not in text:
        problems.append("workflow must use pull_request_target")
    if "branches: [main]" not in text:
        problems.append("workflow must target main")
    required_types = {"opened", "reopened", "synchronize", "ready_for_review"}
    types_match = re.search(r"types:\s*\[([^]]+)\]", text)
    declared_types = set()
    if types_match:
        declared_types = {item.strip() for item in types_match.group(1).split(",")}
    if not required_types <= declared_types:
        problems.append("workflow must handle opened, reopened, synchronize, and ready_for_review")
    if "pull_request:" in text or "workflow_run:" in text:
        problems.append("workflow must not duplicate pull_request/workflow_run execution")
    if re.search(r"^\s*secrets\s*:", text, re.MULTILINE) or "GITHUB_TOKEN" in text:
        problems.append("workflow must not use secrets or expose a token")
    if any(word in text.lower() for word in ("blacksmith", "publish")):
        problems.append("workflow must not publish or use Blacksmith")
    if re.search(r"^\s*[A-Za-z_-]+:\s*write\s*$", text, re.MULTILINE):
        problems.append("workflow must not request write permissions")
    in_run, run_indent = False, -1
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s+run:\s*(?:\||>)?\s*$", line):
            in_run, run_indent = True, indent
        elif in_run and line.strip() and indent <= run_indent:
            in_run = False
        if in_run and "${{" in line:
            problems.append("run blocks must not interpolate GitHub expressions")
        if "uses:" in line:
            if line.strip().startswith("uses: ./"):
                problems.append("workflow must not invoke a repository-local action")
            elif _PINNED_ACTION.match(line) is None:
                problems.append(f"external action is not pinned: {line.strip()}")
    return problems


def validate_files(entries: Iterable[ChangedPath], root: Path) -> list[str]:
    """Validate existing text metadata; deleted/binary non-metadata is legitimate."""
    problems: list[str] = []
    for entry in entries:
        if entry.status == "D" or not (is_markdown(entry.path) or is_workflow(entry.path)):
            continue
        try:
            data = (root / entry.path).read_bytes()
        except FileNotFoundError:
            problems.append(f"changed metadata path is missing from merge checkout: {entry.path}")
            continue
        if b"\0" in data:
            problems.append(f"selected metadata contains NUL bytes: {entry.path}")
            continue
        if is_markdown(entry.path):
            problems.extend(_validate_markdown(data, entry.path))
        if is_workflow(entry.path):
            problems.extend(f"{entry.path}: {problem}" for problem in _validate_workflow(data, entry.path))
    return problems


def _require_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not _SHA.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty immutable commit SHA")
    return value


def inspect_environment() -> tuple[list[ChangedPath], str, Path]:
    base = Path(os.environ.get("BASE_DIR", ""))
    candidate = Path(os.environ.get("CANDIDATE_DIR", ""))
    if not base.is_dir() or not candidate.is_dir():
        raise ValueError("base and candidate checkouts are required")
    base_sha, head_sha = _require_sha("BASE_SHA"), _require_sha("PR_HEAD_SHA")
    parents = _git(candidate, "rev-list", "--parents", "-n", "1", "HEAD").decode().split()
    if len(parents) != 3 or parents[1] != base_sha or parents[2] != head_sha:
        raise ValueError("synthetic merge must have base SHA as parent 1 and exact PR head as parent 2")
    entries = parse_name_status(_git(candidate, "diff", "--name-status", "-z", base_sha, "HEAD"))
    result = subprocess.run(
        [
            "git", "diff", "--check", base_sha, "HEAD", "--", ".",
            ":(exclude,glob)**/*.md",
            ":(exclude,glob)**/*.mdx",
            ":(exclude,glob)**/*.markdown",
        ],
        cwd=candidate, capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError("git diff --check rejected the candidate diff")
    return entries, head_sha, candidate


def _write_outputs(values: dict[str, str]) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as output:
        for key, value in values.items():
            if not value or "\n" in value:
                raise ValueError(f"invalid empty or multiline output: {key}")
            output.write(f"{key}={value}\n")


def aggregate(needs: dict[str, object], source: str) -> list[str]:
    """Require inspect success and the exact expected source-test result."""
    if source not in {"true", "false"}:
        return ["inspect.source=missing-or-invalid"]
    inspect = needs.get("inspect")
    source_test = needs.get("source-test")
    failures: list[str] = []
    if not isinstance(inspect, dict) or inspect.get("result") != "success":
        failures.append(f"inspect={inspect.get('result', 'missing') if isinstance(inspect, dict) else 'missing'}")
    expected = "success" if source == "true" else "skipped"
    actual = source_test.get("result") if isinstance(source_test, dict) else None
    if actual != expected:
        failures.append(f"source-test={actual or 'missing'} (expected {expected})")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect")
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--json", required=True)
    aggregate_parser.add_argument("--source", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            entries, head_sha, candidate = inspect_environment()
            problems = validate_files(entries, candidate)
            if problems:
                for problem in problems:
                    print(f"::error::{problem}", file=sys.stderr)
                return 1
            source = str(source_change(entries)).lower()
            _write_outputs({"source": source, "head_sha": head_sha})
            print(f"checked PR head SHA: {head_sha}; source: {source}")
            return 0
        needs = json.loads(args.json)
        if not isinstance(needs, dict):
            raise ValueError("needs JSON must be an object")
        failures = aggregate(needs, args.source)
        if failures:
            print(f"::error::required validation did not succeed: {', '.join(failures)}")
            return 1
        print("all required validation succeeded")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
