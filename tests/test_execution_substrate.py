import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

sys.path.insert(0, str(ROOT / "src"))

from runtime_agents import cli
from runtime_agents import execution_substrate


def run_cli(args, env):
    cmd = [sys.executable, "-m", "runtime_agents.cli", *args]
    return subprocess.run(cmd, text=True, capture_output=True, env=env, cwd=ROOT)


def make_env(base_dir: Path):
    config_home = base_dir / "config"
    state_home = base_dir / "state"
    config_home.mkdir()
    state_home.mkdir()
    (config_home / "VERSION").write_text("1.5.1\n", encoding="utf-8")
    (config_home / "telegram.yaml").write_text(
        "telegram:\n  enabled: false\n  bot_token_env: RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN\n  allowed_user_ids: []\n",
        encoding="utf-8",
    )
    agents = {
        "models": {"primary": "gpt-5.5", "fallbacks": [], "cheap": "gpt-5.5"},
        "amb": {"mode": "mcp_stdio", "command": sys.executable, "args": ["-c", "print('ok')"]},
        "tools": {
            "codex": {"command": str(FIXTURES / "fake-codex-ok")},
            "claude": {"command": str(FIXTURES / "fake-claude-ok")},
            "gemini": {"command": str(FIXTURES / "fake-gemini-ok")},
        },
        "agents": {
            "planner": {"tool": "codex", "model": "gpt-5.5", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
            "reviewer": {"tool": "claude", "model": "gpt-5.5", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
            "cheap": {"tool": "gemini", "model": "gpt-5.5", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
        },
        "capability_rules": {},
    }
    (config_home / "agents.yaml").write_text(yaml.safe_dump(agents, sort_keys=False), encoding="utf-8")
    workspace_path = base_dir / "workspace"
    workspace_path.mkdir()
    (config_home / "workspaces.yaml").write_text(
        yaml.safe_dump({"test-ws": {"path": str(workspace_path), "memory_namespace": "project:test-ws"}}, sort_keys=False),
        encoding="utf-8",
    )
    (config_home / "profiles.yaml").write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "runtime-dev": {
                        "title": "Runtime Development",
                        "description": "Default runtime development profile.",
                        "default_agent": "planner",
                        "allowed_agents": ["planner", "reviewer"],
                        "workspace_required": True,
                        "allowed_tools": ["repo_read"],
                        "blocked_capabilities": ["git_push", "deploy"],
                        "approval_required": ["workspace_write", "git_push", "deploy"],
                        "default_run_goal": "inspect repo status",
                        "default_plan_goal": "improve tests",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["RUNTIME_AGENTS_CONFIG_HOME"] = str(config_home)
    env["RUNTIME_AGENTS_STATE_HOME"] = str(state_home)
    env["PATH"] = str(FIXTURES) + os.pathsep + env.get("PATH", "")
    return env


class ExecutionSubstrateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-substrate-"))
        self.env = make_env(self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_legacy_direct_tools_are_characterized(self):
        self.assertEqual(execution_substrate.classify_agent_execution({"tool": "codex"})["execution_substrate"], "legacy-direct:codex")
        self.assertEqual(execution_substrate.classify_agent_execution({"tool": "claude"})["execution_substrate"], "legacy-direct:claude")
        self.assertEqual(execution_substrate.classify_agent_execution({"tool": "gemini"})["execution_substrate"], "legacy-direct:gemini")

    def test_opencode_command_contract_is_documented_in_code(self):
        self.assertEqual(
            execution_substrate.build_opencode_exec_command("gpt-5.5", "inspect", autonomy="read_only"),
            ["opencode", "run", "--print", "--model", "gpt-5.5", "--permission", "read", "inspect"],
        )
        self.assertEqual(
            execution_substrate.build_opencode_exec_command("gpt-5.5", "fix", autonomy="workspace_write"),
            ["opencode", "run", "--print", "--model", "gpt-5.5", "--permission", "edit", "fix"],
        )

    def test_opencode_is_not_live_routed_in_phase_zero(self):
        with self.assertRaises(SystemExit) as raised:
            cli.build_command("opencode", "gpt-5.5", "inspect")
        self.assertIn("Unsupported tool: opencode", str(raised.exception))

    def test_existing_direct_adapter_commands_remain_unchanged(self):
        self.assertEqual(
            cli.build_command("codex", "gpt-5.5", "inspect", autonomy="read_only"),
            ["codex", "exec", "--skip-git-repo-check", "-m", "gpt-5.5", "-c", 'approval_policy="never"', "-c", 'sandbox_mode="read-only"', "inspect"],
        )
        self.assertEqual(cli.build_command("claude", "gpt-5.5", "inspect"), ["claude", "--bare", "-p", "--model", "gpt-5.5", "inspect"])
        self.assertEqual(cli.build_command("gemini", "gpt-5.5", "inspect"), ["gemini", "-m", "gpt-5.5", "-p", "inspect"])

    def test_run_dry_run_reports_current_and_intended_substrate(self):
        proc = run_cli(["run", "planner", "inspect", "repo", "--dry-run"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["execution_substrate"], "legacy-direct:codex")
        self.assertTrue(payload["legacy_direct"])
        self.assertEqual(payload["intended_primary_substrate"], "opencode")

    def test_inspect_reports_legacy_substrate_without_switching_default(self):
        proc = run_cli(["inspect", "reviewer"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["tool"], "claude")
        self.assertEqual(payload["execution_substrate"], "legacy-direct:claude")
        self.assertTrue(payload["legacy_direct"])
        self.assertEqual(payload["intended_primary_substrate"], "opencode")


if __name__ == "__main__":
    unittest.main()
