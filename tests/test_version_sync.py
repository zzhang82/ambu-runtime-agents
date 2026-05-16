import json
import re
import tempfile
import unittest
from pathlib import Path

from test_smoke import make_env, run_cli


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_expected_version() -> str:
    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject_text, re.MULTILINE)
    if not match:
        raise AssertionError("pyproject.toml does not contain a project version")
    return match.group(1)


class VersionSyncTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-agents-version-sync-"))
        self.env = make_env(self.tempdir)

    def tearDown(self):
        if self.tempdir.exists():
            for child in sorted(self.tempdir.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            self.tempdir.rmdir()

    def test_version_surfaces_match(self):
        expected_version = read_expected_version()
        expected_contract = f"agentctl-v{expected_version}"

        payload = json.loads(run_cli(["version", "--json"], self.env).stdout)
        self.assertEqual(payload["version"], expected_version)
        self.assertEqual(payload["contract"], expected_contract)

        contract_doc = (REPO_ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        self.assertIn(f"# runtime-agents Contract (v{expected_version})", contract_doc)
        self.assertIn(f"`agentctl version --json` reports contract `{expected_contract}`.", contract_doc)

        architecture_doc = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        self.assertIn(f"# Architecture (v{expected_version})", architecture_doc)

        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 1.5.1", changelog)
        self.assertNotIn("## 1.6.0", changelog)
