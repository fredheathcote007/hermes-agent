"""Contracts for bounded automatic observation of abandoned phase 2 workspaces."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pytest

from hermes_cli.fermes_reliability import recover_orphans
from hermes_cli.fermes_reliability.recovery import owner_identity, write_checkpoint

pytestmark = pytest.mark.platforms("linux")


def _checkpoint(workspace: Path, **updates):
    return {
        "run_id": "run-a", "attempt_id": "attempt-a", "state": "RUNNING", "status": "running",
        "gateway_instance_id": "gateway-a", "gateway_profile_id": "profile-a",
        "gateway_authority_epoch": 7, "session_id": "local-session-a", "generation": 4,
        "subscription_id": "sub-a", "admission_id": "admission-a", "submission_id": None,
        "last_observation": None, "deadline": 100, "deadline_at": 100,
        "replay_epoch": "epoch-a", "last_sequence": 0, "working_dir": str(workspace),
        "next_action": "observe only", **owner_identity(), **updates,
    }


class RecoverOrphansTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name) / "retained"
        self.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_owner_identity_requires_same_boot_and_process_start_time(self):
        identity = owner_identity()
        self.assertEqual(recover_orphans._live_owner(identity)[0], "active")
        self.assertEqual(recover_orphans._live_owner({**identity, "supervisor_start_ticks": 1})[0],
                         "manual_review")
        self.assertEqual(recover_orphans._live_owner({**identity, "boot_id": "other-boot"})[0],
                         "manual_review")
        missing_pid = {**identity, "supervisor_pid": 2_000_000_000}
        self.assertEqual(recover_orphans._live_owner(missing_pid)[0], "abandoned")

    def workspace(self, name="hermes-supervised-a", **updates):
        workspace = self.parent / name
        workspace.mkdir()
        write_checkpoint(workspace / "phase2-checkpoint.json", _checkpoint(workspace, **updates))
        return workspace

    def test_live_owner_is_ignored(self):
        self.workspace()
        with patch.object(recover_orphans, "_live_owner", return_value=("active", "live")), \
                patch.object(recover_orphans, "recover", side_effect=AssertionError("must not recover")):
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(result["outcomes"][0]["outcome"], "active")

    def test_dead_owner_invokes_existing_observer_once(self):
        self.workspace()
        observer_result = {"state": "RUNNING", "next_action": "observe same session"}
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(return_value=observer_result)) as observe:
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(observe.await_count, 1)
        self.assertEqual(result["outcomes"][0]["outcome"], "observed")
        self.assertEqual(result["outcomes"][0]["state"], "RUNNING")

    def test_default_scan_is_preview_only_for_orphan_candidate(self):
        self.workspace()
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", side_effect=AssertionError("must remain observe-only")):
            result = asyncio.run(recover_orphans.scan(self.parent))
        self.assertEqual(result["outcomes"][0]["outcome"], "would_observe")

    def test_symlink_workspace_is_manual_review_and_never_followed(self):
        elsewhere = Path(self.temp.name) / "elsewhere"
        elsewhere.mkdir()
        self.workspace("outside")
        (self.parent / "hermes-supervised-link").symlink_to(elsewhere, target_is_directory=True)
        with patch.object(recover_orphans, "_live_owner", side_effect=AssertionError("not read")):
            result = asyncio.run(recover_orphans.scan(self.parent))
        rows = {Path(row["workspace"]).name: row for row in result["outcomes"]}
        self.assertEqual(rows["hermes-supervised-link"]["outcome"], "manual_review")

    def test_running_observation_is_claimed_once_across_scans(self):
        workspace = self.workspace()
        observer_result = {"state": "RUNNING", "next_action": "observe same session"}
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(return_value=observer_result)) as observe:
            first = asyncio.run(recover_orphans.scan(self.parent, observe=True))
            second = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(observe.await_count, 1)
        self.assertEqual(first["outcomes"][0]["state"], "RUNNING")
        self.assertEqual(second["outcomes"][0]["outcome"], "skipped")
        record = json.loads((workspace / "phase2-checkpoint.json").read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "RUNNING")
        self.assertEqual(record["auto_recovery_claimed_attempt_id"], "attempt-a")
        self.assertIsInstance(record["auto_recovery_claimed_at"], str)
        journal = [json.loads(line) for line in
                   (workspace / "phase2-checkpoint.json.jsonl").read_text().splitlines()]
        self.assertEqual(journal[0]["event"], "automatic_recovery_claimed")
        self.assertEqual(journal[0]["attempt_id"], "attempt-a")

    def test_claim_journal_failure_keeps_claim_and_prevents_retry(self):
        workspace = self.workspace()
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "append_journal", side_effect=OSError("disk full")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock()) as observe:
            first = asyncio.run(recover_orphans.scan(self.parent, observe=True))
            second = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(first["outcomes"][0]["outcome"], "manual_review")
        self.assertEqual(second["outcomes"][0]["outcome"], "skipped")
        self.assertEqual(observe.await_count, 0)
        record = json.loads((workspace / "phase2-checkpoint.json").read_text())
        self.assertEqual(record["auto_recovery_claimed_attempt_id"], "attempt-a")

    def test_failed_claim_write_does_not_attach_or_record_a_claim(self):
        workspace = self.workspace()
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "write_checkpoint", side_effect=OSError("disk full")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock()) as observe:
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(result["outcomes"][0]["outcome"], "manual_review")
        self.assertEqual(observe.await_count, 0)
        record = json.loads((workspace / "phase2-checkpoint.json").read_text())
        self.assertNotIn("auto_recovery_claimed_attempt_id", record)

    def test_exception_after_claim_does_not_retry_automatically(self):
        self.workspace()
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(side_effect=RuntimeError("observer crash"))) as observe:
            first = asyncio.run(recover_orphans.scan(self.parent, observe=True))
            second = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(observe.await_count, 1)
        self.assertEqual(first["outcomes"][0]["outcome"], "manual_review")
        self.assertEqual(second["outcomes"][0]["outcome"], "skipped")

    def test_malformed_checkpoint_and_old_checkpoint_fail_closed(self):
        malformed = self.parent / "hermes-supervised-malformed"
        malformed.mkdir()
        (malformed / "phase2-checkpoint.json").write_text("{", encoding="utf-8")
        old = self.workspace("hermes-supervised-old")
        record = json.loads((old / "phase2-checkpoint.json").read_text(encoding="utf-8"))
        for field in ("supervisor_pid", "supervisor_start_ticks", "boot_id"):
            record.pop(field)
        (old / "phase2-checkpoint.json").write_text(json.dumps(record), encoding="utf-8")
        with patch.object(recover_orphans, "_live_owner", return_value=("manual_review", "owner missing")), \
                patch.object(recover_orphans, "recover", side_effect=AssertionError("must not recover")):
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual([row["outcome"] for row in result["outcomes"]], ["manual_review", "manual_review"])

    def test_invalid_state_type_is_reported_without_stopping_later_workspaces(self):
        malformed = self.workspace("hermes-supervised-invalid-state", state="LAUNCHING")
        checkpoint_file = malformed / "phase2-checkpoint.json"
        invalid = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        invalid["state"] = ["RUNNING"]
        checkpoint_file.write_text(json.dumps(invalid), encoding="utf-8")
        good = self.workspace("hermes-supervised-good")
        with patch.object(recover_orphans, "_live_owner", return_value=("active", "live")):
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        outcomes = {Path(row["workspace"]).name: row["outcome"] for row in result["outcomes"]}
        self.assertEqual(outcomes[malformed.name], "manual_review")
        self.assertEqual(outcomes[good.name], "active")

    def test_duplicate_scanner_lock_and_terminal_or_operator_blocked_are_not_recovered(self):
        locked = self.workspace()
        lock_path = locked / "phase2-checkpoint.json.recovery.lock"
        with lock_path.open("a") as lock_file:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                    patch.object(recover_orphans, "recover", side_effect=AssertionError("must not recover")):
                result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
            self.assertEqual(result["outcomes"][0]["outcome"], "locked")
        (locked / "phase2-checkpoint.json").unlink()
        self.workspace("hermes-supervised-terminal", state="TERMINAL")
        self.workspace("hermes-supervised-blocked", state="BLOCKED")
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", side_effect=AssertionError("must not recover")):
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        outcomes = {Path(row["workspace"]).name: row["outcome"] for row in result["outcomes"]}
        self.assertEqual(outcomes["hermes-supervised-terminal"], "skipped")
        self.assertEqual(outcomes["hermes-supervised-blocked"], "manual_review")

    def test_atomic_report_is_written_and_scan_is_bounded(self):
        self.workspace()
        for index in range(3):
            path = self.parent / f"hermes-supervised-{index}"
            path.mkdir()
        report = self.parent / "report.json"
        with patch.object(recover_orphans, "_live_owner", return_value=("active", "live")):
            result = asyncio.run(recover_orphans.scan(self.parent, limit=1, report_path=report))
        self.assertEqual(result["outcomes"][-1]["outcome"], "limit_reached")
        self.assertTrue(result["attention_required"])
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), result)
        self.assertFalse(list(self.parent.glob(".*.tmp")))

    def test_cli_reports_observation_results_with_zero_exit(self):
        self.workspace()
        report = self.parent / "report.json"
        output = io.StringIO()
        with patch.object(recover_orphans, "_live_owner", return_value=("active", "live")), \
                redirect_stdout(output):
            exit_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report),
            ])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["outcomes"][0]["outcome"], "active")
        self.assertEqual(json.loads(output.getvalue())["outcomes"][0]["outcome"], "active")

    def test_cli_marks_manual_review_as_failed_service_run(self):
        self.workspace("hermes-supervised-invalid-state", state="UNRECOGNIZED")
        with redirect_stdout(io.StringIO()):
            exit_code = recover_orphans.main(["--workspace-parent", str(self.parent)])
        self.assertEqual(exit_code, 1)

    def test_cli_epoch_drift_observed_blocked_requires_attention(self):
        self.workspace()
        report = self.parent / "report.json"
        blocked = {"state": "BLOCKED", "next_action": "gateway epoch changed"}
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(return_value=blocked)), \
                redirect_stdout(io.StringIO()):
            exit_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report), "--observe",
            ])
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertTrue(result["attention_required"])
        self.assertEqual(result["outcomes"][0]["outcome"], "observed")
        self.assertEqual(result["outcomes"][0]["state"], "BLOCKED")

    def test_settled_unknown_observation_requires_attention(self):
        outcome = {"outcome": "observed", "state": "SETTLED_UNKNOWN"}
        self.assertTrue(recover_orphans._needs_attention([outcome]))

    def test_cli_running_observation_exits_one(self):
        self.workspace()
        report = self.parent / "report.json"
        running = {"state": "RUNNING", "next_action": "observe same session"}
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(return_value=running)), \
                redirect_stdout(io.StringIO()):
            exit_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report), "--observe",
            ])
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertTrue(result["attention_required"])
        self.assertEqual(result["outcomes"][0]["outcome"], "observed")
        self.assertEqual(result["outcomes"][0]["state"], "RUNNING")

    def test_cli_claimed_running_attempt_requires_attention(self):
        self.workspace()
        report = self.parent / "report.json"
        observer_result = {"state": "RUNNING", "next_action": "still running"}
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(return_value=observer_result)), \
                redirect_stdout(io.StringIO()):
            first_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report), "--observe",
            ])
            second_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report), "--observe",
            ])
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(first_code, 1)
        self.assertEqual(second_code, 1)
        self.assertTrue(result["attention_required"])
        self.assertEqual(result["outcomes"][0]["outcome"], "skipped")
        self.assertIn("already claimed", result["outcomes"][0]["reason"])

    def test_cli_terminal_skip_requires_review_and_empty_scan_succeeds(self):
        self.workspace("hermes-supervised-terminal", state="TERMINAL")
        report = self.parent / "report.json"
        with redirect_stdout(io.StringIO()):
            terminal_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report),
            ])
        terminal_report = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(terminal_code, 1)
        self.assertTrue(terminal_report["attention_required"])
        self.assertEqual(terminal_report["outcomes"][0]["reason"], "attempt is already terminal")

        for workspace in self.parent.glob("hermes-supervised-*"):
            import shutil
            shutil.rmtree(workspace)
        with redirect_stdout(io.StringIO()):
            empty_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report),
            ])
        self.assertEqual(empty_code, 0)
        self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["attention_required"])

    def test_cli_terminal_observation_requires_outcome_review(self):
        self.workspace()
        report = self.parent / "report.json"
        terminal = {"state": "TERMINAL", "next_action": "terminal receipt observed"}
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock(return_value=terminal)), \
                redirect_stdout(io.StringIO()):
            exit_code = recover_orphans.main([
                "--workspace-parent", str(self.parent), "--report", str(report), "--observe",
            ])
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertTrue(result["attention_required"])
        self.assertEqual(result["outcomes"][0]["outcome"], "observed")

    def test_ephemeral_scan_error_uses_exit_two(self):
        with patch.object(recover_orphans, "scan", new=unittest.mock.AsyncMock(side_effect=OSError("temporary"))), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            exit_code = recover_orphans.main(["--workspace-parent", str(self.parent)])
        self.assertEqual(exit_code, 2)

    def test_parent_and_recovery_lock_symlinks_fail_closed(self):
        alias = self.parent.parent / "retained-alias"
        alias.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            asyncio.run(recover_orphans.scan(alias))

        workspace = self.workspace()
        outside = self.parent.parent / "outside-lock-target"
        outside.write_text("preserve", encoding="ascii")
        lock_path = workspace / "phase2-checkpoint.json.recovery.lock"
        lock_path.symlink_to(outside)
        with patch.object(recover_orphans, "_live_owner", return_value=("abandoned", "dead")), \
                patch.object(recover_orphans, "recover", new=unittest.mock.AsyncMock()) as observe:
            result = asyncio.run(recover_orphans.scan(self.parent, observe=True))
        self.assertEqual(result["outcomes"][0]["outcome"], "manual_review")
        self.assertEqual(outside.read_text(encoding="ascii"), "preserve")
        self.assertEqual(observe.await_count, 0)


if __name__ == "__main__":
    unittest.main()
