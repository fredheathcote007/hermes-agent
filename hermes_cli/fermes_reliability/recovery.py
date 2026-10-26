"""Durable, fail-closed records for the isolated Hermes supervisor."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any
from datetime import UTC

try:
    import fcntl
except ImportError:  # The command handler refuses non-Linux hosts before reaching these operations.
    fcntl = None

SCHEMA_VERSION = 3
REQUIRED = {
    "schema_version", "run_id", "attempt_id", "state", "gateway_instance_id", "gateway_profile_id",
    "gateway_authority_epoch", "session_id",
    "generation", "subscription_id", "admission_id", "submission_id", "status",
    "last_observation", "deadline", "deadline_at", "replay_epoch", "last_sequence",
    "working_dir", "next_action", "supervisor_pid", "supervisor_start_ticks", "boot_id",
}
OPTIONAL = {
    "auto_recovery_claimed_attempt_id", "auto_recovery_claimed_at", "failure_type",
    "original_failure_type", "cli_return_code",
}


def _safe_target(path: str | Path, *, must_exist: bool = False) -> Path:
    """Reject symlinked parents and non-regular checkpoint/journal files."""
    target = Path(os.path.abspath(path))
    parent = target.parent
    try:
        if parent.resolve(strict=True) != parent:
            raise ValueError("record parent must not contain symlinks")
    except OSError as exc:
        raise ValueError("record parent must already exist") from exc
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        if must_exist:
            raise ValueError("record file is missing") from None
    else:
        import stat
        if not stat.S_ISREG(mode):
            raise ValueError("record path must be a regular non-symlink file")
    return target


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def owner_identity(pid: int | None = None) -> dict[str, Any]:
    """Return a Linux process identity that detects PID reuse and host reboot."""
    process_id = os.getpid() if pid is None else pid
    if type(process_id) is not int or process_id < 1:
        raise ValueError("invalid owner pid")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    stat = Path(f"/proc/{process_id}/stat").read_text(encoding="ascii")
    # The command name is parenthesized and may contain spaces or parentheses.
    fields_after_comm = stat[stat.rfind(")") + 2:].split()
    start_ticks = int(fields_after_comm[19])  # proc stat field 22
    if not boot_id or start_ticks < 1:
        raise ValueError("process identity unavailable")
    return {"supervisor_pid": process_id, "supervisor_start_ticks": start_ticks,
            "boot_id": boot_id}


def write_checkpoint(path: str | Path, record: dict[str, Any], *,
                     expected_state: str | None = None,
                     expected_attempt_id: str | None = None) -> None:
    """Serialize writers and optionally reject stale observer results."""
    if fcntl is None:
        raise RuntimeError("durable recovery locks require Linux")
    target = _safe_target(path)
    lock_fd = os.open(str(target) + ".write.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise ValueError("checkpoint lock must be a regular file")
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if expected_state is not None or expected_attempt_id is not None:
            current = read_checkpoint(target)
            if (expected_state is not None and current.get("state") != expected_state
                    or expected_attempt_id is not None
                    and current.get("attempt_id") != expected_attempt_id):
                raise RuntimeError("checkpoint changed during recovery; newer state preserved")
        _write_checkpoint_atomic(target, record)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _write_checkpoint_atomic(path: str | Path, record: dict[str, Any]) -> None:
    """Atomically replace and fsync a checkpoint; callers must never include credentials/prompts."""
    payload = dict(record)
    payload["schema_version"] = SCHEMA_VERSION
    missing = REQUIRED - payload.keys()
    if missing:
        raise ValueError(f"checkpoint fields missing: {', '.join(sorted(missing))}")
    unexpected = payload.keys() - REQUIRED - OPTIONAL
    if unexpected:
        raise ValueError(f"checkpoint fields unsupported: {', '.join(sorted(unexpected))}")
    if not isinstance(payload["attempt_id"], str) or not payload["attempt_id"]:
        raise ValueError("attempt_id is required")
    if not isinstance(payload["run_id"], str) or not payload["run_id"]:
        raise ValueError("run_id is required")
    for key in ("gateway_instance_id", "gateway_profile_id", "boot_id"):
        if not isinstance(payload[key], str) or not payload[key]:
            raise ValueError(f"{key} is required")
    for key in ("gateway_authority_epoch", "supervisor_pid", "supervisor_start_ticks"):
        if type(payload[key]) is not int or payload[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if payload["state"] in {"RUNNING", "TERMINAL"} and (
            not isinstance(payload["session_id"], str) or not payload["session_id"]
            or type(payload["generation"]) is not int or payload["generation"] < 1
            or not isinstance(payload["admission_id"], str) or not payload["admission_id"]):
        raise ValueError("running/terminal checkpoint requires exact session, generation, and admission IDs")
    target = _safe_target(path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        _fsync_directory(target.parent)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_checkpoint(path: str | Path) -> dict[str, Any]:
    target = _safe_target(path, must_exist=True)
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("checkpoint must be a regular file")
    with os.fdopen(fd, encoding="utf-8") as stream:
        record = json.load(stream)
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported or malformed checkpoint schema")
    missing = REQUIRED - record.keys()
    if missing:
        raise ValueError(f"checkpoint fields missing: {', '.join(sorted(missing))}")
    unexpected = record.keys() - REQUIRED - OPTIONAL
    if unexpected:
        raise ValueError(f"checkpoint fields unsupported: {', '.join(sorted(unexpected))}")
    if not isinstance(record["attempt_id"], str) or not record["attempt_id"]:
        raise ValueError("invalid attempt_id")
    if not isinstance(record["run_id"], str) or not record["run_id"]:
        raise ValueError("invalid run_id")
    return record


def runtime_matches(record: dict[str, Any], runtime: object) -> bool:
    """Fence observations to the exact gateway process/profile captured at launch."""
    return (isinstance(runtime, dict)
            and type(runtime.get("authority_epoch")) is int
            and runtime.get("authority_epoch") == record.get("gateway_authority_epoch")
            and isinstance(runtime.get("instance_id"), str)
            and runtime.get("instance_id") == record.get("gateway_instance_id")
            and isinstance(runtime.get("profile_id"), str)
            and runtime.get("profile_id") == record.get("gateway_profile_id"))


def append_journal(path: str | Path, event: dict[str, Any]) -> None:
    """Append one secret-free observation and fsync before reporting recovery state."""
    if fcntl is None:
        raise RuntimeError("durable recovery locks require Linux")
    target = _safe_target(path)
    created = not target.exists()
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("journal must be a regular file")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(json.dumps({"schema_version": SCHEMA_VERSION, **event}, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    if created:
        _fsync_directory(target.parent)


def persist_state(path: str | Path, record: dict[str, Any], state: str, *, status: str,
                  next_action: str, **updates: Any) -> None:
    """Durably record a state transition in the checkpoint and append-only journal."""
    from datetime import datetime, timezone

    now = datetime.now(UTC).isoformat()
    record.update(updates, state=state, status=status, next_action=next_action,
                  last_observation={"at": now, "state": state, "status": status})
    write_checkpoint(path, record)
    append_journal(Path(path).with_suffix(Path(path).suffix + ".jsonl"), {
        "run_id": record["run_id"], "attempt_id": record["attempt_id"], "state": state, "status": status,
        "session_id": record.get("session_id"), "generation": record.get("generation"),
        "gateway_authority_epoch": record.get("gateway_authority_epoch"), "at": now,
        "subscription_id": record.get("subscription_id"), "admission_id": record.get("admission_id"),
        "submission_id": record.get("submission_id"),
        "replay_epoch": record.get("replay_epoch"), "last_sequence": record.get("last_sequence"),
    })


def reconcile(record: dict[str, Any], runtime: object, snapshot: object,
              receipt: object = None) -> dict[str, Any]:
    """Classify one exact gateway observation. Unknown/mismatched state always blocks."""
    if not isinstance(runtime, dict) or type(runtime.get("authority_epoch")) is not int:
        return {"state": "BLOCKED", "next_action": "gateway epoch unavailable; inspect gateway and workspace; do not replay"}
    if not runtime_matches(record, runtime):
        return {"state": "BLOCKED", "next_action": "gateway profile, instance, or epoch changed; inspect original workspace and admission ledger; if unknown, inspect effects and explicitly resolve with the session owner; do not replay or discard"}
    if not isinstance(record.get("session_id"), str) or not record["session_id"]:
        return {"state": "BLOCKED", "next_action": "session ID was never captured; inspect gateway history and workspace; do not replay"}
    if type(record.get("generation")) is not int or record["generation"] < 1:
        return {"state": "BLOCKED", "next_action": "generation was never captured; inspect gateway history and workspace; do not replay"}
    if not isinstance(snapshot, dict) or snapshot.get("session_id") != record["session_id"]:
        return {"state": "BLOCKED", "next_action": "session identity unavailable or conflicting; inspect gateway history; do not replay"}
    if type(snapshot.get("authority_epoch")) is not int or snapshot["authority_epoch"] != record["gateway_authority_epoch"]:
        return {"state": "BLOCKED", "next_action": "snapshot authority mismatch; inspect gateway history; do not replay"}
    if type(snapshot.get("execution_generation")) is not int or snapshot["execution_generation"] != record["generation"]:
        return {"state": "BLOCKED", "next_action": "execution generation drifted; inspect receipt and workspace; do not replay"}
    pending = snapshot.get("pending")
    if not isinstance(pending, list):
        return {"state": "BLOCKED", "next_action": "pending admission snapshot is unavailable or malformed; inspect gateway ledger; do not replay"}
    matching = []
    for row in pending:
        if not isinstance(row, dict):
            return {"state": "BLOCKED", "next_action": "pending admission row is malformed; inspect gateway ledger; do not replay"}
        admission_id = row.get("admission_id")
        if not isinstance(admission_id, str) or not admission_id:
            return {"state": "BLOCKED", "next_action": "pending admission identity is unavailable; inspect gateway ledger; do not replay"}
        status = row.get("status")
        if not isinstance(status, str) or status not in {"queued", "started", "unknown", "terminal"}:
            return {"state": "BLOCKED", "next_action": "pending admission status is unrecognized; inspect gateway ledger; do not replay"}
        generation = row.get("execution_generation")
        if generation is None:
            if admission_id == record.get("admission_id"):
                return {"state": "BLOCKED", "next_action": "matching pending admission generation is unavailable; inspect gateway ledger; do not replay"}
            continue
        if type(generation) is not int or generation < 1:
            return {"state": "BLOCKED", "next_action": "pending admission generation is unavailable; inspect gateway ledger; do not replay"}
        if generation != record["generation"] and admission_id == record.get("admission_id"):
            return {"state": "BLOCKED", "next_action": "matching admission has a conflicting execution generation; inspect gateway ledger; do not replay"}
        if generation != record["generation"]:
            continue
        matching.append(row)
    if any(row["status"] == "unknown" for row in matching):
        return {"state": "BLOCKED", "next_action": "gateway reports an unknown admission; inspect effects, then explicitly resolve with the session owner; do not replay"}
    ids = {row["admission_id"] for row in matching}
    if len(ids) > 1 or (record.get("admission_id") and ids and record["admission_id"] not in ids):
        return {"state": "BLOCKED", "next_action": "conflicting admission IDs for this generation; inspect gateway ledger; do not replay"}
    if record.get("admission_id"):
        if not isinstance(receipt, dict) or receipt.get("admission_id") != record["admission_id"]:
            return {"state": "BLOCKED", "next_action": "admission receipt unavailable or conflicting; inspect prompt.receipt manually; do not replay"}
        if (type(receipt.get("authority_epoch")) is not int
                or receipt["authority_epoch"] != record["gateway_authority_epoch"]
                or type(receipt.get("execution_generation")) is not int
                or receipt["execution_generation"] != record["generation"]):
            return {"state": "BLOCKED", "next_action": "admission receipt epoch or generation conflicts with the checkpoint; inspect gateway ledger; do not replay"}
        if receipt.get("status") == "unknown":
            return {"state": "BLOCKED", "next_action": "admission is unknown after restart; inspect effects, then explicitly resolve with the session owner; do not discard or replay"}
        if receipt.get("status") not in {"queued", "started", "terminal"}:
            return {"state": "BLOCKED", "next_action": "admission receipt status is unrecognized; human review required; do not replay"}
        if receipt.get("status") == "terminal":
            return {
                "state": "TERMINAL",
                "receipt_outcome": receipt.get("outcome"),
                "next_action": "matching terminal admission receipt observed; inspect its outcome and original workspace; no replay",
            }
    if snapshot.get("running") is True:
        return {"state": "RUNNING", "next_action": "observe this same session and generation later; do not submit another turn"}
    if snapshot.get("running") is False:
        return {"state": "SETTLED_UNKNOWN", "next_action": "inspect gateway receipt and original workspace; human decision required; do not replay"}
    return {"state": "BLOCKED", "next_action": "gateway execution state unknown; inspect original workspace and gateway; do not replay"}
