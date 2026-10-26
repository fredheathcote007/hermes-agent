"""Opt-in live FHM-004 qualification against a disposable local gateway and model stub.

Run only on an authorized Linux host with HERMES_FHM004_LIVE=1. This test starts
real Hermes processes, but all state, HTTP traffic, and temporary profiles stay
inside pytest's disposable directory and loopback.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading

import pytest

from tests.gateway.test_normal_runtime_boot import control
from tests.waiting import wait_until


pytestmark = [
    # Only an explicit opt-in test may send real signals; all targets below are
    # disposable session leaders checked against PID start ticks / cmdline.
    pytest.mark.live_system_guard_bypass,
    pytest.mark.platforms("linux"),
    pytest.mark.skipif(os.environ.get("HERMES_FHM004_LIVE") != "1",
                       reason="set HERMES_FHM004_LIVE=1 to run disposable live FHM-004 qualification"),
]

class _LoopbackModel(BaseHTTPRequestHandler):
    """Deterministic OpenAI-compatible endpoint with per-prompt crash barriers."""

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = next((message.get("content", "") for message in reversed(body.get("messages", []))
                     if message.get("role") == "user"), "")
        with self.server.requests_lock:
            self.server.requests.append({"text": text, "body": body})
        barrier = self.server.barriers.get(text)
        if barrier is not None:
            barrier[0].set()
            barrier[1].wait(90)

        message = {"role": "assistant", "content": "LOCAL_FHM004_ACK:" + str(text)}
        payload = json.dumps({"id": "fhm004-local", "choices": [{
            "index": 0, "message": message, "finish_reason": "stop",
        }], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        content_type = "application/json"
        if body.get("stream"):
            event = {"id": "fhm004-local", "choices": [{
                "index": 0, "delta": message, "finish_reason": "stop",
            }]}
            payload = ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode()
            content_type = "text/event-stream"
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _proc_info(pid: int) -> dict | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2:].split()
        return {"state": fields[0], "ppid": int(fields[1]), "pgrp": int(fields[2]),
                "start_ticks": int(fields[19])}
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
        return None


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace")
    except OSError:
        return ""


def _owned_process(proc: subprocess.Popen, start_ticks: int, *, group_leader: bool) -> bool:
    info = _proc_info(proc.pid)
    return bool(info and info["start_ticks"] == start_ticks
                and (not group_leader or info["pgrp"] == proc.pid))


def _group_has_live_process(group_id: int) -> bool:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        info = _proc_info(int(entry.name))
        if info and info["pgrp"] == group_id and info["state"] != "Z":
            return True
    return False


def _checkpoint(workspaces: Path, *, state: str | None = None) -> tuple[Path, dict] | None:
    for workspace in sorted(workspaces.glob("hermes-supervised-*"),
                            key=lambda path: path.stat().st_mtime_ns, reverse=True):
        path = workspace / "phase2-checkpoint.json"
        if path.is_file():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if state is None or record.get("state") == state:
                    return path, record
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _run_cli(root: Path, env: dict[str, str], args: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "hermes_cli/main.py"), *args],
                          cwd=root, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=timeout, check=False)


def _scan(root: Path, env: dict[str, str], parent: Path, *, observe: bool) -> tuple[int, dict]:
    args = ["gateway", "recover-orphans", "--workspace-parent", str(parent)]
    if observe:
        args.append("--observe")
    result = _run_cli(root, env, args)
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"orphan scanner did not return JSON: {result.stdout!r} {result.stderr!r}") from exc


def _admission(home: Path, admission_id: str) -> tuple[str, str, str] | None:
    database = home / "state.db"
    if not database.is_file():
        return None
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        return db.execute(
            "SELECT status, COALESCE(outcome, ''), target_session_id "
            "FROM session_admissions WHERE admission_id=?", (admission_id,),
        ).fetchone()


def _start_gateway(root: Path, home: Path, env: dict[str, str], logfile: Path):
    stream = logfile.open("w+")
    proc = subprocess.Popen([sys.executable, "-m", "gateway.run"], cwd=root, env=env,
                            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                            start_new_session=True)
    info = _proc_info(proc.pid)
    assert info is not None and info["pgrp"] == proc.pid, "gateway did not start in its owned process group"
    start_ticks = info["start_ticks"]
    try:
        ready = wait_until(lambda: _identify_ready(home), timeout=90,
                           what="disposable Hermes gateway readiness")
        assert ready.get("state") == "ready", ready
        return proc, start_ticks, ready, stream
    except BaseException:
        _stop_owned_gateway(proc, start_ticks, home, None)
        stream.close()
        raise


def _identify_ready(home: Path) -> dict | None:
    try:
        descriptor = control(home, "identify")
    except (OSError, ValueError, RuntimeError, AssertionError):
        return None
    return descriptor if descriptor.get("state") == "ready" else None


def _stop_owned_gateway(proc: subprocess.Popen, start_ticks: int, home: Path,
                        expected_instance: str | None) -> None:
    """Stop only the fixture's gateway incarnation after PID/start-time/identity checks."""
    if proc.poll() is not None:
        return
    info = _proc_info(proc.pid)
    if (not info or info["start_ticks"] != start_ticks or info["pgrp"] != proc.pid
            or "gateway.run" not in _cmdline(proc.pid)):
        return
    if expected_instance:
        try:
            descriptor = control(home, "identify")
        except (OSError, ValueError, RuntimeError):
            descriptor = None
        if descriptor is not None and descriptor.get("instance_id") != expected_instance:
            return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        info = _proc_info(proc.pid)
        if info and info["start_ticks"] == start_ticks and info["pgrp"] == proc.pid:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


