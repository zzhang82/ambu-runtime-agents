# P1 acceptance contract

Development scope: evidence-based acceptance within the existing run/iterate lifecycle.
No process-status, policy, routing, dependency, installed CLI, or deployment changes.

## Frozen input

`run` and `iterate` accept `--acceptance-contract PATH` (JSON). The supervisor
loads it once before dispatch, validates it, canonicalizes it, and stores its SHA-256
fingerprint and content in task metadata and `acceptance-contract.json`. Worker
stdout is never a contract source. Retry/resume inherit the recorded contract.
Uncontracted history and uncontracted new runs remain acceptance `unknown`.
Existing iterate check/artifact arguments create a minimal supervisor contract
when no explicit contract is provided; they do not invent a substantive output.

Required keys: `contract_version: 1`, `result_type` (implementation, review,
extraction, research), `required_outputs`, `required_checks`,
`required_permissions`, `validation_rules`. Unknown/unsupported rules fail closed.

Outputs: objects with unique `id`, `source` (`file` or `stdout`), and `path` for
files. Supported assertions: `equals` (exact text), `nonempty` (explicit), `schema`
(JSON Schema subset below). Files must stay within the task workspace. Output
bytes are independently read, hashed and snapshotted in the run's evidence folder.
Implementation requires a file output or an actual declared check. Review,
extraction and research require a JSON output. Their minimal schemas:

- Review: `verdict` is `findings` with a nonempty `findings` array, or `no_findings`
  with an empty `findings` array. Each finding is a nonempty string or object.
- Extraction: an explicit output `schema`, including declared required fields.
- Research: nonempty `answer`, nonempty `evidence` array of nonempty references,
  and explicit `limitations` array. This verifies representation, not claim truth.
  Automatic acceptance additionally requires a deterministic expected-answer rule:
  output `equals`, root schema `enum`, or `schema.properties.answer.enum`. Otherwise
  a structurally valid answer is `needs_review`, since substance cannot be judged
  from nonempty text or citations. This is conservative deterministic P1 validation,
  not an AI grader or an attestation of reference truth.

The supported JSON schema subset is `type`, `properties`, `required`, `items`,
`enum`, `minLength`, `minItems`, `additionalProperties` (boolean). Unsupported
keywords are rejected, not silently ignored. Semantic requirements can use
`validation_rules.manual_review: true` to force `needs_review`.

Checks: unique `id`, optional `command`, optional nonnegative `timeout` (default
300 seconds; zero retains the existing runner's timeout behavior), optional `inputs`
mapping workspace-relative paths to SHA-256
digests. A check with no command is explicitly `not_run`. Checks execute through
the existing supervisor shell-check runner, after the existing approval gates.
Declared check input digests detect changed verifier scripts; arbitrary shell
commands are not sandboxed or made safe by this contract. Declare hashes for
workspace verifier scripts in `inputs`; undeclared command dependencies are not
hermetically sealed. Each executed check also records the declared file outputs'
digests. If a later check changes those outputs, earlier passes cannot establish
acceptance of the final bytes and the result becomes `needs_review`.

Permissions: exact `{operation, target}` pairs. Required pairs live in
`required_permissions`; optional pairs in `validation_rules.optional_permissions`.
The native stderr `permission requested: OP (TARGET); auto-rejecting` record is
matched exactly to these pairs. Other denials are `unresolved`, never inferred
optional from keyword absence. Worker text is not proof of permission or checks.
The native request's immediately following standard rejection message is retained
in raw logs but is not counted as a second, unrelated denial. Permission
declarations classify denials; they are not grants or attestations that an
operation happened. Task outputs and checks must supply the evidence of work.

## Results and precedence

Existing `status` and CLI process return codes retain their old meaning. Consumers
must inspect `acceptance_status`, not infer acceptance from `completed` or exit 0.
Independent top-level fields: `deliverable_status`, `acceptance_status`,
`acceptance_reason`, `contract_fingerprint`, plus an `acceptance` evidence record.
`show --json` projects unknown acceptance for legacy records without rewriting them.

Precedence: no contract -> unknown; missing/invalid output -> failed; actual failed
check -> failed; required denied operation -> failed; unresolved denial or integrity
conflict (including changed output bytes after a check) -> needs_review; required
check not executed -> not_run; unavailable evidence
-> unknown; declared manual semantic review -> needs_review; otherwise passed.
An earlier failed iterate check remains in history but only the latest evaluation
of the current artifact is eligible to pass. Denials across the execution remain
visible across fallback attempts and rounds. A `retry` creates a linked new
execution with the original frozen contract; the prior execution remains intact.
Process failure alone is not acceptance
failure. An unexecuted post-worker check cannot reuse a pre-worker passing result.

`passed` means the declared applicable criteria passed with recorded evidence. It
does not certify exhaustive review, universal correctness, citation truth, or any
optional work. This is supervisor ownership within the existing trusted local
runtime, not OS isolation against a malicious process with the supervisor's UID.

## Inspection baseline

- Installed source: `/home/zzs333/code/runtime-agents`, `master`,
  `9ce375462380fb309b62a38d0b45d5363449c527`, version 1.5.1.
- Remote default `master`: `f14122238bcd118b008b45c38fcf2d2b6622ceaf`;
  no remote main. Drift is reported, not reconciled.
- Existing modifications: `src/runtime_agents/model_catalog.py`, `uv.lock`.
- `cli.py:run_task` maps exit zero to completed; `iterate_cmd` already has shell
  checks, per-round logs, artifact verification, bounded repair and approval gates.
- Retained planner record `20260923-030618-planner-ab3227`: completed, returncode 0,
  with headless permission rejections in stderr. No raw production log is copied.
- P1-T01 through T05 on baseline: process completed in all cases; all five P1
  assertions fail because deliverable/acceptance dimensions do not exist.

Development branch: `p1/evidence-based-acceptance`. Implementation and test results
will be documented in the accompanying handoff; this file is the schema contract.
