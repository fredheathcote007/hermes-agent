#!/usr/bin/env python3
"""Safely observe abandoned phase 2 attempts in one explicitly selected parent."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone, UTC
import json
import os
import stat
from pathlib import Path
import tempfile
import sys
from typing import Any

try:
    import fcntl
except ImportError:  # The CLI gates scanning to Linux before importing this module.
    fcntl = None

from hermes_cli.fermes_reliability.recover_attempt import recover
from hermes_cli.fermes_reliability.recovery import append_journal, read_checkpoint, write_checkpoint

MAX_WORKSPACES = 100
INCOMPLETE_STATES = {"LAUNCHING", "SESSION_IDENTIFIED", "RUNNING", "SETTLED_UNKNOWN"}
TERMINAL_STATES = {"TERMINAL", "COMPLETE", "COMPLETED"}
WORKSPACE_PREFIX = "hermes-supervised-"


def _needs_attention(outcomes: list[dict[str, Any]]) -> bool:
    """Flag outcomes that leave an attempt or scan result unresolved for an operator."""
    for row in outcomes:
        outcome = row.get("outcome")
        if outcome in {"active", "locked"}:
            continue
        return True
    return False


def _live_owner(record: dict[str, Any]) -> tuple[str, str]:
    pid = record.get("supervisor_pid")
    ticks = record.get("supervisor_start_ticks")
    boot_id = record.get("boot_id")
    if type(pid) is not int or pid < 1 or type(ticks) is not int or ticks < 1 or not isinstance(boot_id, str) or not boot_id:
        return "manual_review", "owner identity missing or malformed"
    try:
        current_boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return "manual_review", "current boot identity unavailable"
    if current_boot != boot_id:
        return "manual_review", "owner boot identity does not match this host boot"
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return "abandoned", "owner process is absent on the recorded boot"
    except (PermissionError, OSError):
        return "manual_review", "owner process identity cannot be inspected"
    fields_after_comm = stat[stat.rfind(")") + 2:].split()
    if len(fields_after_comm) <= 19:
        return "manual_review", "owner process stat is malformed"
    try:
        current_ticks = int(fields_after_comm[19])
    except ValueError:
        return "manual_review", "owner process start time is malformed"
    if current_ticks != ticks:
        return "manual_review", "owner PID has a different start time"
    return "active", "owner process identity is still live"


def _valid_parent(path: Path) -> Path:
    """Treat the caller's exact canonical parent as the scan allowlist root."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("workspace parent must be an absolute, non-symlink path")
    current = Path("/")
    for component in path.parts[1:]:
        current /= component
        try:
            mode = current.lstat().st_mode
        except OSError:
            raise ValueError("workspace parent must be an existing, non-symlink path") from None
        if stat.S_ISLNK(mode):
            raise ValueError("workspace parent must be an absolute, non-symlink path")
    parent = path.resolve(strict=True)
    if not parent.is_dir() or parent == Path("/").resolve() or parent == Path.home().resolve():
        raise ValueError("workspace parent is outside the permitted scan boundary")
    return parent


