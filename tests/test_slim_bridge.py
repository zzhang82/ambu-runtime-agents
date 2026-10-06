import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime_agents import execution_substrate
from runtime_agents import slim_bridge


class SlimBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_load_slim_config_missing_file_returns_none(self):
        res = slim_bridge.load_slim_config(self.tempdir / "missing.json")
        self.assertIsNone(res)

    def test_load_slim_config_invalid_json_returns_none(self):
        f = self.tempdir / "bad.json"
        f.write_text("{bad-json", encoding="utf-8")
        self.assertIsNone(slim_bridge.load_slim_config(f))

    def test_get_active_preset_finds_configured_and_fallback(self):
        data = {
            "preset": "my-preset",
            "presets": {
                "my-preset": {"oracle": {"model": "local/gpt-6.1"}},
                "other": {"oracle": {"model": "local/other"}},
            },
        }
        name, roles = slim_bridge.get_active_preset(data)
        self.assertEqual(name, "my-preset")
        self.assertIn("oracle", roles)

        # Fallback when preset not in presets
        data_missing = {"preset": "non-existent", "presets": {"fallback-preset": {"fixer": {}}}}
        name, roles = slim_bridge.get_active_preset(data_missing)
        self.assertEqual(name, "fallback-preset")
        self.assertIn("fixer", roles)

    def test_discover_slim_agents_infers_autonomy_and_metadata(self):
        slim_file = self.tempdir / "slim.json"
        slim_file.write_text(
            json.dumps({
                "preset": "test",
                "disabled_agents": ["explorer"],
                "presets": {
                    "test": {
                        "oracle": {
                            "model": "local/claude-opus-4-6-thinking",
                            "variant": "high",
                            "skills": ["simplify"],
                            "mcps": ["context7"],
                        },
                        "fixer": {
                            "model": "local/grok-4.7-build-fast",
                            "skills": [],
                            "mcps": [],
                        },
                        "explorer": {
                            "model": "local/gemini-3.8-flash-high",
                        },
                    }
                },
            }),
            encoding="utf-8",
        )
        agents = slim_bridge.discover_slim_agents(slim_file)
        self.assertIn("oracle", agents)
        self.assertIn("fixer", agents)
        self.assertNotIn("explorer", agents, "Disabled agent should be excluded")

        oracle = agents["oracle"]
        self.assertEqual(oracle["model"], "local/claude-opus-4-6-thinking")
        self.assertEqual(oracle["variant"], "high")
        self.assertEqual(oracle["autonomy"], "read_only")
        self.assertIn("workspace_write", oracle["approval_required"])
        self.assertEqual(oracle["routing_frame"], "review")

        fixer = agents["fixer"]
        self.assertEqual(fixer["model"], "local/grok-4.7-build-fast")
        self.assertEqual(fixer["autonomy"], "workspace_write")
        self.assertNotIn("workspace_write", fixer["approval_required"])
        self.assertEqual(fixer["routing_frame"], "implementation_ready")

    def test_overlay_slim_agents_enriches_config(self):
        slim_file = self.tempdir / "slim.json"
        slim_file.write_text(
            json.dumps({
                "preset": "test",
                "presets": {
                    "test": {
                        "oracle": {"model": "local/oracle-model", "variant": "xhigh"},
                        "existing_agent": {"model": "local/new-model", "variant": "max"},
                    }
                },
            }),
            encoding="utf-8",
        )

        base_config = {
            "agents": {
                "existing_agent": {
                    "tool": "opencode",
                    "model": "local/old-model",
                    "opencode_agent": "build",
                    "autonomy": "workspace_write",
                }
            }
        }

        enriched = slim_bridge.overlay_slim_agents(base_config, slim_file)
        agents = enriched["agents"]

        # New agent added
        self.assertIn("oracle", agents)
        self.assertEqual(agents["oracle"]["model"], "local/oracle-model")
        self.assertEqual(agents["oracle"]["variant"], "xhigh")

        # Existing agent preserved with variant overlaid
        existing = agents["existing_agent"]
        self.assertEqual(existing["model"], "local/old-model")
        self.assertEqual(existing["variant"], "max")

    def test_build_opencode_exec_command_with_variant(self):
        cmd = execution_substrate.build_opencode_exec_command(
            "local/gpt-6.1",
            "ping",
            opencode_agent="oracle",
            variant="xhigh",
        )
        self.assertEqual(cmd, [
            "opencode", "run",
            "--model", "local/gpt-6.1",
            "--variant", "xhigh",
            "--agent", "oracle",
            "ping",
        ])


if __name__ == "__main__":
    unittest.main()
