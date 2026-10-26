"""Contracts for launching and identifying the exact supervised Hermes chat."""
from __future__ import annotations

import asyncio
import argparse
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
import pytest

from hermes_cli.fermes_reliability import supervise_chat
from hermes_cli.subcommands.gateway import build_gateway_parser

pytestmark = pytest.mark.platforms("linux")


def test_gateway_reliability_cli_is_explicit_and_orphan_scan_defaults_to_preview():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_gateway_parser(subparsers, cmd_gateway=lambda _args: 0,
                         cmd_proxy=lambda _args: 0, cmd_gateway_enroll=lambda _args: 0)
    args = parser.parse_args(["gateway", "recover-orphans", "--workspace-parent", "/tmp"])
    assert args.observe is False
    assert args.func.__name__ == "cmd_recover_orphans"
    args = parser.parse_args(["gateway", "supervise", "--deadline", "30", "--query-file", "-"])
    assert args.query_file == "-"
    assert args.func.__name__ == "cmd_supervise"


class _Output:
    def __init__(self):
        self.buffer = self
        self.data = bytearray()

    def write(self, value):
        if isinstance(value, bytes):
            self.data.extend(value)
        else:
            self.data.extend(value.encode())

    def flush(self):
        pass


class _Input:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, value):
        self.data.extend(value)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class _Gateway:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def rpc(self, method, **params):
        self.calls.append((method, params))
        if method == "runtime.describe":
            return {"authority_epoch": 4, "instance_id": "gateway-x", "profile_id": "profile-x"}
        if method == "session.resume":
            return {"session_id": "session-x", "authority_epoch": 4,
                    "execution_generation": 2, "subscription_id": "sub-x", "running": False}
        if method == "session.detach":
            return {"session_id": "session-x", "subscription_id": "sub-x", "detached": True}
        if method == "prompt.receipt":
            return {"admission_id": params["admission_id"], "authority_epoch": 4,
                    "execution_generation": 2, "status": "terminal"}
        raise AssertionError(method)


class _Process:
    def __init__(self):
        self.pid = 2_000_000_000
        self.stdin = _Input()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data((json.dumps({"type": "system", "subtype": "init",
                                          "session_id": ""}) + "\n").encode())
        self.stdout.feed_eof()
        self.stderr.feed_data(b"\nSession: session-x\n")
        self.stderr.feed_eof()
        self.returncode = None

    async def wait(self):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class _PendingProcess(_Process):
    def __init__(self):
        super().__init__()
        self.returncode = None
        self.finished = asyncio.Event()

    async def wait(self):
        await self.finished.wait()
        return self.returncode

    def finish(self, code=0):
        self.returncode = code
        self.finished.set()

    def terminate(self):
        self.finish(-15)

    def kill(self):
        self.finish(-9)


class _GenerationGateway(_Gateway):
    def __init__(self, process):
        super().__init__()
        self.process = process
        self.snapshots = [
            {"session_id": "session-x", "authority_epoch": 4,
             "execution_generation": 1, "subscription_id": "sub-x", "running": False},
            {"session_id": "session-x", "authority_epoch": 4,
             "execution_generation": 2, "subscription_id": "sub-x", "running": True,
             "pending": [{"execution_generation": 2, "admission_id": "admission-x"}]},
            {"session_id": "session-x", "authority_epoch": 4,
             "execution_generation": 2, "subscription_id": "sub-x", "running": False},
        ]

    async def rpc(self, method, **params):
        if method == "session.resume":
            self.calls.append((method, params))
            snapshot = self.snapshots.pop(0)
            if snapshot["running"] is True:
                self.process.finish()
            return snapshot
        return await super().rpc(method, **params)


class _SilentProcess:
    def __init__(self):
        self.pid = 2_000_000_001
        self.stdin = _Input()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = None
        self.stopped = asyncio.Event()

    async def wait(self):
        await self.stopped.wait()
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.stopped.set()

    def kill(self):
        self.terminate()


class _LateIdentityProcess(_SilentProcess):
    def terminate(self):
        self.returncode = -15
        self.stderr.feed_data(b"Session: local-late\n")
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.stopped.set()


class SuperviseChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_init_uses_actual_stderr_session_id_and_idle_fast_completion(self):
        gateway = _Gateway()
        process = _Process()
        spawn = asyncio.Future()

        async def create(*args, **kwargs):
            launch_checkpoint = Path(kwargs["cwd"]) / "phase2-checkpoint.json"
            before_spawn = json.loads(launch_checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(before_spawn["state"], "LAUNCHING")
            self.assertEqual(before_spawn["session_id"], None)
            self.assertEqual(before_spawn["supervisor_pid"], __import__("os").getpid())
            self.assertIsInstance(before_spawn["supervisor_start_ticks"], int)
            self.assertTrue(before_spawn["boot_id"])
            spawn.set_result((args, kwargs))
            return process

        stdout, stderr = _Output(), _Output()
        with tempfile.TemporaryDirectory() as parent, redirect_stdout(stdout), redirect_stderr(stderr):
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                result = await supervise_chat.supervise_chat(
                    "inspect this", deadline=5, executable="/usr/bin/hermes", workspace_parent=parent)
            args, kwargs = await spawn
            workspace = kwargs["cwd"]
            self.assertEqual(result, 0)
            self.assertEqual(args, ("/usr/bin/hermes", "chat", "--in", workspace,
                                    "--query-file", "-", "--format", "stream-json"))
            self.assertNotIn("inspect this", args)
            self.assertEqual(bytes(process.stdin.data), b"inspect this")
            self.assertTrue(process.stdin.closed)
            self.assertTrue(Path(workspace).is_absolute())
            self.assertTrue(Path(workspace).is_dir())
            self.assertEqual(kwargs["cwd"], workspace)
            self.assertTrue(kwargs["start_new_session"])
            checkpoint_path = Path(workspace) / "phase2-checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["state"], "SETTLED_UNKNOWN")
            self.assertEqual(checkpoint["gateway_authority_epoch"], 4)
            self.assertEqual(checkpoint["session_id"], "session-x")
            self.assertNotIn("inspect this", checkpoint_path.read_text(encoding="utf-8"))
            self.assertTrue(Path(str(checkpoint_path) + ".jsonl").is_file())
            self.assertIn(b'"session_id": ""', stdout.data)
            self.assertIn(b"Session: session-x", stderr.data)
            self.assertEqual(gateway.calls[1], ("session.resume", {
                "session_id": "session-x", "omit_messages": True, "defer_history": True}))
            self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 1)

    async def test_idle_snapshot_does_not_pin_stale_generation_before_running_bump(self):
        process = _PendingProcess()
        gateway = _GenerationGateway(process)

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                result = await supervise_chat.supervise_chat(
                    "inspect this", deadline=5, executable="hermes", workspace_parent=parent)
        self.assertEqual(result, 0)
        self.assertEqual([call[0] for call in gateway.calls].count("session.resume"), 3)
        self.assertFalse(any(method == "session.interrupt" for method, _ in gateway.calls))

    async def test_detach_mismatch_overwrites_terminal_checkpoint_with_blocked(self):
        process = _PendingProcess()

        class BadDetachGateway(_Gateway):
            def __init__(self):
                super().__init__()
                self.resumes = 0

            async def rpc(self, method, **params):
                if method == "session.resume":
                    self.calls.append((method, params))
                    self.resumes += 1
                    if self.resumes == 1:
                        process.finish(0)
                        return {"session_id": "session-x", "authority_epoch": 4,
                                "execution_generation": 2, "subscription_id": "sub-x",
                                "running": True,
                                "pending": [{"execution_generation": 2, "admission_id": "admission-x"}]}
                    return {"session_id": "session-x", "authority_epoch": 4,
                            "execution_generation": 2, "subscription_id": "sub-x",
                            "running": False}
                if method == "session.detach":
                    self.calls.append((method, params))
                    return {"session_id": "session-x", "subscription_id": "other-sub", "detached": True}
                return await super().rpc(method, **params)

        gateway = BadDetachGateway()

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            checkpoint = Path(parent) / "supervisor.json"
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                with self.assertRaisesRegex(supervise_chat.SupervisionBlocked, "did not confirm"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=5, executable="hermes", workspace_parent=parent,
                        checkpoint_path=str(checkpoint))
            journal = [json.loads(line) for line in Path(str(checkpoint) + ".jsonl").read_text().splitlines()]
            self.assertEqual([row["state"] for row in journal][-2:], ["TERMINAL", "BLOCKED"])
            self.assertEqual(json.loads(checkpoint.read_text())["state"], "BLOCKED")
            self.assertEqual(journal[-1]["status"], "supervisor subscription detach unconfirmed")
        self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 1)
        self.assertTrue(all(params.get("omit_messages") is True and params.get("defer_history") is True
                            for method, params in gateway.calls if method == "session.resume"))

    async def test_confirmed_detach_keeps_successful_run_terminal(self):
        process = _PendingProcess()

        class SuccessfulGateway(_Gateway):
            def __init__(self):
                super().__init__()
                self.resumes = 0

            async def rpc(self, method, **params):
                if method == "session.resume":
                    self.calls.append((method, params))
                    self.resumes += 1
                    if self.resumes == 1:
                        process.finish(0)
                        return {"session_id": "session-x", "authority_epoch": 4,
                                "execution_generation": 2, "subscription_id": "sub-x",
                                "running": True,
                                "pending": [{"execution_generation": 2, "admission_id": "admission-x"}]}
                    return {"session_id": "session-x", "authority_epoch": 4,
                            "execution_generation": 2, "subscription_id": "sub-x",
                            "running": False}
                return await super().rpc(method, **params)

        gateway = SuccessfulGateway()

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            checkpoint = Path(parent) / "supervisor.json"
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                self.assertEqual(await supervise_chat.supervise_chat(
                    "inspect this", deadline=5, executable="hermes", workspace_parent=parent,
                    checkpoint_path=str(checkpoint)), 0)
            journal = [json.loads(line) for line in Path(str(checkpoint) + ".jsonl").read_text().splitlines()]
            self.assertEqual(json.loads(checkpoint.read_text())["state"], "TERMINAL")
            self.assertEqual(journal[-1]["state"], "TERMINAL")
        self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 1)

    async def test_detach_persistence_failure_is_reported_with_both_reasons(self):
        process = _PendingProcess()

        class DetachFailureGateway(_Gateway):
            def __init__(self):
                super().__init__()
                self.resumes = 0

            async def rpc(self, method, **params):
                if method == "session.resume":
                    self.calls.append((method, params))
                    self.resumes += 1
                    if self.resumes == 1:
                        process.finish(0)
                        return {"session_id": "session-x", "authority_epoch": 4,
                                "execution_generation": 2, "subscription_id": "sub-x",
                                "running": True,
                                "pending": [{"execution_generation": 2, "admission_id": "admission-x"}]}
                    return {"session_id": "session-x", "authority_epoch": 4,
                            "execution_generation": 2, "subscription_id": "sub-x",
                            "running": False}
                if method == "session.detach":
                    self.calls.append((method, params))
                    raise RuntimeError("detach connection lost")
                return await super().rpc(method, **params)

        gateway = DetachFailureGateway()
        real_persist = supervise_chat.persist_state

        def fail_blocked_detach(path, record, state, **kwargs):
            if state == "BLOCKED" and kwargs.get("status") == "supervisor subscription detach unconfirmed":
                raise OSError("checkpoint fsync failed")
            return real_persist(path, record, state, **kwargs)

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            checkpoint = Path(parent) / "supervisor.json"
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create), \
                    patch.object(supervise_chat, "persist_state", side_effect=fail_blocked_detach):
                with self.assertRaisesRegex(
                        supervise_chat.SupervisionBlocked,
                        "detach connection lost.*could not durably persist BLOCKED.*checkpoint fsync failed"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=5, executable="hermes", workspace_parent=parent,
                        checkpoint_path=str(checkpoint))
            # The old terminal checkpoint remains, so the propagated error must make
            # clear that BLOCKED was not durably recorded.
            self.assertEqual(json.loads(checkpoint.read_text())["state"], "TERMINAL")
        self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 1)

    async def test_idle_fast_completion_without_subscription_is_blocked(self):
        gateway = _Gateway()
        process = _Process()

        async def idle_without_subscription(method, **params):
            gateway.calls.append((method, params))
            if method == "runtime.describe":
                return {"authority_epoch": 4, "instance_id": "gateway-x", "profile_id": "profile-x"}
            if method == "session.resume":
                return {"session_id": "session-x", "authority_epoch": 4,
                        "execution_generation": 2, "running": False}
            raise AssertionError(method)

        gateway.rpc = idle_without_subscription

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            checkpoint = Path(parent) / "supervisor.json"
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                with self.assertRaisesRegex(supervise_chat.SupervisionBlocked,
                                            "no supervisor subscription ID.*ambiguous.*do not replay"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=5, executable="hermes", workspace_parent=parent,
                        checkpoint_path=str(checkpoint))
            record = json.loads(checkpoint.read_text())
            self.assertEqual(record["state"], "BLOCKED")
            self.assertIn("do not replay", record["next_action"])
        self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 0)

    async def test_stale_authority_epoch_refuses_generation_capture(self):
        gateway = _Gateway()
        gateway.rpc = _stale_epoch_rpc(gateway)
        process = _Process()

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                with self.assertRaisesRegex(supervise_chat.SupervisionBlocked, "authority epoch"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=5, executable="hermes", workspace_parent=parent)
        self.assertFalse(any(method == "session.interrupt" for method, _ in gateway.calls))

    async def test_late_reliable_identity_is_interrupted_once_after_cli_shutdown(self):
        process = _LateIdentityProcess()

        class LateGateway(_Gateway):
            def __init__(self):
                super().__init__()
                self.interrupted = False

            async def rpc(self, method, **params):
                self.calls.append((method, params))
                if method == "runtime.describe":
                    return {"authority_epoch": 4, "instance_id": "gateway-x", "profile_id": "profile-x"}
                if method == "session.resume":
                    return {"session_id": "local-late", "authority_epoch": 4,
                            "execution_generation": 8, "subscription_id": "sub-late",
                            "running": not self.interrupted}
                if method == "session.interrupt":
                    self.interrupted = True
                    return {"ref": {"session_id": "local-late"}, "execution_generation": 8,
                            "authority_epoch": 4, "execution_state": "running"}
                if method == "session.detach":
                    return {"session_id": "local-late", "subscription_id": "sub-late", "detached": True}
                raise AssertionError(method)

        gateway = LateGateway()

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                with self.assertRaisesRegex(supervise_chat.SupervisionBlocked, "unrecoverable ambiguous"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=0.01, settlement_timeout=1, workspace_parent=parent)
        self.assertEqual([method for method, _ in gateway.calls].count("session.interrupt"), 1)
        self.assertEqual([method for method, _ in gateway.calls].count("session.resume"), 2)
        self.assertTrue(all(
            params.get("session_id") == "local-late"
            and params.get("omit_messages") is True
            and params.get("defer_history") is True
            for method, params in gateway.calls if method == "session.resume"
        ))

    async def test_missing_identity_blocks_and_stops_cli_without_retry(self):
        gateway = _Gateway()
        process = _SilentProcess()

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent:
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                with self.assertRaisesRegex(supervise_chat.SupervisionBlocked, "unrecoverable ambiguous"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=0.01, settlement_timeout=1, workspace_parent=parent)
        self.assertEqual(process.returncode, -15)
        self.assertEqual([method for method, _ in gateway.calls], ["runtime.describe"])

    async def test_gateway_failure_after_session_identification_journals_blocked(self):
        gateway = _Gateway()

        async def fail_resume(method, **params):
            gateway.calls.append((method, params))
            if method == "runtime.describe":
                return {"authority_epoch": 4, "instance_id": "gateway-x", "profile_id": "profile-x"}
            if method == "session.resume":
                raise RuntimeError("gateway unavailable")
            raise AssertionError(method)

        gateway.rpc = fail_resume
        process = _Process()

        async def create(*_args, **_kwargs):
            return process

        with tempfile.TemporaryDirectory() as parent, redirect_stdout(_Output()), redirect_stderr(_Output()):
            checkpoint = Path(parent) / "supervisor.json"
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway), \
                    patch.object(asyncio, "create_subprocess_exec", side_effect=create):
                with self.assertRaisesRegex(RuntimeError, "gateway unavailable"):
                    await supervise_chat.supervise_chat(
                        "inspect this", deadline=5, executable="hermes", workspace_parent=parent,
                        checkpoint_path=str(checkpoint))
            self.assertEqual(json.loads(checkpoint.read_text())["state"], "BLOCKED")
            journal = [json.loads(line) for line in Path(str(checkpoint) + ".jsonl").read_text().splitlines()]
            self.assertEqual([row["state"] for row in journal],
                             ["LAUNCHING", "SESSION_IDENTIFIED", "BLOCKED"])
            self.assertEqual(journal[-1]["status"], "supervision failed")

    def test_session_id_parser_reads_stream_init_and_stderr_contract(self):
        init = json.dumps({"type": "system", "subtype": "init", "session_id": "sid"}).encode()
        self.assertEqual(supervise_chat._session_id_from_line(init, json_stream=True), "sid")
        self.assertEqual(supervise_chat._session_id_from_line(b"session_id: sid", json_stream=False), "sid")
        self.assertEqual(supervise_chat._session_id_from_line(b"Session: local-123", json_stream=False),
                         "local-123")
        self.assertIsNone(supervise_chat._session_id_from_line(
            b'{"type":"system","subtype":"init","session_id":""}', json_stream=True))
        self.assertIsNone(supervise_chat._session_id_from_line(b"not json", json_stream=True))


def _stale_epoch_rpc(gateway):
    async def rpc(method, **params):
        gateway.calls.append((method, params))
        if method == "runtime.describe":
            return {"authority_epoch": 4, "instance_id": "gateway-x", "profile_id": "profile-x"}
        if method == "session.resume":
            return {"session_id": "session-x", "authority_epoch": 3,
                    "execution_generation": 9, "subscription_id": "sub-x", "running": True}
        if method == "session.detach":
            return {"session_id": "session-x", "subscription_id": "sub-x", "detached": True}
        raise AssertionError(method)
    return rpc


if __name__ == "__main__":
    unittest.main()