def _atomic_report(path: Path, report: dict[str, Any]) -> None:
    from hermes_cli.fermes_reliability.recovery import _fsync_directory, _safe_target
    path = _safe_target(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _candidate_mtime(entry: Path) -> int:
    try:
        return entry.stat(follow_symlinks=False).st_mtime_ns
    except OSError:
        return 0


async def _recover_locked(checkpoint: Path) -> dict[str, Any]:
    """Re-read after locking, then invoke the existing same-session observer once."""
    record = read_checkpoint(checkpoint)
    state = record.get("state")
    if not isinstance(state, str) or state not in INCOMPLETE_STATES:
        return {"outcome": "skipped", "reason": "checkpoint is no longer eligible"}
    if not isinstance(record.get("session_id"), str) or not record["session_id"]:
        return {"outcome": "manual_review", "reason": "session identity is unavailable"}
    if (type(record.get("gateway_authority_epoch")) is not int
            or record["gateway_authority_epoch"] < 1):
        return {"outcome": "manual_review", "reason": "gateway epoch is unavailable"}
    if type(record.get("generation")) is not int or record["generation"] < 1:
        return {"outcome": "manual_review", "reason": "execution generation is unavailable"}
    if Path(str(record.get("working_dir", ""))).resolve() != checkpoint.parent.resolve():
        return {"outcome": "manual_review", "reason": "checkpoint workspace path changed"}
    owner_state, owner_reason = _live_owner(record)
    if owner_state != "abandoned":
        return {"outcome": owner_state, "reason": owner_reason}

    claim_attempt = record.get("auto_recovery_claimed_attempt_id")
    claim_time = record.get("auto_recovery_claimed_at")
    if claim_attempt is not None or claim_time is not None:
        if claim_attempt == record["attempt_id"] and isinstance(claim_time, str) and claim_time:
            return {"outcome": "skipped", "reason": "automatic recovery was already claimed for this attempt"}
        return {"outcome": "manual_review", "reason": "automatic recovery claim is malformed or belongs to another attempt"}

    # Claim before attaching: session.resume can trigger gateway-side continuation even
    # when it only returns RUNNING. A crash after this durable write must not reattach.
    record["auto_recovery_claimed_at"] = datetime.now(UTC).isoformat()
    record["auto_recovery_claimed_attempt_id"] = record["attempt_id"]
    write_checkpoint(checkpoint, record, expected_state=state,
                     expected_attempt_id=record["attempt_id"])
    append_journal(checkpoint.with_suffix(checkpoint.suffix + ".jsonl"), {
        "run_id": record["run_id"], "attempt_id": record["attempt_id"], "state": state,
        "event": "automatic_recovery_claimed", "at": record["auto_recovery_claimed_at"],
        "session_id": record.get("session_id"), "generation": record.get("generation"),
        "gateway_authority_epoch": record.get("gateway_authority_epoch"),
    })
    observed = await recover(checkpoint, expected_state=state,
                              expected_attempt_id=record["attempt_id"], _claim_owned=True)
    return {"outcome": "observed", "state": observed.get("state"),
            "reason": observed.get("next_action")}


async def scan(workspace_parent: Path, *, limit: int = MAX_WORKSPACES, observe: bool = False,
               report_path: Path | None = None) -> dict[str, Any]:
    if fcntl is None:
        raise RuntimeError("orphan scanning requires Linux")
    parent = _valid_parent(workspace_parent)
    if type(limit) is not int or not 1 <= limit <= MAX_WORKSPACES:
        raise ValueError(f"limit must be between 1 and {MAX_WORKSPACES}")
    outcomes: list[dict[str, Any]] = []
    candidates = sorted((entry for entry in parent.iterdir()
                         if entry.name.startswith(WORKSPACE_PREFIX)),
                        key=lambda item: (-_candidate_mtime(item), item.name))
    for workspace in candidates[:limit]:
        item: dict[str, Any] = {"workspace": str(workspace)}
        if workspace.is_symlink() or not workspace.is_dir():
            item.update(outcome="manual_review", reason="workspace is not a real direct-child directory")
            outcomes.append(item)
            continue
        resolved = workspace.resolve(strict=True)
        if resolved.parent != parent:
            item.update(outcome="manual_review", reason="workspace escapes the selected parent")
            outcomes.append(item)
            continue
        checkpoint = resolved / "phase2-checkpoint.json"
        if not checkpoint.is_file() or checkpoint.is_symlink():
            item.update(outcome="manual_review", reason="checkpoint is missing or not a regular file")
            outcomes.append(item)
            continue
        try:
            record = read_checkpoint(checkpoint)
        except Exception as exc:
            item.update(outcome="manual_review", reason=f"checkpoint is malformed ({type(exc).__name__})")
            outcomes.append(item)
            continue
        state = record.get("state")
        if not isinstance(state, str):
            item.update(outcome="manual_review", reason="checkpoint state has an invalid type")
            outcomes.append(item)
            continue
        if state in TERMINAL_STATES:
            item.update(outcome="skipped", reason="attempt is already terminal")
            outcomes.append(item)
            continue
        if state == "BLOCKED":
            item.update(outcome="manual_review", reason="BLOCKED requires operator review")
            outcomes.append(item)
            continue
        if state not in INCOMPLETE_STATES:
            item.update(outcome="manual_review", reason="checkpoint state is unknown")
            outcomes.append(item)
            continue
        if Path(str(record.get("working_dir", ""))).resolve() != resolved:
            item.update(outcome="manual_review", reason="checkpoint workspace path does not match")
            outcomes.append(item)
            continue
        owner_state, owner_reason = _live_owner(record)
        if owner_state != "abandoned":
            item.update(outcome=owner_state, reason=owner_reason)
            outcomes.append(item)
            continue
        if not observe:
            item.update(outcome="would_observe", reason="orphan candidate; pass --observe to claim once and attach read-only")
            outcomes.append(item)
            continue
        lock_path = checkpoint.with_name(checkpoint.name + ".recovery.lock")
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(lock_fd, "a", encoding="ascii") as lock_file:
                if not stat.S_ISREG(os.fstat(lock_file.fileno()).st_mode):
                    raise OSError("checkpoint lock is not a regular file")
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    item.update(outcome="locked", reason="another scanner owns this checkpoint")
                else:
                    try:
                        result = await _recover_locked(checkpoint)
                    except Exception as exc:
                        result = {"outcome": "manual_review",
                                  "reason": f"recovery failed closed ({type(exc).__name__})"}
                    item.update(result)
        except OSError as exc:
            item.update(outcome="manual_review", reason=f"checkpoint lock unavailable ({type(exc).__name__})")
        outcomes.append(item)
    if len(candidates) > limit:
        outcomes.append({"outcome": "limit_reached",
                         "reason": f"only the {limit} most recently modified workspaces scanned; older workspaces remain in the visible backlog"})
    result = {"at": datetime.now(UTC).isoformat(), "workspace_parent": str(parent),
              "attention_required": _needs_attention(outcomes), "outcomes": outcomes}
    if report_path is not None:
        _atomic_report(report_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-parent", required=True, type=Path,
                        help="exact scan allowlist root; only direct-child supervised workspaces are considered")
    parser.add_argument("--limit", type=int, default=MAX_WORKSPACES,
                        help=f"maximum workspaces to inspect (1-{MAX_WORKSPACES})")
    parser.add_argument("--observe", action="store_true",
                        help="explicitly claim and observe orphan attempts once; never submits or replays prompts")
    parser.add_argument("--report", type=Path,
                        help="atomic JSON outcome report (defaults to parent/.phase2-recovery-report.json)")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(scan(
            args.workspace_parent, limit=args.limit, observe=args.observe,
            report_path=args.report or args.workspace_parent / ".phase2-recovery-report.json"))
    except Exception as exc:
        result = {"outcome": "error", "reason": f"scan refused ({type(exc).__name__})"}
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return int(result["attention_required"])


if __name__ == "__main__":
    sys.exit(main())
