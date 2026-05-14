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


if __name__ == "__main__":
    unittest.main()
