"""Portable regressions for the five Steward Air package differences.

All worker/check fixtures are local and deterministic. No host credentials,
provider calls, permission policy changes, or installed runtime are used.
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_agents import cli, loop_engine, policy
from test_iterate import make_env, run_cli


class CommandCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = patch.object(cli, "load_config", return_value={})
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_diagnostic_profile_selects_existing_readonly_agent(self):
        with patch.dict(os.environ, {
            "RUNTIME_AGENTS_DIAGNOSTIC_PROFILE": "read_only",
            "RUNTIME_AGENTS_DIAGNOSTIC_EVIDENCE": "/fixture/evidence with spaces.json",
        }):
            cmd = cli.build_command("opencode", "local/test", "inspect", autonomy="read_only", opencode_agent="plan")
        self.assertIn("--pure", cmd)
        self.assertEqual(cmd[cmd.index("--format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "hcp-readonly-diagnostic")
        self.assertEqual(cmd[cmd.index("--file") + 1], "/fixture/evidence with spaces.json")
        self.assertEqual(cmd[-1], "inspect")

    def test_diagnostic_profile_rejects_writable_or_unknown_mode(self):
        for profile, autonomy in [("read_only", "workspace_write"), ("typo", "read_only")]:
            with self.subTest(profile=profile), patch.dict(os.environ, {"RUNTIME_AGENTS_DIAGNOSTIC_PROFILE": profile}):
                with self.assertRaisesRegex(SystemExit, "diagnostic"):
                    cli.build_command("opencode", "local/test", "inspect", autonomy=autonomy)

    def test_final_model_guard_enforces_both_allowlists(self):
        config = {"model_routing": {"required": True, "allowed_models": ["local/a", "local/b"]}}
        with patch.object(cli, "load_config", return_value=config), patch.dict(os.environ, {
            "RUNTIME_AGENTS_MODEL_ALLOWLIST": "local/b,local/c",
        }):
            self.assertIn("local/b", cli.build_command("opencode", "local/b", "inspect"))
            for model in (None, "local/a", "local/c"):
                with self.subTest(model=model), self.assertRaisesRegex(SystemExit, "allowlist"):
                    cli.build_command("opencode", model, "inspect")

    def test_denial_guidance_does_not_offer_escalation(self):
        prompt = loop_engine.build_iteration_prompt("fix", "check", None, "", "", "execution", "failed")
        self.assertIn("Respect permission denials", prompt)

    def test_fallbacks_remain_preflight_order_not_environment_order(self):
        results = [
            {"returncode": 1, "stdout": "", "stderr": "429 rate limit"},
            {"returncode": 0, "stdout": "ok", "stderr": ""},
        ]
        with patch.dict(os.environ, {"RUNTIME_AGENTS_MODEL_ALLOWLIST": "local/extra,local/second,local/first"}), patch.object(cli, "run_command", side_effect=results), patch.object(cli.model_catalog_mod, "record_cooldown"), patch.object(cli.time, "sleep"):
            attempts, final = cli.execute_agent_attempts(
                {"opencode_agent": "build"}, "opencode", "local/first", "repair",
                "workspace_write", False, 1, routing_fallbacks=["local/second"],
            )
        self.assertEqual([a["model"] for a in attempts], ["local/first", "local/second"])
        self.assertEqual(final["returncode"], 0)


class CheckerCompatibilityTests(unittest.TestCase):
    def test_missing_python_checker_is_check_rubric(self):
        for code, reason in [(2, "No such file or directory"), (13, "Permission denied"), (1, "Operation not permitted")]:
            stderr = f"/usr/bin/python3: can't open file '/fixture/check.py': [Errno {code}] {reason}\n"
            with self.subTest(code=code):
                self.assertEqual(loop_engine.classify_gap("", stderr, 2)[0], "check_rubric")

    def test_product_failures_and_stdout_remain_execution(self):
        for stderr in (
            "FileNotFoundError: [Errno 2] No such file or directory: 'product.json'",
            "PermissionError: [Errno 13] Permission denied: 'product.json'",
            "AssertionError: external_directory permission denied",
            "FAIL: no such file or directory",
            "external_directory",
            "AssertionError: python3: can't open file 'x': [Errno 2] No such file or directory",
        ):
            with self.subTest(stderr=stderr):
                self.assertEqual(loop_engine.classify_gap("", stderr, 1)[0], "execution")
        self.assertEqual(loop_engine.classify_gap("python3: can't open file 'x': [Errno 2] No such file or directory", "", 2)[0], "execution")

    def test_existing_policy_parser_covers_steward_and_later_fixes(self):
        for text, expected in (
            ("Do not push, merge, or deploy.", []),
            ("Push the branch. Do not deploy.", ["git_push"]),
            ("Do not merge but push the branch.", ["git_push"]),
            ("Do not review the plan but deploy the preview.", ["deploy"]),
            ("Do not merge, deploy the preview.", ["deploy"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(policy.detect_capabilities(text), expected)


class RuntimeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = make_env(self.root)
        for key in ("RUNTIME_AGENTS_MODEL_ALLOWLIST", "RUNTIME_AGENTS_DIAGNOSTIC_PROFILE", "RUNTIME_AGENTS_DIAGNOSTIC_EVIDENCE"):
            self.env.pop(key, None)
        self.env["RUNTIME_AGENTS_EVENTS_JSONL"] = str(self.root / "isolated" / "events.jsonl")

    def test_events_are_written_to_explicit_path(self):
        proc = run_cli(["iterate", "planner", "inspect", "--check", "true", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        events = Path(self.env["RUNTIME_AGENTS_EVENTS_JSONL"])
        self.assertTrue(events.is_file())
        event = json.loads(events.read_text().strip())
        self.assertEqual(event["run_id"], json.loads(proc.stdout)["task_id"])

    def test_events_default_remains_unchanged(self):
        env = self.env.copy()
        env.pop("RUNTIME_AGENTS_EVENTS_JSONL")
        proc = subprocess.run([sys.executable, "-c", "from runtime_agents.paths import EVENTS_JSONL, SELF_IMPROVE_HOME; assert EVENTS_JSONL == SELF_IMPROVE_HOME / 'events' / 'agent-runs.jsonl'"], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_inaccessible_check_stops_before_worker_and_retains_p1_evidence(self):
        for check in ("non_existent_checker_compat_123", f"{shlex.quote(sys.executable)} {shlex.quote(str(self.root / 'missing-check.py'))}"):
            with self.subTest(check=check):
                proc = run_cli(["iterate", "coder", "repair", "--check", check, "--workspace", "test-ws", "--no-memory", "--max-rounds", "3", "--json"], self.env)
                self.assertEqual(proc.returncode, 3, proc.stderr)
                result = json.loads(proc.stdout)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["gap_classification"], "check_rubric")
                self.assertEqual(result["halt_reason"], "inaccessible_check")
                self.assertEqual(result["rounds"], 0)
                self.assertFalse(result["final_check_passed"])
                self.assertEqual(result["acceptance_status"], "failed")
                run_dir = self.root / "state" / "runs" / result["task_id"]
                self.assertTrue((run_dir / "rounds" / "0" / "check-stderr.log").is_file())
                self.assertFalse((run_dir / "rounds" / "1").exists())

    def test_preflight_or_explicit_pin_never_uses_legacy_fallback(self):
        # Stub preflight and subprocess results inside a real CLI invocation.
        # An environment allowlist must not become a new candidate list, and
        # --fallback must not add legacy profiles after a transient failure.
        for command in ("run", "iterate"):
            for required, explicit in ((True, False), (False, True)):
                with self.subTest(command=command, required=required, explicit=explicit):
                    routing = {"required": required, "explicit_override": explicit,
                               "selected_model": "local/gpt-5.5", "fallbacks": []}
                    script = (
                        "from runtime_agents import cli\n"
                        f"cli.model_catalog_mod.dispatch_preflight = lambda *a, **k: {routing!r}\n"
                        "cli.model_catalog_mod.record_cooldown = lambda *a, **k: None\n"
                        "cli.time.sleep = lambda *a: None\n"
                        "cli.run_command = lambda *a, **k: {'returncode': 1, 'stdout': '', 'stderr': '429 rate limit', 'started_at': 'a', 'ended_at': 'b'}\n"
                        "raise SystemExit(cli.main())\n"
                    )
                    args = [command, "coder", "repair", "--fallback", "--json", "--no-memory"]
                    if command == "iterate":
                        args += ["--check", "false", "--max-rounds", "1"]
                    env = self.env.copy()
                    env["RUNTIME_AGENTS_MODEL_ALLOWLIST"] = "local/gpt-5.5,local/gpt-5.4"
                    proc = subprocess.run([sys.executable, "-c", script, *args], env=env, cwd=self.root, capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 1, proc.stderr)
                    result = json.loads(proc.stdout)
                    run_dir = self.root / "state" / "runs" / result["task_id"]
                    record_path = run_dir / "result.json" if command == "run" else run_dir / "rounds" / "1" / "result.json"
                    record = json.loads(record_path.read_text())
                    self.assertEqual([attempt["model"] for attempt in record["attempts"]], ["local/gpt-5.5"])

    def test_checker_becomes_unavailable_after_round_one(self):
        # No checker mutation: the worker changes an ordinary artifact and the
        # same shell command subsequently returns the check-rubric exit code.
        bindir = self.root / "bin"
        bindir.mkdir()
        worker = bindir / "opencode"
        worker.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath('attempted').write_text('yes')\n")
        worker.chmod(0o755)
        self.env["PATH"] = str(bindir) + os.pathsep + self.env["PATH"]
        check = "if test -f attempted; then exit 126; else exit 1; fi"
        proc = run_cli(["iterate", "coder", "repair", "--workspace", "test-ws", "--no-memory", "--check", check, "--max-rounds", "3", "--max-same-failure", "3", "--json"], self.env)
        self.assertEqual(proc.returncode, 3, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(result["halt_reason"], "inaccessible_check")
        self.assertEqual(result["acceptance_status"], "failed")
        self.assertEqual(result["acceptance"]["checks"][0]["returncode"], 126)


if __name__ == "__main__":
    unittest.main()
