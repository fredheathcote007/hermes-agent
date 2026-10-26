"""Fail-closed supervisor for one explicitly identified gateway execution."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Awaitable, Callable


class SupervisionBlocked(RuntimeError):
    """The runner cannot prove that it is safe to execute this work again."""


def _receipt(path: Path | None, record: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _handle_matches(handle: object, session_id: str, generation: int, authority_epoch: int | None) -> bool:
    if not isinstance(handle, dict):
        return False
    ref = handle.get("ref")
    if not isinstance(ref, dict) or ref.get("session_id") != session_id:
        return False
    if handle.get("execution_generation") != generation:
        return False
    if authority_epoch is not None and handle.get("authority_epoch") != authority_epoch:
        return False
    return handle.get("execution_state") in {"running", "idle", "waiting", "terminal"}


async def wait_gateway_idle(client, session_id: str, generation: int, authority_epoch: int | None,
                            timeout: float, *, poll_interval: float = 0.25,
                            keep_subscription_id: str | None = None) -> bool:
    """Poll the supported session.resume snapshot until this exact run is idle."""
    deadline = time.monotonic() + timeout
    while True:
        snapshot = await client.rpc("session.resume", _timeout=max(0.001, deadline - time.monotonic()),
                                    session_id=session_id,
                                    omit_messages=True, defer_history=True)
        subscription_id = snapshot.get("subscription_id") if isinstance(snapshot, dict) else None
        try:
            if not isinstance(snapshot, dict) or snapshot.get("session_id") != session_id:
                raise SupervisionBlocked("gateway returned a snapshot for another session")
            if snapshot.get("execution_generation") != generation:
                raise SupervisionBlocked("gateway execution generation changed while settling")
            if authority_epoch is not None and snapshot.get("authority_epoch") != authority_epoch:
                raise SupervisionBlocked("gateway authority epoch changed while settling")
            idle = snapshot.get("running") is False
        finally:
            if (isinstance(subscription_id, str) and subscription_id
                    and subscription_id != keep_subscription_id):
                detached = await client.rpc("session.detach",
                                            _timeout=max(0.001, deadline - time.monotonic()),
                                            session_id=session_id,
                                            subscription_id=subscription_id)
                if (not isinstance(detached, dict) or detached.get("session_id") != session_id
                        or detached.get("subscription_id") != subscription_id
                        or detached.get("detached") is not True):
                    raise SupervisionBlocked("settlement snapshot subscription detach was not confirmed")
        if idle:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(poll_interval, remaining))


async def wait_gateway_settled(client, session_id: str, generation: int, authority_epoch: int,
                               admission_id: str, timeout: float, *, poll_interval: float = 0.25,
                               keep_subscription_id: str | None = None) -> bool:
    """Require both an idle exact generation and its matching durable terminal receipt."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        idle = await wait_gateway_idle(client, session_id, generation, authority_epoch, remaining,
                                       poll_interval=poll_interval,
                                       keep_subscription_id=keep_subscription_id)
        if not idle:
            return False
        receipt = await client.rpc("prompt.receipt", session_id=session_id,
                                   admission_id=admission_id, include_result=False)
        if (not isinstance(receipt, dict) or receipt.get("admission_id") != admission_id
                or type(receipt.get("authority_epoch")) is not int
                or receipt.get("authority_epoch") != authority_epoch
                or type(receipt.get("execution_generation")) is not int
                or receipt.get("execution_generation") != generation):
            raise SupervisionBlocked("gateway terminal receipt identity did not match the attempt")
        status = receipt.get("status")
        if status == "terminal":
            return True
        if status == "unknown":
            raise SupervisionBlocked("gateway reports an unknown admission; inspect external effects; do not replay")
        if status not in {"queued", "started"}:
            raise SupervisionBlocked("gateway receipt status is unavailable or unrecognized; do not replay")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(poll_interval, remaining))


