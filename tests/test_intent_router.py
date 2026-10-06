import unittest

from runtime_agents import intent_router

AVAILABLE_AGENTS = {"oracle", "fixer", "eli", "designer", "librarian", "coder", "reviewer", "planner"}


class IntentRouterTests(unittest.TestCase):
    def test_empty_prompt_returns_safe_readonly_fallback(self):
        res = intent_router.classify_intent("", AVAILABLE_AGENTS)
        self.assertEqual(res["intent"], "unknown")
        self.assertEqual(res["selected_agent"], "oracle")
        self.assertEqual(res["autonomy"], "read_only")
        self.assertEqual(res["execution_mode"], "run")

    def test_review_intent_routes_to_oracle(self):
        res = intent_router.classify_intent("Review database migrations for table lock risks", AVAILABLE_AGENTS)
        self.assertEqual(res["intent"], "review")
        self.assertEqual(res["selected_agent"], "oracle")
        self.assertEqual(res["autonomy"], "read_only")
        self.assertEqual(res["execution_mode"], "run")
        self.assertTrue(any(k.startswith("review") for k in res["matched_keywords"]))
        self.assertTrue(any(k.startswith("risk") for k in res["matched_keywords"]))

    def test_research_intent_routes_to_librarian(self):
        res = intent_router.classify_intent("Find documentation and library reference for Upstash Redis", AVAILABLE_AGENTS)
        self.assertEqual(res["intent"], "research")
        self.assertEqual(res["selected_agent"], "librarian")
        self.assertEqual(res["autonomy"], "read_only")

    def test_design_intent_routes_to_designer(self):
        res = intent_router.classify_intent("Make the navbar responsive with css styling", AVAILABLE_AGENTS)
        self.assertEqual(res["intent"], "design")
        self.assertEqual(res["selected_agent"], "designer")
        self.assertEqual(res["autonomy"], "read_only")

    def test_fix_intent_with_check_routes_to_fixer_iterate(self):
        res = intent_router.classify_intent(
            "Fix the broken auth login issue",
            AVAILABLE_AGENTS,
            has_check=True,
        )
        self.assertEqual(res["intent"], "fix")
        self.assertEqual(res["selected_agent"], "fixer")
        self.assertEqual(res["autonomy"], "workspace_write")
        self.assertEqual(res["execution_mode"], "iterate")
        self.assertIsNone(res["advisory"])

    def test_fix_intent_without_check_routes_to_fixer_run_with_advisory(self):
        res = intent_router.classify_intent("Fix the broken auth login issue", AVAILABLE_AGENTS, has_check=False)
        self.assertEqual(res["intent"], "fix")
        self.assertEqual(res["selected_agent"], "fixer")
        self.assertEqual(res["autonomy"], "workspace_write")
        self.assertEqual(res["execution_mode"], "run")
        self.assertIsNotNone(res["advisory"])
        self.assertIn("--check", res["advisory"])

    def test_implement_intent_routes_to_coder(self):
        res = intent_router.classify_intent("Implement new endpoint for billing invoices", AVAILABLE_AGENTS)
        self.assertEqual(res["intent"], "implement")
        self.assertEqual(res["selected_agent"], "coder")
        self.assertEqual(res["autonomy"], "workspace_write")

    # Klaus Adversarial Corpus Tests
    def test_klaus_negation_suppresses_write_and_routes_to_readonly(self):
        prompt = "Do not fix this, just review why it broke"
        res = intent_router.classify_intent(prompt, AVAILABLE_AGENTS)
        self.assertTrue(res["write_negated"])
        self.assertEqual(res["intent"], "review")
        self.assertEqual(res["selected_agent"], "oracle")
        self.assertEqual(res["autonomy"], "read_only")

    def test_klaus_word_boundary_avoids_matching_code_identifier(self):
        prompt = "Investigate why def fix_user() raises 500"
        res = intent_router.classify_intent(prompt, AVAILABLE_AGENTS)
        # 'fix_user' must not match 'fix'; only 'investigate' and 'why' match -> review
        self.assertEqual(res["intent"], "review")
        self.assertEqual(res["selected_agent"], "oracle")
        self.assertEqual(res["autonomy"], "read_only")
        self.assertNotIn("fix", res["matched_keywords"])

    def test_klaus_compound_tied_intent_defaults_to_readonly(self):
        prompt = "Review the migration and fix slow queries"
        res = intent_router.classify_intent(prompt, AVAILABLE_AGENTS)
        # 'review' (1 match) vs 'fix' (1 match) -> tied -> Klaus rule defaults to read-only
        self.assertEqual(res["intent"], "review")
        self.assertEqual(res["selected_agent"], "oracle")
        self.assertEqual(res["autonomy"], "read_only")
        self.assertIn("tied", res["reason"])

    def test_fallback_when_preferred_agent_missing(self):
        # Pool has coder and reviewer, but not oracle or fixer
        limited_pool = {"coder", "reviewer"}
        res_review = intent_router.classify_intent("Review architecture", limited_pool)
        self.assertEqual(res_review["selected_agent"], "reviewer")

        res_fix = intent_router.classify_intent("Fix the bug", limited_pool)
        self.assertEqual(res_fix["selected_agent"], "coder")


if __name__ == "__main__":
    unittest.main()
