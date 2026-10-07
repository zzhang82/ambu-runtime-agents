import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import cli, amb_adapter


class P1ReliabilityTests(unittest.TestCase):
    def test_schedule_deduplication_with_spaces_in_name(self):
        # A schedule with a space in its name should not be duplicated in latest_schedules
        events = [
            {"schedule_id": "daily-review", "name": "daily review", "cron": "* * * * *", "enabled": True},
            {"schedule_id": "daily-review", "name": "daily review", "last_due_window": "2026-10-07T00:00:00Z"},
        ]
        with patch.object(cli, "read_schedule_events", return_value=events):
            schedules = cli.latest_schedules()
            # Must contain only one canonical entry keyed by schedule_id
            self.assertEqual(len(schedules), 1)
            self.assertIn("daily-review", schedules)
            self.assertEqual(schedules["daily-review"]["name"], "daily review")

            # schedule_by_name can still resolve by original name
            resolved = cli.schedule_by_name("daily review")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved["schedule_id"], "daily-review")

    def test_plan_dependencies_enforced_in_queue_claim(self):
        # Subtask 2 depends on subtask 1. Subtask 2 must not be claimed until subtask 1 completes.
        latest = {
            "q1": {"queue_id": "q1", "plan_id": "p1", "subtask_id": "1", "status": "failed", "depends_on": []},
            "q2": {"queue_id": "q2", "plan_id": "p1", "subtask_id": "2", "status": "queued", "depends_on": ["1"]},
        }
        # Subtask 2 is NOT eligible because subtask 1 failed
        self.assertFalse(cli.is_queue_item_eligible(latest["q2"], latest))

        # If subtask 1 is completed, subtask 2 becomes eligible
        latest["q1"]["status"] = "completed"
        self.assertTrue(cli.is_queue_item_eligible(latest["q2"], latest))

        # With first_queued_item
        with patch.object(cli, "latest_queue_items", return_value=latest):
            claimed = cli.first_queued_item()
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed["queue_id"], "q2")

    def test_validation_cleanup_does_not_cancel_real_user_goals(self):
        # A legitimate development task with "validation" in the goal must NOT be safe to cancel
        user_task = {
            "queue_id": "q-real",
            "status": "queued",
            "goal": "Implement validation for invoice totals",
            "created_from": "user",
        }
        res = cli.classify_validation_artifact_queue_item(user_task)
        self.assertFalse(res["safe_to_cancel"])
        self.assertFalse(res["matched"])

        # Selftest artifact MUST be matched and safe to cancel
        selftest_task = {
            "queue_id": "q-test",
            "status": "queued",
            "goal": "selftest queued noop",
            "created_from": "selftest",
        }
        res_test = cli.classify_validation_artifact_queue_item(selftest_task)
        self.assertTrue(res_test["safe_to_cancel"])
        self.assertTrue(res_test["matched"])

    def test_amb_adapter_preserves_iserror_envelope(self):
        adapter = amb_adapter.AMBAdapter({"mode": "mcp_stdio", "command": "echo"})
        # When MCP returns isError: True in raw envelope
        raw_error_payload = {
            "isError": True,
            "content": [{"type": "text", "text": "Storage capacity exceeded"}],
        }
        with patch.object(adapter, "call_tool", return_value={"ok": False, "isError": True, "error": "Storage capacity exceeded"}):
            store_res = adapter.store("project:test", "memory", {"note": "test"})
            self.assertFalse(store_res["ok"])
            self.assertTrue(store_res["isError"])
            self.assertIn("capacity exceeded", store_res["error"])

    def test_writeback_verifies_recall_receipt(self):
        # When --verify is passed and recall fails to confirm the stored id, writeback must fail
        candidate = {
            "candidate_id": "t:cand-1",
            "title": "lesson",
            "claim": "claim",
            "decision": "approved",
            "writeback_recommended": True,
        }
        adapter_mock = Mock()
        adapter_mock.store.return_value = {"ok": True, "id": "id1", "isError": False}
        adapter_mock.recall.return_value = {"ok": True, "response": {"items": []}}  # id1 NOT in recalled items!

        task = {"task_id": "t1", "run_dir": "/tmp", "model": "test-model", "memory_namespace": "project:test"}
        with patch.object(cli, "latest_task", return_value=task), \
             patch.object(cli, "latest_queue_items", return_value={}), \
             patch.object(cli, "queue_item_for_task_id", return_value={}), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "write_text"), \
             patch.object(cli, "load_json_file", return_value={}), \
             patch.object(cli, "load_memory_candidates_for_task", return_value=([candidate], Path("/tmp"))), \
             patch.object(cli, "AMBAdapter", return_value=adapter_mock), \
             patch.object(cli, "print_json") as printed:

            args = Mock(task_id="t1", json=True, dry_run=False, verify=True)
            rc = cli.writeback_cmd(args)
            self.assertEqual(rc, 1)  # Must exit with failure!
            receipt = printed.call_args.args[0]
            self.assertEqual(receipt["status"], "failed")
            self.assertFalse(receipt["records"][0]["verified"])

    def test_cancel_queue_item_signals_running_pid(self):
        with patch.object(cli, "latest_queue_items", return_value={"q1": {"queue_id": "q1", "pid": 99999, "status": "running"}}), \
             patch.object(cli, "append_queue"), \
             patch("os.getpgid", return_value=99999), \
             patch("os.killpg") as mock_killpg:
            cli.cancel_queue_item("q1", "user cancelled", previous_status="running")
            mock_killpg.assert_called_once_with(99999, signal.SIGTERM)

    def test_classify_failure_handles_503_and_quota_without_test_stdout_false_positive(self):
        from runtime_agents import policy
        # 503 in stderr must be recognized
        self.assertEqual(policy.classify_failure("", "HTTP 503 Service Unavailable", 1), "transient_model_error")
        # insufficient_quota in stderr must be recognized
        self.assertEqual(policy.classify_failure("", "insufficient_quota: plan quota exceeded", 1), "transient_model_error")
        # test assertion in stdout containing 429 must NOT be classified as transient model failure
        self.assertIsNone(policy.classify_failure("AssertionError: assert response.status_code == 429", "", 1))


if __name__ == "__main__":
    unittest.main()
