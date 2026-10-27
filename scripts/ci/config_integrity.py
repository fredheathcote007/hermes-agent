#!/usr/bin/env python3
"""Scan changed editor and JavaScript/TypeScript configuration files.

This is intentionally a small, read-only PR scanner.  It reads blobs from the
requested Git range and never imports, evaluates, or executes the changed
files.  A non-zero result means that a reviewer should inspect the change.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_JS_TS_EXTENSIONS = {".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"}
_CONFIG_NAMES = {
    "babel.config",
    "electron-builder.config",
    "esbuild.config",
    "eslint.config",
    "jest.config",
    "prettier.config",
    "rollup.config",
    "tsup.config",
    "vite.config",
    "webpack.config",
}
_OBFUSCATION = (
    re.compile(r"\batob\s*\("),
    re.compile(r"\bString\s*\.\s*fromCharCode\s*\("),
    re.compile(r"\bBuffer\s*\.\s*from\s*\([^;\n]{0,400}\bSTRING_BASE64\b"),
    re.compile(r"\bunescape\s*\("),
)
_DYNAMIC_EXECUTION = (
    re.compile(r"(?<![\w$])eval\s*\("),
    re.compile(r"(?<![\w$])new\s+Function\s*\("),
    re.compile(r"(?<![\w$])Function\s*\("),
    re.compile(r"\bvm\s*\.\s*(?:runIn\w+|Script)\s*\("),
    re.compile(r"\b(?:child_process|cp)\s*\.\s*(?:exec|execFile|spawn)\s*\("),
)


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


class ScanError(RuntimeError):
    """An inability to establish the requested diff is itself blocking."""


def _display_path(path: str) -> str:
    """Keep filenames safe and unambiguous in CI logs and review comments."""
    return path.encode("unicode_escape", errors="backslashreplace").decode("ascii")


def _git(repo: Path, args: list[str]) -> bytes:
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_PAGER"] = "cat"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            env=env,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScanError(f"git command failed: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ScanError(detail or f"git exited with status {result.returncode}")
    return result.stdout


def _validate_revision(value: str, name: str) -> str:
    if not value or value.startswith("-") or any(ord(char) < 32 for char in value):
        raise ScanError(f"invalid {name} revision")
    return value


def _diff_range(base: str, head: str) -> str:
    return f"{_validate_revision(base, 'base')}...{_validate_revision(head, 'head')}"


def _changed_paths(repo: Path, revision_range: str) -> list[str]:
    raw = _git(
        repo,
        ["diff", "--name-status", "-z", "--no-ext-diff", "--no-textconv", revision_range, "--"],
    )
    fields = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].decode("ascii", errors="replace")
        index += 1
        if not status:
            break
        if status[0] in "RC":
            if index + 1 >= len(fields):
                raise ScanError("git returned an incomplete rename/copy record")
            index += 1  # The old path is not a blob introduced by this change.
            path = fields[index]
            index += 1
        else:
            if index >= len(fields):
                raise ScanError("git returned an incomplete name-status record")
            path = fields[index]
            index += 1
        if status[0] != "D":
            paths.append(os.fsdecode(path))
    return paths


def _blob(repo: Path, head: str, path: str) -> str:
    raw = _git(repo, ["cat-file", "blob", f"{_validate_revision(head, 'head')}:{path}"])
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScanError(f"changed file is not valid UTF-8: {_display_path(path)}") from exc


def _added_lines(repo: Path, revision_range: str, path: str) -> list[str]:
    raw = _git(
        repo,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--unified=0",
            revision_range,
            "--",
            path,
        ],
    )
    text = raw.decode("utf-8", errors="replace")
    in_hunk = False
    added: list[str] = []
    for line in text.splitlines():
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added.append(line[1:])
    return added


def _strip_jsonc(source: str) -> str:
    output: list[str] = []
    index = 0
    quote = False
    escaped = False
    block_comment = False
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if block_comment:
            if char == "*" and next_char == "/":
                output.extend((" ", " "))
                index += 2
                block_comment = False
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            output.append(char)
            index += 1
        elif char == "/" and next_char == "/":
            output.extend((" ", " "))
            index += 2
            while index < len(source) and source[index] != "\n":
                output.append(" ")
                index += 1
        elif char == "/" and next_char == "*":
            output.extend((" ", " "))
            index += 2
            block_comment = True
        else:
            output.append(char)
            index += 1
    if block_comment:
        raise ValueError("unterminated block comment")

    clean = "".join(output)
    result: list[str] = []
    index = 0
    quote = False
    escaped = False
    while index < len(clean):
        char = clean[index]
        if quote:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            result.append(char)
            index += 1
        elif char == ",":
            lookahead = index + 1
            while lookahead < len(clean) and clean[lookahead].isspace():
                lookahead += 1
            if lookahead < len(clean) and clean[lookahead] in "}]":
                index += 1
            else:
                result.append(char)
                index += 1
        else:
            result.append(char)
            index += 1
    return "".join(result)


def _tasks_findings(path: str, source: str) -> list[Finding]:
    try:
        document = json.loads(_strip_jsonc(source))
    except (ValueError, json.JSONDecodeError) as exc:
        detail = str(exc).splitlines()[0]
        return [Finding(path, f"tasks.json is not valid JSONC: {detail}")]
    if not isinstance(document, dict) or ("tasks" in document and not isinstance(document["tasks"], list)):
        return [Finding(path, "tasks.json has an invalid top-level tasks schema")]
    tasks = document.get("tasks", [])
    findings: list[Finding] = []
    for number, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            findings.append(Finding(path, f"task {number} is not an object; inspection failed closed"))
            continue
        options = task.get("runOptions")
        if options is not None and not isinstance(options, dict):
            findings.append(Finding(path, f"task {number} has an invalid runOptions schema"))
            continue
        if isinstance(options, dict) and options.get("runOn") == "folderOpen":
            label = task.get("label", f"task {number}")
            findings.append(Finding(path, f"task {label!r} runs automatically on folderOpen"))
    return findings


def _mask_javascript(source: str) -> str:
    """Mask comments and strings while retaining a token for base64 mode."""
    output: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if char == "/" and next_char == "/":
            output.extend((" ", " "))
            index += 2
            while index < len(source) and source[index] != "\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and next_char == "*":
            output.extend((" ", " "))
            index += 2
            while index < len(source):
                if source[index] == "*" and index + 1 < len(source) and source[index + 1] == "/":
                    output.extend((" ", " "))
                    index += 2
                    break
                output.append("\n" if source[index] == "\n" else " ")
                index += 1
            continue
        if char in "'\"`":
            quote = char
            value: list[str] = []
            index += 1
            while index < len(source):
                if source[index] == "\\" and index + 1 < len(source):
                    value.append(source[index:index + 2])
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    value.append(source[index])
                    index += 1
            token = "STRING_BASE64" if "".join(value).strip().lower() == "base64" else "STRING"
            output.append(token)
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _has_signal(patterns: tuple[re.Pattern[str], ...], source: str) -> bool:
    return any(pattern.search(source) for pattern in patterns)


def _minified_like(path: str, source: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if ".min." in name or name.endswith(".min.js"):
        return True
    lines = [line for line in source.splitlines() if line.strip()]
    return len(lines) <= 3 and any(len(line) > 1000 for line in lines)


def _js_findings(path: str, source: str, added: list[str]) -> list[Finding]:
    masked_source = _mask_javascript(source)
    masked_added = _mask_javascript("\n".join(added))
    obfuscated = _has_signal(_OBFUSCATION, masked_source)
    dynamic = _has_signal(_DYNAMIC_EXECUTION, masked_source)
    added_obfuscated = _has_signal(_OBFUSCATION, masked_added)
    added_dynamic = _has_signal(_DYNAMIC_EXECUTION, masked_added)
    findings: list[Finding] = []
    if (added_obfuscated and dynamic) or (added_dynamic and obfuscated):
        findings.append(Finding(path, "added code combines obfuscation with dynamic execution"))

    minified = _minified_like(path, source)
    for line in added:
        stripped = line.lstrip()
        padding = len(line) - len(stripped)
        if padding >= 128 and stripped and not stripped.startswith(("//", "/*", "*")):
            findings.append(Finding(path, "added code has unusually deep whitespace padding"))
            break
    if not minified:
        for line in added:
            if len(line) > 1200 and not line.lstrip().startswith(("//", "/*", "*")):
                findings.append(Finding(path, "added code contains a suspiciously overlong line"))
                break
    return findings


def _is_tasks_file(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return PurePosixPath(path).name == "tasks.json" and ".vscode" in parts


def _is_js_ts_config(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix.lower() not in _JS_TS_EXTENSIONS:
        return False
    stem = pure.name.rsplit(".", 1)[0].lower()
    if stem in _CONFIG_NAMES or "config" in stem or "build" in stem:
        return True
    return any(part.lower() in {"build", "config", "scripts"} for part in pure.parts[:-1])


def scan(repo: Path, base: str, head: str) -> list[Finding]:
    revision_range = _diff_range(base, head)
    findings: list[Finding] = []
    for path in _changed_paths(repo, revision_range):
        if _is_tasks_file(path):
            findings.extend(_tasks_findings(path, _blob(repo, head, path)))
        elif _is_js_ts_config(path):
            source = _blob(repo, head, path)
            findings.extend(_js_findings(path, source, _added_lines(repo, revision_range, path)))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base commit for the PR three-dot diff")
    parser.add_argument("--head", required=True, help="head commit for the PR three-dot diff")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository to inspect")
    args = parser.parse_args(argv)
    try:
        findings = scan(args.repo, args.base, args.head)
    except ScanError as exc:
        print(f"[config-integrity] ERROR: {exc}", file=sys.stderr)
        return 2
    if not findings:
        print("[config-integrity] no blocking findings in changed configuration files")
        return 0
    for finding in findings:
        print(f"[config-integrity] {_display_path(finding.path)}: {finding.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
