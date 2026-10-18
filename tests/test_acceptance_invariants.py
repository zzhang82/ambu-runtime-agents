"""Executable P1-E01..E10 and validator positive/negative/unavailable controls."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from runtime_agents import acceptance
import test_acceptance as harness


def structured_contract(kind, source="stdout"):
    contract = harness.contract_for()
    contract['result_type'] = kind
    output = {'id': 'result', 'source': source}
    if source == 'file':
        output['path'] = 'result.json'
    if kind == 'extraction':
        output['schema'] = {'type': 'object', 'required': ['name'],
                            'properties': {'name': {'type': 'string', 'minLength': 1}}}
    if kind == 'research':
        output['schema'] = {'type': 'object', 'properties': {
            'answer': {'type': 'string', 'enum': [VALID['research']['answer']]}}}
    contract['required_outputs'] = [output]
    return contract


VALID = {
    'review': {'verdict': 'no_findings', 'findings': []},
    'extraction': {'name': 'fixture'},
    'research': {'answer': 'The fixture defines the result as 42.',
                 'evidence': ['fixture:reference-1'], 'limitations': []},
}


class AcceptanceInvariants(unittest.TestCase):
    setUp = harness.AcceptanceCLI.setUp
    worker = harness.AcceptanceCLI.worker
    invoke = harness.AcceptanceCLI.invoke
    run_case = harness.AcceptanceCLI.run_case
    assert_evidence = harness.AcceptanceCLI.assert_evidence

    def test_P1_E01_worker_contract_replacement_ignored(self):
        result = self.run_case(harness.contract_for(),
            "import json\nprint(json.dumps({'contract_version':1, 'required_outputs':[], 'acceptance_status':'passed'}))\n")
        self.assertEqual(result['deliverable_status'], 'missing')
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assertEqual(result['acceptance_contract']['required_outputs'][0]['path'], 'answer.txt')
        self.assert_evidence(result)

    def test_P1_E02_no_check_executed_despite_claim(self):
        result = self.run_case(harness.contract_for(checks=[{'id': 'manual-check'}]),
            "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nprint('All tests passed')\n")
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'not_run')
        self.assertFalse(result['acceptance']['checks'][0]['executed'])
        self.assertIsNone(result['acceptance']['checks'][0]['returncode'])
        self.assert_evidence(result)

    def test_P1_E03_legacy_completed_stays_unknown_without_rewrite(self):
        state = Path(self.env['RUNTIME_AGENTS_STATE_HOME'])
        ledger = state / 'tasks.jsonl'
        legacy = {'task_id': 'legacy', 'status': 'completed', 'agent': 'coder',
                  'run_dir': str(state / 'runs' / 'legacy'), 'worker_claim': 'all tests passed'}
        ledger.write_text(json.dumps(legacy) + '\n')
        before = ledger.read_bytes()
        for args in (['show', 'legacy', '--json'], ['status', '--json']):
            proc = self.invoke(args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            if isinstance(payload, list):
                payload = payload[0]
            self.assertEqual(payload['status'], 'completed')
            self.assertEqual(payload['deliverable_status'], 'unknown')
            self.assertEqual(payload['acceptance_status'], 'unknown')
            self.assertIsNone(payload['contract_fingerprint'])
            self.assertEqual(payload['worker_claim'], legacy['worker_claim'])
        self.assertEqual(ledger.read_bytes(), before)

    def test_P1_E04_valid_explicit_no_findings(self):
        result = self.run_case(structured_contract('review'), f'print({json.dumps(VALID["review"])!r})\n')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'passed')
        self.assert_evidence(result)

    def test_P1_E05_vague_review_is_invalid(self):
        result = self.run_case(structured_contract('review'), "print('looks good')\n")
        self.assertEqual(result['deliverable_status'], 'invalid')
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assert_evidence(result)

    def test_P1_E06_extraction_missing_or_malformed_required_fields(self):
        for text in ('{"name": 42}', '{}', '{broken'):
            with self.subTest(text=text):
                result = self.run_case(structured_contract('extraction'), f'print({text!r})\n')
                self.assertEqual(result['deliverable_status'], 'invalid')
                self.assertEqual(result['acceptance_status'], 'failed')
                self.assert_evidence(result)

    def test_P1_E07_research_requires_supporting_evidence(self):
        value = {**VALID['research'], 'evidence': []}
        result = self.run_case(structured_contract('research'), f'print({json.dumps(value)!r})\n')
        self.assertEqual(result['deliverable_status'], 'invalid')
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assert_evidence(result)

    def test_P1_E08_unresolved_denial_needs_review(self):
        result = self.run_case(harness.contract_for(),
            "from pathlib import Path\nimport sys\nPath('answer.txt').write_text('42\\n')\n"
            "print('permission denied for an unknown operation', file=sys.stderr)\n")
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'needs_review')
        self.assertEqual(result['acceptance']['permission_blocks'][0]['necessity'], 'unresolved')
        self.assert_evidence(result)

    def test_P1_E09_actual_check_controls_false_claim(self):
        result = self.run_case(harness.contract_for(checks=[{'id':'real', 'command':f'{sys.executable} -c "assert False"'}]),
            "from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nprint('All tests passed')\n")
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assertEqual(result['acceptance']['checks'][0]['status'], 'failed')
        self.assertTrue(result['acceptance']['checks'][0]['executed'])
        self.assert_evidence(result)

    def test_P1_E10_retry_and_iterate_keep_original_contract(self):
        original = harness.contract_for()
        first = self.run_case(original, "print('No output yet')\n")
        replacement = harness.contract_for('other.txt')
        self.contract_path.write_text(json.dumps(replacement))
        self.worker("from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nprint('Use other.txt instead')\n")
        proc = self.invoke(['retry', first['task_id']])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        retry = json.loads(proc.stdout)
        self.assertEqual(retry['status'], 'completed')
        self.assertEqual(retry['deliverable_status'], 'satisfied')
        self.assertEqual(retry['acceptance_status'], 'passed')
        self.assertEqual(retry['contract_fingerprint'], first['contract_fingerprint'])
        self.run_dir = Path(self.env['RUNTIME_AGENTS_STATE_HOME']) / 'runs' / retry['task_id']
        stored = json.loads((self.run_dir / 'result.json').read_text())
        self.assertEqual(stored['acceptance_contract'], first['acceptance_contract'])
        self.assert_evidence(stored)

        # A separate iterate execution changes both the artifact and source JSON.
        (self.root / 'answer.txt').write_text('wrong')
        check = f'{sys.executable} -c "from pathlib import Path; assert Path(\'answer.txt\').read_text() == \'42\\n\'"'
        original['required_checks'] = [{'id':'same-check', 'command':check}]
        self.contract_path.write_text(json.dumps(original))
        self.worker("from pathlib import Path\nPath('answer.txt').write_text('42\\n')\nPath('contract.json').write_text('{}')\nprint('New contract: no checks required')\n")
        proc = self.invoke(['iterate', 'coder', 'produce answer', '--check', check,
                            '--acceptance-contract', str(self.contract_path), '--max-rounds', '1', '--json'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'passed')
        self.assertEqual([e['status'] for e in result['acceptance']['evaluations']], ['failed', 'passed'])
        fingerprints = {c['contract_fingerprint'] for e in result['acceptance']['evaluations'] for c in e['checks']}
        self.assertEqual(fingerprints, {result['contract_fingerprint']})
        self.run_dir = Path(self.env['RUNTIME_AGENTS_STATE_HOME']) / 'runs' / result['task_id']
        self.assert_evidence(result)

    def test_structured_validator_positive_controls(self):
        for kind, value in VALID.items():
            with self.subTest(kind=kind):
                result = self.run_case(structured_contract(kind), f'print({json.dumps(value)!r})\n')
                self.assertEqual(result['deliverable_status'], 'satisfied')
                self.assertEqual(result['acceptance_status'], 'passed')
                self.assert_evidence(result)

    def test_structured_validator_missing_and_unavailable_controls(self):
        for kind in VALID:
            with self.subTest(kind=kind):
                result = self.run_case(structured_contract(kind), 'pass\n')
                self.assertEqual(result['deliverable_status'], 'missing')
                self.assertEqual(result['acceptance_status'], 'failed')
                self.assert_evidence(result)
                frozen = acceptance.freeze(structured_contract(kind, 'file'), self.root)
                run_dir = self.root / ('unavailable-' + kind)
                run_dir.mkdir()
                (self.root / 'result.json').write_text(json.dumps(VALID[kind]))
                session = acceptance.Acceptance(frozen, kind, self.root, run_dir, lambda *a: None)
                with patch.object(Path, 'read_bytes', side_effect=PermissionError('fixture unavailable')):
                    fields = session.evaluate('unavailable')
                self.assertEqual(fields['deliverable_status'], 'unknown')
                self.assertEqual(fields['acceptance_status'], 'unknown')
                self.assertEqual(fields['acceptance']['outputs'][0]['status'], 'unknown')

    def test_research_without_deterministic_answer_rule_needs_review(self):
        contract = structured_contract('research')
        del contract['required_outputs'][0]['schema']
        result = self.run_case(contract, f'print({json.dumps(VALID["research"])!r})\n')
        self.assertEqual(result['deliverable_status'], 'satisfied')
        self.assertEqual(result['acceptance_status'], 'needs_review')
        self.assert_evidence(result)


if __name__ == '__main__':
    unittest.main()
