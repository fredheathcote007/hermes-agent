"""Opt-in real gateway restart test: stale execution authority must never replay.

Requires HERMES_FHM004_LIVE=1. All process signaling is limited to uniquely
owned disposable gateway/supervisor/CLI groups, verified by PID birth identity.
"""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading

import pytest

from tests.hermes_cli.test_fermes_live_recovery import (
    _LoopbackModel,
    _checkpoint,
    _owned_chat_child,
    _proc_info,
    _scan,
    _start_gateway,
    _start_supervisor,
    _stop_owned_chat_group,
    _stop_owned_gateway,
)
from tests.waiting import wait_until


pytestmark = [
    pytest.mark.platforms("linux"),
    pytest.mark.live_system_guard_bypass,
    pytest.mark.skipif(
        os.environ.get("HERMES_FHM004_LIVE") != "1",
        reason="set HERMES_FHM004_LIVE=1 to run disposable gateway tests",
    ),
]


def test_restarted_gateway_blocks_stale_epoch_without_duplicate_admission(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home, user, spaces = (tmp_path / "profile", tmp_path / "user", tmp_path / "retained")
    for directory in (home, user, spaces):
        directory.mkdir(mode=0o700)

    request_text = "FHM004_RESTART_GATE"
    started, released = threading.Event(), threading.Event()
    peer = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackModel)
    peer.requests = []
    peer.requests_lock = threading.Lock()
    peer.barriers = {request_text: (started, released)}
    peer.daemon_threads = True
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{peer.server_port}/v1"
    (home / "config.yaml").write_text(json.dumps({
        "gateway": {"multiplex_profiles": False},
        "model": {"provider": "custom", "default": "fhm004-restart", "base_url": url},
        "auxiliary": {"title_generation": {"enabled": False}},
        "platform_toolsets": {"cli": []},
        "terminal": {"cwd": str(home)},
    }), encoding="utf-8")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    env.update({
        "HOME": str(user), "USERPROFILE": str(user), "HERMES_HOME": str(home),
        "PYTHONPATH": str(root), "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "OPENAI_API_KEY": "loopback-only",
        "OPENAI_BASE_URL": url,
    })
    wrapper = tmp_path / "hermes-local"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {root / "hermes_cli/main.py"} "$@"\n',
                       encoding="utf-8")
    wrapper.chmod(0o700)

    first_gateway = second_gateway = supervisor = None
    first_log = second_log = supervisor_log = None
    child_pid = child_ticks = None
    try:
        first_gateway, first_ticks, first_runtime, first_log = _start_gateway(
            root, home, env, tmp_path / "gateway-first.log"
        )
        supervisor, supervisor_ticks, supervisor_log = _start_supervisor(
            root, env, spaces, wrapper, request_text, tmp_path / "supervisor.log"
        )
        assert started.wait(30), "disposable model never received the admitted turn"
        checkpoint, before = wait_until(
            lambda: _checkpoint(spaces, state="RUNNING"),
            timeout=30, what="original admitted running turn",
        )
        child_pid, child_ticks = _owned_chat_child(supervisor)
        assert before["admission_id"] and before["generation"] == 1
        assert before["gateway_instance_id"] == first_runtime["instance_id"]
        assert before["gateway_authority_epoch"] == first_runtime["authority_epoch"]
        assert _proc_info(supervisor.pid)["start_ticks"] == supervisor_ticks

        os.kill(supervisor.pid, signal.SIGKILL)
        assert supervisor.wait(timeout=10) == -signal.SIGKILL
        _stop_owned_gateway(first_gateway, first_ticks, home, first_runtime["instance_id"])
        first_gateway = None
        released.set()

        second_gateway, second_ticks, second_runtime, second_log = _start_gateway(
            root, home, env, tmp_path / "gateway-second.log"
        )
        assert (second_runtime["instance_id"] != first_runtime["instance_id"]
                or second_runtime["authority_epoch"] != first_runtime["authority_epoch"])

        before_preview = checkpoint.read_bytes()
        preview_rc, preview = _scan(root, env, spaces, observe=False)
        assert preview_rc == 1 and preview["outcomes"][0]["outcome"] == "would_observe", preview
        assert checkpoint.read_bytes() == before_preview
        observe_rc, observed = _scan(root, env, spaces, observe=True)
        assert observe_rc == 1 and observed["outcomes"][0]["outcome"] == "observed", observed
        assert observed["outcomes"][0]["state"] == "BLOCKED", observed
        after = json.loads(checkpoint.read_text(encoding="utf-8"))
        assert after["attempt_id"] == before["attempt_id"]
        assert after["admission_id"] == before["admission_id"]
        assert after["state"] == "BLOCKED"
        repeated_rc, repeated = _scan(root, env, spaces, observe=True)
        assert repeated_rc == 1
        assert repeated["outcomes"][0]["outcome"] == "manual_review", repeated

        with peer.requests_lock:
            submissions = [row for row in peer.requests if row["text"] == request_text]
        assert len(submissions) == 1, "restarted gateway issued a duplicate model request"
        with sqlite3.connect(home / "state.db") as db:
            admission_ids = [row[0] for row in db.execute(
                "SELECT admission_id FROM session_admissions WHERE target_session_id=?",
                (before["session_id"],),
            )]
        assert admission_ids == [before["admission_id"]], "duplicate durable admission"
    finally:
        released.set()
        if supervisor is not None and supervisor.poll() is None:
            info = _proc_info(supervisor.pid)
            if info and info["start_ticks"] == supervisor_ticks:
                os.kill(supervisor.pid, signal.SIGKILL)
            supervisor.wait(timeout=10)
        _stop_owned_chat_group(child_pid, child_ticks)
        if second_gateway is not None:
            _stop_owned_gateway(second_gateway, second_ticks, home,
                                second_runtime["instance_id"])
        if first_gateway is not None:
            _stop_owned_gateway(first_gateway, first_ticks, home,
                                first_runtime["instance_id"])
        for stream in (first_log, second_log, supervisor_log):
            if stream is not None:
                stream.close()
        peer.shutdown()
        peer.server_close()
        thread.join(timeout=5)
