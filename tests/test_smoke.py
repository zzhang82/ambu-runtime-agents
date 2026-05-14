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
    (config_home / "tools.yaml").write_text(
        yaml.safe_dump(
            {
                "tools": {
                    "repo_read": {
                        "title": "Repo Read",
                        "description": "Read repository files.",
                        "kind": "builtin",
                        "enabled": True,
                        "command": None,
                        "args": [],
                        "trust_level": "trusted",
                        "data_classes": ["project_source"],
                        "egress": "none",
                        "capabilities": ["filesystem_read"],
                        "workspace_scoped": True,
                        "profile_scope": ["runtime-dev"],
                    },
                    "telegram_notify": {
                        "title": "Telegram Notify",
                        "description": "Send Telegram notifications.",
                        "kind": "builtin",
                        "enabled": True,
                        "command": None,
                        "args": [],
                        "trust_level": "trusted",
                        "data_classes": ["workspace_files"],
                        "egress": "telegram",
                        "capabilities": ["api_call"],
                        "workspace_scoped": False,
                        "profile_scope": ["shopping-watch"],
                    },
                    "web_fetch": {
                        "title": "Web Fetch",
                        "description": "Fetch public webpages.",
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
                        "capabilities": ["filesystem_read", "filesystem_write", "workspace_write"],
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
    workspaces = {
        "test-ws": {
            "path": str(workspace_path),
            "memory_namespace": "project:test-ws",
        }
    }
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
                        "allowed_tools": ["repo_read", "web_fetch", "workspace_files"],
                        "blocked_capabilities": ["git_push", "deploy", "secrets", "global_config", "destructive_delete", "global_install"],
                        "approval_required": ["workspace_write", "git_push", "deploy"],
                        "default_run_goal": "inspect repo status",
                        "default_plan_goal": "improve tests",
                    },
                    "shopping-watch": {
                        "title": "Shopping Watch",
                        "description": "Notification-only shopping monitor.",
                        "default_agent": "planner",
                        "allowed_agents": ["planner", "reviewer"],
                        "workspace_required": False,
                        "allowed_tools": ["telegram_notify"],
                        "blocked_capabilities": ["external_purchase", "checkout", "payment", "captcha_bypass"],
                        "approval_required": [],
                        "default_run_goal": "review item",
                        "default_plan_goal": "plan item review",
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
        self.assertEqual(payload["version"], "1.5.0")
        self.assertEqual(payload["contract"], "agentctl-v1.5.0")

    def test_guardrail_commands(self):
        listed = run_cli(["guardrail", "list", "--json"], self.env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        rules_payload = json.loads(listed.stdout)
        self.assertTrue(any(item["rule_id"] == "profile_blocked_capability" for item in rules_payload["rules"]))

        allow_eval = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "repo_read", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(allow_eval.returncode, 0, allow_eval.stderr)
        allow_payload = json.loads(allow_eval.stdout)
        self.assertEqual(allow_payload["decision"], "allow")

        blocked_eval = run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "external_purchase", "--json"], self.env)
        self.assertEqual(blocked_eval.returncode, 1, blocked_eval.stderr)
        blocked_payload = json.loads(blocked_eval.stdout)
        self.assertEqual(blocked_payload["decision"], "block")

        missing_tool = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "missing-tool", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(missing_tool.returncode, 1, missing_tool.stderr)
        self.assertEqual(json.loads(missing_tool.stdout)["rule_id"], "unknown_tool")

        tool_not_allowed = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "telegram_notify", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(tool_not_allowed.returncode, 1, tool_not_allowed.stderr)
        self.assertEqual(json.loads(tool_not_allowed.stdout)["rule_id"], "tool_not_allowed_for_profile")

        disabled_tool = Path(self.env["RUNTIME_AGENTS_CONFIG_HOME"]) / "tools.yaml"
        config_tools = yaml.safe_load(disabled_tool.read_text(encoding="utf-8"))
        config_tools["tools"]["repo_read"]["enabled"] = False
        disabled_tool.write_text(yaml.safe_dump(config_tools, sort_keys=False), encoding="utf-8")
        disabled_eval = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "repo_read", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(disabled_eval.returncode, 1, disabled_eval.stderr)
        self.assertEqual(json.loads(disabled_eval.stdout)["rule_id"], "tool_disabled")

        config_tools["tools"]["repo_read"]["enabled"] = True
        disabled_tool.write_text(yaml.safe_dump(config_tools, sort_keys=False), encoding="utf-8")

        disabled_profile = Path(self.env["RUNTIME_AGENTS_CONFIG_HOME"]) / "profiles.yaml"
        config_profiles = yaml.safe_load(disabled_profile.read_text(encoding="utf-8"))
        original_allowed_tools = config_profiles["profiles"]["runtime-dev"].get("allowed_tools", [])
        config_profiles["profiles"]["runtime-dev"]["allowed_tools"] = ["web_fetch"]
        disabled_profile.write_text(yaml.safe_dump(config_profiles, sort_keys=False), encoding="utf-8")
        profile_block_eval = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "repo_read", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(profile_block_eval.returncode, 1, profile_block_eval.stderr)
        self.assertEqual(json.loads(profile_block_eval.stdout)["rule_id"], "tool_not_allowed_for_profile")

        config_profiles["profiles"]["runtime-dev"]["allowed_tools"] = original_allowed_tools
        disabled_profile.write_text(yaml.safe_dump(config_profiles, sort_keys=False), encoding="utf-8")

        approval_eval = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "workspace_files", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(approval_eval.returncode, 1, approval_eval.stderr)
        self.assertEqual(json.loads(approval_eval.stdout)["decision"], "approval_required")

        purchase_eval = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--action", "external_purchase", "--json"], self.env)
        self.assertEqual(purchase_eval.returncode, 1, purchase_eval.stderr)
        self.assertEqual(json.loads(purchase_eval.stdout)["decision"], "block")

        shell_eval = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--action", "shell", "--json"], self.env)
        self.assertEqual(shell_eval.returncode, 1, shell_eval.stderr)
        self.assertEqual(json.loads(shell_eval.stdout)["rule_id"], "block_arbitrary_shell")

        private_external_eval = run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(private_external_eval.returncode, 1, private_external_eval.stderr)
        self.assertEqual(json.loads(private_external_eval.stdout)["rule_id"], "require_approval_private_external_summary")

        untrusted_private_tool = Path(self.env["RUNTIME_AGENTS_CONFIG_HOME"]) / "tools.yaml"
        changed_tools = yaml.safe_load(untrusted_private_tool.read_text(encoding="utf-8"))
        changed_tools["tools"]["telegram_notify"]["trust_level"] = "untrusted_input"
        untrusted_private_tool.write_text(yaml.safe_dump(changed_tools, sort_keys=False), encoding="utf-8")
        untrusted_eval = run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(untrusted_eval.returncode, 1, untrusted_eval.stderr)
        self.assertEqual(json.loads(untrusted_eval.stdout)["rule_id"], "block_untrusted_private_external_send")

        changed_tools["tools"]["telegram_notify"]["trust_level"] = "trusted"
        changed_tools["tools"]["telegram_notify"]["capabilities"] = ["broker_order_submit"]
        untrusted_private_tool.write_text(yaml.safe_dump(changed_tools, sort_keys=False), encoding="utf-8")
        broker_eval = run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(broker_eval.returncode, 1, broker_eval.stderr)
        self.assertEqual(json.loads(broker_eval.stdout)["rule_id"], "block_broker_order_submit")

        changed_tools["tools"]["telegram_notify"]["capabilities"] = ["external_purchase"]
        untrusted_private_tool.write_text(yaml.safe_dump(changed_tools, sort_keys=False), encoding="utf-8")
        purchase_tool_eval = run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(purchase_tool_eval.returncode, 1, purchase_tool_eval.stderr)
        self.assertEqual(json.loads(purchase_tool_eval.stdout)["rule_id"], "block_external_purchase")

        same_strength = run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "external_purchase", "--json"], self.env)
        self.assertEqual(same_strength.returncode, 1, same_strength.stderr)
        same_strength_payload = json.loads(same_strength.stdout)
        self.assertTrue(any(item["decision"] == "block" for item in same_strength_payload["policy_decisions"]))
        self.assertEqual(same_strength_payload["decision"], "block")

        implicit_tool = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(implicit_tool.returncode, 0, implicit_tool.stderr)
        implicit_payload = json.loads(implicit_tool.stdout)
        self.assertEqual(implicit_payload["decision"], "allow")
        self.assertEqual(implicit_payload["context_state"]["tool_trace"], [])
        self.assertIn("repo_read", implicit_payload["context_state"]["tools_considered"])

        context_source = run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "repo_read", "--action", "profile_run", "--json"], self.env)
        self.assertEqual(context_source.returncode, 0, context_source.stderr)
        self.assertEqual(json.loads(context_source.stdout)["context_state"]["tool_trace"][0]["source"], "config")

        self.assertEqual(rules_payload["rules"][-1]["rule_id"], "default_allow")
        self.assertEqual(rules_payload["rules"][-1]["decision"], "allow")

        profile_payload = json.loads(run_cli(["profile", "show", "runtime-dev", "--json"], self.env).stdout)
        self.assertEqual(profile_payload["resolved"]["tools"][0], "repo_read")

        tool_payload = json.loads(run_cli(["tool", "show", "repo_read", "--json"], self.env).stdout)
        self.assertEqual(tool_payload["profile_scope"], ["runtime-dev"])

        action_payload = json.loads(run_cli(["assistant-exec", "list", "workspaces", "--json"], self.env).stdout)
        self.assertEqual(action_payload["action_result"]["status"], "completed")

        self.assertTrue(all(rule["description"] for rule in rules_payload["rules"]))

        allow_payload = json.loads(run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "repo_read", "--action", "profile_run", "--json"], self.env).stdout)
        self.assertEqual(allow_payload["context_state"]["profile"], "runtime-dev")
        self.assertEqual(allow_payload["context_state"]["workspace"], None)
        self.assertIn("profile_run", allow_payload["context_state"]["capabilities"])

        approval_payload = json.loads(run_cli(["guardrail", "eval", "--profile", "runtime-dev", "--tool", "workspace_files", "--action", "profile_run", "--json"], self.env).stdout)
        self.assertTrue(any(item["rule_id"] == "profile_approval_required" for item in approval_payload["policy_decisions"]))

        config_tools = yaml.safe_load((Path(self.env["RUNTIME_AGENTS_CONFIG_HOME"]) / "tools.yaml").read_text(encoding="utf-8"))

        blocked_payload = json.loads(run_cli(["guardrail", "eval", "--profile", "shopping-watch", "--tool", "telegram_notify", "--action", "external_purchase", "--json"], self.env).stdout)
        self.assertTrue(any(item["rule_id"] == "profile_blocked_capability" for item in blocked_payload["policy_decisions"]))

        list_payload = json.loads(run_cli(["guardrail", "list", "--json"], self.env).stdout)
        self.assertEqual(list_payload["rules"][0]["rule_id"], "block_arbitrary_shell")

        self.assertEqual(json.loads(run_cli(["version", "--json"], self.env).stdout)["contract"], "agentctl-v1.5.0")

        dry_run_payload = json.loads(run_cli(["profile", "run", "runtime-dev", "inspect", "repo", "status", "--workspace", "test-ws", "--dry-run", "--json"], self.env).stdout)
        self.assertIn("context_state", dry_run_payload)
        self.assertIn("policy_decisions", dry_run_payload)

        plan_create = run_cli(["profile", "plan", "runtime-dev", "improve", "tests", "--workspace", "test-ws", "--json"], self.env)
        self.assertEqual(plan_create.returncode, 0, plan_create.stderr)
        plan_payload = json.loads(plan_create.stdout)
        self.assertIn("context_state", plan_payload)
        self.assertIn("policy_decisions", plan_payload)
        shown_plan = json.loads(run_cli(["plan", "show", plan_payload["plan_id"], "--json"], self.env).stdout)
        self.assertIn("context_state", shown_plan)
        self.assertIn("policy_decisions", shown_plan)

        blocked_run = run_cli(["profile", "run", "shopping-watch", "buy", "this", "item", "--tool", "telegram_notify", "--json"], self.env)
        self.assertEqual(blocked_run.returncode, 2, blocked_run.stderr)

        doctor_payload = {row["name"]: row for row in json.loads(run_cli(["doctor", "--json"], self.env).stdout)}
        self.assertIn("guardrails_loadable", doctor_payload)
        self.assertIn("guardrails_eval_smoke", doctor_payload)

        smoke_payload = json.loads(run_cli(["smoke", "--json"], self.env).stdout)
        self.assertTrue(smoke_payload["guardrails_ok"])
        self.assertGreater(smoke_payload["guardrails_rules_count"], 0)

        self.assertEqual(json.loads(run_cli(["queue", "--json"], self.env).stdout), [])

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
        validated_payload = json.loads(validated.stdout)
        self.assertTrue(validated_payload["ok"])
        self.assertEqual(validated_payload["invalid_count"], 0)

        strict_validated = run_cli(["runbook", "validate", "--strict", "--json"], self.env)
        self.assertEqual(strict_validated.returncode, 0, strict_validated.stderr)
        self.assertTrue(json.loads(strict_validated.stdout)["ok"])

    def test_runbook_validate_and_doctor_report_invalid_local_runbook(self):
        bad_runbook = Path(self.env["RUNTIME_AGENTS_CONFIG_HOME"]) / "runbooks" / "bad.md"
        bad_runbook.parent.mkdir(exist_ok=True)
        bad_runbook.write_text("not frontmatter\n", encoding="utf-8")

        validated = run_cli(["runbook", "validate", "--json"], self.env)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        validated_payload = json.loads(validated.stdout)
        self.assertTrue(validated_payload["ok"])
        self.assertEqual(validated_payload["invalid_count"], 1)
        self.assertEqual(validated_payload["skipped_count"], 1)

        strict_validated = run_cli(["runbook", "validate", "--strict", "--json"], self.env)
        self.assertEqual(strict_validated.returncode, 1, strict_validated.stderr)
        strict_payload = json.loads(strict_validated.stdout)
        self.assertFalse(strict_payload["ok"])

        doctor = run_cli(["doctor", "--json"], self.env)
        self.assertEqual(doctor.returncode, 1, doctor.stderr)
        checks = json.loads(doctor.stdout)
        by_name = {row["name"]: row for row in checks}
        self.assertFalse(by_name["runbooks_invalid_count"]["ok"])
        self.assertFalse(by_name["runbooks_strict_valid"]["ok"])
        self.assertIn("runbooks_loadable", by_name)

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
        self.assertEqual(payload["version"], "1.5.0")
        self.assertTrue(payload["tools_ok"])
        self.assertTrue(payload["profiles_ok"])
        self.assertTrue(payload["guardrails_ok"])
        self.assertGreater(payload["guardrails_rules_count"], 0)
        self.assertEqual(payload["tools_invalid_count"], 0)
        self.assertEqual(payload["profiles_invalid_count"], 0)
        self.assertEqual(json.loads(run_cli(["queue", "--json"], self.env).stdout), [])

    def test_profile_run_dry_run(self):
        proc = run_cli(["profile", "run", "runtime-dev", "inspect", "repo", "status", "--workspace", "test-ws", "--dry-run", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "dry_run_ok")
        self.assertEqual(payload["workspace"], "test-ws")
        self.assertIn("context_state", payload)
        self.assertIn("policy_decisions", payload)
        self.assertIn("repo_read", payload["context_state"]["tools_considered"])

    def test_profile_plan(self):
        proc = run_cli(["profile", "plan", "runtime-dev", "improve", "tests", "--workspace", "test-ws", "--json"], self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("plan_id", payload)
        self.assertIn("context_state", payload)
        self.assertIn("policy_decisions", payload)
        shown = run_cli(["plan", "show", payload["plan_id"], "--json"], self.env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        plan = json.loads(shown.stdout)
        self.assertEqual(plan["profile_id"], "runtime-dev")
        self.assertIn("context_state", plan)
        self.assertIn("policy_decisions", plan)

    def test_profile_run_blocks_unknown_tool(self):
        proc = run_cli(["profile", "run", "runtime-dev", "inspect", "repo", "status", "--workspace", "test-ws", "--tool", "missing-tool", "--dry-run", "--json"], self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["rule_id"], "unknown_tool")

    def test_profile_run_blocks_tool_outside_profile(self):
        proc = run_cli(["profile", "run", "runtime-dev", "inspect", "repo", "status", "--workspace", "test-ws", "--tool", "telegram_notify", "--dry-run", "--json"], self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["rule_id"], "tool_not_allowed_for_profile")

    def test_profile_run_approval_required_for_workspace_write_tool(self):
        proc = run_cli(["profile", "run", "runtime-dev", "inspect", "repo", "status", "--workspace", "test-ws", "--tool", "workspace_files", "--dry-run", "--json"], self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "approval_required")
        self.assertTrue(any(item["rule_id"] == "profile_approval_required" for item in payload["policy_decisions"]))

    def test_doctor_reports_guardrails(self):
        doctor = run_cli(["doctor", "--json"], self.env)
        checks = json.loads(doctor.stdout)
        by_name = {row["name"]: row for row in checks}
        self.assertIn("guardrails_loadable", by_name)
        self.assertIn("guardrails_rules_count", by_name)
        self.assertIn("guardrails_eval_smoke", by_name)
        self.assertTrue(by_name["guardrails_loadable"]["ok"])
        self.assertTrue(by_name["guardrails_eval_smoke"]["ok"])

    def test_selftest_reports_guardrails(self):
        selftest = run_cli(["selftest", "--json"], self.env)
        payload = json.loads(selftest.stdout)
        steps = {row["name"]: row for row in payload["steps"]}
        self.assertIn("guardrail_list", steps)
        self.assertIn("guardrail_eval_allow", steps)
        self.assertIn("guardrail_eval_unknown_tool", steps)
        self.assertIn("guardrail_eval_block_purchase", steps)
        self.assertTrue(steps["guardrail_list"]["ok"])
        self.assertTrue(steps["guardrail_eval_allow"]["ok"])
        self.assertTrue(steps["guardrail_eval_unknown_tool"]["ok"])
        self.assertTrue(steps["guardrail_eval_block_purchase"]["ok"])

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

    def test_tool_commands(self):
        listed = run_cli(["tool", "list", "--json"], self.env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        items = json.loads(listed.stdout)
        self.assertTrue(any(item["id"] == "web_fetch" for item in items))

        shown = run_cli(["tool", "show", "web_fetch", "--json"], self.env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["id"], "web_fetch")

        validated = run_cli(["tool", "validate", "--json"], self.env)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["ok"])

    def test_profile_commands(self):
        listed = run_cli(["profile", "list", "--json"], self.env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        items = json.loads(listed.stdout)
        self.assertTrue(any(item["id"] == "runtime-dev" for item in items))

        shown = run_cli(["profile", "show", "runtime-dev", "--json"], self.env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        shown_payload = json.loads(shown.stdout)
        self.assertEqual(shown_payload["id"], "runtime-dev")

        validated = run_cli(["profile", "validate", "--json"], self.env)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["ok"])


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
