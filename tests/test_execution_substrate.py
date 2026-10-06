import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

sys.path.insert(0, str(ROOT / "src"))

from runtime_agents import cli
from runtime_agents import execution_substrate
from unittest.mock import patch


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
        "models": {"primary": "local/gpt-5.5", "fallbacks": [], "cheap": "local/gpt-5.4-mini"},
        "amb": {"mode": "mcp_stdio", "command": sys.executable, "args": ["-c", "print('ok')"]},
        "tools": {
            "opencode": {"command": str(FIXTURES / "fake-opencode-ok")},
        },
        "agents": {
            "planner": {"tool": "opencode", "model": "local/gpt-5.5", "opencode_agent": "plan", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
            "reviewer": {"tool": "opencode", "model": "local/gpt-5.5", "opencode_agent": "reviewer", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
            "cheap": {"tool": "opencode", "model": "local/gpt-5.4-mini", "opencode_agent": "general", "autonomy": "read_only", "approval_required": ["workspace_write", "git_push", "deploy"]},
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

    def test_opencode_tool_is_characterized(self):
        payload = execution_substrate.classify_agent_execution({"tool": "opencode"})
        self.assertEqual(payload["execution_substrate"], "opencode")
        self.assertFalse(payload["legacy_direct"])

    def test_opencode_command_contract_is_documented_in_code(self):
        self.assertEqual(
            execution_substrate.build_opencode_exec_command("local/gpt-5.5", "inspect", autonomy="read_only", opencode_agent="plan"),
            ["opencode", "run", "--model", "local/gpt-5.5", "--agent", "plan", "inspect"],
        )
        self.assertEqual(
            execution_substrate.build_opencode_exec_command("local/gpt-5.5", "fix", autonomy="workspace_write", opencode_agent="build"),
            ["opencode", "run", "--model", "local/gpt-5.5", "--agent", "build", "fix"],
        )

    def test_opencode_build_command_is_live_routed(self):
        self.assertEqual(
            cli.build_command("opencode", "local/gpt-5.5", "inspect", autonomy="read_only", opencode_agent="plan"),
            ["opencode", "run", "--model", "local/gpt-5.5", "--agent", "plan", "inspect"],
        )

    def test_dynamic_transient_failure_uses_next_model_and_records_cooldown(self):
        results = [
            {"started_at": "a", "ended_at": "b", "returncode": 1, "stdout": "", "stderr": "429 rate limit"},
            {"started_at": "c", "ended_at": "d", "returncode": 0, "stdout": "ok", "stderr": ""},
        ]
        with patch.object(cli, "run_command", side_effect=results), patch.object(cli.model_catalog_mod, "record_cooldown") as cooldown:
            attempts, final = cli.execute_agent_attempts(
                {"opencode_agent": "build"},
                "opencode",
                "local/grok-composer-2.5-fast",
                "implement",
                "workspace_write",
                False,
                30,
                routing_fallbacks=["local/gemini-3.7-flash-high"],
                cooldown_seconds=120,
            )
        self.assertEqual([item["model"] for item in attempts], ["local/grok-composer-2.5-fast", "local/gemini-3.7-flash-high"])
        if final is None:
            self.fail("expected a successful fallback attempt")
        self.assertEqual(final["model"], "local/gemini-3.7-flash-high")
        cooldown.assert_called_once_with("local/grok-composer-2.5-fast", "transient_model_error", 120)

    def test_direct_runtime_tools_are_unsupported(self):
        for tool in ("codex", "claude", "gemini"):
            with self.subTest(tool=tool):
                with self.assertRaises(SystemExit) as raised:
                    cli.build_command(tool, "local/gpt-5.5", "inspect")
                self.assertIn(f"Unsupported tool: {tool}", str(raised.exception))

    def test_run_dry_run_reports_current_and_intended_substrate(self):
        proc = run_cli(["run", "planner", "inspect", "repo", "--dry-run"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["execution_substrate"], "opencode")
        self.assertFalse(payload["legacy_direct"])
        self.assertEqual(payload["intended_primary_substrate"], "opencode")

    def test_inspect_reports_opencode_substrate(self):
        proc = run_cli(["inspect", "reviewer"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["tool"], "opencode")
        self.assertEqual(payload["execution_substrate"], "opencode")
        self.assertFalse(payload["legacy_direct"])
        self.assertEqual(payload["intended_primary_substrate"], "opencode")

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_timeout_terminates_spawned_process_group_and_preserves_output(self):
        child_pid_path = self.tempdir / "child.pid"
        orphan_marker = self.tempdir / "orphan-marker"
        child_code = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(orphan_marker)!r}).write_text('orphan', encoding='utf-8')"
        parent_code = (
            "import subprocess, sys, time\n"
            "from pathlib import Path\n"
            f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            f"Path({str(child_pid_path)!r}).write_text(str(child.pid), encoding='utf-8')\n"
            "print('parent stdout', flush=True)\n"
            "print('parent stderr', file=sys.stderr, flush=True)\n"
            "time.sleep(30)\n"
        )

        started = time.monotonic()
        result = cli.run_command([sys.executable, "-c", parent_code], self.tempdir, timeout=0.2)
        elapsed = time.monotonic() - started

        self.assertEqual(result["returncode"], 124)
        self.assertLess(elapsed, 2.0)
        self.assertIn("parent stdout", result["stdout"])
        self.assertIn("parent stderr", result["stderr"])
        self.assertIn("timeout after 0.2s", result["stderr"])
        self.assertTrue(child_pid_path.exists())
        time.sleep(0.7)
        self.assertFalse(orphan_marker.exists())

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_timeout_cleans_exited_launcher_group_without_touching_unrelated_process(self):
        child_pid_path = self.tempdir / "exited-launcher-child.pid"
        orphan_marker = self.tempdir / "exited-launcher-orphan-marker"
        unrelated_marker = self.tempdir / "unrelated-process-marker"
        child_code = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(orphan_marker)!r}).write_text('orphan', encoding='utf-8')"
        launcher_code = (
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            f"Path({str(child_pid_path)!r}).write_text(str(child.pid), encoding='utf-8')\n"
            "print('launcher stdout', flush=True)\n"
        )
        unrelated_code = f"import time; from pathlib import Path; time.sleep(0.4); Path({str(unrelated_marker)!r}).write_text('unrelated', encoding='utf-8')"
        unrelated = subprocess.Popen([sys.executable, "-c", unrelated_code])

        try:
            started = time.monotonic()
            result = cli.run_command([sys.executable, "-c", launcher_code], self.tempdir, timeout=0.1)
            elapsed = time.monotonic() - started

            self.assertEqual(result["returncode"], 124)
            self.assertLess(elapsed, 1.5)
            self.assertIn("launcher stdout", result["stdout"])
            self.assertIn("timeout after 0.1s", result["stderr"])
            self.assertTrue(child_pid_path.exists())
            unrelated.wait(timeout=2)
            self.assertFalse(orphan_marker.exists())
            self.assertTrue(unrelated_marker.exists())
        finally:
            if unrelated.poll() is None:
                unrelated.terminate()
                unrelated.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
