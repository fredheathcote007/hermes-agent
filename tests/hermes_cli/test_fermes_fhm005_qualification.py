"""Opt-in FHM-005 qualification against a real Hermes process and loopback model.

These tests drive the real one-shot AIAgent runtime in a disposable child
process.  The only synthetic boundary is the OpenAI-compatible model served on
127.0.0.1; the delegated child, terminal side effect, finalizer, SQLite ledger,
and restart/resume path are real Hermes code.  They are intentionally opt-in
because the tests send signals to fixture-owned process groups.

This file does not qualify gateway ingress/delivery or a trusted verifier.  A
finite one-shot turn joins its child synchronously, so detached late delivery
is covered by the focused delegate tests rather than claimed as live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
from typing import Any

import hermes_yaml as yaml
import pytest

from tests.fakes.fake_llm_provider import (
    FakeLLMServer,
    Text,
    ToolCall,
    write_hermes_home,
)
from tests.waiting import wait_until


REPO_ROOT = Path(__file__).resolve().parents[2]
_LIVE = (
    os.environ.get("HERMES_FHM005_LIVE") == "1"
    or os.environ.get("HERMES_E2E_STRICT_ACCEPTANCE") == "fhm005"
)

pytestmark = [
    pytest.mark.live_system_guard_bypass,
    pytest.mark.platforms("linux"),
    pytest.mark.skipif(
        not _LIVE,
        reason="set HERMES_FHM005_LIVE=1 (or HERMES_E2E_STRICT_ACCEPTANCE=fhm005 via the test runner)",
    ),
]


_AGENT_RUNNER = r"""
import json
import sys
from pathlib import Path

from gateway.session_context import declare_stateless_channel
from hermes_cli.oneshot import _run_agent

