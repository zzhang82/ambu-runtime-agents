# Steward Air compatibility patch assessment

Inspected 2026-10-18. Base: merged P1 `4c73b05a4d71b0393a3f31b549a81629704e51bd`
on `origin/master`. This is a source compatibility PR, not a host deployment or a
new P1 verification claim. No services, credentials, model assignments, allowlists,
or installed CLIs are changed.

## Five installed differences

Read-only comparison covered all 45 non-cache files in Steward Air's imported
`runtime_agents` package. Exactly these five existing files differed from both
the old `9ce3754` baseline and merged P1. P1 also adds `acceptance.py`.

| Installed file | Decision for upstream | Reason and boundary |
| --- | --- | --- |
| `cli.py` | Adapt | Keep final model allowlist enforcement and opt-in diagnostic command construction. Do not copy the host's replacement of preflight fallbacks with an environment list: that could restore excluded models. Keep required preflight candidates and explicit pins authoritative over legacy `--fallback` profiles. |
| `model_catalog.py` | Adapt | Keep optional configured allowlists, agent-specific filtering, required live preflight, and existing OpenCode `{file:...}` key-reference support. Intersect config and environment restrictions; never infer candidates from them. Keep agent-free advisory planner ordering unchanged. |
| `paths.py` | Adopt | Preserve `RUNTIME_AGENTS_EVENTS_JSONL` so confined Hostkeeper work writes events to its existing scratch directory. Default path remains unchanged. |
| `loop_engine.py` | Adapt selectively | Stop for unavailable check commands using existing `check_rubric` classification. Add narrow direct Python checker-open diagnostics and workspace/denial guidance. Do not import broad substring detection, `ISSUE1_`/assertion-marker exemptions, a new `infrastructure` status, or the extra retry allowance. |
| `policy.py` | Retain upstream, no source patch | PR #2 already supersedes the host parser, including later affirmative clauses after a prohibition. Replacing it would regress those fixes. Run the existing policy suite plus representative host/later-fix cases. |

The diagnostic agent is a host dependency, not a new bundled role. The inspection
found Hostkeeper actively sets the model restriction and event-path overrides;
these are not unused compatibility shims.

## Contract

- `model_routing.allowed_models`, when present, is a nonempty list of `local/...`
  model names. `RUNTIME_AGENTS_MODEL_ALLOWLIST`, when present, is a nonempty
  comma-separated list. Invalid values and empty intersections fail closed.
- Config and environment lists intersect. Neither may expand the routing frame,
  catalog, quota, cooldown, or deprecation-filtered candidates. Restrictions
  require `model_routing.required: true`; `--model` also respects them. Advisory
  recommendations without an agent remain advisory, not dispatch authority.
- `--fallback` can use legacy profiles only when live routing is not required
  and the model is not explicitly pinned. Required dispatch uses only the
  preflight fallback list, even when that list is empty.
- OpenCode file references resolve relative to its config directory, or expand
  `~`/absolute paths. Missing, unreadable, or empty references fail without
  disclosing the value or sending the literal reference. Tests use synthetic
  files only. The host's credentials/config are neither read into fixtures nor
  modified.
- `RUNTIME_AGENTS_DIAGNOSTIC_PROFILE=read_only` requires `read_only` autonomy,
  selects the already-installed `hcp-readonly-diagnostic` agent, and adds
  `--pure --format json`. An unknown profile or writable autonomy is rejected.
  Optional `RUNTIME_AGENTS_DIAGNOSTIC_EVIDENCE` is one `--file` argument. This
  does not install the agent or provide filesystem confinement; the host owns
  those controls.
- A check returning 126/127 or a direct Python "can't open file" diagnostic
  stops the iterate loop with process `blocked`, exit 3, and
  `halt_reason: inaccessible_check`. Initial failures dispatch zero workers;
  later failures stop further repair. Check evidence still reaches P1.
- Product `FileNotFoundError`, `PermissionError`, assertions, and stdout strings
  do not trigger the new Python diagnostic rule. Classification is a bounded
  heuristic, not proof about arbitrary check scripts. P1 permission-denial
  evidence remains a separate mechanism.
- The initial failed check still counts toward `--max-same-failure`, as upstream
  documents and tests. Steward's extra allowance is intentionally not adopted;
  budget changes are not needed for compatibility or protection.

## Verification

Tests live in `tests/test_steward_compat.py`, `tests/test_model_allowlist.py`, and
the existing model, execution-substrate, iterate, policy, and P1 suites. The
new compatibility tests were first run against the merged baseline to reproduce
missing controls.

Local baseline evidence: `/tmp/ambu-steward-compat.KdOv14/compat-baseline.txt`.
It records 10 tests with 13 failing subcases before implementation. Selected
policy and product-error negative controls already passed on the baseline.
No production logs or credentials are committed as fixtures.

Observed on WSL, Python 3.12.3, 2026-10-18:

| Check | Observed result | Status |
| --- | --- | --- |
| New command/loop/event compatibility tests | 13 tests pass | PASS |
| New model restriction/file-reference tests | 10 tests pass | PASS |
| Existing P1 acceptance tests | 36 tests pass | PASS |
| Existing policy tests | 14 tests pass; policy source unchanged | PASS |
| Full suite after fixture corrections | 367 tests pass in 37.270 seconds | PASS |
| TruffleHog 3.95.3 | Nine changed files scanned, zero findings | PASS |
| Independent Ren review | First attempt hit a denied shell command; file-read-only retry timed out without verdict | INCONCLUSIVE |
| Installed macOS/Python 3.14 behavior | No package installation or execution of this build on Steward | NOT_RUN |

Commands: `PYTHONPATH=src python3 -B -m unittest discover -s tests -v`, with
`-p 'test_steward_compat.py'`, `-p 'test_model_allowlist.py'`,
`-p 'test_acceptance*.py'`, and `-p 'test_policy.py'` for focused runs.
Local output is retained under `/tmp/ambu-steward-compat.KdOv14/` in
`full-suite-final.txt`, `compat-tests.txt`, `model-tests.txt`, `p1-tests.txt`,
`policy-tests.txt`, and `secret-scan.txt`.

The lead inspected the implementation and tests directly; there is no independent
review approval. The draft PR preserves this limitation. Eli's implementation
attempt also timed out without changes; the lead completed the code locally.
No worker exit-zero result was treated as proof of review or implementation.

Two fixture defects were corrected: mocked tilde expansion needed to handle bare
`~`, and iterate fixtures needed the registered `--workspace` instead of an
unsupported `--cwd` flag. The accidental disposable marker was removed and the
full suite rerun. No existing test expectation was weakened.

The first PR CI run (`39186278633`) passed on Python 3.11/3.12 but found a
Python 3.10-only fixture error: pathlib retains an `os.path.expanduser` alias,
so replacing the module attribute does not intercept it. The tilde test now stubs
the common OS user-home lookup and exercises the real pathlib implementation.
No production code or expected behavior changed for that correction. The
follow-up CI run is the authority for cross-version results.

## Deployment remains held

Steward inspection found macOS arm64, Python 3.14, both old/new 1.5.1 distribution
metadata, and a host-patched imported package with no P1 module. The source
version string alone cannot identify what is installed. The next host update
must preserve a rollback copy, inspect exact installed hashes/entrypoints, and
verify the reviewed package in that environment without weakening permissions.

Hostkeeper's current caller checks process exit/status and `final_check_passed`,
not `acceptance_status`. Updating Ambu alone does not make that caller fully
evidence-based. Caller adoption is a separate explicitly scoped change. This PR
does not restart Hostkeeper, alter routing, or run another canary.
