#!/usr/bin/env python3
"""Observe one persisted attempt without ever submitting a new prompt."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone, UTC
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

try:
    import fcntl
except ImportError:  # The CLI gates recovery to Linux before importing this module.
    fcntl = None

from hermes_cli.fermes_reliability.recovery import (
    _safe_target, append_journal, read_checkpoint, reconcile, runtime_matches, write_checkpoint,
)


async def _await_receipt(client, record, receipt):
    """Poll the read-only admission ledger until terminal evidence or the saved deadline."""
    deadline_at = record.get("deadline_at")
    while (isinstance(receipt, dict) and receipt.get("status") in {"queued", "started"}
           and isinstance(deadline_at, (float, int)) and time.time() < deadline_at):
        await asyncio.sleep(min(0.5, max(0, deadline_at - time.time())))
        receipt = await client.rpc("prompt.receipt", session_id=record["session_id"],
                                  admission_id=record["admission_id"], include_result=False)
    return receipt


async def _await_event(client, record, snapshot):
    """Use the bounded replay ring only when its cursor and process epoch are exact."""
    replay_epoch = snapshot.get("replay_epoch") if isinstance(snapshot, dict) else None
    sequence = snapshot.get("last_sequence") if isinstance(snapshot, dict) else None
    deadline_at = record.get("deadline_at")
    if not isinstance(replay_epoch, str) or type(sequence) is not int or not isinstance(deadline_at, (int, float)):
        return None, "event replay cursor unavailable; inspect the gateway receipt and workspace; do not replay"
    first_page = True
    while first_page or time.time() < deadline_at:
        first_page = False
        page = await client.rpc("session.events.since", session_id=record["session_id"],
                                last_sequence=sequence, replay_epoch=replay_epoch)
        if (not isinstance(page, dict) or page.get("replay_epoch") != replay_epoch
                or page.get("truncated") is not False or page.get("snapshot_required") is not False):
            return None, "event replay gap or epoch drift; inspect the gateway receipt and workspace; do not replay"
        events = page.get("events")
        if not isinstance(events, list):
            return None, "event replay response malformed; inspect the gateway and workspace; do not replay"
        for event in events:
            if not isinstance(event, dict):
                continue
            sequence = max(sequence, event.get("seq", sequence)) if type(event.get("seq", sequence)) is int else sequence
            if (event.get("type") == "message.complete"
                    and event.get("session_id") == record["session_id"]
                    and type(event.get("authority_epoch")) is int
                    and event.get("authority_epoch") == record["gateway_authority_epoch"]
                    and type(event.get("execution_generation")) is int
                    and event.get("execution_generation") == record["generation"]
                    and (not record.get("admission_id") or event.get("admission_id") == record["admission_id"])):
                return event, None
        sequence = max(sequence, page.get("latest_seq", sequence)) if type(page.get("latest_seq", sequence)) is int else sequence
        if time.time() >= deadline_at:
            break
        await asyncio.sleep(min(0.5, max(0, deadline_at - time.time())))
    return None, None


async def recover(path: Path, *, expected_state: str | None = None,
                  expected_attempt_id: str | None = None,
                  _claim_owned: bool = False) -> dict[str, Any]:
    """Serialize explicit observers with the orphan scanner's per-attempt claim."""
    if _claim_owned:
        return await _recover(path, expected_state=expected_state,
                              expected_attempt_id=expected_attempt_id)
    if fcntl is None:
        raise RuntimeError("recovery locks require Linux")
    checkpoint = _safe_target(path, must_exist=True)
    lock_path = checkpoint.with_name(checkpoint.name + ".recovery.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("recovery lock must be a regular file")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another recovery observer owns this attempt") from exc
        try:
            return await _recover(checkpoint, expected_state=expected_state,
                                  expected_attempt_id=expected_attempt_id)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