prompt, output_path = sys.argv[1], Path(sys.argv[2])
resume = sys.argv[3] if len(sys.argv) > 3 else None
declare_stateless_channel()
response, result = _run_agent(
    prompt,
    model="fake-model",
    provider="custom",
    toolsets=["delegation", "file", "terminal"],
    use_config_toolsets=False,
    resume=resume,
)
output_path.write_text(json.dumps({"response": response, "result": result}, default=str), encoding="utf-8")
"""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return ""


def _user_text(body: dict[str, Any]) -> str:
    return "\n".join(
        _content_text(message.get("content"))
        for message in body.get("messages", [])
        if message.get("role") == "user"
    )


def _has_tool_result(body: dict[str, Any]) -> bool:
    return any(message.get("role") == "tool" for message in body.get("messages", []))


@dataclass
class _QualificationModel:
    mode: str
    artifact: Path
    child_started: threading.Event | None = None
    release_child: threading.Event | None = None
    model_response_released: threading.Event | None = None
    parent_success_attempts: int = 0
    child_tool_calls: int = 0
    decisions: list[str] = field(default_factory=list)

    def __call__(self, record: dict[str, Any]):
        body = record["body"]
        users = _user_text(body)

        if "FHM005_RESTART" in users:
            self.decisions.append("restart_parent_text")
            return Text("FHM005_RESTART_PARENT_CLAIMS_SUCCESS")

        child_marker = f"FHM005_CHILD_{self.mode.upper()}"
        if child_marker in users:
            if not _has_tool_result(body):
                self.child_tool_calls += 1
                self.decisions.append("child_dispatch")
                if self.child_started is not None:
                    self.child_started.set()
                if self.release_child is not None:
                    self.release_child.wait(timeout=30)
                if self.model_response_released is not None:
                    self.model_response_released.set()
                if self.mode == "side_effect":
                    command = (
                        f"printf FHM005_SIDE_EFFECT > {shlex.quote(str(self.artifact))}"
                    )
                    return ToolCall("terminal", {"command": command})
                return ToolCall("read_file", {"path": str(self.artifact)})
            self.decisions.append("child_text")
            return Text(f"FHM005_CHILD_{self.mode.upper()}_COMPLETE")

        if _has_tool_result(body):
            self.parent_success_attempts += 1
            self.decisions.append("parent_success_attempt")
            return Text("FHM005_PARENT_CLAIMS_SUCCESS")

        self.decisions.append("parent_delegate")
        return ToolCall(
            "delegate_task",
            {
                "tasks": [
                    {
                        "goal": f"Run FHM005_CHILD_{self.mode.upper()} and report the result.",
                    }
                ]
            },
        )


def _configure_home(home: Path, base_url: str, project: Path, *, api_key: str) -> None:
    write_hermes_home(home, base_url, api_key=api_key)
    config_path = home / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config.update(
        {
            "agent": {**config.get("agent", {}), "max_iterations": 8},
            "approvals": {"single_query_mode": "approve"},
            "delegation": {
                "model": "fake-model",
                "base_url": base_url,
                "api_key": api_key,
            },
            "display": {"compact": True},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "terminal": {"backend": "local", "cwd": str(project)},
            "updates": {"check": False},
        }
    )
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _child_env(home: Path) -> dict[str, str]:
    allowed = {
        key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ
    }
    allowed.update(
        {
            "HOME": str(home.parent),
            "USERPROFILE": str(home.parent),
            "HERMES_HOME": str(home),
            "PYTHONPATH": str(REPO_ROOT),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HERMES_SINGLE_QUERY_SESSION": "1",
            "HERMES_ACCEPT_HOOKS": "1",
            "HERMES_VERIFY_ON_STOP": "1",
            "OPENAI_API_KEY": "fhm005-loopback-only",
        }
    )
    return allowed


def _proc_info(pid: int) -> dict[str, int] | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2 :].split()
        return {
            "state": fields[0],
            "pgrp": int(fields[2]),
            "start_ticks": int(fields[19]),
        }
    except (
        FileNotFoundError,
        ProcessLookupError,
        PermissionError,
        ValueError,
        IndexError,
    ):
        return None


def _group_has_live_process(group_id: int) -> bool:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        info = _proc_info(int(entry.name))
        if info and info["pgrp"] == group_id and info["state"] != "Z":
            return True
    return False


def _start_agent(
    home: Path,
    prompt: str,
    output_path: Path,
    log_path: Path,
    resume: str | None = None,
):
    log = log_path.open("w+")
    args = [sys.executable, "-c", _AGENT_RUNNER, prompt, str(output_path)]
    if resume:
        args.append(resume)
    process = subprocess.Popen(
        args,
        cwd=home.parent,
        env=_child_env(home),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    info = _proc_info(process.pid)
    assert info is not None and info["pgrp"] == process.pid
    return process, info["start_ticks"], log


def _stop_owned(
    process: subprocess.Popen, start_ticks: int, *, signal_number: int = signal.SIGTERM
) -> None:
    if process.poll() is not None:
        return
    info = _proc_info(process.pid)
    if not info or info["start_ticks"] != start_ticks or info["pgrp"] != process.pid:
        return
    os.killpg(process.pid, signal_number)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        info = _proc_info(process.pid)
        if info and info["start_ticks"] == start_ticks and info["pgrp"] == process.pid:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    wait_until(
        lambda: not _group_has_live_process(process.pid),
        timeout=10,
        what="fixture-owned Hermes process group cleanup",
    )


def _result(process: subprocess.Popen, output_path: Path, log: Any) -> dict[str, Any]:
    def log_text() -> str:
        log.seek(0)
        return log.read()

    def read_result() -> dict[str, Any] | None:
        if output_path.is_file():
            try:
                return json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        if process.poll() is not None:
            raise AssertionError(
                f"Hermes runner exited without result: {log.name}\n{log_text()}"
            )
        return None

    result = wait_until(
        read_result, timeout=90, what="real Hermes qualification result"
    )
    assert process.wait(timeout=10) == 0, log_text()
    return result


def _pending_rows(home: Path) -> list[dict[str, Any]]:
    database = home / "verification_evidence.db"
    if not database.is_file():
        return []
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute(
                    "SELECT session_id, attempt_id, task_index, authority, state, paths_json, unobservable "
                    "FROM delegated_verification_pending ORDER BY pending_id",
                )
            ]
    except sqlite3.Error:
        return []


def test_live_side_effect_reaches_child_but_parent_completion_fails_closed(tmp_path):
    """A real child writes a file, then a parent success response is rejected."""
    home = tmp_path / "side-effect-home"
    project = tmp_path / "side-effect-project"
    home.mkdir()
    project.mkdir()
    artifact = project / "delegated.txt"
    model = _QualificationModel("side_effect", artifact)
    with FakeLLMServer(model) as server:
        _configure_home(home, server.base_url, project, api_key="fhm005-loopback-only")
        process, start_ticks, log = _start_agent(
            home,
            "FHM005_PARENT_SIDE_EFFECT",
            tmp_path / "side-result.json",
            tmp_path / "side.log",
        )
        try:
            result = _result(process, tmp_path / "side-result.json", log)
        finally:
            _stop_owned(process, start_ticks)
            log.close()

        durable = wait_until(
            lambda: _pending_rows(home) or None,
            timeout=10,
            what="durable unresolved delegated side-effect row",
        )
        assert artifact.read_text(encoding="utf-8") == "FHM005_SIDE_EFFECT"
        assert model.parent_success_attempts >= 1, model.decisions
        assert result["result"]["completed"] is False, result
        assert result["result"]["verification_unresolved"] is True, result
        assert result["result"]["failed"] is True, result
        assert result["result"]["turn_exit_reason"] == "verification_unresolved", result
        assert "incomplete" in result["response"].lower(), result
        assert len(durable) == 1, durable
        # The child also runs verify-on-stop: its real terminal mutation makes
        # the child turn fail closed, not a successful completion receipt.
        assert durable[0]["state"] == "failed", durable
        assert durable[0]["unobservable"] == 1, durable
        assert json.loads(durable[0]["paths_json"]) == []


def test_live_pure_read_child_is_a_clean_completion_control(tmp_path):
    """A real child read-only tool can retire its exact marker after success."""
    home = tmp_path / "pure-read-home"
    project = tmp_path / "pure-read-project"
    home.mkdir()
    project.mkdir()
    artifact = project / "input.txt"
    artifact.write_text("FHM005_PURE_READ", encoding="utf-8")
    child_started = threading.Event()
    release_child = threading.Event()
    model = _QualificationModel("pure_read", artifact, child_started, release_child)
    with FakeLLMServer(model) as server:
        _configure_home(home, server.base_url, project, api_key="fhm005-loopback-only")
        process, start_ticks, log = _start_agent(
            home,
            "FHM005_PARENT_PURE_READ",
            tmp_path / "read-result.json",
            tmp_path / "read.log",
        )
        try:
            assert child_started.wait(45), "pure-read child never reached loopback model"
            armed = wait_until(
                lambda: _pending_rows(home) or None,
                timeout=10,
                what="pure-read delegated marker armed before child completes",
            )
            assert len(armed) == 1 and armed[0]["state"] == "running", armed
            release_child.set()
            result = _result(process, tmp_path / "read-result.json", log)
        finally:
            release_child.set()
            _stop_owned(process, start_ticks)
            log.close()

        assert result["result"]["completed"] is True, result
        assert result["result"].get("verification_unresolved") is not True, result
        assert result["result"].get("failed") is not True, result
        assert model.child_tool_calls == 1, model.decisions
        assert "child_dispatch" in model.decisions, model.decisions
        assert "child_text" in model.decisions, model.decisions
        assert model.parent_success_attempts >= 1, model.decisions
        # Unlike _pending_rows (which tolerates missing DB during startup), this
        # final check must fail on a missing or unreadable verification ledger.
        ledger = home / "verification_evidence.db"
        assert ledger.is_file(), "delegated child never persisted its ledger"
        with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=2) as db:
            assert db.execute("SELECT COUNT(*) FROM delegated_verification_pending").fetchone()[0] == 0


def test_live_restart_rehydrates_pending_and_does_not_replay_child(tmp_path):
    """Killing the owner before child completion leaves restart-time work incomplete."""
    home = tmp_path / "restart-home"
    project = tmp_path / "restart-project"
    home.mkdir()
    project.mkdir()
    artifact = project / "must-not-be-replayed.txt"
    child_started = threading.Event()
    release_child = threading.Event()
    model_response_released = threading.Event()
    model = _QualificationModel(
        "side_effect", artifact, child_started, release_child, model_response_released
    )
    with FakeLLMServer(model) as server:
        _configure_home(home, server.base_url, project, api_key="fhm005-loopback-only")
        first_output = tmp_path / "crash-result.json"
        process, start_ticks, log = _start_agent(
            home, "FHM005_PARENT_SIDE_EFFECT", first_output, tmp_path / "crash.log"
        )
        try:
            assert child_started.wait(45), (
                "delegated child never reached the loopback model"
            )
            durable_before = wait_until(
                lambda: _pending_rows(home) or None,
                timeout=10,
                what="pending row before owner crash",
            )
            session_id = durable_before[0]["session_id"]
            _stop_owned(process, start_ticks, signal_number=signal.SIGKILL)
            process.wait(timeout=10)
        finally:
            # Kill the identity-checked fixture group even if child readiness or
            # SQLite polling fails; never release the scripted tool action before
            # stopping the owner, or a failing test could trigger a late write.
            try:
                _stop_owned(process, start_ticks, signal_number=signal.SIGKILL)
            finally:
                release_child.set()
                log.close()

        assert model_response_released.wait(10), (
            "loopback model handler never released the blocked response"
        )
        # A model handler release is not a child-process completion signal.
        assert not _group_has_live_process(process.pid), (
            "disposable owner/delegated child process group survived SIGKILL"
        )
        assert not artifact.exists(), (
            "the killed child unexpectedly completed its side effect"
        )
        durable_after = wait_until(
            lambda: _pending_rows(home) or None,
            timeout=10,
            what="pending row after owner crash",
        )
        assert durable_after == durable_before

        restart_output = tmp_path / "restart-result.json"
        restarted, restart_ticks, restart_log = _start_agent(
            home,
            "FHM005_RESTART",
            restart_output,
            tmp_path / "restart.log",
            resume=session_id,
        )
        try:
            result = _result(restarted, restart_output, restart_log)
        finally:
            _stop_owned(restarted, restart_ticks)
            restart_log.close()

        assert result["result"]["completed"] is False, result
        assert result["result"]["verification_unresolved"] is True, result
        assert result["result"]["failed"] is True, result
        assert result["result"]["turn_exit_reason"] == "verification_unresolved", result
        assert model.child_tool_calls == 1, model.decisions
        assert not artifact.exists(), (
            "restart replayed the uncertain delegated side effect"
        )
