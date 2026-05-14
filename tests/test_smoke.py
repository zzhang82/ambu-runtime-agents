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
    agents = {
        "models": {"primary": "gpt-5.5", "fallbacks": ["claude-sonnet-4-6", "gpt-5.4"], "cheap": "gpt-5.5"},
        "amb": {"mode": "mcp_stdio", "command": sys.executable, "args": ["-c", "print('ok')"]},
        "tools": {
            "codex": {"command": str(FIXTURES / "fake-codex-ok")},
            "claude": {"command": str(FIXTURES / "fake-claude-ok")},
            "gemini": {"command": str(FIXTURES / "fake-gemini-ok")},
        },
        "agents": {
            "coder": {
                "tool": "codex",
                "model": "gpt-5.5",
                "fallback_profiles": ["sonnet", "gpt54"],
                "autonomy": "workspace_write",
                "approval_required": ["git_push", "deploy", "secrets", "global_config", "destructive_delete", "global_install"],
            },
            "reviewer": {
                "tool": "claude",
                "model": "gpt-5.5",
                "fallback_profiles": ["sonnet", "gpt54"],
                "autonomy": "read_only",
                "approval_required": ["workspace_write", "git_push", "deploy"],
            },
            "planner": {
                "tool": "codex",
                "model": "gpt-5.5",
                "autonomy": "read_only",
                "approval_required": ["workspace_write", "git_push", "deploy"],
            },
            "cheap": {
                "tool": "gemini",
                "model": "gpt-5.5",
                "autonomy": "read_only",
                "approval_required": ["workspace_write", "git_push", "deploy", "global_config"],
            },
        },
        "capability_rules": {
            "git_push": {"patterns": ["push", "git push"]},
            "deploy": {"patterns": ["deploy"]},
            "secrets": {"patterns": ["api key", "secret", "password", ".env", "credentials"]},
            "global_config": {"patterns": ["~/.config", "/home/zzs333/.config", "~/.ssh", "/home/zzs333/.ssh", "~/.bashrc", "~/.zshrc"]},
            "destructive_delete": {"patterns": ["rm -rf /", "rm -rf ~", "find * -delete"]},
            "global_install": {"patterns": ["npm install -g", "pip install --user", "sudo apt install", "brew install"]},
        },
    }
    (config_home / "agents.yaml").write_text(yaml.safe_dump(agents, sort_keys=False), encoding="utf-8")
    workspace_path = base_dir / "workspace"
    workspace_path.mkdir()
    workspaces = {
        "test-ws": {
            "path": str(workspace_path),
            "memory_namespace": "project:test-ws",
        }
    }
    (config_home / "workspaces.yaml").write_text(yaml.safe_dump(workspaces, sort_keys=False), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["RUNTIME_AGENTS_CONFIG_HOME"] = str(config_home)
    env["RUNTIME_AGENTS_STATE_HOME"] = str(state_home)
    env["PATH"] = str(FIXTURES) + os.pathsep + env.get("PATH", "")
    return env


class RuntimeAgentsSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-test-"))
        self.env = make_env(self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_version_json(self):
        proc = run_cli(["version", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["version"], "1.1.1")
        self.assertEqual(payload["contract"], "agentctl-v1.3.0")

    def test_runbook_commands(self):
        listed = run_cli(["runbook", "list", "--json"], self.env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        items = json.loads(listed.stdout)
        self.assertTrue(any(item["id"] == "list_workspaces" for item in items))

        shown = run_cli(["runbook", "show", "list_workspaces", "--json"], self.env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        payload = json.loads(shown.stdout)
        self.assertEqual(payload["id"], "list_workspaces")

        validated = run_cli(["runbook", "validate", "--json"], self.env)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["ok"])

    def test_assistant_exec_read_only(self):
        proc = run_cli(["assistant-exec", "list", "workspaces", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "list_workspaces")
        self.assertEqual(payload["execution"][0]["type"], "list_workspaces")

    def test_assistant_exec_workspace_write_requires_confirmation(self):
        proc = run_cli(["assistant-exec", "fix", "tests", "in", "test-ws", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "pending_confirmation")
        self.assertEqual(payload["runbook_id"], "fix_tests")

    def test_assistant_route_repo_health(self):
        proc = run_cli(["assistant-route", "repo", "health", "test-ws", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["runbook_id"], "repo_health_check")

    def test_assistant_route_missing_workspace(self):
        proc = run_cli(["assistant-route", "repo", "health", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "needs_clarification")

    def test_assistant_route_list_runbooks(self):
        proc = run_cli(["assistant-route", "list", "runbooks", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["runbook_id"], "list_runbooks")

    def test_assistant_route_check_workspace(self):
        proc = run_cli(["assistant-route", "check", "workspace", "test-ws", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["runbook_id"], "check_workspace")

    def test_assistant_route_fix_tests(self):
        proc = run_cli(["assistant-route", "fix", "tests", "in", "test-ws", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["runbook_id"], "fix_tests")
        self.assertTrue(payload["requires_confirmation"])

    def test_assistant_route_dangerous(self):
        proc = run_cli(["assistant-route", "run", "rm", "-rf", "/", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "blocked")

    def test_assistant_exec_status_overview(self):
        proc = run_cli(["assistant-exec", "what", "needs", "attention?", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["runbook_id"], "status_overview")
        self.assertEqual(payload["execution"][0]["type"], "status_overview")

    def test_assistant_route_list_workspaces(self):
        proc = run_cli(["assistant-route", "list", "workspaces", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["runbook_id"], "list_workspaces")

    def test_assistant_route_show_logs_needs_task(self):
        proc = run_cli(["assistant-route", "show", "logs", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual(payload["runbook_id"], "show_logs")

    def test_config_validate_json(self):
        proc = run_cli(["config", "validate", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])

    def test_smoke_json(self):
        proc = run_cli(["smoke", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])

    def test_queue_empty_json(self):
        proc = run_cli(["queue", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [])

    def test_schedule_add_show_remove(self):
        add = run_cli(["schedule", "add", "test-health", "--workspace", "test-ws", "--type", "run", "--agent", "planner", "--goal", "check health", "--cron", "* * * * *"], self.env)
        self.assertEqual(add.returncode, 0, add.stderr)
        show = run_cli(["schedule", "show", "test-health", "--json"], self.env)
        self.assertEqual(show.returncode, 0, show.stderr)
        payload = json.loads(show.stdout)
        self.assertEqual(payload["name"], "test-health")
        remove = run_cli(["schedule", "remove", "test-health"], self.env)
        self.assertEqual(remove.returncode, 0, remove.stderr)

    def test_plan_create_show(self):
        create = run_cli(["plan", "create", "--workspace", "test-ws", "analyze", "repo", "health"], self.env)
        self.assertEqual(create.returncode, 0, create.stderr)
        payload = json.loads(create.stdout)
        show = run_cli(["plan", "show", payload["plan_id"], "--json"], self.env)
        self.assertEqual(show.returncode, 0, show.stderr)

    def test_assistant_route_basic(self):
        proc = run_cli(["assistant-route", "what needs attention?", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["intent"], "status_overview")

    def test_assistant_route_blocks_dangerous(self):
        proc = run_cli(["assistant-route", "run rm -rf /tmp/test", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn(payload["intent"], {"refuse_dangerous", "unsupported"})


if __name__ == "__main__":
    unittest.main()
