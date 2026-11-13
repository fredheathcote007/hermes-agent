"""Durable provenance handoff for delegated child results."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _get_parent_verification_lock(parent: Any):
    from agent.verification_evidence import _get_parent_verification_lock as get_lock

    return get_lock(parent)


def record_child_verification(
    *,
    child: Any,
    result: dict[str, Any],
    task_index: int,
    parent: Any,
    child_paths: set[str],
) -> tuple[bool, bool]:
    """Persist exact child telemetry and return ``(used_command, unobservable)``."""
    from tools.delegate_tool_child_run import _build_tool_trace

    tool_trace = _build_tool_trace(result.get("messages") or [])
    file_mutation_tools = {"write_file", "patch"}
    tool_failed = any(item.get("status") != "ok" for item in tool_trace)
    used_command = any(
        str(item.get("tool", "")).lower() in {"terminal", "execute_code"}
        for item in tool_trace
    )
    outcome = (
        "completed"
        if result.get("completed") is True and not tool_failed
        else "failed"
        if result.get("failed")
        or result.get("error")
        or result.get("interrupted")
        or any(item.get("status") == "error" for item in tool_trace)
        else "unknown"
    )
    unobservable = tool_failed or any(
        bool(item.get("effect_capable"))
        and (
            str(item.get("tool", "")).lower() not in file_mutation_tools
            or not child_paths
        )
        for item in tool_trace
    )
    session_id = str(
        getattr(child, "_delegate_verification_session_id", None)
        or getattr(parent, "session_id", None)
        or ""
    )
    attempt_id = str(getattr(child, "_delegate_verification_attempt_id", None) or "")
    authority = str(getattr(child, "_delegate_verification_authority", None) or "")
    parent_lock = _get_parent_verification_lock(parent) if parent is not None else None
    if session_id and attempt_id and authority:
        from agent.verification_evidence import update_delegated_verification

        if (
            not update_delegated_verification(
                session_id=session_id,
                attempt_id=attempt_id,
                task_index=task_index,
                authority=authority,
                state=outcome,
                paths=child_paths,
                unobservable=unobservable,
            )
            and parent is not None
        ):
            with parent_lock:
                parent._pending_unobservable_delegated_work = True
    if child_paths:
        from agent.coding_context import project_facts_for
        from agent.verification_evidence import mark_workspace_edited

        for path in child_paths:
            candidate = Path(str(path)).expanduser()
            cwd = str(candidate.parent) if project_facts_for(candidate.parent) else None
            if cwd:
                mark_workspace_edited(
                    session_id=session_id
                    or str(getattr(parent, "session_id", None) or "default"),
                    cwd=cwd,
                    paths=[str(candidate)],
                )
    if parent is not None and (unobservable or child_paths):
        with parent_lock:
            if child_paths:
                parent_paths = getattr(parent, "_turn_file_mutation_paths", None)
                if isinstance(parent_paths, set):
                    parent_paths.update(str(path) for path in child_paths if path)
            pending_paths = getattr(
                parent, "_pending_delegated_verification_paths", None
            )
            if not isinstance(pending_paths, set):
                pending_paths = set()
                parent._pending_delegated_verification_paths = pending_paths
            pending_paths.update(str(path) for path in child_paths if path)
            if unobservable:
                parent._pending_unobservable_delegated_work = True
                parent._turn_unobservable_delegated_work = True
    return used_command, unobservable
