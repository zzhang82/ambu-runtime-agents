import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

sys.path.insert(0, str(ROOT / "src"))


def _run_cli(args, env):
    import subprocess

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
            "planner": {"tool": "codex", "model": "gpt-5.5", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
            "coder": {"tool": "codex", "model": "gpt-5.5", "autonomy": "workspace_write", "approval_required": ["git_push", "deploy"]},
            "reviewer": {"tool": "claude", "model": "gpt-5.5", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
        },
        "capability_rules": {},
    }
    (config_home / "agents.yaml").write_text(yaml.safe_dump(agents, sort_keys=False), encoding="utf-8")
    (config_home / "tools.yaml").write_text(
        yaml.safe_dump(
            {
                "tools": {
                    "web_fetch": {
                        "title": "Web Fetch",
                        "description": "Fetch web pages.",
                        "kind": "builtin",
                        "enabled": True,
                        "command": None,
                        "args": [],
                        "trust_level": "untrusted_input",
                        "data_classes": ["public_web"],
                        "egress": "public_web",
                        "capabilities": ["web_read"],
                        "workspace_scoped": False,
                        "profile_scope": ["runtime-dev"],
                    },
                    "workspace_files": {
                        "title": "Workspace Files",
                        "description": "Read and edit workspace files.",
                        "kind": "builtin",
                        "enabled": True,
                        "command": None,
                        "args": [],
                        "trust_level": "trusted",
                        "data_classes": ["workspace_files"],
                        "egress": "none",
                        "capabilities": ["filesystem_read", "filesystem_write"],
                        "workspace_scoped": True,
                        "profile_scope": ["runtime-dev"],
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    workspace_path = base_dir / "workspace"
    workspace_path.mkdir()
    workspaces = {"test-ws": {"path": str(workspace_path), "memory_namespace": "project:test-ws"}}
    (config_home / "workspaces.yaml").write_text(yaml.safe_dump(workspaces, sort_keys=False), encoding="utf-8")
    (config_home / "profiles.yaml").write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "runtime-dev": {
                        "title": "Runtime Development",
                        "description": "Default runtime development profile.",
                        "default_agent": "planner",
                        "allowed_agents": ["planner", "reviewer", "coder"],
                        "workspace_required": True,
                        "allowed_tools": ["web_fetch", "workspace_files"],
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


class AssistantExecTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-assistant-exec-"))
        self.env = make_env(self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_list_workspaces_exec_completes(self):
        proc = _run_cli(["assistant-exec", "list", "workspaces", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["action_result"]["status"], "completed")
        self.assertEqual(payload["execution"][0]["type"], "list_workspaces")

    def test_fix_tests_requires_confirmation(self):
        proc = _run_cli(["assistant-exec", "fix", "tests", "in", "test-ws", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "pending_confirmation")
        self.assertEqual(payload["action_result"]["status"], "pending_confirmation")

    def test_dangerous_phrase_stays_blocked(self):
        proc = _run_cli(["assistant-exec", "run", "rm", "-rf", "/", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "blocked")

    def test_repo_health_without_workspace_needs_clarification(self):
        proc = _run_cli(["assistant-exec", "repo", "health", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "needs_clarification")

    def test_list_profiles_exec_completes(self):
        proc = _run_cli(["assistant-exec", "list", "profiles", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["execution"][0]["type"], "list_profiles")

    def test_show_profile_exec_completes(self):
        proc = _run_cli(["assistant-exec", "show", "profile", "runtime-dev", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["execution"][0]["type"], "show_profile")

    def test_profile_run_exec_resolves_payload(self):
        proc = _run_cli(["assistant-exec", "run", "profile", "runtime-dev", "inspect", "repo", "status", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["execution"][0]["type"], "profile_run")


if __name__ == "__main__":
    unittest.main()
