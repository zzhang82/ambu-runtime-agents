import unittest

from runtime_agents import assistant_router


class AssistantRouterTests(unittest.TestCase):
    def test_status_overview(self):
        payload = assistant_router.route_assistant_message("what needs attention?", workspace_names=["test-ws"])
        self.assertEqual(payload["intent"], "status_overview")

    def test_check_workspace(self):
        payload = assistant_router.route_assistant_message("check test-ws", workspace_names=["test-ws"])
        self.assertEqual(payload["intent"], "repo_health_check")
        self.assertEqual(payload["workspace"], "test-ws")

    def test_dangerous_blocked(self):
        payload = assistant_router.route_assistant_message("please git push now", workspace_names=[])
        self.assertEqual(payload["intent"], "refuse_dangerous")


if __name__ == "__main__":
    unittest.main()