def _start_supervisor(root: Path, env: dict[str, str], workspaces: Path,
                      wrapper: Path, prompt: str, logfile: Path):
    stream = logfile.open("w+")
    proc = subprocess.Popen([
        sys.executable, str(root / "hermes_cli/main.py"), "gateway", "supervise",
        "--deadline", "60", "--settlement-timeout", "4", "--workspace-parent", str(workspaces),
        "--hermes", str(wrapper), "--query-file", "-",
    ], cwd=root, env=env, stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT)
    info = _proc_info(proc.pid)
    assert info is not None
    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()
    return proc, info["start_ticks"], stream


def _owned_chat_child(supervisor: subprocess.Popen) -> tuple[int, int]:
    children_file = Path(f"/proc/{supervisor.pid}/task/{supervisor.pid}/children")
    children = [int(value) for value in children_file.read_text(encoding="ascii").split()]
    candidates = []
    for pid in children:
        info = _proc_info(pid)
        if info and info["pgrp"] == pid and "hermes_cli/main.py chat" in _cmdline(pid):
            candidates.append((pid, info["start_ticks"]))
    assert len(candidates) == 1, f"expected one isolated live Hermes chat child, got {candidates}"
    return candidates[0]


def _stop_owned_chat_group(pid: int | None, start_ticks: int | None) -> None:
    if pid is None or start_ticks is None:
        return
    info = _proc_info(pid)
    if not info or info["start_ticks"] != start_ticks or info["pgrp"] != pid:
        return
    if "hermes_cli/main.py chat" not in _cmdline(pid):
        return
    os.killpg(pid, signal.SIGTERM)
    try:
        wait_until(lambda: not _group_has_live_process(pid), timeout=5,
                   what="fixture-owned chat process group termination")
    except AssertionError:
        info = _proc_info(pid)
        if info and info["start_ticks"] == start_ticks and info["pgrp"] == pid:
            os.killpg(pid, signal.SIGKILL)
        wait_until(lambda: not _group_has_live_process(pid), timeout=5,
                   what="fixture-owned chat process group kill")


