# Ambu P1 engineering handoff

P1 VERIFIED — all eleven mandatory gates passed within the tested conditions.

Environment: Astra Codex local development, Linux WSL2
`6.18.54.1-microsoft-standard-WSL2`, Python 3.12.3, 2026-10-18.
No merge, push, installation update, or deployment was performed.

### Publication integration

The original development record below describes the installed-source baseline.
For PR publication on 2026-10-18, the three P1 commits were cherry-picked onto
remote `master` at `f14122238bcd118b008b45c38fcf2d2b6622ceaf` in the separate
`p1/evidence-based-acceptance-pr` branch. There were no conflicts. The newer
`policy.py` and `test_policy.py` changes are retained without modification.
The two P1 product-source hashes still match [source-digests.json](p1-evidence/source-digests.json).

The integrated source passed 36 focused acceptance tests and the full 344-test
suite (308 existing + 36 P1) on Python 3.12.3. The 335-test log below remains the
original baseline's result, not the integrated suite's count. README and Unreleased
changelog entries now explain caller adoption and unchanged process exit codes.
The existing CI matrix covers Python 3.10, 3.11, and 3.12; its PR results are a
separate publication gate. No version bump, merge, installation update, or
Steward Air deployment is part of this PR.

## A. Implementation

- Worktree: `/home/zzs333/code/ambu-p1-acceptance`.
- Branch: `p1/evidence-based-acceptance`.
- Tested implementation commit: `ac0fa624954ae9630b77a6f85ca5dcdbd03afda6`.
- Initial implementation commit: `0e9d7c96bdd68db639b09963ccf98395161b56bd`.
- Base installed-source commit: `9ce375462380fb309b62a38d0b45d5363449c527`.
- Source fingerprints: [source-digests.json](p1-evidence/source-digests.json).
- Diff: `git diff 9ce3754 ac0fa62 -- src/runtime_agents tests docs/p1-acceptance.md`.

Product changes are limited to two files:

| File | Change |
|---|---|
| `src/runtime_agents/acceptance.py` | Frozen canonical contract, fingerprint, strict rule validation, task-specific output validators, independent checks, denial classification, evidence and precedence |
| `src/runtime_agents/cli.py` | `--acceptance-contract`, pre-dispatch freezing and policy gating, run/iterate integration, retry/resume inheritance, additive status/show fields |
| `tests/test_acceptance.py` | T01–T05; controlled worker harness and optional sanitized evidence capture |
| `tests/test_acceptance_invariants.py` | E01–E10; structured-validator controls and unresolved research judgment |
| `tests/test_acceptance_integrity.py` | Immutability, malformed contracts, approval gates, timeout, unavailable/stale evidence, process independence, legacy normalization |
| `docs/p1-acceptance.md`, `docs/p1-handoff.md`, `docs/p1-evidence/**` | Schema, handoff, sanitized test and real-execution evidence |

[The schema document](p1-acceptance.md) defines every accepted field and the exact
precedence. The supervisor freezes version 1 criteria before dispatch. Its immutable
canonical value and SHA-256 identity, not returned worker JSON, govern acceptance.
Malformed or unsupported contract rules fail before worker execution.

The existing JSON/JSONL ledger is extended; no database or migration is introduced.
New independent fields are `deliverable_status`, `acceptance_status`,
`acceptance_reason`, `contract_fingerprint`, `acceptance_contract`, and `acceptance`.
The last field records per-output/check/denial provenance and evaluation history.
Files and evidence are hashed/snapshotted; actual checks use the existing shell runner.
Frozen check timeouts and declared verifier-input hashes are enforced.

Compatibility: process `status`, process exit codes, and legacy loop-driving
`--check`/`--eval-artifact` behavior retain their meaning. Acceptance is additive,
not a replacement success boolean. Extra acceptance criteria do not replace the
existing iterate repair driver. Consumers must read `acceptance_status`; exit zero
or `completed` is not acceptance. Uncontracted history and new uncontracted `run`
tasks remain `unknown`. Existing iterate arguments synthesize a minimal contract.
Historical records are not rewritten. The source version remains 1.5.1; this is
development work, not a release.

## B. Regression matrix

All rows below are **PASS**. Process, deliverable, acceptance, and evidence are
asserted independently. `C` means process `completed`, not accepted.
Full fixture inputs, frozen contracts, observed records, assertion locations and
individual statuses are in [regressions.json](p1-evidence/regressions.json).
The matching `test_P1_<ID>_*` method is the executable assertion reference.

