"""Durable delegated-verification handling for turn finalization."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("agent.conversation_loop")


def verification_unresolved_at_finalize(agent: Any) -> bool:
    """Return the opt-in fail-closed verdict and retire only proven rows."""
    pending_lock = getattr(agent, "_pending_delegated_verification_lock", None)
    if pending_lock is None:
        pending_lock = threading.RLock()
        agent._pending_delegated_verification_lock = pending_lock
    try:
        from agent.verification_stop import verification_unresolved, verify_on_stop_enabled

        if not verify_on_stop_enabled():
            return False
        from agent.verification_evidence import (
            clear_verified_delegated_verification, pending_delegated_verification, verification_authority,
        )

        with pending_lock:
            pending_paths = set(getattr(agent, "_pending_delegated_verification_paths", set()))
            pending_unobservable = bool(getattr(agent, "_pending_unobservable_delegated_work", False))
            current_paths = set(getattr(agent, "_turn_file_mutation_paths", set()))
            unobservable = bool(getattr(agent, "_turn_unobservable_delegated_work", False))
        authority = verification_authority(agent)
        durable_pending = pending_delegated_verification(
            session_id=getattr(agent, "session_id", None), authority=authority,
        )
        all_paths = current_paths | pending_paths | set(durable_pending["paths"])
        unresolved = verification_unresolved(
            session_id=getattr(agent, "session_id", None), changed_paths=all_paths,
        ) or unobservable or pending_unobservable or durable_pending["unknown"] or durable_pending["error"]
        if unresolved:
            return True
        if not clear_verified_delegated_verification(
            session_id=getattr(agent, "session_id", None), authority=authority,
        ):
            return True
        # A late child may have arrived while evidence was checked. Clear only
        # the exact pending snapshot evaluated; newer receipts remain queued.
        with pending_lock:
            if (getattr(agent, "_pending_delegated_verification_paths", set()) == pending_paths
                    and bool(getattr(agent, "_pending_unobservable_delegated_work", False)) == pending_unobservable):
                agent._pending_delegated_verification_paths.clear()
                agent._pending_unobservable_delegated_work = False
        return False
    except Exception:  # health: allow BLE001 -- evidence lookup must fail closed
        # health: allow BLE001 -- evidence lookup must fail closed at this boundary
        logger.exception("durable delegated verification finalization failed")
        # Any failure to classify or read verification evidence is unresolved.
        # Checking only in-memory markers would miss durable-only pending work
        # following process restart or agent eviction (FHM-005).
        return True


def apply_verification_outcome(
    *, verification_unresolved: bool, interrupted: bool, failed: bool,
    exit_reason: Any, final_response: Any,
) -> tuple[bool, Any, Any]:
    """Apply the machine-readable incomplete response at the turn boundary."""
    if verification_unresolved:
        # Interruption preserves its own exit reason and any already-streamed
        # text, but unresolved delegated work must still carry a failed verdict.
        failed = True
    if verification_unresolved and not interrupted:
        exit_reason = "verification_unresolved"
        final_response = (
            "Work is incomplete: independent verification evidence is missing, stale, "
            "or unavailable. The changes require review and verification before they "
            "can be reported as successful."
        )
    return failed, exit_reason, final_response
