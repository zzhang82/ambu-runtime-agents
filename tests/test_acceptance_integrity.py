"""P1 boundary controls beyond the named T/E matrix."""
import json
from argparse import Namespace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from runtime_agents import acceptance, cli
import test_acceptance as harness
from test_acceptance import contract_for


class AcceptanceIntegrity(unittest.TestCase):
    setUp = harness.AcceptanceCLI.setUp
    worker = harness.AcceptanceCLI.worker
    invoke = harness.AcceptanceCLI.invoke
    run_case = harness.AcceptanceCLI.run_case
    assert_evidence = harness.AcceptanceCLI.assert_evidence

    def test_contract_snapshot_is_written_before_worker_and_not_reloaded(self):
        worker = """from pathlib import Path
import json, os
root = Path(os.environ['RUNTIME_AGENTS_STATE_HOME']) / 'runs'
frozen = next(root.glob('*/acceptance-contract.json'))
assert json.loads(frozen.read_text())['required_outputs'][0]['equals'] == '42\\n'
Path('contract.json').write_text('{}')
Path('answer.txt').write_text('wrong')
print(json.dumps({'acceptance_contract': {'required_outputs': []}, 'acceptance_status': 'passed'}))
"""
        result = self.run_case(contract_for(), worker)
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assertEqual(result['deliverable_status'], 'invalid')
        self.assert_evidence(result)

    def test_frozen_object_cannot_be_mutated_and_payload_is_detached(self):
        frozen = acceptance.freeze(contract_for(), self.root)
        data = frozen.payload()
        data['required_outputs'].clear()
        self.assertTrue(frozen.payload()['required_outputs'])
        with self.assertRaises(AttributeError):
            frozen.document = '{}'

    def test_synthesized_contract_preserves_legacy_artifact_normalization(self):
        args = Namespace(check=None, eval_artifact=[' answer.txt ', str(self.root / 'inside.txt'), ' '])
        frozen = acceptance.from_args(args, self.root, iterate=True)
        self.assertEqual([o['path'] for o in frozen.payload()['required_outputs']], ['answer.txt', 'inside.txt'])

    def test_persisted_contract_tampering_is_review_not_acceptance(self):
        result = self.run_case(contract_for(), """from pathlib import Path
import os
root = Path(os.environ['RUNTIME_AGENTS_STATE_HOME']) / 'runs'
next(root.glob('*/acceptance-contract.json')).write_text('{}')
Path('answer.txt').write_text('42\\n')
""")
        self.assertEqual(result['acceptance_status'], 'needs_review')
        self.assert_evidence(result)

    def test_check_claim_cannot_replace_actual_execution(self):
        result = self.run_case(contract_for(checks=[{'id': 'manual'}]),
            "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nprint('all tests passed')\n")
        self.assertEqual(result['acceptance_status'], 'not_run')
        check = result['acceptance']['checks'][0]
        self.assertFalse(check['executed'])
        self.assertIsNone(check['returncode'])
        self.assert_evidence(result)

    def test_check_error_and_output_unavailability_are_unknown(self):
        frozen = acceptance.freeze(contract_for(checks=[{'id': 'missing', 'command': 'test'}]), self.root)
        run_dir = self.root / 'unit-run'
        run_dir.mkdir()
        def unavailable(*args):
            raise OSError('fixture unavailable')
        session = acceptance.Acceptance(frozen, 'unit-task', self.root, run_dir, unavailable)
        (self.root / 'answer.txt').write_text('42\n')
        result = session.evaluate('1')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'unknown')
        self.assertFalse(result['acceptance']['checks'][0]['executed'])
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('unavailable')):
            result = session.evaluate('2', execute=False)
        self.assertEqual(result['deliverable_status'], 'unknown')
        self.assertEqual(result['acceptance_status'], 'not_run')

    def test_binary_file_has_no_undeclared_text_requirement(self):
        contract = contract_for()
        del contract['required_outputs'][0]['equals']
        result = self.run_case(contract, "from pathlib import Path\nPath('answer.txt').write_bytes(bytes([255,0,254]))\n")
        self.assertEqual(result['acceptance_status'], 'passed')

    def test_check_modifying_output_cannot_certify_stale_bytes(self):
        contract = contract_for(checks=[{'id': 'mutator', 'command':
            f'{sys.executable} -c "from pathlib import Path; Path(\'answer.txt\').write_text(\'wrong\')"'}])
        result = self.run_case(contract, "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\n")
        self.assertEqual(result['deliverable_status'], 'invalid')
        self.assertEqual(result['acceptance_status'], 'failed')

    def test_malformed_contracts_never_dispatch(self):
        for mutate in (
            lambda c: c.pop('required_permissions'),
            lambda c: c.update(result_type='other'),
            lambda c: c.update(result_type=[]),
            lambda c: c.update(contract_fingerprint='wrong'),
            lambda c: c['required_outputs'][0].update(path='../escape'),
            lambda c: c['required_outputs'][0].update(schema={'type':'object', 'anyOf': []}),
            lambda c: c['validation_rules'].update(unknown=True),
            lambda c: c.update(required_outputs=[], required_checks=[]),
        ):
            with self.subTest(mutate=mutate):
                contract = contract_for()
                mutate(contract)
                self.contract_path.write_text(json.dumps(contract))
                self.worker("from pathlib import Path\nPath('dispatched').touch()\n")
                proc = self.invoke(['run', 'coder', 'produce answer', '--acceptance-contract', str(self.contract_path)])
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn('Invalid acceptance contract', proc.stderr)
                self.assertFalse((self.root / 'dispatched').exists())

    def test_later_check_mutation_invalidates_earlier_pass_evidence(self):
        contract = contract_for(checks=[{'id':'first', 'command':'true'}, {'id':'mutator', 'command':
            f'{sys.executable} -c "from pathlib import Path; Path(\'answer.txt\').write_text(\'changed\')"'}])
        del contract['required_outputs'][0]['equals']
        result = self.run_case(contract, "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\n")
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual([c['status'] for c in result['acceptance']['checks']], ['passed', 'passed'])
        self.assertEqual(result['acceptance_status'], 'needs_review')

    def test_contract_commands_cannot_bypass_run_or_iterate_policy(self):
        contract = contract_for(checks=[{'id': 'restricted', 'command': 'git push'}])
        self.contract_path.write_text(json.dumps(contract))
        self.worker("from pathlib import Path\nPath('dispatched').touch()\n")
        for command in ('run', 'iterate'):
            args = [command, 'coder', 'produce answer', '--acceptance-contract', str(self.contract_path), '--json']
            if command == 'iterate':
                args.extend(['--check', 'true'])
            proc = self.invoke(args)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result['status'], 'approval_required')
            self.assertNotEqual(result['acceptance_status'], 'passed')
            self.assertFalse((self.root / 'dispatched').exists())

    def test_process_failed_can_have_independently_passed_acceptance(self):
        self.contract_path.write_text(json.dumps(contract_for()))
        self.worker("from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nraise SystemExit(7)\n")
        proc = self.invoke(['run', 'coder', 'produce answer', '--acceptance-contract', str(self.contract_path), '--json'])
        self.assertEqual(proc.returncode, 7)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'passed')

    def test_iterate_failed_worker_does_not_reuse_earlier_check(self):
        contract = contract_for(checks=[{'id': 'check', 'command': 'false'}])
        self.contract_path.write_text(json.dumps(contract))
        self.worker("from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nraise SystemExit(1)\n")
        proc = self.invoke(['iterate', 'coder', 'produce answer', '--check', 'false',
                            '--max-rounds', '1', '--acceptance-contract', str(self.contract_path), '--json'])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'not_run')
        self.assertEqual(result['acceptance']['evaluations'][0]['checks'][0]['status'], 'failed')
        self.assertEqual(result['acceptance']['checks'][0]['status'], 'not_run')

    def test_check_input_digest_mismatch_never_passes(self):
        contract = contract_for(checks=[{'id':'pinned', 'command':'true', 'inputs':{'answer.txt':'0'*64}}])
        result = self.run_case(contract, "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\n")
        self.assertEqual(result['acceptance_status'], 'unknown')
        self.assertFalse(result['acceptance']['checks'][0]['executed'])

    def test_iterate_does_not_execute_changed_verifier(self):
        check = f'{sys.executable} -c "from pathlib import Path; Path(\'unsafe-check-ran\').touch()"'
        contract = contract_for(checks=[{'id':'pinned', 'command':check, 'inputs':{'answer.txt':'0'*64}}])
        self.contract_path.write_text(json.dumps(contract))
        (self.root / 'answer.txt').write_text('42\n')
        self.worker("print('No change')\n")
        proc = self.invoke(['iterate', 'coder', 'produce answer', '--check', check,
                            '--max-rounds', '0', '--acceptance-contract', str(self.contract_path), '--json'])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertFalse((self.root / 'unsafe-check-ran').exists())
        self.assertEqual(result['acceptance_status'], 'unknown')
        self.assertFalse(result['acceptance']['checks'][0]['executed'])

    def test_missing_and_failed_evidence_precede_unresolved_denial(self):
        result = self.run_case(contract_for(), "import sys\nprint('permission denied', file=sys.stderr)\n")
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assertEqual(result['acceptance']['permission_blocks'][0]['necessity'], 'unresolved')

    def test_explicit_manual_review_never_invents_semantic_verification(self):
        contract = contract_for()
        contract['validation_rules']['manual_review'] = True
        result = self.run_case(contract, "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\n")
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'needs_review')

    def test_iterate_honors_frozen_check_timeout(self):
        check = f'{sys.executable} -c "import time; time.sleep(2)"'
        contract = contract_for(checks=[{'id':'bounded', 'command':check, 'timeout':1}])
        self.contract_path.write_text(json.dumps(contract))
        (self.root / 'answer.txt').write_text('42\n')
        self.worker('pass\n')
        proc = self.invoke(['iterate', 'coder', 'produce answer', '--check', check,
                            '--check-timeout', '15', '--max-rounds', '0',
                            '--acceptance-contract', str(self.contract_path), '--json'])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assertEqual(result['acceptance']['checks'][0]['returncode'], 124)
        self.assertTrue(result['acceptance']['checks'][0]['executed'])


if __name__ == '__main__':
    unittest.main()