async def _recover(path: Path, *, expected_state: str | None = None,
                   expected_attempt_id: str | None = None) -> dict[str, Any]:
    from hermes_cli.gateway_client import connect_gateway

    record = read_checkpoint(path)
    # An operator has already classified this attempt as blocked or terminal.
    # A later observation must never undo that explicit decision, even if the
    # gateway reports activity. It requires a separate owner-led resolution.
    if record.get("state") in {"BLOCKED", "TERMINAL", "COMPLETE", "COMPLETED"}:
        raise RuntimeError(
            "attempt is already blocked or terminal; operator resolution required; do not replay"
        )
    # Standalone recovery must also use compare-and-swap. Without this the
    # operator can mark an attempt BLOCKED while a slow gateway observation is
    # in flight, then have that newer decision overwritten by the observer.
    if expected_state is None:
        expected_state = record["state"]
    if expected_attempt_id is None:
        expected_attempt_id = record["attempt_id"]
    if (expected_state is not None and record.get("state") != expected_state
            or expected_attempt_id is not None
            and record.get("attempt_id") != expected_attempt_id):
        raise RuntimeError("checkpoint changed before recovery; newer state preserved")
    try:
        async with connect_gateway() as client:
            runtime = await client.rpc("runtime.describe")
            if not runtime_matches(record, runtime):
                result = reconcile(record, runtime, None)
            elif not isinstance(record.get("session_id"), str) or not record["session_id"]:
                result = {"state": "BLOCKED", "next_action": "session ID was never captured; inspect gateway history and original workspace; do not replay"}
            elif type(record.get("generation")) is not int or record["generation"] < 1:
                result = {"state": "BLOCKED", "next_action": "generation was never captured; inspect gateway history and original workspace; do not replay"}
            else:
                snapshot = None
                subscription_id = None
                result = None
                try:
                    snapshot = await client.rpc("session.resume", session_id=record["session_id"],
                                                omit_messages=True, defer_history=True)
                    if isinstance(snapshot, dict):
                        subscription_id = snapshot.get("subscription_id")
                    if not isinstance(subscription_id, str) or not subscription_id:
                        result = {"state": "BLOCKED", "next_action": "session attachment did not provide a subscription ID; inspect gateway and workspace; do not replay"}
                    else:
                        receipt = None
                        if record.get("admission_id"):
                            receipt = await client.rpc("prompt.receipt", session_id=record["session_id"],
                                                       admission_id=record["admission_id"], include_result=False)
                            receipt = await _await_receipt(client, record, receipt)
                        elif isinstance(snapshot, dict) and snapshot.get("running") is True:
                            event, replay_error = await _await_event(client, record, snapshot)
                            if replay_error:
                                result = {"state": "BLOCKED", "next_action": replay_error}
                            elif event:
                                # An event without the original admission ID
                                # proves only that *some* turn finished in this
                                # generation. Never certify the unknown attempt.
                                result = {"state": "BLOCKED", "next_action":
                                          "message.complete matched session/generation but admission ID is absent; "
                                          "inspect external effects and original workspace; do not replay"}
                        if result is None:
                            result = reconcile(record, runtime, snapshot, receipt)
                except Exception as exc:
                    result = {"state": "BLOCKED", "next_action": f"gateway observation failed ({type(exc).__name__}); inspect gateway and original workspace; do not replay"}
                finally:
                    if isinstance(subscription_id, str) and subscription_id:
                        try:
                            detached = await client.rpc("session.detach", session_id=record["session_id"],
                                                        subscription_id=subscription_id)
                            if (not isinstance(detached, dict)
                                    or detached.get("session_id") != record["session_id"]
                                    or detached.get("subscription_id") != subscription_id
                                    or detached.get("detached") is not True):
                                raise RuntimeError("detach confirmation did not match the attachment")
                        except Exception as exc:
                            result = {"state": "BLOCKED", "next_action": f"session detach failed or was unconfirmed ({type(exc).__name__}); inspect gateway and original workspace; do not replay"}
    except Exception as exc:
        result = {"state": "BLOCKED", "next_action": f"gateway observation failed ({type(exc).__name__}); inspect gateway and original workspace; do not replay"}
    now = datetime.now(UTC).isoformat()
    record["last_observation"] = {"at": now, **result}
    record["state"] = result["state"]
    record["status"] = result["state"].lower()
    record["next_action"] = result["next_action"]
    write_checkpoint(path, record, expected_state=expected_state,
                     expected_attempt_id=expected_attempt_id)
    append_journal(path.with_suffix(path.suffix + ".jsonl"), {
        "run_id": record["run_id"], "attempt_id": record["attempt_id"],
        "session_id": record.get("session_id"),
        "generation": record.get("generation"), "gateway_authority_epoch": record.get("gateway_authority_epoch"),
        "admission_id": record.get("admission_id"), "observation": record["last_observation"],
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover-from", required=True, type=Path, help="phase 2 checkpoint JSON")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(recover(args.recover_from))
    except Exception as exc:
        result = {"state": "BLOCKED", "next_action": f"recovery observation failed ({type(exc).__name__}); inspect gateway and original workspace; do not replay"}
    print(json.dumps(result, sort_keys=True))
    return 125


if __name__ == "__main__":
    sys.exit(main())
