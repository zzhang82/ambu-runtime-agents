# AMH / AMB Memory Contract

This document defines the first docs-only contract for runtime-agents memory integration.

## Boundary model

```text
runtime-agents control plane
  -> AMH memory workflow / governance layer
        -> AMB governed durable memory substrate
```

AMB is the durable governed substrate and MCP-compatible storage/retrieval source for memory records. AMH is the workflow and governance layer that decides how memory is recalled, packaged, proposed, promoted, audited, and validated before or after AMB access.

runtime-agents keeps operational state separately from durable memory. Queue, task, plan, run, schedule, Telegram session, and local profile state remain runtime local state, not AMB durable memory. Repo files, git history, tests, manifests, and release artifacts remain implementation and release authority.

## Non-goals

- Do not add a hard AMH dependency for base `agentctl` operation.
- Do not make AMH a second durable memory database over AMB.
- Do not require production AMB writes for this contract.
- Do not build learning sessions in this slice.
- Do not store raw transcripts, secrets, credentials, or unverified release claims as durable memory.

## Authority classes

Memory records and candidates must declare or be assigned one authority class before they are presented as governed memory.

| Class | Meaning | Release proof |
| --- | --- | --- |
| `context_hint` | Useful context that must be verified against live files or current state. | No |
| `handoff` | Session/task continuity and next-step context. | No |
| `status` | Operational snapshot that may be stale. | No |
| `procedure` | Reusable rule, workflow, or safe operating pattern. | No |
| `decision` | Human/project decision with date and scope. | No |
| `belief_proposal` | Candidate belief awaiting promotion or rejection. | No |
| `release_evidence` | Claim tied to explicit git, test, version, or artifact evidence. | Only with evidence |
| `persona_preference` | User/operator preference, not implementation truth. | No |
| `sensitive_excluded` | Marker for content that must not be written durably. | No |

## Namespace policy

Namespace resolution should be explicit and visible in JSON decisions.

Resolution order:

1. CLI flag or command argument.
2. Profile `memory_namespace`.
3. Workspace default memory namespace.
4. Safe no-memory degraded mode.

runtime-agents must not infer a durable namespace from arbitrary task text. If no namespace resolves, recall and writeback should degrade safely instead of writing to a guessed namespace.

## Recall request

AMH-compatible recall requests describe intent and limits without requiring AMH to exist at runtime.

```json
{
  "schema_version": "memory.recall_request.v1",
  "goal": "prepare context for profile run",
  "namespace": "project:runtime-agents",
  "query": "guardrail burn-in profile dry-run gotchas",
  "max_records": 8,
  "allowed_authority_classes": ["context_hint", "handoff", "procedure", "decision"],
  "require_verification": true,
  "source": {
    "command": "agentctl profile run",
    "profile_id": "runtime-dev"
  }
}
```

## Recall decision

Recall decisions make policy outcomes visible even when runtime-agents uses the current direct AMB compatibility path.

```json
{
  "schema_version": "memory.recall_decision.v1",
  "status": "allowed",
  "namespace": "project:runtime-agents",
  "selected_records": [
    {
      "id": "20260521000000000000-example",
      "authority_class": "procedure",
      "reason": "matched profile burn-in procedure",
      "verification_required": true
    }
  ],
  "degraded_mode": null,
  "policy_reasons": ["namespace_resolved_from_profile", "repo_files_remain_authority"]
}
```

If recall cannot proceed safely, `status` is `degraded` or `denied` and `selected_records` is empty.

## Memory candidate

Memory candidates are proposed facts or procedures. They are not durable AMB records until policy allows writeback and the configured write path succeeds.

```json
{
  "schema_version": "memory.candidate.v1",
  "authority_class": "procedure",
  "namespace": "project:runtime-agents",
  "title": "Profile dry-run must expose memory degradation",
  "content": {
    "claim": "Profile dry-run output should show when memory recall is degraded.",
    "trigger": "profile dry-run uses a memory namespace but recall is unavailable",
    "fix_or_decision": "surface degraded memory status in JSON instead of failing the dry-run"
  },
  "evidence": {
    "files": ["src/runtime_agents/cli.py", "tests/test_profile_memory.py"],
    "commands": ["python3 -m unittest discover -s tests"]
  },
  "sensitivity": "normal"
}
```

Candidates with `sensitivity` of `secret`, `credential`, `raw_transcript`, or `sensitive_excluded` must be denied before durable writeback.

## Writeback decision

Writeback decisions must preserve dry-run behavior and explain every denied candidate.

```json
{
  "schema_version": "memory.writeback_decision.v1",
  "dry_run": true,
  "status": "denied",
  "namespace": "project:runtime-agents",
  "candidate_title": "Release v1.5.1 is complete",
  "authority_class": "release_evidence",
  "reasons": ["release_evidence_requires_git_test_version_evidence", "dry_run_no_write"],
  "would_write": false
}
```

## Writeback receipt

Receipts prove what the runtime attempted and what AMB returned. They are not release proof by themselves.

```json
{
  "schema_version": "memory.writeback_receipt.v1",
  "status": "stored",
  "namespace": "project:runtime-agents",
  "record_id": "20260521000000000000-example",
  "candidate_authority_class": "procedure",
  "verification": {
    "requested": true,
    "status": "verified"
  }
}
```

## Audit event

AMH and runtime-agents should emit audit events for recall, writeback, policy denial, and degraded modes.

```json
{
  "schema_version": "memory.audit_event.v1",
  "event_type": "recall_degraded",
  "namespace": "project:runtime-agents",
  "degraded_mode": "amb_unavailable",
  "command": "agentctl profile run",
  "safe_to_continue": true,
  "message": "Continuing without memory context; repo files and command inputs remain authoritative."
}
```

## Degraded modes

The memory layer must fail closed for writes and fail soft for context-only recall when safe.

| Mode | Meaning | Safe behavior |
| --- | --- | --- |
| `amh_unavailable` | AMH workflow layer is not configured or not reachable. | Use current direct AMB compatibility path when configured; otherwise continue without memory. |
| `amb_unavailable` | AMB substrate is not reachable. | Continue without recall context; deny durable writeback. |
| `namespace_missing` | No explicit namespace resolved. | Continue without recall context; deny durable writeback. |
| `policy_denied` | Governance rules denied recall or writeback. | Surface reasons in JSON; do not bypass policy. |
| `verification_failed` | Evidence or post-write verification failed. | Treat memory as untrusted; deny promotion or mark receipt unverified. |

## Compatibility rule

Existing direct AMB recall and writeback behavior remains the compatibility path while AMH adapters mature. This contract adds vocabulary and JSON shapes for policy visibility; it does not require AMH at runtime and does not change production write behavior by itself.
