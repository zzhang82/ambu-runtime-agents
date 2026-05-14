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

    def test_profile_run_executes(self):
        route = {"status": "matched", "risk": "read_only"}
        result = actions.execute_action(
            {"type": "profile_run", "profile_id": "runtime-dev", "goal": "inspect repo status"},
            route,
            deps={
                "resolve_profile": lambda *_args, **_kwargs: {
                    "profile": {"default_run_goal": "inspect repo status", "allowed_tools": ["web_fetch"], "blocked_capabilities": [], "approval_required": []},
                    "agent": "planner",
                    "workspace": "test-ws",
                    "cwd": "/tmp/test-ws",
                    "memory_namespace": "project:test-ws",
                    "allowed_tools": [{"id": "web_fetch", "trust_level": "untrusted_input", "data_classes": ["public_web"], "capabilities": ["web_read"], "egress": "public_web"}],
                },
                "tools_by_id": lambda: {"web_fetch": {"id": "web_fetch", "trust_level": "untrusted_input", "data_classes": ["public_web"], "capabilities": ["web_read"], "egress": "public_web", "enabled": True}},
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.result["type"], "profile_run")
        self.assertIn("context_state", result.result)
        self.assertIn("policy_decisions", result.result)

    def test_profile_run_blocks_tool_outside_profile(self):
        route = {"status": "matched", "risk": "read_only"}
        result = actions.execute_action(
            {"type": "profile_run", "profile_id": "runtime-dev", "goal": "inspect repo status", "tool": "workspace_files"},
            route,
            deps={
                "resolve_profile": lambda *_args, **_kwargs: {
                    "profile": {"default_run_goal": "inspect repo status", "allowed_tools": ["web_fetch"], "blocked_capabilities": [], "approval_required": []},
                    "agent": "planner",
                    "workspace": "test-ws",
                    "cwd": "/tmp/test-ws",
                    "memory_namespace": "project:test-ws",
                    "allowed_tools": [{"id": "web_fetch", "trust_level": "untrusted_input", "data_classes": ["public_web"], "capabilities": ["web_read"], "egress": "public_web"}],
                },
                "tools_by_id": lambda: {"workspace_files": {"id": "workspace_files", "trust_level": "trusted", "data_classes": ["workspace_files"], "capabilities": ["filesystem_read"], "egress": "none", "enabled": True}},
            },
        )
        self.assertEqual(result.status, "blocked")

    def test_profile_plan_returns_guardrail_metadata(self):
        route = {"status": "matched", "risk": "read_only"}
        saved = {}

        def save_plan(plan):
            saved.update(plan)

        result = actions.execute_action(
            {"type": "profile_plan", "profile_id": "runtime-dev", "goal": "improve tests"},
            route,
            deps={
                "resolve_profile": lambda *_args, **_kwargs: {
                    "profile": {"default_plan_goal": "improve tests", "default_agent": "planner", "allowed_agents": ["planner"], "allowed_tools": ["web_fetch"], "blocked_capabilities": [], "approval_required": [], "workspace_required": False},
                    "agent": "planner",
                    "workspace": "test-ws",
                    "cwd": "/tmp/test-ws",
                    "memory_namespace": "project:test-ws",
                    "allowed_tools": [{"id": "web_fetch", "trust_level": "untrusted_input", "data_classes": ["public_web"], "capabilities": ["web_read"], "egress": "public_web"}],
                },
                "tools_by_id": lambda: {"web_fetch": {"id": "web_fetch", "trust_level": "untrusted_input", "data_classes": ["public_web"], "capabilities": ["web_read"], "egress": "public_web", "enabled": True}},
                "plan_id": lambda: "20260514-120000-plan-abc123",
                "default_plan_for_goal": lambda pid, workspace, memory_namespace, goal: {"plan_id": pid, "workspace": workspace, "memory_namespace": memory_namespace, "goal": goal, "status": "draft"},
                "plan_dir": lambda _pid: Path(tempfile.mkdtemp(prefix="action-plan-test-")) / _pid,
                "save_plan": save_plan,
                "update_plan_status_file": lambda _plan: None,
            },
        )
        self.assertTrue(result.ok)
        self.assertIn("context_state", result.result)
        self.assertIn("policy_decisions", result.result)
        self.assertIn("context_state", saved)
        self.assertIn("policy_decisions", saved)

    def test_execute_route_preserves_matched_status_on_success(self):
        route = {"status": "matched", "risk": "read_only", "actions": [{"type": "list_workspaces"}]}
        payload = actions.execute_route(route, deps={"load_workspaces": lambda: {}})
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["execution"][0]["type"], "list_workspaces")
        self.assertEqual(payload["action_result"]["status"], "completed")

    def test_execute_route_preserves_matched_status_on_success(self):
        route = {"status": "matched", "risk": "read_only", "actions": [{"type": "list_workspaces"}]}
        payload = actions.execute_route(route, deps={"load_workspaces": lambda: {}})
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["execution"][0]["type"], "list_workspaces")
        self.assertEqual(payload["action_result"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