| ID | Expected | Observed |
|---|---|---|
| T01 | Exit zero cannot accept missing output | C; missing; failed |
| T02 | Actual failing check defeats existing artifact | C; satisfied; check executed/nonzero; failed |
| T03 | Required denial survives reassurance | C; satisfied; required denial; failed |
| T04 | Optional denial does not reject verified work | C; satisfied; actual check passed; optional denial retained; passed |
| T05 | Correct file can pass with empty stdout | C; satisfied; exact bytes and SHA-256 recorded; passed |
| E01 | Worker cannot replace criteria | Original frozen output still required; missing; failed |
| E02 | Worker claim cannot manufacture check execution | C; satisfied; check not_run/executed=false; acceptance not_run |
| E03 | Legacy success cannot become verified success | C retained; deliverable/acceptance unknown; ledger bytes unchanged |
| E04 | Explicit valid no-findings review accepted | C; satisfied; passed |
| E05 | Vague review rejected | C; invalid; failed |
| E06 | Malformed/missing extraction fields rejected | All three probes: C; invalid; failed |
| E07 | Research requires supporting references | C; invalid; failed |
| E08 | Unclassifiable denial cannot silently pass | C; satisfied; unresolved denial; needs_review |
| E09 | Real verification defeats optimistic claim | C; satisfied; actual assertion fails; failed |
| E10 | Original criteria survive retries/rounds | Retry retains fingerprint and passes; separate iterate records failed then passed under one unchanged fingerprint |

Evidence: [focused test output](p1-evidence/focused-tests.log),
[T tests](../tests/test_acceptance.py), [E tests](../tests/test_acceptance_invariants.py),
[boundary tests](../tests/test_acceptance_integrity.py).

There are 36 focused tests. Every validator category has valid, invalid, and
missing/unavailable evidence controls. Review accepts explicit `no_findings` but
does not claim exhaustive defect discovery. Research with a deterministically
pinned answer can pass; structurally valid but unjudged research is `needs_review`.
No AI grading was used.

Before implementation, all five T cases failed P1 assertions because acceptance
dimensions did not exist; their workers nevertheless completed with exit zero.
[Baseline output](p1-evidence/baseline-tests.log) preserves that result. A retained
planner record and a new read-only reviewer attempt also independently confirmed
exit-zero completion despite rejected headless operations. Production logs were
not copied into fixtures; native denial shape was recreated with `/fixture/` paths.

## C. Real iterate demonstration

**PASS.** One real check-driven repair, not a mocked worker:

- Task: `20261018-001829-iterate-coder-be9c23`.
- Worker: registered `coder`, OpenCode `build`, model `local/gpt-6-luna`.
- Bounds: at most two rounds, 90-second worker timeout, 15-second check timeout.
- Actual work: one worker attempt, one repair round.
- Authority: existing workspace-write worker; no extra approvals or permission changes.
- Fixture/state: `/tmp/ambu-p1-demo.Q2ia0G`, separate from production task state.
- Contract: `3daf4a2008e18e1b49b609d6de4d905d36fc957bfe2db4722147d425c3dbd64b`.

The same deterministic command evaluates `double(0)`, `double(3)`, `double(-4)`:

| Stage | Actual evidence |
|---|---|
| Initial supervisor check | Exit 1; `AssertionError: [1, 4, -3]` |
| Real worker repair | `return value + 1` changed to `return value * 2` |
| Later supervisor check | Exit 0; `double-values PASS` |
| Final result | Process completed; deliverable satisfied; acceptance passed |

Evidence: [execution/attempt record](p1-evidence/iterate-run/execution.json),
[frozen contract](p1-evidence/iterate-run/acceptance-contract.json),
[both evaluations](p1-evidence/iterate-run/acceptance.json),
[initial failure](p1-evidence/iterate-run/rounds/0/check-stderr.log),
[worker trace](p1-evidence/iterate-run/rounds/1/stderr.log),
[supervisor final check](p1-evidence/iterate-run/rounds/1/check-stdout.log).
The before/after artifact snapshots and their hashes are linked from the evaluations.
The worker's own verification claim is retained but is not the acceptance authority.

The real worker run preceded final semantic/timeout hardening. After those changes,
the final validator reran the same original frozen check against the actual repaired
artifact, verified its hash against the real run, and passed again. This is recorded
as `final-code-recheck` in [post-review evidence](p1-evidence/post-review/acceptance.json),
with final code hashes in `source-digests.json`. No second worker repair was substituted.

## D. Quality, safety and limits

