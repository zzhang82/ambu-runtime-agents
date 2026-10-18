"""P1 CLI regressions. All workers are controlled; checks execute real processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_iterate import make_env, ROOT


def contract_for(path="answer.txt", checks=None, permissions=None):
    return {
        "contract_version": 1,
        "result_type": "implementation",
        "required_outputs": [{"id": "answer", "source": "file", "path": path,
                              "equals": "42\n"}],
        "required_checks": checks or [],
        "required_permissions": permissions or [],
        "validation_rules": {},
    }


class AcceptanceCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ambu-p1-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = make_env(self.root)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]
        self.contract_path = self.root / "contract.json"
        evidence_root = os.environ.get("P1_EVIDENCE_DIR")
        if evidence_root:
            def save_case():
                destination = Path(evidence_root) / self._testMethodName
                destination.mkdir(parents=True, exist_ok=True)
                # Only this synthetic test fixture is copied; never host config/logs.
                for source in self.root.rglob('*'):
                    relative = source.relative_to(self.root)
                    if not source.is_file() or relative.parts[0] == 'config':
                        continue
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    content = source.read_bytes()
                    content = content.replace(str(self.root).encode(), b'<fixture>')
                    target.write_bytes(content)
                failures = self._outcome.result.failures + self._outcome.result.errors
                (destination / 'case.json').write_text(json.dumps({
                    'test': self.id(), 'status': 'FAIL' if any(t is self for t, _ in failures) else 'PASS',
                    'assertions': f'{type(self).__module__}.py::{self._testMethodName}',
                    'environment': f'Python {sys.version.split()[0]}; isolated synthetic worker',
                }, indent=2) + '\n')
            self.addCleanup(save_case)

    def worker(self, source):
        script = self.bin / "opencode"
        script.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
        script.chmod(0o755)

    def invoke(self, args):
        return subprocess.run([sys.executable, "-B", "-m", "runtime_agents.cli", *args],
                              cwd=self.root, env=self.env, text=True, capture_output=True)

    def run_case(self, contract, worker):
        self.contract_path.write_text(json.dumps(contract), encoding="utf-8")
        self.worker(worker)
        proc = self.invoke(["run", "coder", "Produce the declared answer.",
                            "--acceptance-contract", str(self.contract_path), "--json", "--no-memory"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.run_dir = Path(self.env["RUNTIME_AGENTS_STATE_HOME"]) / "runs" / payload["task_id"]
        result = json.loads((self.run_dir / "result.json").read_text())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["returncode"], 0)
        return result

    def assert_evidence(self, result):
        acceptance = result["acceptance"]
        frozen = json.loads((self.run_dir / "acceptance-contract.json").read_text())
        self.assertEqual(acceptance["contract_fingerprint"], frozen["contract_fingerprint"])
        evidence = json.loads((self.run_dir / "acceptance.json").read_text())
        self.assertEqual(evidence, acceptance)
        for record in acceptance["outputs"] + acceptance["checks"] + acceptance["permission_blocks"]:
            self.assertEqual(record["task_id"], result["task_id"])
            self.assertEqual(record["contract_fingerprint"], frozen["contract_fingerprint"])
            self.assertIn("attempt", record)
            self.assertIn("validator", record)
            self.assertIn("executed", record)
            self.assertIn("started_at", record)
            self.assertIn("ended_at", record)
            if record.get("evidence_ref"):
                self.assertTrue((self.run_dir / record["evidence_ref"]).is_file())

    def test_P1_T01_zero_exit_missing_deliverable(self):
        result = self.run_case(contract_for(), "print('All done, all tests passed.')\n")
        self.assertEqual(result["deliverable_status"], "missing")
        self.assertEqual(result["acceptance_status"], "failed")
        self.assert_evidence(result)

    def test_P1_T02_real_failing_check(self):
        contract = contract_for(checks=[{"id": "arithmetic", "command":
                                       f'{sys.executable} -c "assert 1 == 2"'}])
        result = self.run_case(contract, "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\n")
        self.assertEqual(result["deliverable_status"], "satisfied")
        self.assertEqual(result["acceptance_status"], "failed")
        check = result["acceptance"]["checks"][0]
        self.assertTrue(check["executed"])
        self.assertEqual(check["status"], "failed")
        self.assertNotEqual(check["returncode"], 0)
        self.assert_evidence(result)

    def test_P1_T03_required_denial_despite_reassurance(self):
        permission = {"operation": "external_directory", "target": "/fixture/input/*"}
        result = self.run_case(contract_for(permissions=[permission]),
            "from pathlib import Path\nimport sys\nPath('answer.txt').write_text('42\\n')\n"
            "print('All good, everything passed.')\n"
            "print('permission requested: external_directory (/fixture/input/*); auto-rejecting', file=sys.stderr)\n")
        self.assertEqual(result["deliverable_status"], "satisfied")
        self.assertEqual(result["acceptance_status"], "failed")
        self.assertEqual(result["acceptance"]["permission_blocks"][0]["necessity"], "required")
        self.assert_evidence(result)

    def test_P1_T04_optional_denial_does_not_reject(self):
        contract = contract_for(checks=[{"id": "answer-check", "command":
            f'{sys.executable} -c "from pathlib import Path; assert Path(\'answer.txt\').read_text() == \'42\\n\'"'}])
        contract["validation_rules"]["optional_permissions"] = [
            {"operation": "external_directory", "target": "/fixture/optional/*"}]
        result = self.run_case(contract,
            "from pathlib import Path\nimport sys\nPath('answer.txt').write_text('42\\n')\n"
            "print('permission requested: external_directory (/fixture/optional/*); auto-rejecting', file=sys.stderr)\n"
            "print('tool failed', file=sys.stderr)\n"
            "print('Error: The user rejected permission to use this specific tool call.', file=sys.stderr)\n")
        self.assertEqual(result["deliverable_status"], "satisfied")
        self.assertEqual(result["acceptance_status"], "passed")
        self.assertEqual(result["acceptance"]["permission_blocks"][0]["necessity"], "optional")
        self.assertEqual(result["acceptance"]["checks"][0]["status"], "passed")
        self.assert_evidence(result)

    def test_P1_T05_correct_file_empty_stdout(self):
        result = self.run_case(contract_for(), "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\n")
        self.assertEqual(result["attempts"][0]["stdout"], "")
        self.assertEqual(result["deliverable_status"], "satisfied")
        self.assertEqual(result["acceptance_status"], "passed")
        self.assertEqual(result["acceptance"]["outputs"][0]["sha256"],
                         __import__('hashlib').sha256(b"42\n").hexdigest())
        self.assert_evidence(result)


if __name__ == "__main__":
    unittest.main()
