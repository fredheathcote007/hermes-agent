"""Behavior contracts for durable, observation-only attempt recovery."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import pytest
from hermes_cli.fermes_reliability import recover_attempt
from hermes_cli.fermes_reliability.recovery import (
    append_journal, owner_identity, persist_state, read_checkpoint, reconcile, runtime_matches,
    write_checkpoint,
)

pytestmark = pytest.mark.platforms("linux")


def checkpoint():
    return {
        "run_id": "run-a", "attempt_id": "attempt-a", "state": "RUNNING", "status": "running",
        "gateway_instance_id": "gateway-a", "gateway_profile_id": "profile-a",
        "gateway_authority_epoch": 7, "session_id": "local-session-a", "generation": 4,
        "subscription_id": "sub-a", "admission_id": "admission-a", "submission_id": None,
        "last_observation": None, "deadline": 100, "deadline_at": time.time(),
        "replay_epoch": "epoch-a", "last_sequence": 0, "working_dir": "/tmp/project",
        "next_action": "observe only", **owner_identity(),
    }


class _Gateway:
    def __init__(self, snapshot=None, receipt=None):
        self.calls = []
        self.snapshot = snapshot or {
            "session_id": "local-session-a", "authority_epoch": 7,
            "execution_generation": 4, "subscription_id": "sub-a", "running": True, "pending": [],
        }
        self.receipt = receipt or {
            "admission_id": "admission-a", "authority_epoch": 7,
            "execution_generation": 4, "status": "started",
        }
        self.receipt_error = False
        self.detach_response = {"session_id": "local-session-a", "subscription_id": "sub-a", "detached": True}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def rpc(self, method, **params):
        self.calls.append((method, params))
        if method == "runtime.describe":
            return {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}
        if method == "session.resume":
            return self.snapshot
        if method == "prompt.receipt":
            if self.receipt_error:
                raise RuntimeError("receipt unavailable")
            return self.receipt
        if method == "session.detach":
            return self.detach_response
        raise AssertionError(f"unexpected RPC: {method}")


class RecoveryTests(unittest.TestCase):
    def test_checkpoint_state_transitions_are_durable_and_secret_free(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            record = checkpoint()
            record["state"] = "LAUNCHING"
            record["session_id"] = None
            record["generation"] = None
            persist_state(path, record, "LAUNCHING", status="launching", next_action="await launch")
            first = read_checkpoint(path)
            self.assertEqual(first["state"], "LAUNCHING")
            self.assertEqual(first["attempt_id"], "attempt-a")
            persist_state(path, record, "SESSION_IDENTIFIED", status="session identified",
                          next_action="observe only", session_id="local-session-a")
            persist_state(path, record, "RUNNING", status="running", next_action="observe only",
                          generation=4, subscription_id="sub-a", admission_id="admission-a")
            stored = path.read_text(encoding="utf-8")
            self.assertNotIn("prompt text", stored)
            self.assertNotIn("secret", stored)
            self.assertEqual(read_checkpoint(path)["state"], "RUNNING")
            rows = [json.loads(line) for line in path.with_suffix(".json.jsonl").read_text().splitlines()]
            self.assertEqual([row["state"] for row in rows], ["LAUNCHING", "SESSION_IDENTIFIED", "RUNNING"])

    def test_recovery_uses_exact_attach_payload_and_receipt_without_submission(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            write_checkpoint(path, checkpoint())
            gateway = _Gateway()
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway):
                result = asyncio.run(recover_attempt.recover(path))
            self.assertEqual(result["state"], "RUNNING")
            self.assertEqual(gateway.calls, [
                ("runtime.describe", {}),
                ("session.resume", {"session_id": "local-session-a", "omit_messages": True,
                                   "defer_history": True}),
                ("prompt.receipt", {"session_id": "local-session-a", "admission_id": "admission-a",
                                     "include_result": False}),
                ("session.detach", {"session_id": "local-session-a", "subscription_id": "sub-a"}),
            ])
            self.assertNotIn("prompt.submit", [method for method, _ in gateway.calls])
            resume = next(params for method, params in gateway.calls if method == "session.resume")
            self.assertEqual(resume, {"session_id": "local-session-a", "omit_messages": True,
                                      "defer_history": True})
            self.assertNotIn("lazy", resume)

    def test_missing_admission_uses_reliable_bounded_event_replay(self):
        class EventGateway(_Gateway):
            async def rpc(self, method, **params):
                if method == "session.resume":
                    self.calls.append((method, params))
                    return {**self.snapshot, "replay_epoch": "epoch-a", "last_sequence": 12}
                if method == "session.events.since":
                    self.calls.append((method, params))
                    return {
                        "replay_epoch": "epoch-a", "truncated": False,
                        "snapshot_required": False, "latest_seq": 13,
                        "events": [{"type": "message.complete", "session_id": "local-session-a",
                                    "authority_epoch": 7, "execution_generation": 4, "seq": 13}],
                    }
                return await super().rpc(method, **params)

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            record = checkpoint()
            record["admission_id"] = None
            # A pending launch without admission cannot be certified RUNNING.
            record["state"] = "SESSION_IDENTIFIED"
            record["deadline_at"] = time.time() + 10
            write_checkpoint(path, record)
            gateway = EventGateway()
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway):
                result = asyncio.run(recover_attempt.recover(path))
            self.assertEqual(result["state"], "BLOCKED")
            self.assertIn("admission ID is absent", result["next_action"])
            self.assertEqual(gateway.calls[1], (
                "session.resume", {"session_id": "local-session-a", "omit_messages": True,
                                   "defer_history": True}))
            self.assertEqual(gateway.calls[2], (
                "session.events.since", {"session_id": "local-session-a", "last_sequence": 12,
                                          "replay_epoch": "epoch-a"}))
            self.assertEqual(gateway.calls[-1][0], "session.detach")

    def test_operator_blocked_checkpoint_never_reopens_from_standalone_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            record = checkpoint()
            record["state"] = "BLOCKED"
            record["next_action"] = "operator inspect original effects"
            write_checkpoint(path, record)
            with patch("hermes_cli.gateway_client.connect_gateway",
                       side_effect=AssertionError("must never attach")):
                with self.assertRaisesRegex(RuntimeError, "operator resolution"):
                    asyncio.run(recover_attempt.recover(path))
            preserved = read_checkpoint(path)
            self.assertEqual(preserved["state"], "BLOCKED")
            self.assertEqual(preserved["next_action"], "operator inspect original effects")

    def test_epoch_drift_and_missing_identity_block_before_attach(self):
        record = checkpoint()
        self.assertEqual(reconcile(record, {"authority_epoch": 8}, None)["state"], "BLOCKED")
        record["session_id"] = None
        self.assertIn("session ID", reconcile(record, {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}, None)["next_action"])
        record["session_id"] = "local-session-a"
        record["generation"] = None
        self.assertIn("generation", reconcile(record, {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}, None)["next_action"])

    def test_reconcile_fences_same_epoch_to_exact_gateway_instance_and_profile(self):
        record = checkpoint()
        runtime = {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}
        self.assertTrue(runtime_matches(record, runtime))
        self.assertFalse(runtime_matches(record, {**runtime, "instance_id": "replacement"}))
        self.assertFalse(runtime_matches(record, {**runtime, "profile_id": "another-profile"}))
        mismatch = reconcile(record, {**runtime, "instance_id": "replacement"}, None)
        self.assertEqual(mismatch["state"], "BLOCKED")
        self.assertIn("instance", mismatch["next_action"])

    def test_generation_drift_unknown_conflict_and_unavailable_receipt_block(self):
        record = checkpoint()
        runtime = {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}
        snapshot = {"session_id": "local-session-a", "authority_epoch": 7,
                    "execution_generation": 5, "running": False}
        self.assertIn("generation drifted", reconcile(record, runtime, snapshot)["next_action"])
        snapshot["execution_generation"] = 4
        snapshot["pending"] = [{"admission_id": "admission-a", "execution_generation": 4, "status": "unknown"}]
        self.assertIn("unknown admission", reconcile(record, runtime, snapshot)["next_action"])
        self.assertIn("unknown admission", reconcile(record, runtime, snapshot, None)["next_action"])
        snapshot["pending"] = [
            {"admission_id": "admission-a", "execution_generation": 4, "status": "started"},
            {"admission_id": "admission-b", "execution_generation": 4, "status": "started"},
        ]
        self.assertIn("conflicting admission", reconcile(record, runtime, snapshot)["next_action"])
        snapshot["pending"] = []
        self.assertIn("receipt unavailable", reconcile(record, runtime, snapshot, None)["next_action"])

    def test_malformed_pending_snapshot_blocks_even_with_terminal_receipt(self):
        record = checkpoint()
        runtime = {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}
        receipt = {"admission_id": "admission-a", "authority_epoch": 7,
                   "execution_generation": 4, "status": "terminal"}
        base = {"session_id": "local-session-a", "authority_epoch": 7,
                "execution_generation": 4, "running": False}
        for pending in (None, [{"admission_id": "admission-a", "execution_generation": 4,
                                "status": "future-status"}],
                        [{"admission_id": "admission-a", "execution_generation": 4,
                          "status": ["terminal"]}],
                        [{"admission_id": "admission-a", "execution_generation": None,
                          "status": "started"}],
                        [{"admission_id": "admission-a", "execution_generation": 5,
                          "status": "terminal"}]):
            with self.subTest(pending=pending):
                result = reconcile(record, runtime, {**base, "pending": pending}, receipt)
                self.assertEqual(result["state"], "BLOCKED")
                self.assertNotEqual(result.get("receipt_outcome"), "terminal")

        queued = {**base, "pending": [{"admission_id": "later-admission",
                                        "execution_generation": None, "status": "queued"}]}
        self.assertEqual(reconcile(record, runtime, queued, receipt)["state"], "TERMINAL")

    def test_receipt_failure_and_detach_failure_block_after_one_attach(self):
        for failure in ("receipt", "detach"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "state.json"
                write_checkpoint(path, checkpoint())
                gateway = _Gateway()
                if failure == "receipt":
                    gateway.receipt_error = True
                else:
                    gateway.detach_response = {"session_id": "local-session-a", "subscription_id": "wrong",
                                               "detached": True}
                with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway):
                    result = asyncio.run(recover_attempt.recover(path))
                self.assertEqual(result["state"], "BLOCKED")
                self.assertEqual([method for method, _ in gateway.calls].count("session.resume"), 1)
                self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 1)
                self.assertNotIn("prompt.submit", [method for method, _ in gateway.calls])

    def test_unknown_admission_blocks_and_detaches(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            write_checkpoint(path, checkpoint())
            gateway = _Gateway(
                snapshot={"session_id": "local-session-a", "authority_epoch": 7,
                          "execution_generation": 4, "subscription_id": "sub-a", "running": True,
                          "pending": [{"admission_id": "admission-a", "execution_generation": 4,
                                       "status": "unknown"}]},
                receipt={"admission_id": "admission-a", "authority_epoch": 7,
                         "execution_generation": 4, "status": "unknown"},
            )
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway):
                result = asyncio.run(recover_attempt.recover(path))
            self.assertEqual(result["state"], "BLOCKED")
            self.assertIn("unknown admission", result["next_action"])
            self.assertEqual([method for method, _ in gateway.calls].count("session.resume"), 1)
            self.assertEqual([method for method, _ in gateway.calls].count("session.detach"), 1)

    def test_running_and_terminal_are_observations_never_replay(self):
        record = checkpoint()
        runtime = {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}
        snapshot = {"session_id": "local-session-a", "authority_epoch": 7,
                    "execution_generation": 4, "running": True, "pending": []}
        receipt = {"admission_id": "admission-a", "authority_epoch": 7,
                   "execution_generation": 4, "status": "started"}
        self.assertEqual(reconcile(record, runtime, snapshot, receipt)["state"], "RUNNING")
        snapshot["running"] = False
        receipt["status"] = "terminal"
        self.assertEqual(reconcile(record, runtime, snapshot, receipt)["state"], "TERMINAL")
        receipt["status"] = "unknown"
        self.assertEqual(reconcile(record, runtime, snapshot, receipt)["state"], "BLOCKED")

    def test_terminal_receipt_supersedes_same_generation_running_snapshot(self):
        record = checkpoint()
        runtime = {"authority_epoch": 7, "instance_id": "gateway-a", "profile_id": "profile-a"}
        snapshot = {"session_id": "local-session-a", "authority_epoch": 7,
                    "execution_generation": 4, "running": True, "pending": []}
        receipt = {"admission_id": "admission-a", "authority_epoch": 7,
                   "execution_generation": 4, "status": "terminal", "outcome": "error"}

        result = reconcile(record, runtime, snapshot, receipt)

        self.assertEqual(result["state"], "TERMINAL")
        self.assertEqual(result["receipt_outcome"], "error")
        self.assertNotIn("successful", result["next_action"])
        for field, value in (("admission_id", "other-admission"),
                             ("authority_epoch", 8), ("execution_generation", 5)):
            with self.subTest(field=field):
                mismatched = {**receipt, field: value}
                self.assertEqual(reconcile(record, runtime, snapshot, mismatched)["state"], "BLOCKED")
        self.assertEqual(
            reconcile(record, runtime, snapshot, {**receipt, "status": "unknown"})["state"],
            "BLOCKED",
        )

    def test_ten_crash_recovery_points_keep_one_attempt_and_never_submit(self):
        for point in range(10):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "state.json"
                record = checkpoint()
                record["attempt_id"] = f"attempt-{point}"
                write_checkpoint(path, record)
                # Model process death after each durable checkpoint boundary. Recovery observes
                # the original attempt; the fake gateway rejects every write/submit method.
                gateway = _Gateway()
                with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway):
                    outcome = asyncio.run(recover_attempt.recover(path))
                recovered = read_checkpoint(path)
                self.assertEqual(recovered["attempt_id"], f"attempt-{point}")
                self.assertEqual(outcome["state"], "RUNNING")
                self.assertEqual([method for method, _ in gateway.calls].count("session.resume"), 1)
                self.assertFalse(any(method in {"prompt.submit", "prompt.resolve_unknown", "prompt.cancel"}
                                     for method, _ in gateway.calls))
                self.assertEqual(len(path.with_suffix(".json.jsonl").read_text().splitlines()), 1)

    def test_unsupported_checkpoint_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_checkpoint(path)

    def test_symlink_checkpoint_and_journal_are_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            target = parent / "outside.json"
            target.write_text("keep", encoding="utf-8")
            checkpoint_path = parent / "checkpoint.json"
            checkpoint_path.symlink_to(target)
            with self.assertRaises(ValueError):
                write_checkpoint(checkpoint_path, checkpoint())
            with self.assertRaises(ValueError):
                read_checkpoint(checkpoint_path)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_checkpoint_rejects_unrecognized_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            with self.assertRaisesRegex(ValueError, "fields unsupported"):
                write_checkpoint(path, {**checkpoint(), "prompt": "must not persist"})

    def test_recovery_does_not_overwrite_operator_blocked_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            write_checkpoint(path, checkpoint())

            class OperatorUpdateGateway(_Gateway):
                async def rpc(inner_self, method, **params):
                    result = await super(OperatorUpdateGateway, inner_self).rpc(method, **params)
                    if method == "session.detach":
                        updated = read_checkpoint(path)
                        updated.update(state="BLOCKED", status="operator review",
                                       next_action="operator review required")
                        write_checkpoint(path, updated)
                    return result

            gateway = OperatorUpdateGateway()
            with patch("hermes_cli.gateway_client.connect_gateway", return_value=gateway):
                with self.assertRaisesRegex(RuntimeError, "newer state preserved"):
                    asyncio.run(recover_attempt.recover(
                        path, expected_state="RUNNING", expected_attempt_id="attempt-a"))
            self.assertEqual(read_checkpoint(path)["state"], "BLOCKED")
            self.assertNotIn("prompt.submit", [method for method, _ in gateway.calls])


if __name__ == "__main__":
    unittest.main()
