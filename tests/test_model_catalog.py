import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_agents import model_catalog as catalog


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_parsing_and_comparison(self):
        snapshot = {"models": catalog.parse_catalog({"data": [{"id": "b", "owned_by": "openai"}, {"id": "a"}]})}
        self.assertEqual(snapshot["models"][0]["id"], "a")
        comparison = catalog.catalog_comparison(snapshot, ["local/a", "local/c"])
        self.assertEqual(comparison["missing_from_opencode"], ["local/b"])
        self.assertEqual(comparison["stale_in_opencode"], ["local/c"])

    def test_refresh_snapshot_is_secret_free(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"RUNTIME_AGENTS_CPA_BASE_URL": "http://example/v1", "RUNTIME_AGENTS_CPA_API_KEY": "do-not-save"}, clear=False):
            def fetch(url, key):
                return {"data": [{"id": "gpt", "owned_by": "openai"}]} if url.endswith("/models") else {"access_token": "also-secret", "rows": [{"name": "person@example.com", "weekly_left": 2}]}
            snapshot = catalog.refresh_snapshot(temp, fetch)
            saved = Path(temp, catalog.SNAPSHOT_NAME).read_text()
            self.assertNotIn("do-not-save", saved)
            self.assertNotIn("also-secret", saved)
            self.assertNotIn("person@example.com", saved)
            self.assertNotIn("accounts_label", saved)
            self.assertNotIn('"accounts"', saved)
            self.assertEqual(snapshot["models"][0]["id"], "gpt")

    def test_quota_only_excludes_openai_and_recommendation_is_deterministic(self):
        snapshot = {"generated_at": "now", "models": [{"id": "gpt-5", "owned_by": "openai"}, {"id": "gemini", "owned_by": "google"}], "sources": {"quota": {"ok": True, "provider": "openai", "data": {"exhausted": True}}}}
        config = {"model_routing": {"frames": {"recon": ["local/gpt-5", "local/gemini"]}}}
        result = catalog.recommend(snapshot, "recon", config)
        self.assertEqual(result["selected_model"], "local/gemini")
        self.assertEqual(result["skipped"][0]["reason"], "openai_weekly_quota_exhausted")

    def test_constrained_quota_penalizes_only_openai(self):
        snapshot = {
            "generated_at": "2026-08-23T00:00:00+00:00",
            "models": [
                {"id": "gpt-5", "owned_by": "openai"},
                {"id": "claude", "owned_by": "anthropic"},
                {"id": "gemini", "owned_by": "google"},
            ],
            "sources": {
                "quota": {
                    "ok": True,
                    "provider": "openai",
                    "data": {"weekly_avg_left": "12%", "weekly_min_left": "0%"},
                }
            },
        }
        config = {"model_routing": {"frames": {"deep_work": ["local/gpt-5", "local/claude", "local/gemini"]}}}
        result = catalog.recommend(snapshot, "deep_work", config)
        self.assertEqual(result["selected_model"], "local/claude")
        self.assertEqual(result["fallbacks"], ["local/gemini", "local/gpt-5"])
        self.assertEqual(result["penalized"], [{"model": "local/gpt-5", "reason": "openai_weekly_quota_constrained"}])

    def test_authoritative_owner_prevents_gpt_prefix_false_positive(self):
        snapshot = {
            "models": [
                {"id": "gpt-oss-120b-medium", "owned_by": "antigravity"},
                {"id": "gpt-5", "owned_by": "openai"},
            ],
            "sources": {
                "quota": {
                    "ok": True,
                    "provider": "openai",
                    "data": {"weekly_avg_left": "10%", "weekly_min_left": "0%"},
                }
            },
        }
        config = {"model_routing": {"frames": {"bounded_work": ["local/gpt-5", "local/gpt-oss-120b-medium"]}}}
        result = catalog.recommend(snapshot, "bounded_work", config)
        self.assertEqual(result["selected_model"], "local/gpt-oss-120b-medium")
        self.assertEqual(result["penalized"], [{"model": "local/gpt-5", "reason": "openai_weekly_quota_constrained"}])

    def test_degraded_catalog_uses_static_candidates(self):
        result = catalog.recommend({"sources": {"cpa": {"ok": False}}}, "bounded_work")
        self.assertEqual(result["selected_model"], "local/gemini-3.7-flash-high")
        self.assertTrue(result["advisory_only"])

    def test_agent_candidates_override_frame_defaults(self):
        snapshot = {
            "models": [
                {"id": "gemini-3.7-flash-high", "owned_by": "google"},
                {"id": "gpt-5.4-mini", "owned_by": "openai"},
                {"id": "gpt-5.6-luna", "owned_by": "openai"},
            ],
            "sources": {"quota": {"ok": False, "provider": "openai"}},
        }
        config = {"model_routing": {"agents": {"cheap": ["local/gemini-3.7-flash-high", "local/gpt-5.4-mini"]}}}
        result = catalog.recommend(snapshot, "recon", config, "cheap")
        self.assertEqual(result["selected_model"], "local/gemini-3.7-flash-high")
        self.assertEqual(result["fallbacks"], ["local/gpt-5.4-mini"])

    def test_required_dispatch_preflight_fails_closed_without_catalog(self):
        config = {
            "model_routing": {"required": True, "frames": {"recon": ["local/gemini-3.7-flash-high"]}},
            "agents": {"cheap": {"model": "local/gemini-3.7-flash-high", "routing_frame": "recon"}},
        }
        with patch.object(catalog, "refresh_snapshot", return_value={"models": [], "sources": {"cpa": {"ok": False}}}):
            result = catalog.dispatch_preflight(config, "cheap")
        self.assertIsNone(result["selected_model"])
        self.assertEqual(result["skipped"], [{"reason": "cpa_catalog_unavailable"}])

    def test_required_dispatch_preflight_fails_closed_on_empty_success_catalog(self):
        config = {
            "model_routing": {"required": True, "frames": {"recon": ["local/gemini-3.7-flash-high"]}},
            "agents": {"cheap": {"model": "local/gemini-3.7-flash-high", "routing_frame": "recon"}},
        }
        with patch.object(catalog, "refresh_snapshot", return_value={"models": [], "sources": {"cpa": {"ok": True}}}):
            result = catalog.dispatch_preflight(config, "cheap")
        self.assertIsNone(result["selected_model"])
        self.assertEqual(result["skipped"], [{"reason": "cpa_catalog_empty"}])

    def test_required_explicit_override_fails_closed_without_catalog(self):
        config = {
            "model_routing": {"required": True, "frames": {"deep_work": ["local/gpt-5"]}},
            "agents": {"coder": {"model": "local/gpt-5", "routing_frame": "deep_work"}},
        }
        with patch.object(catalog, "refresh_snapshot", return_value={"models": [], "sources": {"cpa": {"ok": False}}}):
            result = catalog.dispatch_preflight(config, "coder", "local/gpt-5")
        self.assertIsNone(result["selected_model"])
        self.assertEqual(result["skipped"], [{"reason": "cpa_catalog_unavailable"}])

    def test_required_explicit_override_fails_closed_on_empty_success_catalog(self):
        config = {
            "model_routing": {"required": True, "frames": {"deep_work": ["local/gpt-5"]}},
            "agents": {"coder": {"model": "local/gpt-5", "routing_frame": "deep_work"}},
        }
        with patch.object(catalog, "refresh_snapshot", return_value={"models": [], "sources": {"cpa": {"ok": True}}}):
            result = catalog.dispatch_preflight(config, "coder", "local/gpt-5")
        self.assertIsNone(result["selected_model"])
        self.assertEqual(result["skipped"], [{"reason": "cpa_catalog_empty"}])

    def test_required_dispatch_preflight_is_enforced(self):
        config = {
            "model_routing": {"required": True, "frames": {"recon": ["local/gemini-3.7-flash-high"]}},
            "agents": {"cheap": {"model": "local/gemini-3.7-flash-high", "routing_frame": "recon"}},
        }
        snapshot = {
            "models": [{"id": "gemini-3.7-flash-high", "owned_by": "antigravity"}],
            "sources": {"cpa": {"ok": True}, "quota": {"ok": False, "provider": "openai"}},
        }
        with patch.object(catalog, "refresh_snapshot", return_value=snapshot):
            result = catalog.dispatch_preflight(config, "cheap")
        self.assertTrue(result["enforced"])
        self.assertFalse(result["advisory_only"])

    def test_cooldown_skips_model(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog.record_cooldown("local/grok-composer-2.5-fast", "transient_model_error", 60, temp)
            snapshot = {
                "models": [
                    {"id": "grok-composer-2.5-fast", "owned_by": "xai"},
                    {"id": "gemini-3.7-flash-high", "owned_by": "antigravity"},
                ],
                "sources": {"quota": {"ok": False, "provider": "openai"}},
            }
            config = {"model_routing": {"frames": {"implementation_ready": ["local/grok-composer-2.5-fast", "local/gemini-3.7-flash-high"]}}}
            result = catalog.recommend(snapshot, "implementation_ready", config, state_home=temp)
        self.assertEqual(result["selected_model"], "local/gemini-3.7-flash-high")
        self.assertEqual(result["skipped"][0]["reason"], "local_model_cooldown")

    def test_explicit_openai_override_is_blocked_when_quota_exhausted(self):
        config = {
            "model_routing": {"required": True, "frames": {"deep_work": ["local/gpt-5"]}},
            "agents": {"coder": {"model": "local/gpt-5", "routing_frame": "deep_work"}},
        }
        snapshot = {
            "models": [{"id": "gpt-5", "owned_by": "openai"}],
            "sources": {
                "cpa": {"ok": True},
                "quota": {"ok": True, "provider": "openai", "data": {"exhausted": True}},
            },
        }
        with patch.object(catalog, "refresh_snapshot", return_value=snapshot):
            result = catalog.dispatch_preflight(config, "coder", "local/gpt-5")
        self.assertIsNone(result["selected_model"])
        self.assertEqual(result["skipped"][-1]["reason"], "openai_weekly_quota_exhausted")

    def test_cli_json_smoke_uses_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp, "state")
            state.mkdir()
            Path(state, catalog.SNAPSHOT_NAME).write_text(json.dumps({"generated_at": "now", "models": [], "sources": {"cpa": {"ok": False}}}), encoding="utf-8")
            config = Path(temp, "config")
            config.mkdir()
            Path(config, "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
            env = os.environ | {"RUNTIME_AGENTS_STATE_HOME": str(state), "RUNTIME_AGENTS_CONFIG_HOME": str(config)}
            root = Path(__file__).resolve().parents[1]
            for args in (["model", "status", "--json"], ["model", "recommend", "--json"], ["model", "catalog-check", "--json"]):
                with self.subTest(args=args):
                    proc = subprocess.run([sys.executable, "-m", "runtime_agents.cli", *args], cwd=root, env=env, text=True, capture_output=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIsInstance(json.loads(proc.stdout), dict)
