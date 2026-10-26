"""Durable provenance handoff for delegated child results."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("tools.delegate_tool")


def record_child_verification(
    *, child: Any, result: dict[str, Any], task_index: int, parent: Any, child_paths: set[str],
) -> tuple[bool, bool]:
    """Persist child outcome and return ``(used_command_tool, unobservable)``."""
    from tools.delegate_tool_child_run import _build_tool_trace

    tool_trace = _build_tool_trace(result.get("messages") or [])
    used_command_tool = any(
        str(item.get("tool", "")).lower() in {"terminal", "execute_code"} for item in tool_trace
    )
    outcome = (
        "completed" if result.get("completed") is True
        else "failed" if result.get("failed") or result.get("error") or result.get("interrupted")
        else "unknown"
    )
    unobservable = used_command_tool and not child_paths
    verification_session_id = str(
        getattr(child, "_delegate_verification_session_id", None)
        or getattr(parent, "session_id", None)
        or ""
    )
    verification_attempt_id = str(getattr(child, "_delegate_verification_attempt_id", None) or "")
    verification_authority = str(getattr(child, "_delegate_verification_authority", None) or "")
    if verification_session_id and verification_attempt_id and verification_authority:
        from agent.verification_evidence import update_delegated_verification

        durable_updated = update_delegated_verification(
            session_id=verification_session_id, attempt_id=verification_attempt_id,
            task_index=task_index, authority=verification_authority, state=outcome,
            paths=child_paths, unobservable=unobservable,
        )
        if not durable_updated and parent is not None:
            parent._pending_unobservable_delegated_work = True
    if parent is not None and child_paths:
        parent_paths = getattr(parent, "_turn_file_mutation_paths", None)
        if isinstance(parent_paths, set):
            parent_paths.update(str(path) for path in child_paths if path)
    if child_paths:
        from agent.coding_context import project_facts_for
        from agent.verification_evidence import mark_workspace_edited

        session_id = verification_session_id or str(getattr(parent, "session_id", None) or "default")
        for path in child_paths:
            candidate = Path(str(path)).expanduser()
            cwd = next((str(candidate.parent) for _ in (0,) if project_facts_for(candidate.parent)), None)
            if cwd:
                mark_workspace_edited(session_id=session_id, cwd=cwd, paths=[str(candidate)])
    if parent is not None and (used_command_tool and not child_paths or child_paths):
        lock = getattr(parent, "_pending_delegated_verification_lock", None)
        if lock is None:
            lock = threading.RLock()
            parent._pending_delegated_verification_lock = lock
        with lock:
            pending_paths = getattr(parent, "_pending_delegated_verification_paths", None)
            if not isinstance(pending_paths, set):
                pending_paths = set()
                parent._pending_delegated_verification_paths = pending_paths
            pending_paths.update(str(path) for path in child_paths if path)
            if unobservable:
                parent._pending_unobservable_delegated_work = True
                parent._turn_unobservable_delegated_work = True
    return used_command_tool, unobservable
