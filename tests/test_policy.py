import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import policy


class PolicyTests(unittest.TestCase):
    def test_detect_capabilities(self):
        text = "please git push and deploy; secret API key is here; npm install -g foo; rm -rf /tmp"
        hits = policy.detect_capabilities(text)
        self.assertIn("git_push", hits)
        self.assertIn("deploy", hits)
        self.assertIn("secrets", hits)
        self.assertIn("global_install", hits)

    def test_evaluate_approval_blocks_unapproved(self):
        dec = policy.evaluate_approval("git push and deploy", approved_caps=["git_push"], mode="run", required_caps=["git_push", "deploy"])
        self.assertIn("deploy", dec.blocked)
        self.assertNotIn("git_push", dec.blocked)

    def test_classify_transient_failure(self):
        kind = policy.classify_failure("", "gateway unavailable timeout", 1)
        self.assertEqual(kind, "transient_model_error")

    def test_classify_claude_quota_exhaustion(self):
        kind = policy.classify_failure("", "Error: Resource has been exhausted (e.g. check quota).", 1)
        self.assertEqual(kind, "transient_model_error")

    def test_classify_provider_cooldown(self):
        kind = policy.classify_failure("", "All credentials for model claude-sonnet-4-6 are cooling down", 1)
        self.assertEqual(kind, "transient_model_error")

    def test_negative_only_does_not_request_capability(self):
        self.assertEqual(policy.detect_capabilities("Do not push, merge, or deploy."), [])
        self.assertEqual(policy.detect_capabilities("Never git push."), [])
        self.assertEqual(policy.detect_capabilities("DO NOT PUSH."), [])
        self.assertEqual(policy.detect_capabilities("do not deploy!"), [])
        self.assertEqual(policy.detect_capabilities("Never push. Never deploy."), [])

    def test_affirmative_and_mixed_requests(self):
        self.assertEqual(policy.detect_capabilities("Please push and deploy."), ["deploy", "git_push"])
        self.assertEqual(policy.detect_capabilities("Do not push; deploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Do not push; then push anyway."), ["git_push"])

    def test_ambiguous_and_contradictory_stay_gated(self):
        self.assertIn("git_push", policy.detect_capabilities("Not not push."))
        self.assertIn("git_push", policy.detect_capabilities("Please push. Do not push."))
        self.assertIn("git_push", policy.detect_capabilities("Push the branch. Never push."))
        self.assertIn("git_push", policy.detect_capabilities("Do not push. Please push."))
        self.assertIn("deploy", policy.detect_capabilities("Please deploy. Never deploy."))
        self.assertIn("deploy", policy.detect_capabilities("Never deploy. Please deploy."))
        self.assertIn("git_push", policy.detect_capabilities("PLEASE PUSH. DO NOT PUSH."))
        self.assertIn("git_push", policy.detect_capabilities("Push the branch! Never push."))

    def test_coordinated_prohibitions_do_not_cancel(self):
        self.assertEqual(policy.detect_capabilities("Do not push and do not deploy."), [])
        self.assertEqual(policy.detect_capabilities("Don't push and don't deploy."), [])
        self.assertEqual(policy.detect_capabilities("Never push, never deploy."), [])

    def test_contrast_after_prohibition_stays_requested(self):
        self.assertEqual(policy.detect_capabilities("Do not push but deploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Do not push, but deploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Do not push, then deploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Do not push and deploy the preview."), ["deploy"])

    def test_independent_instruction_boundaries(self):
        self.assertEqual(policy.detect_capabilities("Do not push\nPlease push anyway."), ["git_push"])
        self.assertEqual(policy.detect_capabilities("Never deploy\nPlease deploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Do not push, please deploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Do not deploy\nPush the branch."), ["git_push"])

    def test_coordinated_lines_stay_negative(self):
        self.assertEqual(policy.detect_capabilities("Do not push\nor deploy."), [])
        self.assertEqual(policy.detect_capabilities("Do not push, deploy, or release."), [])
        self.assertEqual(policy.detect_capabilities("Do not push,\ndeploy, or release."), [])
        self.assertEqual(policy.detect_capabilities("Do not\npush."), [])
        self.assertEqual(policy.detect_capabilities("Never\ndeploy."), [])
        self.assertEqual(policy.detect_capabilities("Do not ever\npush."), [])
        self.assertEqual(policy.detect_capabilities("Do not please push."), [])
        self.assertEqual(policy.detect_capabilities("Do not push\ndeploy the preview."), ["deploy"])
        self.assertEqual(policy.detect_capabilities("Please push but do not\ndeploy."), ["git_push"])

    def test_custom_pattern_negative_stays_conservative(self):
        self.assertEqual(policy.detect_capabilities("Do not shipit.", patterns={"deploy": ["shipit"]}), ["deploy"])

    def test_directive_boundary_matrix(self):
        negative = (
            "Do not push or deploy.",
            "Do not push, deploy, or release.",
            "Do not push and do not deploy.",
            "Do not push\nor deploy.",
            "Do not push, merge, or deploy.",
            "Never git push.",
            "Never push. Never deploy.",
            "Don't push and don't deploy.",
            "Never push, never deploy.",
            "Do not push,\ndeploy, or release.",
            "Do not\npush.",
            "Never\ndeploy.",
            "Do not ever\npush.",
            "Do not please push.",
            "Do not push, deploy.",
            "Do not push, merge, deploy.",
            "Do not push\nNow do not deploy.",
        )
        for text in negative:
            with self.subTest(kind="negative", text=text):
                self.assertEqual(policy.detect_capabilities(text), [])

        gated = (
            ("Please push. Do not push.", ["git_push"]),
            ("Do not push; then push anyway.", ["git_push"]),
            ("Do not push but deploy the preview.", ["deploy"]),
            ("Do not push\nNow push the branch.", ["git_push"]),
            ("Do not deploy\nNow deploy the app.", ["deploy"]),
            ("Do not push\nWe need to deploy the preview.", ["deploy"]),
            ("Do not deploy\nWe need to deploy the preview.", ["deploy"]),
            ("Do not push, now deploy the preview.", ["deploy"]),
            ("Please push and deploy.", ["deploy", "git_push"]),
            ("Do not push; deploy the preview.", ["deploy"]),
            ("Do not push\nPlease push anyway.", ["git_push"]),
            ("Never deploy\nPlease deploy the preview.", ["deploy"]),
            ("Do not push, please deploy the preview.", ["deploy"]),
            ("Do not deploy\nPush the branch.", ["git_push"]),
            ("Do not push\ndeploy the preview.", ["deploy"]),
            ("Please push but do not\ndeploy.", ["git_push"]),
            ("Do not push and deploy the preview.", ["deploy"]),
            ("Not not push.", ["git_push"]),
            ("Push the branch. Never push.", ["git_push"]),
            ("Never deploy. Please deploy.", ["deploy"]),
            ("Do not push, deploy the preview.", ["deploy"]),
        )
        for text, expected in gated:
            with self.subTest(kind="gated", text=text):
                self.assertEqual(policy.detect_capabilities(text), expected)


if __name__ == "__main__":
    unittest.main()
