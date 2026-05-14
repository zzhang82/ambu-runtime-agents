import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import actions


class ProfileActionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-profile-action-"))

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def _resolve_profile(self, profile_id, workspace_override=None, agent_override=None):
        cwd = self.tempdir / "workspace"
        cwd.mkdir(exist_ok=True)
        profile = {
            "id": profile_id,
            "default_agent": "planner",
            "allowed_agents": ["planner", "reviewer"],
            "default_run_goal": "inspect repo status",
            "default_plan_goal": "improve tests",
            "allowed_tools": ["web_fetch"],
        }
        agent = agent_override or "planner"
        if agent not in profile["allowed_agents"]:
            raise SystemExit(f"Agent '{agent}' is not allowed for profile '{profile_id}'.")
        return {
            "profile": profile,
            "agent": agent,
            "workspace": workspace_override or "test-ws",
            "cwd": str(cwd),
            "memory_namespace": "project:test-ws",
            "allowed_tools": [{"id": "web_fetch"}],
        }

    def test_profile_run_returns_resolved_payload(self):
        result = actions.execute_action(
            {"type": "profile_run", "profile_id": "runtime-dev", "goal": "inspect repo status"},
            {"status": "matched", "risk": "read_only"},
            deps={"resolve_profile": self._resolve_profile},
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.result["profile_id"], "runtime-dev")
        self.assertEqual(result.result["agent"], "planner")

    def test_profile_plan_creates_profile_aware_plan(self):
        saved = {}

        def save_plan(plan):
            saved.update(plan)

        result = actions.execute_action(
            {"type": "profile_plan", "profile_id": "runtime-dev", "goal": "improve tests"},
            {"status": "matched", "risk": "read_only"},
            deps={
                "resolve_profile": self._resolve_profile,
                "plan_id": lambda: "20260514-120000-plan-abc123",
                "default_plan_for_goal": lambda pid, workspace, memory_namespace, goal: {
                    "plan_id": pid,
                    "workspace": workspace,
                    "memory_namespace": memory_namespace,
                    "goal": goal,
                    "status": "draft",
                },
                "plan_dir": lambda _pid: self.tempdir / "plan-dir",
                "save_plan": save_plan,
                "update_plan_status_file": lambda _plan: None,
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.result["profile_id"], "runtime-dev")
        self.assertEqual(saved["profile_id"], "runtime-dev")


if __name__ == "__main__":
    unittest.main()
