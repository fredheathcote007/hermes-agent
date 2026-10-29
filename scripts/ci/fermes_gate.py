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
GATE_CRITICAL_FILES = (
    ".github/workflows/fermes-pr-checks.yml",
    ".github/workflows/fermes-source-tests.yml",
    "scripts/ci/fermes_gate.py",
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ChangedPath:
    status: str
    path: str
    old_path: str | None = None


def _git(root: Path, *args: str, check: bool = True) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=False, capture_output=True, timeout=_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"git {' '.join(args)} timed out") from exc
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
    return any(not is_markdown(name) for name in names)


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
    return problems


def validate_gate_integrity(base: Path, candidate: Path) -> list[str]:
    """Require every protected gate input to be byte-identical to trusted base."""
    problems: list[str] = []
    for name in GATE_CRITICAL_FILES:
        base_path, candidate_path = base / name, candidate / name
        if not base_path.is_file() or base_path.is_symlink():
            problems.append(f"trusted base is missing gate-critical file: {name}; owner bootstrap required")
            continue
        if not candidate_path.is_file() or candidate_path.is_symlink():
            problems.append(f"candidate removed or replaced gate-critical file: {name}")
            continue
        if base_path.read_bytes() != candidate_path.read_bytes():
            problems.append(f"candidate changed gate-critical file: {name}; owner-controlled migration required")
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
        cwd=candidate, capture_output=True, check=False, timeout=_GIT_TIMEOUT_SECONDS
    )
    if result.returncode:
        raise ValueError("git diff --check rejected the candidate diff")
    return entries, head_sha, candidate


def classify_environment() -> tuple[list[ChangedPath], str]:
    """Classify the exact synthetic merge using the trusted checkout's helper."""
    entries, head_sha, candidate = inspect_environment()
    problems = validate_files(entries, candidate)
    if problems:
        raise ValueError("; ".join(problems))
    return entries, head_sha


def _write_outputs(values: dict[str, str]) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as output:
        for key, value in values.items():
            if not value or "\n" in value:
                raise ValueError(f"invalid empty or multiline output: {key}")
            output.write(f"{key}={value}\n")


def aggregate(needs: dict[str, object]) -> list[str]:
    """Require the base-trusted inspection job to finish successfully."""
    inspect = needs.get("inspect")
    failures: list[str] = []
    if not isinstance(inspect, dict) or inspect.get("result") != "success":
        failures.append(f"inspect={inspect.get('result', 'missing') if isinstance(inspect, dict) else 'missing'}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect")
    subparsers.add_parser("classify")
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--json", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            entries, head_sha, candidate = inspect_environment()
            problems = validate_gate_integrity(Path(os.environ["BASE_DIR"]), candidate)
            problems.extend(validate_files(entries, candidate))
            if problems:
                for problem in problems:
                    print(f"::error::{problem}", file=sys.stderr)
                return 1
            source = str(source_change(entries)).lower()
            _write_outputs({"source": source, "head_sha": head_sha})
            print(f"checked PR head SHA: {head_sha}; source: {source}")
            return 0
        if args.command == "classify":
            entries, head_sha = classify_environment()
            source = str(source_change(entries)).lower()
            _write_outputs({"source": source, "head_sha": head_sha})
            print(f"checked PR head SHA: {head_sha}; source: {source}")
            return 0
        needs = json.loads(args.json)
        if not isinstance(needs, dict):
            raise ValueError("needs JSON must be an object")
        failures = aggregate(needs)
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
