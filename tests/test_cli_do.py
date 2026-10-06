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


def run_cli(args, env):
    cmd = [sys.executable, "-m", "runtime_agents.cli", *args]
    return subprocess.run(cmd, text=True, capture_output=True, env=env, cwd=ROOT)


def make_env(base_dir: Path):
    config_home = base_dir / "config"
    state_home = base_dir / "state"
    config_home.mkdir()
    state_home.mkdir()
    (config_home / "VERSION").write_text("1.1.1\n", encoding="utf-8")
    (config_home / "telegram.yaml").write_text(
        "telegram:\n  enabled: false\n  bot_token_env: RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN\n  allowed_user_ids: []\n",
        encoding="utf-8",
    )
    (config_home / "workspaces.yaml").write_text(
        yaml.safe_dump({"test-ws": {"path": str(base_dir)}}),
        encoding="utf-8",
    )
    agents = {
        "models": {"primary": "local/gpt-5.5", "fallbacks": ["local/gpt-5.4"], "cheap": "local/gpt-5.4-mini"},
        "amb": {"mode": "mcp_stdio", "command": sys.executable, "args": ["-c", "print('ok')"]},
        "tools": {
            "opencode": {"command": str(FIXTURES / "fake-opencode-ok")},
        },
        "agents": {
            "coder": {
                "tool": "opencode",
                "model": "local/gpt-5.5",
                "opencode_agent": "build",
                "autonomy": "workspace_write",
                "approval_required": ["git_push", "deploy", "secrets", "global_config", "destructive_delete", "global_install"],
            },
            "oracle": {
                "tool": "opencode",
                "model": "local/gpt-5.5",
                "opencode_agent": "oracle",
                "autonomy": "read_only",
                "approval_required": ["workspace_write", "git_push", "deploy"],
            },
            "fixer": {
                "tool": "opencode",
                "model": "local/gpt-5.5",
                "opencode_agent": "fixer",
                "autonomy": "workspace_write",
                "approval_required": ["git_push", "deploy", "secrets", "global_config", "destructive_delete", "global_install"],
            },
            "designer": {
                "tool": "opencode",
                "model": "local/gpt-5.5",
                "opencode_agent": "designer",
                "autonomy": "read_only",
                "approval_required": ["workspace_write", "git_push", "deploy"],
            },
        },
        "default_readonly_agent": "oracle",
        "capability_rules": {},
    }
    (config_home / "agents.yaml").write_text(yaml.safe_dump(agents), encoding="utf-8")
    env = os.environ.copy()
    env["RUNTIME_AGENTS_CONFIG_HOME"] = str(config_home)
    env["RUNTIME_AGENTS_STATE_HOME"] = str(state_home)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PATH"] = str(FIXTURES) + os.pathsep + env.get("PATH", "")
    return env


class CliDoIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp())
        self.env = make_env(self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_do_routes_review_to_oracle_run_mode(self):
        proc = run_cli([
            "do", "Review database migrations for table lock risks",
            "--dry-run", "--json"
        ], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "oracle")
        self.assertEqual(payload["autonomy"], "read_only")
        self.assertEqual(payload["routing"]["intent"], "review")
        self.assertEqual(payload["routing"]["execution_mode"], "run")

    def test_do_routes_fix_with_check_to_fixer_iterate_mode(self):
        proc = run_cli([
            "do", "Fix broken auth login logic",
            "--check", "true",
            "--dry-run", "--json"
        ], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "fixer")
        self.assertEqual(payload["autonomy"], "workspace_write")
        self.assertEqual(payload["routing"]["intent"], "fix")
        self.assertEqual(payload["routing"]["execution_mode"], "iterate")
        self.assertIsNone(payload["routing"]["advisory"])

    def test_do_routes_fix_without_check_to_fixer_run_mode_with_advisory(self):
        proc = run_cli([
            "do", "Fix broken auth login logic",
            "--dry-run", "--json"
        ], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "fixer")
        self.assertEqual(payload["routing"]["execution_mode"], "run")
        self.assertIsNotNone(payload["routing"]["advisory"])
        self.assertIn("--check", payload["routing"]["advisory"])

    def test_do_explicit_agent_overrides_router(self):
        proc = run_cli([
            "do", "Fix broken auth login logic",
            "--agent", "designer",
            "--dry-run", "--json"
        ], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "designer")
        self.assertEqual(payload["routing"]["intent"], "explicit_agent")

    def test_run_command_omits_agent_and_auto_routes(self):
        proc = run_cli([
            "run", "Review architecture design",
            "--dry-run", "--json"
        ], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "oracle")
        self.assertEqual(payload["routing"]["intent"], "review")

    def test_iterate_command_omits_agent_and_auto_routes(self):
        proc = run_cli([
            "iterate", "Fix failing tests",
            "--check", "true",
            "--dry-run", "--json"
        ], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "fixer")
        self.assertEqual(payload["routing"]["intent"], "fix")


if __name__ == "__main__":
    unittest.main()
