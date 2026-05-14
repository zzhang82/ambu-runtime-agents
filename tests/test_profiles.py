import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import profiles


class ProfileRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-profiles-"))
        self.old_config_home = os.environ.get("RUNTIME_AGENTS_CONFIG_HOME")
        os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = str(self.tempdir / "config")
        (self.tempdir / "config").mkdir(parents=True)
        self.agents = {"planner": {}, "reviewer": {}, "coder": {}}
        self.workspaces = {"test-ws": {"path": "/tmp/test-ws", "memory_namespace": "project:test-ws"}}
        self.tool_ids = {"web_fetch", "workspace_files"}

    def tearDown(self):
        if self.old_config_home is None:
            os.environ.pop("RUNTIME_AGENTS_CONFIG_HOME", None)
        else:
            os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = self.old_config_home
        shutil.rmtree(self.tempdir)

    def test_validate_profile_accepts_packaged_shape(self):
        profile = profiles.validate_profile(
            "runtime-dev",
            {
                "title": "Runtime Development",
                "description": "Profile",
                "default_agent": "planner",
                "allowed_agents": ["planner", "reviewer"],
                "workspace_required": True,
                "allowed_tools": ["web_fetch"],
                "blocked_capabilities": ["git_push"],
                "approval_required": ["deploy"],
            },
            agent_names=set(self.agents.keys()),
            workspace_names=set(self.workspaces.keys()),
            tool_ids=self.tool_ids,
        )
        self.assertEqual(profile["default_agent"], "planner")

    def test_default_agent_must_be_in_allowed_agents(self):
        with self.assertRaises(profiles.ProfileValidationError):
            profiles.validate_profile(
                "runtime-dev",
                {
                    "title": "Runtime Development",
                    "description": "Profile",
                    "default_agent": "planner",
                    "allowed_agents": ["reviewer"],
                },
                agent_names=set(self.agents.keys()),
                workspace_names=set(self.workspaces.keys()),
                tool_ids=self.tool_ids,
            )

    def test_unknown_tool_reference_is_rejected(self):
        with self.assertRaises(profiles.ProfileValidationError):
            profiles.validate_profile(
                "runtime-dev",
                {
                    "title": "Runtime Development",
                    "description": "Profile",
                    "default_agent": "planner",
                    "allowed_agents": ["planner"],
                    "allowed_tools": ["missing_tool"],
                },
                agent_names=set(self.agents.keys()),
                workspace_names=set(self.workspaces.keys()),
                tool_ids=self.tool_ids,
            )

    def test_unknown_workspace_is_rejected(self):
        with self.assertRaises(profiles.ProfileValidationError):
            profiles.validate_profile(
                "runtime-dev",
                {
                    "title": "Runtime Development",
                    "description": "Profile",
                    "default_agent": "planner",
                    "allowed_agents": ["planner"],
                    "workspace": "missing-ws",
                },
                agent_names=set(self.agents.keys()),
                workspace_names=set(self.workspaces.keys()),
                tool_ids=self.tool_ids,
            )


if __name__ == "__main__":
    unittest.main()
