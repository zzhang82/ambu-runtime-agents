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


if __name__ == "__main__":
    unittest.main()
