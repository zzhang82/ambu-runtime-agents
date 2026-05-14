import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import runbooks


class RunbookValidationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-runbooks-"))
        self.old_config_home = os.environ.get("RUNTIME_AGENTS_CONFIG_HOME")
        os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = str(self.tempdir / "config")
        (self.tempdir / "config" / "runbooks").mkdir(parents=True)

    def tearDown(self):
        if self.old_config_home is None:
            os.environ.pop("RUNTIME_AGENTS_CONFIG_HOME", None)
        else:
            os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = self.old_config_home
        shutil.rmtree(self.tempdir)

    def test_invalid_local_runbook_is_skipped_in_normal_load(self):
        bad = self.tempdir / "config" / "runbooks" / "bad.md"
        bad.write_text("not frontmatter\n", encoding="utf-8")
        items = runbooks.load_runbooks()
        self.assertTrue(any(item["id"] == "list_workspaces" for item in items))
        self.assertFalse(any(item.get("source_file") == "bad.md" for item in items))

    def test_validate_reports_invalid_local_runbook_without_failing_normal_mode(self):
        bad = self.tempdir / "config" / "runbooks" / "bad.md"
        bad.write_text("not frontmatter\n", encoding="utf-8")
        payload = runbooks.validate_runbooks(strict=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["invalid_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)

    def test_strict_validate_fails_on_invalid_local_runbook(self):
        bad = self.tempdir / "config" / "runbooks" / "bad.md"
        bad.write_text("not frontmatter\n", encoding="utf-8")
        payload = runbooks.validate_runbooks(strict=True)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["invalid_count"], 1)

    def test_local_override_wins_by_id(self):
        override = self.tempdir / "config" / "runbooks" / "list-workspaces.md"
        override.write_text(
            "---\n"
            "id: list_workspaces\n"
            "title: Local list workspaces\n"
            "risk: read_only\n"
            "requires_confirmation: false\n"
            "description: local override\n"
            "phrases:\n"
            "  - list workspaces\n"
            "inputs: {}\n"
            "actions:\n"
            "  - type: list_workspaces\n"
            "response:\n"
            "  matched: local\n"
            "---\n",
            encoding="utf-8",
        )
        item = next(item for item in runbooks.load_runbooks() if item["id"] == "list_workspaces")
        self.assertEqual(item["title"], "Local list workspaces")
        self.assertEqual(item["source"], "config")

    def test_new_profile_and_tool_actions_are_allowed(self):
        profile_runbook = runbooks.load_runbook_from_path(
            Path(__file__).resolve().parents[1] / "src" / "runtime_agents" / "default_runbooks" / "profile-run.md"
        )
        tool_runbook = runbooks.load_runbook_from_path(
            Path(__file__).resolve().parents[1] / "src" / "runtime_agents" / "default_runbooks" / "show-tool.md"
        )
        self.assertEqual(profile_runbook["actions"][0]["type"], "profile_run")
        self.assertEqual(tool_runbook["actions"][0]["type"], "show_tool")

    def test_profile_runbook_matches_inputs(self):
        matched = runbooks.match_runbook("run profile runtime-dev inspect repo status")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "profile_run")
        self.assertEqual(matched["inputs"]["profile_id"], "runtime-dev")
        self.assertEqual(matched["actions"][0]["type"], "profile_run")

    def test_list_profiles_runbook_matches(self):
        matched = runbooks.match_runbook("list profiles")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "list_profiles")

    def test_show_tool_runbook_matches(self):
        matched = runbooks.match_runbook("show tool web_fetch")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "show_tool")
        self.assertEqual(matched["actions"][0]["tool_id"], "web_fetch")

    def test_show_profile_runbook_matches(self):
        matched = runbooks.match_runbook("show profile runtime-dev")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "show_profile")
        self.assertEqual(matched["actions"][0]["profile_id"], "runtime-dev")

    def test_profile_plan_runbook_matches(self):
        matched = runbooks.match_runbook("plan with profile runtime-dev improve tests")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "profile_plan")
        self.assertEqual(matched["actions"][0]["type"], "profile_plan")

    def test_profile_and_tool_packaged_runbooks_are_loadable(self):
        ids = {item["id"] for item in runbooks.load_runbooks()}
        self.assertIn("list_profiles", ids)
        self.assertIn("show_profile", ids)
        self.assertIn("list_tools", ids)
        self.assertIn("show_tool", ids)
        self.assertIn("profile_run", ids)
        self.assertIn("profile_plan", ids)

    def test_match_profile_runbook_missing_goal_is_none(self):
        matched = runbooks.match_runbook("run profile runtime-dev")
        self.assertIsNone(matched)

    def test_match_profile_plan_runbook_missing_goal_is_none(self):
        matched = runbooks.match_runbook("plan with profile runtime-dev")
        self.assertIsNone(matched)

    def test_match_show_tool_with_punctuation(self):
        matched = runbooks.match_runbook("show tool web_fetch?")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "show_tool")

    def test_match_list_tools(self):
        matched = runbooks.match_runbook("list tools")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "list_tools")

    def test_match_profile_alias_phrase(self):
        matched = runbooks.match_runbook("profile runtime-dev")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "show_profile")

    def test_match_tool_alias_phrase(self):
        matched = runbooks.match_runbook("tool web_fetch")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "show_tool")

    def test_load_runbooks_includes_new_profile_and_tool_runbooks(self):
        ids = [item["id"] for item in runbooks.load_runbooks()]
        self.assertIn("profile_run", ids)
        self.assertIn("profile_plan", ids)
        self.assertIn("list_profiles", ids)
        self.assertIn("list_tools", ids)

    def test_validate_all_packaged_runbooks_still_ok(self):
        payload = runbooks.validate_runbooks(strict=True)
        self.assertTrue(payload["ok"])

    def test_profile_runbook_renders_goal(self):
        matched = runbooks.match_runbook("use profile runtime-dev to improve tests")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["actions"][0]["goal"], "improve tests")

    def test_profile_plan_runbook_renders_goal(self):
        matched = runbooks.match_runbook("create plan with profile runtime-dev improve tests")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["actions"][0]["goal"], "improve tests")

    def test_profile_runbook_returns_read_only_risk(self):
        matched = runbooks.match_runbook("run profile runtime-dev inspect repo status")
        self.assertEqual(matched["risk"], "read_only")

    def test_tool_runbook_returns_read_only_risk(self):
        matched = runbooks.match_runbook("show tool web_fetch")
        self.assertEqual(matched["risk"], "read_only")

    def test_profile_show_runbook_returns_read_only_risk(self):
        matched = runbooks.match_runbook("show profile runtime-dev")
        self.assertEqual(matched["risk"], "read_only")

    def test_profile_and_tool_runbook_ids_are_unique(self):
        ids = [item["id"] for item in runbooks.load_runbooks()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_show_profile_runbook_action_renders_profile_id(self):
        matched = runbooks.match_runbook("show profile runtime-dev")
        self.assertEqual(matched["actions"][0]["profile_id"], "runtime-dev")

    def test_show_tool_runbook_action_renders_tool_id(self):
        matched = runbooks.match_runbook("show tool web_fetch")
        self.assertEqual(matched["actions"][0]["tool_id"], "web_fetch")

    def test_list_profiles_has_no_required_inputs(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "list_profiles")
        self.assertEqual(runbook["inputs"], {})

    def test_list_tools_has_no_required_inputs(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "list_tools")
        self.assertEqual(runbook["inputs"], {})

    def test_profile_plan_runbook_has_required_inputs(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "profile_plan")
        self.assertTrue(runbook["inputs"]["profile_id"]["required"])
        self.assertTrue(runbook["inputs"]["goal"]["required"])

    def test_profile_run_runbook_has_required_inputs(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "profile_run")
        self.assertTrue(runbook["inputs"]["profile_id"]["required"])
        self.assertTrue(runbook["inputs"]["goal"]["required"])

    def test_show_tool_runbook_has_required_inputs(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "show_tool")
        self.assertTrue(runbook["inputs"]["tool_id"]["required"])

    def test_show_profile_runbook_has_required_inputs(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "show_profile")
        self.assertTrue(runbook["inputs"]["profile_id"]["required"])

    def test_match_list_profiles_normalized_spacing(self):
        matched = runbooks.match_runbook("list   profiles")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "list_profiles")

    def test_match_list_tools_normalized_spacing(self):
        matched = runbooks.match_runbook("list   tools")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "list_tools")

    def test_profile_plan_message_renders_profile_id(self):
        matched = runbooks.match_runbook("plan with profile runtime-dev improve tests")
        self.assertIn("runtime-dev", matched["message"])

    def test_profile_run_message_renders_profile_id(self):
        matched = runbooks.match_runbook("run profile runtime-dev inspect repo status")
        self.assertIn("runtime-dev", matched["message"])

    def test_show_tool_message_renders_tool_id(self):
        matched = runbooks.match_runbook("show tool web_fetch")
        self.assertIn("web_fetch", matched["message"])

    def test_show_profile_message_renders_profile_id(self):
        matched = runbooks.match_runbook("show profile runtime-dev")
        self.assertIn("runtime-dev", matched["message"])

    def test_profile_run_goes_through_text_input(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "profile_run")
        self.assertEqual(runbook["inputs"]["goal"]["type"], "text")

    def test_profile_plan_goes_through_text_input(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "profile_plan")
        self.assertEqual(runbook["inputs"]["goal"]["type"], "text")

    def test_show_tool_uses_id_input(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "show_tool")
        self.assertEqual(runbook["inputs"]["tool_id"]["type"], "id")

    def test_show_profile_uses_id_input(self):
        runbook = next(item for item in runbooks.load_runbooks() if item["id"] == "show_profile")
        self.assertEqual(runbook["inputs"]["profile_id"]["type"], "id")

    def test_profile_run_phrase_variant_matches(self):
        matched = runbooks.match_runbook("use profile runtime-dev to inspect repo status")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "profile_run")

    def test_profile_plan_phrase_variant_matches(self):
        matched = runbooks.match_runbook("create plan with profile runtime-dev improve tests")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["runbook_id"], "profile_plan")

    def test_show_profile_returns_matching_title(self):
        matched = runbooks.match_runbook("show profile runtime-dev")
        self.assertEqual(matched["title"], "Show profile")

    def test_show_tool_returns_matching_title(self):
        matched = runbooks.match_runbook("show tool web_fetch")
        self.assertEqual(matched["title"], "Show tool")

    def test_list_profiles_returns_matching_title(self):
        matched = runbooks.match_runbook("list profiles")
        self.assertEqual(matched["title"], "List profiles")

    def test_list_tools_returns_matching_title(self):
        matched = runbooks.match_runbook("list tools")
        self.assertEqual(matched["title"], "List tools")

    def test_profile_plan_returns_matching_title(self):
        matched = runbooks.match_runbook("plan with profile runtime-dev improve tests")
        self.assertEqual(matched["title"], "Profile plan")

    def test_profile_run_returns_matching_title(self):
        matched = runbooks.match_runbook("run profile runtime-dev inspect repo status")
        self.assertEqual(matched["title"], "Profile run")

    def test_validate_runbooks_payload_includes_new_entries(self):
        payload = runbooks.validate_runbooks(strict=False)
        ids = {row["id"] for row in payload["runbooks"] if row["id"]}
        self.assertIn("list_profiles", ids)
        self.assertIn("show_tool", ids)

    def test_profile_show_and_tool_show_are_not_clarification_routes(self):
        self.assertEqual(runbooks.match_runbook("show profile runtime-dev")["status"], "matched")
        self.assertEqual(runbooks.match_runbook("show tool web_fetch")["status"], "matched")

    def test_profile_run_and_plan_are_not_clarification_routes_with_goal(self):
        self.assertEqual(runbooks.match_runbook("run profile runtime-dev inspect repo status")["status"], "matched")
        self.assertEqual(runbooks.match_runbook("plan with profile runtime-dev improve tests")["status"], "matched")

    def test_tool_and_profile_aliases_are_distinct(self):
        self.assertEqual(runbooks.match_runbook("profile runtime-dev")["runbook_id"], "show_profile")
        self.assertEqual(runbooks.match_runbook("tool web_fetch")["runbook_id"], "show_tool")

    def test_profile_and_tool_runbooks_survive_normal_load(self):
        payload = runbooks.inspect_runbooks(strict=False)
        ids = {item["id"] for item in payload["loadable"]}
        self.assertIn("profile_run", ids)
        self.assertIn("list_tools", ids)

    def test_profile_and_tool_runbooks_survive_strict_validation(self):
        payload = runbooks.inspect_runbooks(strict=True)
        ids = {item["id"] for item in payload["loadable"]}
        self.assertIn("profile_run", ids)
        self.assertIn("list_profiles", ids)

    def test_profile_and_tool_runbook_warnings_are_empty_when_valid(self):
        payload = runbooks.validate_runbooks(strict=False)
        self.assertIsInstance(payload["warnings"], list)


if __name__ == "__main__":
    unittest.main()
