"""Strict and advisory delegated-verification decisions at the turn boundary."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_parent_verification_lock(agent: Any):
    from agent.verification_evidence import _get_parent_verification_lock as get_lock

    return get_lock(agent)


def verification_state_at_finalize(agent: Any) -> tuple[bool, str | None]:
    """Return ``(strict_failure, advisory_status)`` for delegated work."""
    from agent.verification_stop import (
        outcome_verification_mode,
        verification_unresolved,
    )

    mode = outcome_verification_mode(agent=agent)
    if mode == "off":
        return False, None
    lock = _get_parent_verification_lock(agent)
    with lock:
        pending_paths = set(
            getattr(agent, "_pending_delegated_verification_paths", set())
        )
        pending_unobservable = bool(
            getattr(agent, "_pending_unobservable_delegated_work", False)
        )
        turn_paths = set(getattr(agent, "_turn_file_mutation_paths", set()))
        turn_unobservable = bool(
            getattr(agent, "_turn_unobservable_delegated_work", False)
        )
    try:
        from agent.verification_evidence import (
            pending_delegated_verification,
            verification_authority,
        )

        durable = pending_delegated_verification(
            session_id=getattr(agent, "session_id", None),
            authority=verification_authority(agent),
        )
        unresolved = (
            verification_unresolved(
                session_id=getattr(agent, "session_id", None),
                changed_paths=turn_paths | pending_paths | set(durable["paths"]),
            )
            or pending_unobservable
            or turn_unobservable
            or durable["unknown"]
            or durable["error"]
        )
        if mode == "strict":
            if unresolved:
                return True, None
            from agent.verification_evidence import (
                clear_verified_delegated_verification,
            )

            if not clear_verified_delegated_verification(
                session_id=getattr(agent, "session_id", None),
                authority=verification_authority(agent),
            ):
                return True, None
            return False, None
        return False, "unverified" if unresolved else None
    except Exception:
        logger.debug("delegated verification finalization failed", exc_info=True)
        return (True, None) if mode == "strict" else (False, "unverified")


def verification_unresolved_at_finalize(agent: Any) -> bool:
    return verification_state_at_finalize(agent)[0]


def apply_verification_outcome(
    *,
    verification_unresolved: bool,
    interrupted: bool,
    failed: bool,
    exit_reason: Any,
    final_response: Any,
) -> tuple[bool, Any, Any]:
    """Preserve the historical strict response and exit fields."""
    if verification_unresolved:
        failed = True
    if verification_unresolved and not interrupted:
        exit_reason = "verification_unresolved"
        final_response = (
            "Work is incomplete: independent verification evidence is missing, stale, "
            "or unavailable. The changes require review and verification before they "
            "can be reported as successful."
        )
    return failed, exit_reason, final_response
