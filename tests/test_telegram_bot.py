import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-telegram-bot-"))
        self.config_home = self.tempdir / "config"
        self.state_home = self.tempdir / "state"
        self.config_home.mkdir()
        self.state_home.mkdir()
        (self.config_home / "telegram.yaml").write_text(
            yaml.safe_dump(
                {
                    "telegram": {
                        "enabled": False,
                        "bot_token_env": "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN",
                        "allowed_user_ids": [123],
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.old_config_home = os.environ.get("RUNTIME_AGENTS_CONFIG_HOME")
        self.old_state_home = os.environ.get("RUNTIME_AGENTS_STATE_HOME")
        os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = str(self.config_home)
        os.environ["RUNTIME_AGENTS_STATE_HOME"] = str(self.state_home)

        from runtime_agents import telegram_bot

        self.bot = importlib.reload(telegram_bot)

    def tearDown(self):
        if self.old_config_home is None:
            os.environ.pop("RUNTIME_AGENTS_CONFIG_HOME", None)
        else:
            os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = self.old_config_home
        if self.old_state_home is None:
            os.environ.pop("RUNTIME_AGENTS_STATE_HOME", None)
        else:
            os.environ["RUNTIME_AGENTS_STATE_HOME"] = self.old_state_home
        shutil.rmtree(self.tempdir)

    def test_unauthorized_user_gets_no_status_details(self):
        response = self.bot.handle_command("/status", 999)

        self.assertEqual(response, "unauthorized")
        self.assertNotIn("Daemon:", response)

    def test_shell_like_slash_commands_remain_blocked(self):
        for command in ("/exec ls", "/shell pwd", "/bash whoami"):
            with self.subTest(command=command):
                self.assertEqual(self.bot.handle_command(command, 123), "unsupported in Telegram v1.0")

    def test_help_encourages_natural_prompts_without_new_authority(self):
        response = self.bot.handle_command("/help", 123)

        self.assertIn("runtime-agents Telegram Assistant", response)
        self.assertIn("Chat naturally", response)
        self.assertIn("Write-like requests still ask for confirmation", response)
        self.assertIn("/status /queue /plans", response)

    def test_greeting_mentions_confirmation_boundary(self):
        response = self.bot.handle_command("hi", 123)

        self.assertIn("runtime-agents assistant", response)
        self.assertIn("Write-like actions still require confirmation", response)

    def test_confirmation_flow_uses_pending_action_and_agentctl_boundary(self):
        calls = []

        def fake_run_agentctl(args, timeout=60):
            calls.append(args)
            if args[:2] == ["assistant-route", "fix tests in test-ws"]:
                return {
                    "ok": True,
                    "json": {
                        "status": "matched",
                        "intent": "fix_tests",
                        "workspace": "test-ws",
                        "requires_confirmation": True,
                        "confirm_message": "Reply YES to create a plan.",
                        "actions": [{"type": "create_plan"}],
                    },
                    "stdout": "",
                    "stderr": "",
                }
            if args[:2] == ["assistant-exec", "fix tests in test-ws"]:
                return {
                    "ok": True,
                    "json": {
                        "status": "matched",
                        "runbook_id": "fix_tests",
                        "inputs": {"workspace": "test-ws"},
                        "execution": [{"type": "create_plan", "plan_id": "plan-1", "status": "draft"}],
                    },
                    "stdout": "",
                    "stderr": "",
                }
            raise AssertionError(f"unexpected agentctl call: {args}")

        with patch.object(self.bot, "run_agentctl", side_effect=fake_run_agentctl):
            confirm = self.bot.handle_command("fix tests in test-ws", 123)
            result = self.bot.handle_command("YES", 123)

        self.assertIn("Reply YES", confirm)
        self.assertIn("Plan created", result)
        self.assertEqual(calls[0][0], "assistant-route")
        self.assertEqual(calls[1][0], "assistant-exec")


if __name__ == "__main__":
    unittest.main()
