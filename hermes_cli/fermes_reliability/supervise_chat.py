#!/usr/bin/env python3
"""Run one bounded ``hermes chat`` command against its exact gateway execution.

If the CLI dies without exposing a session ID, the wrapper drains and retains both
output streams, then tries any ID that arrived during shutdown. If identity remains
unknown, the gateway execution may be unrecoverable and ambiguous; never retry it.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import sys
import tempfile
import time
import uuid
from pathlib import Path

from hermes_cli.fermes_reliability.bounded_supervisor import (
    SupervisionBlocked, _handle_matches, run_bounded, wait_gateway_idle, wait_gateway_settled,
)
from hermes_cli.fermes_reliability.recovery import owner_identity, persist_state


def _session_id_from_line(line: bytes, *, json_stream: bool) -> str | None:
    text = line.decode("utf-8", errors="replace").strip()
    if json_stream:
        try:
            event = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
            session_id = event.get("session_id")
            return session_id if isinstance(session_id, str) and session_id else None
    elif text.startswith(("session_id:", "Session:")):
        session_id = text.partition(":")[2].strip()
        return session_id or None
    return None


async def _copy_stream(stream, destination, *, session_id_future=None, json_stream=False,
                       on_session_id=None):
    while line := await stream.readline():
        destination.buffer.write(line)
        destination.flush()
        if session_id_future is not None and not session_id_future.done():
            session_id = _session_id_from_line(line, json_stream=json_stream)
            if session_id:
                if on_session_id:
                    on_session_id(session_id)
                session_id_future.set_result(session_id)


def _matching_snapshot(snapshot, session_id: str, authority_epoch: int) -> bool:
    return (isinstance(snapshot, dict) and snapshot.get("session_id") == session_id
            and type(snapshot.get("authority_epoch")) is int
            and snapshot["authority_epoch"] == authority_epoch)


def _persist_failure(checkpoint: str, record: dict, exc: Exception) -> None:
    if record.get("state") in {"TERMINAL", "SETTLED_UNKNOWN"}:
        return
    try:
        persist_state(checkpoint, record, "BLOCKED", status="supervision failed",
                      next_action="inspect the gateway and original workspace; do not replay",
                      failure_type=type(exc).__name__)
    except Exception as persist_exc:
        raise SupervisionBlocked(
            f"supervision failed ({type(exc).__name__}: {exc}); could not durably persist BLOCKED "
            f"({type(persist_exc).__name__}: {persist_exc}); outcome remains ambiguous; do not replay"
        ) from persist_exc


def _persist_detach_unconfirmed(checkpoint: str, record: dict, exc: Exception,
                                original_failure: Exception | None) -> None:
    """Override any apparent completion when this supervisor's detach is uncertain."""
    try:
        persist_state(checkpoint, record, "BLOCKED", status="supervisor subscription detach unconfirmed",
                      next_action="inspect gateway subscriptions and the original workspace; do not replay",
                      failure_type=type(exc).__name__,
                      original_failure_type=type(original_failure).__name__ if original_failure else None)
    except Exception as persist_exc:
        original_reason = (f"; prior supervision failure ({type(original_failure).__name__}: "
                           f"{original_failure})" if original_failure else "")
        raise SupervisionBlocked(
            f"detach failure ({type(exc).__name__}: {exc}){original_reason}; could not durably persist "
            f"BLOCKED ({type(persist_exc).__name__}: {persist_exc}); outcome remains ambiguous; do not replay"
        ) from persist_exc


def _persist_tree_unconfirmed(checkpoint: str, record: dict, exc: Exception) -> None:
    try:
        persist_state(checkpoint, record, "BLOCKED", status="CLI process tree cleanup unconfirmed",
                      next_action="inspect the supervisor process group, gateway admission, and original workspace; do not replay",
                      failure_type=type(exc).__name__)
    except Exception as persist_exc:
        raise SupervisionBlocked(
            f"process tree cleanup failed ({type(exc).__name__}); could not durably persist BLOCKED "
            f"({type(persist_exc).__name__}); outcome remains ambiguous; do not replay") from persist_exc


def _install_stop_handlers(loop, stop_event):
    old_handlers = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            old_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda _sig, _frame: loop.call_soon_threadsafe(stop_event.set))
        except (ValueError, OSError):
            pass
    return old_handlers