def test_live_supervisor_stop_and_killed_owner_recover_once_without_replay(tmp_path):
    """Exercise clean stop, owner SIGKILL, preview, and one same-attempt observation."""
    root = Path(__file__).resolve().parents[2]
    hermes_home = tmp_path / "profile"
    fake_home = tmp_path / "user-home"
    workspace_parent = tmp_path / "retained"
    hermes_home.mkdir(mode=0o700)
    fake_home.mkdir(mode=0o700)
    workspace_parent.mkdir(mode=0o700)
    clean_workspace_parent = tmp_path / "clean-retained"
    clean_workspace_parent.mkdir(mode=0o700)

    clean_prompt = "FHM004_LIVE_CLEAN_STOP"
    crash_prompt = "FHM004_LIVE_SUPERVISOR_KILL"
    barriers = {
        text: (threading.Event(), threading.Event())
        for text in (clean_prompt, crash_prompt)
    }
    peer = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackModel)
    peer.requests = []
    peer.requests_lock = threading.Lock()
    peer.barriers = barriers
    peer_thread = threading.Thread(target=peer.serve_forever, daemon=True)
    peer_thread.start()
    base_url = f"http://127.0.0.1:{peer.server_port}/v1"

    config = {
        "gateway": {"multiplex_profiles": False},
        "model": {"provider": "custom", "default": "fhm004-local-stub", "base_url": base_url},
        "auxiliary": {"title_generation": {"enabled": False}},
        "platform_toolsets": {"cli": []},
        "terminal": {"cwd": str(hermes_home)},
    }
    (hermes_home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    child_env = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    child_env.update({
        "HOME": str(fake_home), "USERPROFILE": str(fake_home),
        "HERMES_HOME": str(hermes_home), "PYTHONPATH": str(root),
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "OPENAI_API_KEY": "fhm004-loopback-only", "OPENAI_BASE_URL": base_url,
    })
    wrapper = tmp_path / "hermes-local"
    wrapper.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
                       f"{shlex.quote(str(root / 'hermes_cli/main.py'))} \"$@\"\n",
                       encoding="utf-8")
    wrapper.chmod(0o700)

    gateway = None
    gateway_stream = None
    supervisor = None
    supervisor_stream = None
    chat_pid = None
    chat_start_ticks = None
    try:
        gateway, gateway_start, runtime, gateway_stream = _start_gateway(
            root, hermes_home, child_env, tmp_path / "gateway.log")

        # A live, blockable inference is interrupted by SIGTERM; require the real supervisor
        # to settle the matching gateway admission and clean its isolated CLI process group.
        supervisor, supervisor_start, supervisor_stream = _start_supervisor(
            root, child_env, clean_workspace_parent, wrapper, clean_prompt,
            tmp_path / "clean-stop.log")
        assert barriers[clean_prompt][0].wait(45), "clean-stop prompt never reached the loopback model"
        clean_checkpoint = wait_until(
            lambda: _checkpoint(clean_workspace_parent), timeout=30,
            what="clean-stop supervisor checkpoint",
        )
        clean_path, clean_record = clean_checkpoint
        clean_record = wait_until(
            lambda: (record if (record := json.loads(clean_path.read_text(encoding="utf-8"))).get("state") == "RUNNING" else None),
            timeout=30, what="clean-stop checkpoint to capture exact running admission",
        )
        assert clean_record["gateway_instance_id"] == runtime["instance_id"]
        assert clean_record["gateway_profile_id"] == str(hermes_home)
        assert clean_record["gateway_authority_epoch"] == runtime["authority_epoch"]
        assert clean_record["supervisor_pid"] == supervisor.pid
        assert _proc_info(supervisor.pid)["start_ticks"] == clean_record["supervisor_start_ticks"]
        chat_pid, chat_start_ticks = _owned_chat_child(supervisor)
        assert _owned_process(supervisor, supervisor_start, group_leader=False)
        os.kill(supervisor.pid, signal.SIGTERM)
        # Release the stub after interruption has been requested; a blocked
        # HTTP handler is not an external side effect and must not indefinitely
        # hold the disposable gateway's own cancellation settlement.
        threading.Timer(1.5, barriers[clean_prompt][1].set).start()
        assert supervisor.wait(timeout=25) == 125, "bounded SIGTERM stop did not return its reviewed stop code"
        assert not _group_has_live_process(chat_pid), "clean stop left a Hermes chat process alive"
        clean_receipt = wait_until(lambda: _admission(hermes_home, clean_record["admission_id"]),
                                   timeout=10, what="clean-stop admission receipt")
        assert clean_receipt[0] == "terminal", clean_receipt
        assert clean_receipt[2] == clean_record["session_id"], clean_receipt
        barriers[clean_prompt][1].set()
        chat_pid = None
        chat_start_ticks = None

        # Start a second active turn, then kill only the supervisor owner process. The chat
        # process remains in its own recorded group until the fixture cleans it up.
        supervisor, supervisor_start, supervisor_stream = _start_supervisor(
            root, child_env, workspace_parent, wrapper, crash_prompt,
            tmp_path / "owner-kill.log")
        assert barriers[crash_prompt][0].wait(45), "crash prompt never reached the loopback model"
        running = wait_until(
            lambda: _checkpoint(workspace_parent, state="RUNNING"),
            timeout=30, what="crash-turn checkpoint to capture exact running admission",
        )
        checkpoint_path, before = running
        assert before["gateway_instance_id"] == runtime["instance_id"]
        assert before["gateway_profile_id"] == str(hermes_home)
        assert before["gateway_authority_epoch"] == runtime["authority_epoch"]
        assert before["session_id"] and before["generation"] and before["admission_id"]
        assert before["supervisor_pid"] == supervisor.pid
        assert _proc_info(supervisor.pid)["start_ticks"] == before["supervisor_start_ticks"]
        chat_pid, chat_start_ticks = _owned_chat_child(supervisor)
        assert _proc_info(chat_pid)["pgrp"] == chat_pid

        # Ownership fence before the intentional SIGKILL.
        assert _owned_process(supervisor, supervisor_start, group_leader=False)
        os.kill(supervisor.pid, signal.SIGKILL)
        assert supervisor.wait(timeout=10) == -signal.SIGKILL

        immutable = {key: before[key] for key in (
            "attempt_id", "run_id", "gateway_instance_id", "gateway_profile_id",
            "gateway_authority_epoch", "session_id", "generation", "admission_id",
        )}
        before_preview_checkpoint = checkpoint_path.read_bytes()
        before_preview_journal = checkpoint_path.with_suffix(checkpoint_path.suffix + ".jsonl").read_bytes()
        preview_rc, preview = _scan(root, child_env, workspace_parent, observe=False)
        assert preview_rc == 1, preview  # candidate found; preview intentionally makes no state changes.
        assert [row["outcome"] for row in preview["outcomes"]] == ["would_observe"], preview
        assert checkpoint_path.read_bytes() == before_preview_checkpoint, "preview changed the checkpoint"
        assert checkpoint_path.with_suffix(checkpoint_path.suffix + ".jsonl").read_bytes() == before_preview_journal, "preview changed the journal"

        threading.Timer(2.0, barriers[crash_prompt][1].set).start()
        observe_rc, observed = _scan(root, child_env, workspace_parent, observe=True)
        assert observe_rc == 1, observed  # RUNNING is observed, never reported as resolved.
        assert observed["outcomes"][0]["outcome"] == "observed", observed
        assert observed["outcomes"][0]["state"] in {"RUNNING", "TERMINAL"}, observed
        after_observe = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert {key: after_observe[key] for key in immutable} == immutable
        assert after_observe["auto_recovery_claimed_attempt_id"] == before["attempt_id"]
        journal = [json.loads(line) for line in checkpoint_path.with_suffix(checkpoint_path.suffix + ".jsonl").read_text().splitlines()]
        claims = [row for row in journal if row.get("event") == "automatic_recovery_claimed"]
        assert len(claims) == 1, claims
        assert {key: claims[0][key] for key in (
            "attempt_id", "session_id", "generation", "gateway_authority_epoch",
        )} == {key: immutable[key] for key in (
            "attempt_id", "session_id", "generation", "gateway_authority_epoch",
        )}

        repeat_rc, repeated = _scan(root, child_env, workspace_parent, observe=True)
        assert repeat_rc == 1, repeated  # existing one-shot claim remains an operator-visible skip.
        assert repeated["outcomes"][0]["outcome"] == "skipped", repeated
        repeated_journal = [json.loads(line) for line in checkpoint_path.with_suffix(checkpoint_path.suffix + ".jsonl").read_text().splitlines()]
        assert sum(row.get("event") == "automatic_recovery_claimed" for row in repeated_journal) == 1

        # The original blocked HTTP request is released after its one observation. Confirm
        # that exact admission settles and that neither recovery pass submitted another prompt.
        barriers[crash_prompt][1].set()
        final_receipt = wait_until(lambda: _admission(hermes_home, before["admission_id"]),
                                   timeout=30, what="original crash-turn admission to settle")
        assert final_receipt[0] == "terminal", final_receipt
        assert final_receipt[2] == before["session_id"], final_receipt
        wait_until(lambda: not _group_has_live_process(chat_pid), timeout=15,
                   what="orphaned original Hermes chat process to exit")
        with peer.requests_lock:
            requests = list(peer.requests)
        assert sum(row["text"] == clean_prompt for row in requests) == 1, requests
        assert sum(row["text"] == crash_prompt for row in requests) == 1, requests
        # Count actual gateway admissions, not only requests reaching the model.
        with sqlite3.connect(hermes_home / "state.db") as db:
            ids = [row[0] for row in db.execute(
                "SELECT admission_id FROM session_admissions WHERE target_session_id=?",
                (before["session_id"],))]
        assert ids == [before["admission_id"]], f"duplicate gateway admission: {ids!r}"
    finally:
        for _started, released in barriers.values():
            released.set()
        if supervisor is not None and supervisor.poll() is None:
            info = _proc_info(supervisor.pid)
            expected_start = supervisor_start if "supervisor_start" in locals() else -1
            if info and info["start_ticks"] == expected_start:
                if chat_pid is None:
                    try:
                        child_pid, child_ticks = _owned_chat_child(supervisor)
                        chat_pid, chat_start_ticks = child_pid, child_ticks
                    except (AssertionError, FileNotFoundError, ProcessLookupError):
                        pass
                os.kill(supervisor.pid, signal.SIGKILL)
            supervisor.wait(timeout=10)
        _stop_owned_chat_group(chat_pid, chat_start_ticks)
        if gateway is not None:
            _stop_owned_gateway(gateway, gateway_start, hermes_home,
                                runtime.get("instance_id") if "runtime" in locals() else None)
        if supervisor_stream is not None:
            supervisor_stream.close()
        if gateway_stream is not None:
            gateway_stream.close()
        peer.shutdown()
        peer.server_close()
        peer_thread.join(timeout=5)
