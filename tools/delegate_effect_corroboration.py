"""Bounded, non-authoritative observations for explicitly advisory delegation.

The file path probe is local-only and same-user best effort. It is not a secure
verifier: a same-user process can still race an observation after the
descriptor is opened. A missing provenance or any ambiguity is abstention.
Git support is a validated parent-intent contract; no production parent
currently supplies that intent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

_MAX_FILE_BYTES = 4 * 1024 * 1024
_HEX_LENGTH = 40
_SAFE_GIT_PATH = re.compile(r"[A-Za-z0-9._/-]+\Z")


def _tool_calls(messages: Any) -> list[tuple[str | None, str, Any]]:
    """Keep malformed sibling calls visible so they cannot hide an opaque effect."""
    calls: list[tuple[str | None, str, Any]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            calls.append((None, "unknown", None))
            continue
        for call in raw_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                calls.append((None, "unknown", None))
                continue
            call_id = call.get("id")
            calls.append((
                call_id if isinstance(call_id, str) and call_id else None,
                str(function.get("name") or "unknown"),
                function.get("arguments", ""),
            ))
    return calls


def _tool_results(messages: Any) -> dict[str, list[Any]]:
    results: dict[str, list[Any]] = {}
    for message in messages if isinstance(messages, list) else []:
        if isinstance(message, dict) and message.get("role") == "tool" and isinstance(message.get("tool_call_id"), str):
            results.setdefault(message["tool_call_id"], []).append(message.get("content", ""))
    return results


def _result_body(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, list):
        raw = "".join(str(part) for part in raw)
    if not isinstance(raw, str):
        return None
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _task_backend(task_id: str | None) -> str | None:
    """Require a live task-local environment; a config fallback is not provenance."""
    if not isinstance(task_id, str) or not task_id:
        return None
    try:
        from tools.terminal_tool_lifecycle import get_active_env
        from tools.environments.local import LocalEnvironment

        return "local" if isinstance(get_active_env(task_id), LocalEnvironment) else None
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError):
        return None


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor or os.sep)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _resolved_local_path(raw_path: str, allowed_paths: set[str], task_id: str | None) -> Path | None:
    if not os.path.isabs(raw_path) or _task_backend(task_id) != "local":
        return None
    try:
        # Check original path before the standard resolver canonicalises links.
        if _has_symlink_component(Path(raw_path)):
            return None
        from tools.file_tools_paths import _resolve_path_for_task

        resolved = _resolve_path_for_task(raw_path, task_id or "default")
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError):
        return None
    if not isinstance(resolved, Path) or str(resolved) not in allowed_paths:
        return None
    return resolved


def _safe_local_bytes(path: Path) -> bytes | None:
    """Read one bounded regular file without following identifiable links/FIFOs."""
    try:
        if _has_symlink_component(path):
            return None
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(str(path), flags | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE_BYTES:
                return None
            data = os.read(fd, _MAX_FILE_BYTES + 1)
            return data if len(data) <= _MAX_FILE_BYTES else None
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None


def _file_observation(messages: Any, allowed_paths: set[str], *, task_id: str | None,
                      completed: bool, failed: bool, truncated: bool) -> dict[str, Any] | None:
    if not completed or failed or truncated:
        return None
    # Only one identifiable write call is supported in Increment 2. Abstain
    # on any additional/unknown/malformed call rather than infer its effects.
    calls = _tool_calls(messages)
    if len(calls) != 1 or not calls[0][0] or calls[0][1] != "write_file":
        return None
    call_id, _, raw_args = calls[0]
    results = _tool_results(messages).get(call_id, [])
    if len(results) != 1:
        return None
    args = _result_body(raw_args)
    body = _result_body(results[0])
    if not isinstance(args, dict) or not isinstance(body, dict):
        return None
    raw_path, content = args.get("path"), args.get("content")
    if not isinstance(raw_path, str) or not isinstance(content, str):
        return None
    # write_file_tool emits WriteResult.to_dict(), whose success contract is
    # bytes_written + absence of error (NOT a boolean success field).
    if body.get("error") or body.get("success") is False or body.get("verified") is False:
        return None
    try:
        expected = content.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (not expected or len(expected) > _MAX_FILE_BYTES or
            type(body.get("bytes_written")) is not int or body["bytes_written"] != len(expected)):
        return None
    path = _resolved_local_path(raw_path, allowed_paths, task_id)
    if path is None:
        return None
    reported = []
    for key in ("resolved_path", "files_modified"):
        if key in body:
            value = body[key]
            values = value if isinstance(value, list) else [value]
            if not values or any(not isinstance(item, str) for item in values):
                return None
            reported.extend(values)
    if reported and set(reported) != {str(path)}:
        return None
    actual = _safe_local_bytes(path)
    if actual is None or actual != expected:
        return None
    return {"status": "observed", "kind": "file_write", "path": str(path),
            "sha256": hashlib.sha256(actual).hexdigest()}


def _valid_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != _HEX_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _valid_git_path(path: Any) -> bool:
    return (isinstance(path, str) and bool(path) and bool(_SAFE_GIT_PATH.fullmatch(path))
            and not path.startswith("/") and ".." not in Path(path).parts and not path.endswith("/"))


def _git_run(cwd: str, args: list[str]) -> subprocess.CompletedProcess[bytes] | None:
    # Keep host executable discovery (and Windows SystemRoot), but discard any
    # inherited Git-specific settings that could redirect local readback.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, timeout=5, check=False, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def _git_observation(intent: Any) -> dict[str, Any] | None:
    if not isinstance(intent, dict) or intent.get("kind") != "git":
        return None
    cwd, head, tree, paths = intent.get("cwd"), intent.get("expected_head"), intent.get("expected_tree"), intent.get("paths")
    if (not isinstance(cwd, str) or not os.path.isabs(cwd) or not Path(cwd).is_dir()
            or not _valid_sha(head) or not _valid_sha(tree) or not isinstance(paths, list)
            or not paths or not all(_valid_git_path(path) for path in paths)):
        return None
    before = _git_run(cwd, ["rev-parse", "--verify", "HEAD"])
    actual_tree = _git_run(cwd, ["rev-parse", "--verify", f"{head}^{{tree}}"])
    changed = _git_run(cwd, ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z",
                             "--no-ext-diff", "--no-textconv", head, "--", *paths])
    after = _git_run(cwd, ["rev-parse", "--verify", "HEAD"])
    if any(item is None or item.returncode != 0 for item in (before, actual_tree, changed, after)):
        return None
    if before.stdout.strip().decode() != head or after.stdout.strip().decode() != head:
        return None
    if actual_tree.stdout.strip().decode() != tree:
        return None
    changed_paths = {item.decode("utf-8") for item in changed.stdout.split(b"\0") if item}
    if not set(paths).issubset(changed_paths):
        return None
    return {"status": "observed", "kind": "git", "head": head, "tree": tree, "paths": paths}


def corroborate_child_effects(messages: Any, *, allowed_paths: set[str], git_intent: Any = None,
                              task_id: str | None = None, completed: bool = True, failed: bool = False,
                              truncated: bool = False) -> dict[str, Any] | None:
    """Return one bounded observation, or ``None`` when the effect is unverifiable."""
    if not completed or failed or truncated:
        return None
    return _file_observation(messages, allowed_paths, task_id=task_id, completed=completed,
                             failed=failed, truncated=truncated) or _git_observation(git_intent)


__all__ = ["corroborate_child_effects"]
