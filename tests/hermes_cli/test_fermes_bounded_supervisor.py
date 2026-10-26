"""Deterministic stdlib contract tests for the isolated phase1 supervisor."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
import pytest

from hermes_cli.fermes_reliability.bounded_supervisor import (
    SupervisionBlocked, run_bounded, wait_gateway_settled,
)

pytestmark = pytest.mark.platforms("linux")


class FakeClient:
    def __init__(self, interrupt=None):
        self.interrupt_result = interrupt if interrupt is not None else {
            "ref": {"profile_id": "profile-a", "session_id": "session-a"},
            "instance_id": "instance-a", "authority_epoch": 3, "revision": 9,
            "execution_generation": 7, "execution_state": "running",
        }
        self.calls = []
        self.snapshots = []

    async def rpc(self, method, **params):
        params.pop("_timeout", None)  # local client budget; not a JSON-RPC parameter
        self.calls.append((method, params))
        if method == "session.detach":
            return {"session_id": params["session_id"],
                    "subscription_id": params["subscription_id"], "detached": True}
        if isinstance(self.interrupt_result, BaseException):
            raise self.interrupt_result
        if method == "session.resume" and self.snapshots:
            return self.snapshots.pop(0)
        return self.interrupt_result


class BoundedSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_completion_writes_receipt_without_stopping(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "receipts.jsonl"
            result = await run_bounded(
                client=client, session_id="session-a", execution_generation=7,
                deadline_seconds=1, execute=self._value,
                wait_settled=self._settled, receipt_path=receipt,
            )
            events = [json.loads(line)["event"] for line in receipt.read_text().splitlines()]
        self.assertEqual(result, "done")
        self.assertEqual(client.calls, [])
        self.assertEqual(events, ["started", "completed"])

    async def test_deadline_interrupts_named_generation_and_requires_settlement(self):
        client = FakeClient()
        entered = asyncio.Event()
        stopped = asyncio.Event()
        settled = []

        async def execute():
            entered.set()
            await stopped.wait()

        async def wait(session_id, generation, epoch, timeout):
            settled.append((session_id, generation, epoch))
            stopped.set()
            return True

        with self.assertRaisesRegex(SupervisionBlocked, "stopped and settled"):
            await run_bounded(client=client, session_id="session-a", execution_generation=7,
                              deadline_seconds=0.01, execute=execute, wait_settled=wait,
                              authority_epoch=3)
        self.assertTrue(entered.is_set())
        self.assertEqual(client.calls, [("session.interrupt", {
            "session_id": "session-a", "execution_generation": 7,
        })])
        self.assertEqual(settled, [("session-a", 7, 3)])

    async def test_explicit_stop_interrupts_only_the_named_execution(self):
        client = FakeClient()
        stop = asyncio.Event()
        stopped = asyncio.Event()

        async def execute():
            await stopped.wait()
            return 130

        async def wait(*_):
            stopped.set()
            return True

        stop.set()
        with self.assertRaisesRegex(SupervisionBlocked, "stopped and settled"):
            await run_bounded(client=client, session_id="session-a", execution_generation=7,
                              authority_epoch=3, deadline_seconds=10, execute=execute,
                              wait_settled=wait, stop_event=stop)
        self.assertEqual(client.calls[0], ("session.interrupt", {
            "session_id": "session-a", "execution_generation": 7,
        }))

    async def test_interrupt_rpc_failure_blocks_without_settlement_or_retry(self):
        client = FakeClient(ConnectionError("unknown outcome"))
        attempts = []
        release = asyncio.Event()
        finished = asyncio.Event()

        async def execute():
            attempts.append("started")
            try:
                await release.wait()
            finally:
                finished.set()

        async def wait(*_):
            self.fail("must not infer settlement after RPC failure")

        with self.assertRaisesRegex(SupervisionBlocked, "unconfirmed"):
            await run_bounded(client=client, session_id="session-a", execution_generation=7,
                              deadline_seconds=0.01, execute=execute, wait_settled=wait)
        self.assertEqual(attempts, ["started"])
        self.assertFalse(finished.is_set(), "failed stop must leave the caller visibly unconfirmed/alive")
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        self.assertEqual(attempts, ["started"], "an ambiguous stop must never start a retry")

    async def test_stale_generation_refusal_blocks(self):
        client = FakeClient(RuntimeError("stale_generation"))

        async def execute():
            await asyncio.Future()

        with self.assertRaisesRegex(SupervisionBlocked, "unconfirmed"):
            await run_bounded(client=client, session_id="session-a", execution_generation=6,
                              deadline_seconds=0.01, execute=execute,
                              wait_settled=self._settled)
        self.assertEqual(client.calls[0][1]["execution_generation"], 6)

    async def test_wrong_session_generation_or_epoch_handle_blocks(self):
        for field, value in (("session_id", "other"), ("execution_generation", 8),
                             ("authority_epoch", 4)):
            handle = {"ref": {"session_id": "session-a"}, "execution_generation": 7,
                      "authority_epoch": 3, "execution_state": "running"}
            if field == "session_id":
                handle["ref"][field] = value
            else:
                handle[field] = value
            client = FakeClient(handle)

            async def execute():
                await asyncio.Future()

            with self.assertRaisesRegex(SupervisionBlocked, "unconfirmed"):
                await run_bounded(client=client, session_id="session-a", execution_generation=7,
                                  authority_epoch=3, deadline_seconds=0.01, execute=execute,
                                  wait_settled=self._settled)

    async def test_real_session_handle_running_is_transitional_then_resume_idle(self):
        client = FakeClient()
        stopped = asyncio.Event()
        client.snapshots = [
            {"session_id": "session-a", "authority_epoch": 3, "execution_generation": 7,
             "running": True, "subscription_id": "sub-a"},
            {"session_id": "session-a", "authority_epoch": 3, "execution_generation": 7,
             "running": False, "subscription_id": "sub-a"},
        ]

        async def execute():
            await stopped.wait()

        async def wait(sid, generation, epoch, timeout):
            from hermes_cli.fermes_reliability.bounded_supervisor import wait_gateway_idle
            result = await wait_gateway_idle(
                client, sid, generation, epoch, timeout, poll_interval=0.001)
            stopped.set()
            return result

        with self.assertRaisesRegex(SupervisionBlocked, "stopped and settled"):
            await run_bounded(client=client, session_id="session-a", execution_generation=7,
                              authority_epoch=3, deadline_seconds=0.01, execute=execute,
                              wait_settled=wait)
        self.assertEqual([call[0] for call in client.calls], [
            "session.interrupt", "session.resume", "session.detach",
            "session.resume", "session.detach"])
        self.assertEqual([params for method, params in client.calls if method == "session.resume"], [
            {"session_id": "session-a", "omit_messages": True, "defer_history": True},
            {"session_id": "session-a", "omit_messages": True, "defer_history": True},
        ])

    async def test_resume_generation_change_blocks(self):
        from hermes_cli.fermes_reliability.bounded_supervisor import wait_gateway_idle
        client = FakeClient()
        client.snapshots = [{"session_id": "session-a", "authority_epoch": 3,
                             "execution_generation": 8, "running": False}]
        with self.assertRaisesRegex(SupervisionBlocked, "generation changed"):
            await wait_gateway_idle(client, "session-a", 7, 3, 1)
        self.assertEqual(client.calls, [("session.resume", {
            "session_id": "session-a", "omit_messages": True, "defer_history": True})])

    async def test_settlement_requires_matching_terminal_admission_receipt(self):
        client = FakeClient()
        client.snapshots = [{"session_id": "session-a", "authority_epoch": 3,
                             "execution_generation": 7, "running": False,
                             "subscription_id": "sub-a"}]
        async def rpc(method, **params):
            if method == "session.resume":
                return client.snapshots.pop(0)
            if method == "session.detach":
                return {"session_id": params["session_id"],
                        "subscription_id": params["subscription_id"], "detached": True}
            if method == "prompt.receipt":
                return {"admission_id": "admission-a", "authority_epoch": 3,
                        "execution_generation": 7, "status": "terminal", "outcome": "interrupted"}
            raise AssertionError(method)
        client.rpc = rpc
        self.assertTrue(await wait_gateway_settled(
            client, "session-a", 7, 3, "admission-a", 1))

    async def test_unknown_receipt_blocks_settlement_without_replay(self):
        client = FakeClient()
        client.snapshots = [{"session_id": "session-a", "authority_epoch": 3,
                             "execution_generation": 7, "running": False,
                             "subscription_id": "sub-a"}]
        async def rpc(method, **params):
            if method == "session.resume":
                return client.snapshots.pop(0)
            if method == "session.detach":
                return {"session_id": params["session_id"],
                        "subscription_id": params["subscription_id"], "detached": True}
            if method == "prompt.receipt":
                return {"admission_id": "admission-a", "authority_epoch": 3,
                        "execution_generation": 7, "status": "unknown"}
            raise AssertionError(method)
        client.rpc = rpc
        with self.assertRaisesRegex(SupervisionBlocked, "unknown admission"):
            await wait_gateway_settled(client, "session-a", 7, 3, "admission-a", 1)

    async def test_gateway_client_wrapper_sends_real_interrupt_contract(self):
        import json
        import types
        from unittest.mock import patch
        from hermes_cli.fermes_reliability.bounded_supervisor import _handle_matches
        from hermes_cli.gateway_client import GatewayClient

        websockets = types.ModuleType("websockets")
        exceptions = types.ModuleType("websockets.exceptions")
        exceptions.ConnectionClosed = type("ConnectionClosed", (Exception,), {})
        websockets.exceptions = exceptions

        class Wire:
            def __init__(self):
                self.frames = asyncio.Queue()
                self.request = None

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await self.frames.get()

            async def send(self, raw):
                self.request = json.loads(raw)
                await self.frames.put(json.dumps({"id": self.request["id"], "result": {
                    "ref": {"profile_id": "profile-a", "session_id": "session-a"},
                    "instance_id": "instance-a", "authority_epoch": 3, "revision": 9,
                    "execution_generation": 7, "execution_state": "running",
                }}))

        wire = Wire()
        with patch.dict("sys.modules", {"websockets": websockets, "websockets.exceptions": exceptions}):
            async with GatewayClient(wire) as client:
                response = await client.rpc("session.interrupt", session_id="session-a",
                                            execution_generation=7)
        self.assertEqual(wire.request["method"], "session.interrupt")
        self.assertEqual(wire.request["params"], {"session_id": "session-a", "execution_generation": 7})
        self.assertTrue(_handle_matches(response, "session-a", 7, 3))
        self.assertEqual(response["execution_state"], "running")

    async def test_false_settlement_blocks_and_never_starts_another_writer(self):
        client = FakeClient()
        writers = 0

        async def execute():
            nonlocal writers
            writers += 1
            await asyncio.Future()

        async def wait(*_):
            return False

        with self.assertRaises(SupervisionBlocked):
            await run_bounded(client=client, session_id="session-a", execution_generation=7,
                              deadline_seconds=0.01, execute=execute, wait_settled=wait)
        self.assertEqual(writers, 1)

    @staticmethod
    async def _value():
        return "done"

    @staticmethod
    async def _settled(*_):
        return True


if __name__ == "__main__":
    unittest.main()
