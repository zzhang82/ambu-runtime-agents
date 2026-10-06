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
                "fallback_profiles": ["gpt54"],
                "autonomy": "workspace_write",
                "approval_required": ["git_push", "deploy", "secrets", "global_config", "destructive_delete", "global_install"],
            },
            "planner": {
                "tool": "opencode",
                "model": "local/gpt-5.5",
                "opencode_agent": "plan",
                "autonomy": "read_only",
                "approval_required": ["workspace_write", "git_push", "deploy"],
            },
        },
        "capability_rules": {},
    }
    (config_home / "agents.yaml").write_text(yaml.safe_dump(agents), encoding="utf-8")
    env = os.environ.copy()
    env["RUNTIME_AGENTS_CONFIG_HOME"] = str(config_home)
    env["RUNTIME_AGENTS_STATE_HOME"] = str(state_home)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PATH"] = str(FIXTURES) + os.pathsep + env.get("PATH", "")
    return env


class IterateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp())
        self.env = make_env(self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_iterate_dry_run_reports_max_same_failure(self):
        proc = run_cli(["iterate", "planner", "check", "system", "--check", "true", "--dry-run", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["would_run"])
        self.assertEqual(payload["max_same_failure"], 2)

    def test_iterate_immediate_success_on_round_zero(self):
        proc = run_cli(["iterate", "planner", "pass", "check", "--check", "true", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["rounds"], 0)
        self.assertTrue(payload["final_check_passed"])

    def test_iterate_halts_early_on_repeated_identical_blocker(self):
        # A check script that consistently fails with the exact same error output
        failing_script = self.tempdir / "check_fail.sh"
        failing_script.write_text("#!/usr/bin/env bash\nprintf 'AssertionError: expected foo got bar\\n' >&2\nexit 1\n", encoding="utf-8")
        failing_script.chmod(0o755)

        # max-rounds is 5, but identical failure should halt after round 1 (failure count 2)
        proc = run_cli([
            "iterate", "coder", "fix", "assertion",
            "--check", str(failing_script),
            "--max-rounds", "5",
            "--max-same-failure", "2",
            "--json"
        ], self.env)

        # Klaus invariant: blocked returns exit code 3
        self.assertEqual(proc.returncode, 3, f"Expected exit code 3 for blocked, got {proc.returncode}")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["halt_reason"], "repeated_identical_failure")
        self.assertEqual(payload["rounds"], 1, "Should halt on round 1 without burning rounds 2-5")
        self.assertEqual(payload["rounds_with_same_blocker"], 2)
        self.assertEqual(payload["gap_classification"], "execution")
        self.assertTrue(payload["blocker_fingerprint"])

    def test_iterate_check_rubric_gap_on_missing_binary(self):
        # Non-existent command triggers exit 127
        proc = run_cli([
            "iterate", "planner", "run", "missing", "tool",
            "--check", "non_existent_binary_xyz_123",
            "--max-rounds", "3",
            "--json"
        ], self.env)

        self.assertEqual(proc.returncode, 3)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["gap_classification"], "check_rubric")
        self.assertIn("127", payload["gap_detail"])

    def test_iterate_completes_when_fix_succeeds_on_round_one(self):
        flag = self.tempdir / "fixed.flag"
        check_script = self.tempdir / "check_flag.sh"
        check_script.write_text(f"#!/usr/bin/env bash\nif [ -f '{flag}' ]; then exit 0; else exit 1; fi\n", encoding="utf-8")
        check_script.chmod(0o755)

        # Create a custom opencode executable that fixes the condition
        custom_bin = self.tempdir / "bin"
        custom_bin.mkdir()
        fake_fixer = custom_bin / "opencode"
        fake_fixer.write_text(f"#!/usr/bin/env bash\ntouch '{flag}'\nprintf 'OK\\n'\n", encoding="utf-8")
        fake_fixer.chmod(0o755)

        env = self.env.copy()
        env["PATH"] = str(custom_bin) + os.pathsep + env["PATH"]

        proc = run_cli([
            "iterate", "coder", "make", "flag",
            "--check", str(check_script),
            "--max-rounds", "3",
            "--json"
        ], env)

        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["rounds"], 1)
        self.assertTrue(payload["final_check_passed"])


if __name__ == "__main__":
    unittest.main()
