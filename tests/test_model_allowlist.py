"""Synthetic model restrictions and file-reference fixtures; no live provider."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_agents import model_catalog as catalog


class ModelAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {
            "model_routing": {"required": True, "allowed_models": ["local/a", "local/b"],
                              "agents": {"coder": ["local/a", "local/b", "local/c"]}},
            "agents": {"coder": {"routing_frame": "implementation_ready"}},
        }
        self.snapshot = {"models": [{"id": x, "owned_by": "unknown"} for x in "abc"],
                         "sources": {"cpa": {"ok": True}}}
        for name, value in (("deprecated_local_models", set()), ("active_cooldowns", {})):
            mock = patch.object(catalog, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_absent_restrictions_preserve_default(self):
        self.assertIsNone(catalog.allowed_models({}))
        self.assertEqual(catalog.dispatch_preflight({"models": {"primary": "local/a"}}, "coder")["selected_model"], "local/a")

    def test_environment_only_and_intersection_keep_order(self):
        with patch.dict(os.environ, {"RUNTIME_AGENTS_MODEL_ALLOWLIST": "local/b, local/a,local/a,local/c"}):
            self.assertEqual(catalog.allowed_models({}), ["local/b", "local/a", "local/c"])
            self.assertEqual(catalog.allowed_models(self.config), ["local/a", "local/b"])

    def test_invalid_restrictions_fail_closed(self):
        for value in (None, [], "local/a", [1], ["local/"], ["other/a"], ["local/a b"]):
            with self.subTest(config=value):
                config = {"model_routing": {"allowed_models": value, "required": True}}
                with self.assertRaises(ValueError):
                    catalog.allowed_models(config)
                result = catalog.dispatch_preflight(config, "coder")
                self.assertIsNone(result["selected_model"])
                self.assertEqual(result["skipped"][0]["reason"], "invalid_model_allowlist")
        for value in ("", " ", "local/a,", "other/a", "local/c"):
            with self.subTest(environment=value), patch.dict(os.environ, {"RUNTIME_AGENTS_MODEL_ALLOWLIST": value}):
                with self.assertRaises(ValueError):
                    catalog.allowed_models(self.config)

    def test_restrictions_require_live_preflight(self):
        for environment_only in (False, True):
            with self.subTest(environment_only=environment_only), patch.dict(os.environ, {"RUNTIME_AGENTS_MODEL_ALLOWLIST": "local/a"} if environment_only else {}):
                config = {} if environment_only else {"model_routing": {"allowed_models": ["local/a"]}}
                result = catalog.dispatch_preflight(config, "coder", "local/a")
                self.assertTrue(result["required"])
                self.assertIsNone(result["selected_model"])
                self.assertEqual(result["skipped"][0]["reason"], "allowlist_requires_live_preflight")

    def test_disallowed_explicit_model_blocks_without_fetch(self):
        with patch.object(catalog, "refresh_snapshot") as refresh:
            result = catalog.dispatch_preflight(self.config, "coder", "local/c")
        refresh.assert_not_called()
        self.assertIsNone(result["selected_model"])
        self.assertEqual(result["skipped"][0]["reason"], "outside_model_allowlist")

    def test_no_allowlist_candidate_injection_and_advisory_unchanged(self):
        self.config["model_routing"]["frames"] = {"implementation_ready": ["local/c", "local/a"]}
        with patch.dict(os.environ, {"RUNTIME_AGENTS_MODEL_ALLOWLIST": "local/b,local/c"}), patch.object(catalog, "refresh_snapshot", return_value=self.snapshot):
            result = catalog.dispatch_preflight(self.config, "coder")
            self.assertEqual(result["selected_model"], "local/b")
            self.assertEqual(result["fallbacks"], [])
            advisory = catalog.recommend(self.snapshot, "implementation_ready", self.config)
            self.assertEqual(advisory["selected_model"], "local/c")
            self.config["model_routing"]["agents"]["coder"] = ["local/a"]
            self.assertIsNone(catalog.dispatch_preflight(self.config, "coder")["selected_model"])

    def test_allowlist_cannot_restore_catalog_quota_deprecated_or_cooled_models(self):
        for kind in ("catalog", "quota", "deprecated", "cooldown"):
            with self.subTest(kind=kind):
                snapshot = json.loads(json.dumps(self.snapshot))
                if kind == "catalog":
                    snapshot["models"] = [{"id": "b"}]
                if kind == "quota":
                    snapshot["models"][0]["owned_by"] = "openai"
                    snapshot["sources"]["quota"] = {"ok": True, "provider": "openai", "data": {"exhausted": True}}
                with patch.object(catalog, "refresh_snapshot", return_value=snapshot), patch.object(catalog, "deprecated_local_models", return_value={"local/a"} if kind == "deprecated" else set()), patch.object(catalog, "active_cooldowns", return_value={"local/a": {"until": "later"}} if kind == "cooldown" else {}):
                    self.assertEqual(catalog.dispatch_preflight(self.config, "coder")["selected_model"], "local/b")
                    self.assertIsNone(catalog.dispatch_preflight(self.config, "coder", "local/a")["selected_model"])

    def test_file_reference_relative_absolute_and_tilde(self):
        value_file = self.root / "synthetic-value.txt"
        value_file.write_text("fixture-only-value\n")
        for reference in (str(value_file), "synthetic-value.txt", "~/synthetic-value.txt"):
            with self.subTest(reference=reference), patch.object(catalog, "_opencode_config_path", return_value=self.root / "opencode.json"), patch.object(catalog, "_opencode_config", return_value={"provider": {"local": {"options": {"apiKey": "{file:" + reference + "}"}}}}):
                # expanduser consults the OS home lookup, not Path.home.
                with patch("os.path.expanduser", side_effect=lambda p: str(self.root) + p[1:] if p == "~" or p.startswith("~/") else p):
                    self.assertEqual(catalog.resolve_cpa_config()["api_key"], "fixture-only-value")

    def test_bad_file_reference_does_not_fetch_or_disclose_value(self):
        for reference in ("{file:missing}", "{file:}", "{file:unterminated"):
            with self.subTest(reference=reference), patch.object(catalog, "_opencode_config", return_value={"provider": {"local": {"options": {"baseURL": "http://fixture.invalid/v1", "apiKey": reference}}}}), patch.object(catalog, "_fetch_json") as fetch:
                with self.assertRaises(ValueError) as raised:
                    catalog.refresh_snapshot(self.root, fetch)
                fetch.assert_not_called()
                self.assertNotIn(reference, str(raised.exception))
        value_file = self.root / "empty.txt"
        value_file.write_text("  \n")
        with patch.object(catalog, "_opencode_config", return_value={"provider": {"local": {"options": {"apiKey": "{file:" + str(value_file) + "}"}}}}):
            with self.assertRaises(ValueError):
                catalog.resolve_cpa_config()
            with patch.object(Path, "read_text", side_effect=PermissionError("private-path")):
                with self.assertRaises(ValueError) as raised:
                    catalog.resolve_cpa_config()
                self.assertNotIn("private-path", str(raised.exception))

    def test_plain_and_environment_values_remain_supported(self):
        config = {"provider": {"local": {"options": {"apiKey": "plain-fixture"}}}}
        with patch.object(catalog, "_opencode_config", return_value=config):
            self.assertEqual(catalog.resolve_cpa_config()["api_key"], "plain-fixture")
            with patch.dict(os.environ, {"RUNTIME_AGENTS_CPA_API_KEY": "env-fixture"}):
                self.assertEqual(catalog.resolve_cpa_config()["api_key"], "env-fixture")


if __name__ == "__main__":
    unittest.main()
