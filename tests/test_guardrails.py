import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import guardrails


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "id": "runtime-dev",
            "allowed_tools": ["workspace_files", "web_fetch"],
            "blocked_capabilities": ["git_push", "external_purchase"],
            "approval_required": ["workspace_write"],
        }
        self.workspace_tool = {
            "id": "workspace_files",
            "enabled": True,
            "trust_level": "trusted",
            "data_classes": ["workspace_files"],
            "capabilities": ["filesystem_read"],
            "egress": "none",
        }
        self.web_tool = {
            "id": "web_fetch",
            "enabled": True,
            "trust_level": "untrusted_input",
            "data_classes": ["public_web"],
            "capabilities": ["web_read"],
            "egress": "public_web",
        }
        self.telegram_tool = {
            "id": "telegram_notify",
            "enabled": True,
            "trust_level": "trusted",
            "data_classes": ["workspace_files"],
            "capabilities": ["notify"],
            "egress": "telegram",
        }

    def _eval(self, *, profile=None, profile_id="runtime-dev", tool=None, requested_tool_id=None, action="profile_run", selected_tools=None, considered_tools=None):
        context_state = guardrails.build_context_state(
            profile_id=profile_id,
            workspace="test-ws",
            selected_tools=selected_tools if selected_tools is not None else ([tool] if tool else []),
            considered_tools=considered_tools if considered_tools is not None else ([tool] if tool else []),
            action=action,
        )
        return guardrails.evaluate_guardrails(
            profile=profile or self.profile,
            profile_id=profile_id,
            tool=tool,
            requested_tool_id=requested_tool_id,
            action=action,
            context_state=context_state,
        )

    def test_default_allow(self):
        payload = self._eval(tool=self.workspace_tool, considered_tools=[self.workspace_tool])
        self.assertEqual(payload["decision"], "allow")
        self.assertEqual(payload["rule_id"], "default_allow")

    def test_arbitrary_shell_blocked(self):
        payload = self._eval(action="shell")
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "block_arbitrary_shell")

    def test_profile_blocked_capability_blocks(self):
        payload = self._eval(action="external_purchase")
        self.assertEqual(payload["decision"], "block")
        self.assertTrue(any(item["rule_id"] == "profile_blocked_capability" for item in payload["policy_decisions"]))

    def test_profile_approval_required(self):
        workspace_write_tool = {**self.workspace_tool, "capabilities": ["filesystem_read", "workspace_write"]}
        payload = self._eval(tool=workspace_write_tool, requested_tool_id="workspace_files", considered_tools=[workspace_write_tool])
        self.assertEqual(payload["decision"], "approval_required")
        self.assertEqual(payload["rule_id"], "profile_approval_required")

    def test_private_data_external_egress_requires_approval(self):
        profile = {**self.profile, "approval_required": [], "allowed_tools": ["telegram_notify"]}
        payload = self._eval(profile=profile, tool=self.telegram_tool, requested_tool_id="telegram_notify", considered_tools=[self.telegram_tool])
        self.assertEqual(payload["decision"], "approval_required")
        self.assertEqual(payload["rule_id"], "require_approval_private_external_summary")

    def test_untrusted_private_external_send_blocks(self):
        risky_tool = {
            "id": "mixed_notify",
            "enabled": True,
            "trust_level": "untrusted_input",
            "data_classes": ["workspace_files"],
            "capabilities": ["notify"],
            "egress": "telegram",
        }
        profile = {**self.profile, "approval_required": [], "allowed_tools": ["mixed_notify"]}
        payload = self._eval(profile=profile, tool=risky_tool, requested_tool_id="mixed_notify", considered_tools=[risky_tool])
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "block_untrusted_private_external_send")

    def test_broker_capability_blocks(self):
        broker_tool = {
            "id": "broker_api",
            "enabled": True,
            "trust_level": "trusted",
            "data_classes": ["private_data"],
            "capabilities": ["broker_order_submit"],
            "egress": "broker",
        }
        profile = {**self.profile, "allowed_tools": ["broker_api"], "approval_required": []}
        payload = self._eval(profile=profile, tool=broker_tool, requested_tool_id="broker_api", considered_tools=[broker_tool])
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "block_broker_order_submit")

    def test_purchase_capability_blocks(self):
        purchase_tool = {
            "id": "checkout_api",
            "enabled": True,
            "trust_level": "trusted",
            "data_classes": ["private_data"],
            "capabilities": ["external_purchase"],
            "egress": "public_web",
        }
        profile = {**self.profile, "allowed_tools": ["checkout_api"], "approval_required": []}
        payload = self._eval(profile=profile, tool=purchase_tool, requested_tool_id="checkout_api", considered_tools=[purchase_tool])
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "block_external_purchase")

    def test_unknown_tool_blocks(self):
        payload = self._eval(tool=None, requested_tool_id="missing-tool", considered_tools=[self.workspace_tool])
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "unknown_tool")

    def test_tool_not_allowed_for_profile_blocks(self):
        profile = {**self.profile, "allowed_tools": ["workspace_files"]}
        payload = self._eval(profile=profile, tool=self.web_tool, requested_tool_id="web_fetch", considered_tools=[self.workspace_tool, self.web_tool])
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "tool_not_allowed_for_profile")

    def test_disabled_tool_blocks(self):
        disabled_tool = {**self.workspace_tool, "enabled": False}
        payload = self._eval(tool=disabled_tool, requested_tool_id="workspace_files", considered_tools=[disabled_tool])
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["rule_id"], "tool_disabled")


if __name__ == "__main__":
    unittest.main()
