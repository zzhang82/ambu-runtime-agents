import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import tools_registry


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-tools-"))
        self.old_config_home = os.environ.get("RUNTIME_AGENTS_CONFIG_HOME")
        os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = str(self.tempdir / "config")
        (self.tempdir / "config").mkdir(parents=True)

    def tearDown(self):
        if self.old_config_home is None:
            os.environ.pop("RUNTIME_AGENTS_CONFIG_HOME", None)
        else:
            os.environ["RUNTIME_AGENTS_CONFIG_HOME"] = self.old_config_home
        shutil.rmtree(self.tempdir)

    def test_packaged_tools_load(self):
        items = tools_registry.load_tools()
        self.assertTrue(any(item["id"] == "web_fetch" for item in items))

    def test_invalid_config_tool_is_reported(self):
        (self.tempdir / "config" / "tools.yaml").write_text(
            "tools:\n  bad_tool:\n    title: Bad\n    description: Broken tool\n    kind: builtin\n    capabilities: [not_real]\n",
            encoding="utf-8",
        )
        payload = tools_registry.validate_tools(strict=False)
        self.assertTrue(any(row["id"] == "bad_tool" and not row["ok"] for row in payload["tools"]))
        self.assertEqual(payload["invalid_count"], 1)

    def test_enabled_defaults_true(self):
        tool = tools_registry.validate_tool(
            "sample",
            {
                "title": "Sample",
                "description": "Sample tool",
                "capabilities": ["web_read"],
            },
        )
        self.assertTrue(tool["enabled"])

    def test_profile_scope_is_retained(self):
        tool = tools_registry.validate_tool(
            "sample",
            {
                "title": "Sample",
                "description": "Sample tool",
                "capabilities": ["web_read"],
                "profile_scope": ["runtime-dev"],
            },
        )
        self.assertEqual(tool["profile_scope"], ["runtime-dev"])


if __name__ == "__main__":
    unittest.main()