| Level | Status | Evidence and scope |
|---|---|---|
| A — Structural | PASS | Frozen contract mutation tests, malformed-input rejection, separate state dimensions, legacy read tests, source diff and resolvable evidence links |
| B — Semantic | PASS | T/E matrix, positive/negative/unavailable controls, manual inspection of output snapshots, native denial records and actual check errors |
| C — Empirical | PASS | Baseline false-success reproductions, corrected deterministic cases, real worker repair, final-code recheck and full regression suite |

Final full suite: **335 tests passed**, including 36 P1 tests and 299 pre-existing
tests. [Full output](p1-evidence/full-suite.log). Reproduce from this worktree:

```sh
PYTHONPATH=src python3 -B -m unittest discover -s tests -p 'test_acceptance*.py' -v
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

Direct review covered the complete source diff, new module, representative artifacts,
schema and evidence links. Gitleaks found no leaks in the changed source, tests and
sanitized evidence. `git diff --check` is clean. No new product dependency,
orchestrator, service, skill, database, or memory integration was added.

Optional independent specialist review: **INCONCLUSIVE**, not an approval. Two
bounded test-authoring attempts timed out without a test file. One Ren attempt
exited zero with empty stdout after a denied shell tool; a read-tools-only follow-up
timed out. The lead implemented the tests, inspected the source and ran the gates
directly. No reviewer consensus or completed specialist review is claimed.

Known limits, not universal correctness claims:

- The JSON-schema subset is intentionally explicit; unsupported keywords are rejected.
- Research reference presence is not proof of truth. Unbounded substantive judgment
  stays `needs_review`; a declared manual-review criterion also stays `needs_review`.
- Native OpenCode denial records are matched exactly to frozen operation/target pairs.
  Other observed denials remain unresolved. This is not exhaustive provider telemetry.
- The supervisor controls criteria in the existing trusted local process. Fingerprints
  and declared verifier-input hashes are not OS isolation against malicious same-UID
  access. Undeclared command dependencies are not hermetically sealed.
- Process-status consumers are unchanged. They must explicitly use the new acceptance
  field when making acceptance decisions. No queue/routing redesign was performed.
- Provider/headless permission mismatches and source/deployment drift were not repaired.
  They did not block the required real repair. No broader reliability percentage is claimed.

Safety/hygiene: the installed checkout remains on `9ce3754`, with only its original
`model_catalog.py` and `uv.lock` tracked modifications. Their before/after SHA-256
values match. The development worktree has no uncommitted tracked changes after
handoff commits. Ignored `.opencode` runtime bootstrap files (`@opencode-ai/plugin`
1.18.30 and its package tree) and Python caches remain untracked; they are not product
dependencies or release artifacts. The demo queue is empty. Temporary fixtures and
test evidence were intentionally retained, not deleted. Detailed synthetic records
remain at `/tmp/ambu-p1-semantic-evidence.0KBp9Z`; portable named-case and real-run
evidence is committed under `docs/p1-evidence/`.

The discipline skill kept changes on the existing lifecycle; evidence-gate and hygiene
skills required separating verified gates from failed specialist attempts and retained
runtime artifacts. They did not add approval steps, policy changes or new infrastructure.

## E. Closure gates

All gates use the environment stated above. No mandatory gate is waived.

| Gate | Status | Inspected evidence |
|---|---|---|
| G01 — Contract integrity | PASS | Before-dispatch snapshot; frozen object; E01/E10; disk/input tamper and timeout tests |
| G02 — Process compatibility | PASS | T01–T05 completed independently of acceptance; failed-process/passed-acceptance control; existing suite |
| G03 — Task-specific validation | PASS | Four validator categories; explicit no-findings; extraction schema; pinned research answer and needs-review control |
| G04 — Evidence provenance | PASS | Supervisor subprocess results, timestamps, criterion/contract/attempt identities, snapshots and hashes; E02/E09 |
| G05 — Permission classification | PASS | T03/T04/E08 and approval-gate tests; native companion rejection handling |
| G06 — Five regressions | PASS | T01–T05; named-case records and focused output |
| G07 — Adversarial invariants | PASS | E01–E10 and boundary controls |
| G08 — Historical compatibility | PASS | E03; unchanged ledger bytes; legacy show/status projections |
| G09 — Existing tests | PASS | 335 tests passed on final source; source hashes recorded |
| G10 — Real iterate repair | PASS | Actual initial failure, real worker edit, actual passing recheck, one frozen contract; final-code recheck |
| G11 — Scope and authority | PASS | Isolated branch; original tracked changes preserved; unchanged approval gates; no merge/push/deployment or installed CLI update |

Closure verdict: **P1 VERIFIED**. No mandatory P1 blocker remains. This is a local
development handoff only; deployment and merging remain unauthorized.