async def run_bounded(*, client, session_id: str, execution_generation: int,
                      deadline_seconds: float, execute: Callable[[], Awaitable[object]],
                      wait_settled: Callable[[str, int, int | None, float], Awaitable[bool]] | None = None,
                      authority_epoch: int | None = None, settlement_timeout: float = 30.0,
                      termination_timeout: float = 10.0,
                      stop_event: asyncio.Event | None = None,
                      receipt_path: str | Path | None = None) -> object:
    """Run once; on deadline interrupt the named run and prove both sides have stopped.

    A successful client RPC returns a SessionHandle, whose ``running`` state is transitional.
    Only a later, identity-matched session.resume snapshot with ``running: false`` is settlement.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("an explicit session_id is required")
    if type(execution_generation) is not int or execution_generation < 1:
        raise ValueError("a positive execution_generation is required")
    if authority_epoch is not None and (type(authority_epoch) is not int or authority_epoch < 1):
        raise ValueError("authority_epoch must be a positive integer")
    if deadline_seconds <= 0 or settlement_timeout <= 0 or termination_timeout <= 0:
        raise ValueError("deadlines must be positive")
    wait_settled = wait_settled or (lambda sid, gen, epoch, timeout:
                                    wait_gateway_idle(client, sid, gen, epoch, timeout))
    receipt = Path(receipt_path) if receipt_path is not None else None
    identity = {"session_id": session_id, "execution_generation": execution_generation,
                "authority_epoch": authority_epoch}
    _receipt(receipt, {**identity, "event": "started", "at": time.time()})
    task = asyncio.create_task(execute())
    stop_waiter = asyncio.create_task(stop_event.wait()) if stop_event is not None else None
    try:
        watched = {task} | ({stop_waiter} if stop_waiter is not None else set())
        done, _ = await asyncio.wait(watched, timeout=deadline_seconds,
                                     return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            result = await task
        else:
            explicit_stop = stop_waiter is not None and stop_waiter in done
            if explicit_stop:
                _receipt(receipt, {**identity, "event": "explicit_stop", "at": time.time()})
            raise TimeoutError("explicit stop" if explicit_stop else "deadline")
        try:
            settled = await asyncio.wait_for(wait_settled(session_id, execution_generation, authority_epoch,
                                                           settlement_timeout), settlement_timeout)
        except TimeoutError as exc:
            raise SupervisionBlocked("CLI exited but gateway settlement timed out; do not retry") from exc
        if settled is not True:
            raise SupervisionBlocked("CLI exited but gateway settlement was not confirmed")
        _receipt(receipt, {**identity, "event": "completed", "at": time.time()})
        return result
    except TimeoutError as exc:
        if str(exc) != "explicit stop":
            _receipt(receipt, {**identity, "event": "deadline", "at": time.time()})
        try:
            response = await client.rpc("session.interrupt", _timeout=termination_timeout,
                                        session_id=session_id,
                                        execution_generation=execution_generation)
            if not _handle_matches(response, session_id, execution_generation, authority_epoch):
                raise SupervisionBlocked("interrupt returned a mismatched SessionHandle")
            _receipt(receipt, {**identity, "event": "interrupt_acknowledged",
                               "execution_state": response["execution_state"], "at": time.time()})
            settled = await asyncio.wait_for(wait_settled(session_id, execution_generation, authority_epoch,
                                                           settlement_timeout), settlement_timeout)
            if settled is not True:
                raise SupervisionBlocked("gateway did not confirm execution settlement")
            await asyncio.wait_for(asyncio.shield(task), termination_timeout)
        except BaseException as stop_error:
            _receipt(receipt, {**identity, "event": "blocked", "at": time.time(),
                               "reason": type(stop_error).__name__})
            if isinstance(stop_error, (KeyboardInterrupt, SystemExit)):
                raise
            raise SupervisionBlocked("deadline expired; stop, settlement, or CLI termination is unconfirmed; "
                                     "do not resume or retry") from stop_error
        _receipt(receipt, {**identity, "event": "settled_after_interrupt", "at": time.time()})
        raise SupervisionBlocked("deadline expired; execution was stopped and settled; do not retry") from exc
    except SupervisionBlocked as exc:
        _receipt(receipt, {**identity, "event": "blocked", "at": time.time(), "reason": str(exc)})
        raise
    except BaseException as exc:
        _receipt(receipt, {**identity, "event": "blocked", "at": time.time(),
                           "reason": type(exc).__name__})
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise SupervisionBlocked("attempt outcome is unconfirmed; do not resume or retry") from exc
    finally:
        if stop_waiter is not None and not stop_waiter.done():
            stop_waiter.cancel()
