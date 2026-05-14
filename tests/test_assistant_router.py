import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import assistant_router


class AssistantRouterTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-router-"))
        self.old_config_home = os.environ.get("RUNTIME_AGENTS_CONFIG_HOME")
        os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = str(self.tempdir / "config")
        (self.tempdir / "config").mkdir()

    def tearDown(self):
        if self.old_config_home is None:
            os.environ.pop("RUNTIME_AGENTS_CONFIG_HOME", None)
        else:
            os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = self.old_config_home
        shutil.rmtree(self.tempdir)

    def test_status_overview(self):
        payload = assistant_router.route_assistant_message("what needs attention?", workspace_names=["test-ws"])
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "status_overview")
        self.assertEqual(payload["intent"], "status_overview")

    def test_check_workspace(self):
        payload = assistant_router.route_assistant_message("check workspace test-ws", workspace_names=["test-ws"])
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "check_workspace")
        self.assertEqual(payload["workspace"], "test-ws")

    def test_repo_health(self):
        payload = assistant_router.route_assistant_message("repo health test-ws", workspace_names=["test-ws"])
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "repo_health_check")
        self.assertEqual(payload["workspace"], "test-ws")

    def test_fix_tests_requires_confirmation(self):
        payload = assistant_router.route_assistant_message("fix tests in test-ws", workspace_names=["test-ws"])
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "fix_tests")
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["risk"], "workspace_write")

    def test_list_runbooks(self):
        payload = assistant_router.route_assistant_message("list runbooks", workspace_names=["test-ws"])
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "list_runbooks")

    def test_missing_workspace_needs_clarification(self):
        payload = assistant_router.route_assistant_message("repo health", workspace_names=["test-ws"])
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual(payload["runbook_id"], "repo_health_check")

    def test_dangerous_blocked(self):
        payload = assistant_router.route_assistant_message("please git push now", workspace_names=[])
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["intent"], "refuse_dangerous")


if __name__ == "__main__":
    unittest.main()
