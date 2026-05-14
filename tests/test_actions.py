import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import actions


class ActionsTests(unittest.TestCase):
    def test_read_only_action_executes(self):
        route = {"status": "matched", "risk": "read_only"}
        result = actions.execute_action(
            {"type": "list_workspaces"},
            route,
            deps={"load_workspaces": lambda: {"test-ws": {"path": "/tmp/ws"}}},
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.result["type"], "list_workspaces")

    def test_workspace_write_route_requires_confirmation(self):
        route = {"status": "matched", "risk": "workspace_write", "message": "queued", "confirm_message": "Reply YES"}
        payload = actions.execute_route(route, deps={})
        self.assertEqual(payload["status"], "pending_confirmation")
        self.assertEqual(payload["message"], "Reply YES")
        self.assertEqual(payload["action_result"]["status"], "pending_confirmation")

    def test_unknown_action_is_unsupported(self):
        route = {"status": "matched", "risk": "read_only"}
        result = actions.execute_action({"type": "not_real"}, route, deps={})
        self.assertEqual(result.status, "unsupported")
        self.assertFalse(result.executed)

    def test_show_logs_missing_task_fails_stably(self):
        route = {"status": "matched", "risk": "read_only"}
        result = actions.execute_action({"type": "show_logs", "task_id": "missing"}, route, deps={"latest_task": lambda _task_id: None})
        self.assertEqual(result.status, "failed")
        self.assertIn("Unknown task id", result.error)

    def test_execute_route_preserves_matched_status_on_success(self):
        route = {"status": "matched", "risk": "read_only", "actions": [{"type": "list_workspaces"}]}
        payload = actions.execute_route(route, deps={"load_workspaces": lambda: {}})
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["execution"][0]["type"], "list_workspaces")
        self.assertEqual(payload["action_result"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