def _restore_signal_handlers(old_handlers) -> None:
    for signum, handler in old_handlers.items():
        signal.signal(signum, handler)


async def supervise_chat(prompt: str, *, deadline: float, settlement_timeout: float = 30,
                         executable: str = "hermes", workspace_parent: str | None = None,
                         checkpoint_path: str | None = None) -> int:
    """Launch the canonical CLI in a retained workspace and supervise its captured session."""
    from hermes_cli.gateway_client import GatewayClientError, connect_gateway

    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if len(prompt.encode("utf-8")) > 1_000_000:
        raise ValueError("prompt exceeds the 1 MB supervisor input limit")
    if deadline <= 0 or settlement_timeout <= 0:
        raise ValueError("deadlines must be positive")
    if os.name != "posix" or not Path("/proc/sys/kernel/random/boot_id").is_file():
        raise SupervisionBlocked("supervised process-tree identity is currently supported on Linux only")
    from hermes_cli.fermes_reliability.recover_orphans import _valid_parent
    safe_parent = _valid_parent(Path(workspace_parent) if workspace_parent else Path(tempfile.gettempdir()))
    async with connect_gateway() as client:
        runtime = await client.rpc("runtime.describe")
        if (not isinstance(runtime, dict) or type(runtime.get("authority_epoch")) is not int
                or not isinstance(runtime.get("instance_id"), str)
                or not isinstance(runtime.get("profile_id"), str)):
            raise SupervisionBlocked("gateway did not provide its profile, instance, and authority identity")
        authority_epoch = runtime["authority_epoch"]
        workspace = os.path.abspath(tempfile.mkdtemp(prefix="hermes-supervised-", dir=safe_parent))
        print(f"Workspace: {workspace}", file=sys.stderr, flush=True)
        checkpoint = os.path.abspath(checkpoint_path or os.path.join(workspace, "phase2-checkpoint.json"))
        record = {
            "run_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()),
            "state": "LAUNCHING", "status": "launching",
            "gateway_instance_id": runtime["instance_id"], "gateway_profile_id": runtime["profile_id"],
            "gateway_authority_epoch": authority_epoch, "session_id": None, "generation": None,
            "subscription_id": None, "admission_id": None, "submission_id": None,
            "replay_epoch": None, "last_sequence": None,
            "last_observation": None, "deadline": deadline, "deadline_at": time.time() + deadline,
            "working_dir": workspace,
            **owner_identity(),
            "next_action": "await the original launch; if the supervisor disappears, recover this checkpoint without replay",
        }
        persist_state(checkpoint, record, "LAUNCHING", status="launching",
                      next_action=record["next_action"])
        print(f"Checkpoint: {checkpoint}", file=sys.stderr, flush=True)
        loop = asyncio.get_running_loop()
        started = loop.time()
        stop_event = asyncio.Event()
        old_handlers = _install_stop_handlers(loop, stop_event)
        try:
            proc = await asyncio.create_subprocess_exec(
                executable, "chat", "--in", workspace, "--query-file", "-", "--format", "stream-json",
                cwd=workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name == "posix"),
            )
        except Exception as exc:
            _restore_signal_handlers(old_handlers)
            _persist_failure(checkpoint, record, exc)
            raise
        try:
            if proc.stdin is None:
                raise SupervisionBlocked("Hermes child stdin was not captured; prompt was not safely delivered")
            proc.stdin.write(prompt.encode("utf-8"))
            await asyncio.wait_for(
                proc.stdin.drain(), timeout=max(0.001, deadline - (loop.time() - started)))
        except Exception as exc:
            _restore_signal_handlers(old_handlers)
            _persist_failure(checkpoint, record, exc)
            await _terminate_process_tree(proc, settlement_timeout)
            raise SupervisionBlocked("bounded prompt delivery failed; inspect the checkpoint and do not replay") from exc
        finally:
            if proc.stdin is not None:
                proc.stdin.close()
        if proc.stdin is not None:
            with contextlib.suppress(Exception):
                await proc.stdin.wait_closed()
        sid_future = asyncio.get_running_loop().create_future()
        process_wait = asyncio.create_task(proc.wait())
        def identified(session_id):
            persist_state(checkpoint, record, "SESSION_IDENTIFIED", status="session identified",
                          next_action="observe the captured session and generation; do not launch another prompt",
                          session_id=session_id)

        stdout_task = asyncio.create_task(_copy_stream(proc.stdout, sys.stdout,
                                                        session_id_future=sid_future, json_stream=True,
                                                        on_session_id=identified))
        stderr_task = asyncio.create_task(_copy_stream(proc.stderr, sys.stderr,
                                                         session_id_future=sid_future,
                                                         on_session_id=identified))
        session_id = None
        subscription_id = None
        generation = None
        fast_completed = False
        original_failure = None
        try:
            try:
                done, _ = await asyncio.wait((sid_future, process_wait), timeout=deadline,
                                              return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise TimeoutError
                if sid_future not in done:
                    if process_wait in done:
                        # Let the pipe readers consume their final buffered records.
                        await asyncio.gather(stdout_task, stderr_task)
                    if not sid_future.done():
                        raise SupervisionBlocked("CLI exited before exposing a session ID; execution identity "
                                                  "is unknown and outcome is ambiguous; do not retry")
                session_id = sid_future.result()
            except TimeoutError as exc:
                raise SupervisionBlocked("deadline expired before the CLI exposed its session ID; gateway "
                                          "execution may continue with an unrecoverable ambiguous outcome; "
                                          "do not retry") from exc
            capture_deadline = started + deadline
            while True:
                previous_subscription = subscription_id
                snapshot = await client.rpc("session.resume", session_id=session_id,
                                            omit_messages=True, defer_history=True)
                if not isinstance(snapshot, dict) or snapshot.get("session_id") != session_id:
                    raise SupervisionBlocked("initial session snapshot did not match the launched session")
                next_subscription = snapshot.get("subscription_id")
                if (isinstance(previous_subscription, str) and previous_subscription
                        and next_subscription != previous_subscription):
                    detached = await client.rpc("session.detach", session_id=session_id,
                                                _timeout=settlement_timeout,
                                                subscription_id=previous_subscription)
                    if (not isinstance(detached, dict) or detached.get("session_id") != session_id
                            or detached.get("subscription_id") != previous_subscription
                            or detached.get("detached") is not True):
                        raise SupervisionBlocked("superseded session subscription detach was not confirmed")
                if (type(snapshot.get("authority_epoch")) is not int
                        or snapshot["authority_epoch"] != authority_epoch):
                    raise SupervisionBlocked("initial session snapshot authority epoch did not match launch")
                subscription_id = next_subscription
                current_generation = snapshot.get("execution_generation")
                if (snapshot.get("running") is True and type(current_generation) is int
                        and current_generation >= 1 and isinstance(subscription_id, str)):
                    generation = current_generation
                    matching = [row for row in snapshot.get("pending", []) if isinstance(row, dict)
                                and row.get("execution_generation") == generation
                                and isinstance(row.get("admission_id"), str)]
                    if len(matching) != 1:
                        persist_state(checkpoint, record, "BLOCKED", status="admission identity is unavailable or conflicting",
                                      next_action="inspect the gateway admission ledger and original workspace; do not replay",
                                      generation=generation, subscription_id=subscription_id)
                        raise SupervisionBlocked("could not capture exactly one admission for the launched generation; do not replay")
                    record["admission_id"] = matching[0]["admission_id"]
                    persist_state(checkpoint, record, "RUNNING", status="running",
                                  next_action="observe this same session and generation; do not submit another turn",
                                  generation=generation, subscription_id=subscription_id,
                                  admission_id=record["admission_id"],
                                  replay_epoch=snapshot.get("replay_epoch"),
                                  last_sequence=snapshot.get("last_sequence"))
                    break
                if process_wait.done():
                    result = process_wait.result()
                    if result == 0 and snapshot.get("running") is False:
                        if not isinstance(subscription_id, str) or not subscription_id:
                            raise SupervisionBlocked("CLI exited successfully with an idle snapshot but no "
                                                      "supervisor subscription ID; outcome is ambiguous; do not replay")
                        # The CLI's own successful exit plus an exact, idle snapshot proves
                        # a fast run settled before a live generation could be observed.
                        fast_completed = True
                        persist_state(checkpoint, record, "SETTLED_UNKNOWN", status="CLI succeeded; no live generation observed",
                                      next_action="inspect original workspace and gateway receipt; do not replay",
                                      generation=current_generation if type(current_generation) is int else None,
                                      subscription_id=subscription_id)
                        break
                    raise SupervisionBlocked("CLI exited without a live generation or successful idle settlement; "
                                              "do not resume or retry")
                if asyncio.get_running_loop().time() >= capture_deadline:
                    raise SupervisionBlocked("could not capture the launched execution generation; "
                                              "execution identity is unrecoverable; do not resume or retry")
                # session.resume is a full attachment that refreshes the lease/policy.
                # Poll slowly while waiting for the launch's running generation to appear.
                await asyncio.sleep(min(1.0, capture_deadline - asyncio.get_running_loop().time()))

            if fast_completed:
                await asyncio.gather(stdout_task, stderr_task)
                # No exact admission receipt was captured. A successful CLI
                # response does not meet the supervisor's verified-completion
                # contract; fail closed rather than returning false success.
                return 125

            async def execute():
                return await process_wait

            remaining = deadline - (asyncio.get_running_loop().time() - started)
            result = await run_bounded(
                client=client, session_id=session_id, execution_generation=generation,
                authority_epoch=authority_epoch, deadline_seconds=max(0.001, remaining),
                settlement_timeout=settlement_timeout, termination_timeout=settlement_timeout,
                stop_event=stop_event,
                execute=execute,
                wait_settled=lambda sid, gen, epoch, timeout: wait_gateway_settled(
                    client, sid, gen, epoch, record["admission_id"], timeout,
                    keep_subscription_id=subscription_id),
            )
            final_state = "TERMINAL" if result == 0 else "SETTLED_UNKNOWN"
            persist_state(checkpoint, record, final_state,
                          status="CLI and exact gateway generation settled; inspect result" if result == 0
                          else "gateway generation settled but CLI returned nonzero",
                          next_action="inspect the original workspace and receipt; no replay",
                          generation=generation, subscription_id=subscription_id,
                          cli_return_code=int(result))
            return int(result)
        except Exception as exc:
            original_failure = exc
            _persist_failure(checkpoint, record, exc)
            raise
        finally:
            _restore_signal_handlers(old_handlers)
            try:
                if session_id is not None and subscription_id is not None:
                    # This detaches only this supervisor's resume subscription.
                    detached = await client.rpc("session.detach", session_id=session_id,
                                                _timeout=settlement_timeout,
                                                subscription_id=subscription_id)
                    if (not isinstance(detached, dict) or detached.get("session_id") != session_id
                            or detached.get("subscription_id") != subscription_id
                            or detached.get("detached") is not True):
                        raise SupervisionBlocked("gateway did not confirm detaching supervisor subscription")
            except Exception as exc:
                _persist_detach_unconfirmed(checkpoint, record, exc, original_failure)
                if original_failure is None:
                    if isinstance(exc, GatewayClientError):
                        raise SupervisionBlocked("could not detach supervisor subscription") from exc
                    raise
            finally:
                try:
                    await _terminate_process_tree(proc, settlement_timeout)
                except Exception as exc:
                    _persist_tree_unconfirmed(checkpoint, record, exc)
                    raise SupervisionBlocked("CLI process tree cleanup was not confirmed; do not replay") from exc
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                # A stream-json init may omit its ID. If stderr identifies the
                # execution while shutdown drains, stop only that session.
                if session_id is None and sid_future.done() and not sid_future.cancelled():
                    late_session_id = sid_future.result()
                    snapshot = await client.rpc("session.resume", session_id=late_session_id,
                                                omit_messages=True, defer_history=True)
                    if _matching_snapshot(snapshot, late_session_id, authority_epoch):
                        late_subscription = snapshot.get("subscription_id")
                        late_generation = snapshot.get("execution_generation")
                        if (snapshot.get("running") is True and type(late_generation) is int
                                and late_generation >= 1 and isinstance(late_subscription, str)):
                            response = await client.rpc("session.interrupt", session_id=late_session_id,
                                                        execution_generation=late_generation)
                            if not _handle_matches(response, late_session_id, late_generation,
                                                   authority_epoch):
                                raise SupervisionBlocked("late-session interrupt was not confirmed; outcome "
                                                          "is ambiguous; do not retry")
                            settled = await wait_gateway_idle(client, late_session_id, late_generation,
                                                              authority_epoch, settlement_timeout,
                                                              keep_subscription_id=late_subscription)
                            if settled is not True:
                                raise SupervisionBlocked("late-session interrupt did not settle; outcome "
                                                          "is ambiguous; do not retry")
                            detached = await client.rpc("session.detach", session_id=late_session_id,
                                                        _timeout=settlement_timeout,
                                                        subscription_id=late_subscription)
                            if (not isinstance(detached, dict)
                                    or detached.get("session_id") != late_session_id
                                    or detached.get("subscription_id") != late_subscription
                                    or detached.get("detached") is not True):
                                raise SupervisionBlocked("late-session subscription detach was not confirmed; "
                                                          "outcome is ambiguous; do not retry")
                        else:
                            raise SupervisionBlocked("CLI identity arrived during shutdown, but its live "
                                                      "generation could not be proved; outcome is ambiguous; "
                                                      "do not retry")
                    else:
                        raise SupervisionBlocked("CLI identity arrived during shutdown, but gateway could not "
                                                  "prove its authority epoch; outcome is ambiguous; do not retry")


async def _terminate_process_tree(proc, timeout: float) -> None:
    """Bound cleanup for the owned process group; do not leave CLI descendants behind."""
    if os.name == "posix":
        import signal
        import time

        # An owned group can be signalled only when the live child is its leader.
        # Never kill a group shared with this supervisor or a different process.
        # If the leader has exited, a surviving group cannot be authenticated
        # safely from the PID alone; block rather than risking unrelated work.
        try:
            observed_pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                # The group is absent; collect a possibly un-reaped child.
                # If it is still waiting, terminate *only the child*, never a
                # group we cannot identify. Retain the prior gateway outcome.
                if proc.returncode is None:
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=min(0.1, max(0.01, timeout)))
                    except TimeoutError:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
                return
            raise SupervisionBlocked(
                "CLI group remains but its leader identity cannot be proved; do not retry"
            )
        if observed_pgid != proc.pid or observed_pgid == os.getpgrp():
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
                except TimeoutError:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
            raise SupervisionBlocked(
                "CLI does not own an isolated process group; descendant cleanup unproven"
            )

        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            if proc.returncode is None:
                proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
        except TimeoutError:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(min(0.1, deadline - time.monotonic()))
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
            except TimeoutError:
                proc.kill()
                await proc.wait()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(min(0.1, deadline - time.monotonic()))
        else:
            raise TimeoutError("owned process group remains after SIGKILL")
    elif proc.returncode is None:
        proc.terminate()
    if proc.returncode is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
        except TimeoutError:
            proc.kill()
            await proc.wait()
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deadline", type=float, required=True, help="overall deadline in seconds")
    parser.add_argument("--settlement-timeout", type=float, default=30.0)
    parser.add_argument("--workspace-parent", help="parent directory for the retained chat workspace")
    parser.add_argument("--checkpoint", help="checkpoint path (defaults to the retained workspace)")
    parser.add_argument("--hermes", default=os.environ.get("HERMES_EXECUTABLE", "hermes"),
                        help="Hermes CLI executable (default: hermes on PATH)")
    parser.add_argument("--query-file", required=True,
                        help="read prompt from a file (use - for closed/finite stdin); never passed in argv")
    args = parser.parse_args(argv)
    try:
        if args.query_file == "-":
            if sys.stdin.isatty():
                raise ValueError("--query-file - requires finite non-interactive stdin")
            prompt_bytes = sys.stdin.buffer.read(1_000_001)
        else:
            with open(args.query_file, "rb") as source:
                prompt_bytes = source.read(1_000_001)
        if len(prompt_bytes) > 1_000_000:
            raise ValueError("prompt exceeds the 1 MB supervisor input limit")
        prompt = prompt_bytes.decode("utf-8")
        return asyncio.run(supervise_chat(prompt, deadline=args.deadline,
                                          settlement_timeout=args.settlement_timeout,
                                          executable=args.hermes, workspace_parent=args.workspace_parent,
                                          checkpoint_path=args.checkpoint))
    except Exception as exc:
        print(f"Supervisor blocked: {exc}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
