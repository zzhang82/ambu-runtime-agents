# Backlog: Queue Hygiene and Assistant UX

## Objective

Improve operator clarity after `v1.5.1` burn-in by making queue residue, assistant payloads, and Telegram status/queue views easier to understand without adding watchers or learning automation.

## Facts and evidence

- `docs/burn-in-v1.5.1.md` identified queue residue as the main friction.
- `queue active --json` exposed stale validation/selftest artifacts.
- `queue cleanup-validation --dry-run --json` correctly identified cleanup candidates.
- Burn-in observed `active_count: 50` for validation residue.
- `assistant-exec "list workspaces"` returned two workspaces but summarized count as `1`, because current generic count reflects action count, not domain count.
- Telegram `/status` and `/queue` currently risk amplifying raw queue noise.

## Requirements

1. Preserve event-sourced JSONL queue model.
2. Preserve `queue cleanup-validation --dry-run` as safe preview.
3. Classify validation/selftest artifacts with reasons and confidence.
4. Keep cleanup conservative; uncertain real work must not be silently cancelled.
5. Add an operator-friendly queue hygiene summary or filtering option.
6. Improve Telegram `/status` and `/queue` so validation residue does not dominate.
7. Fix or clarify assistant `count` semantics while preserving compatibility.
8. Add tests for queue classification, dry-run non-mutation, real cleanup, assistant counts, and Telegram rendering.

## Non-goals

- Do not add watchers.
- Do not start Learning Sessions.
- Do not add automatic cleanup by default.
- Do not change queue storage away from JSONL.
- Do not allow Telegram to approve dangerous actions.

## Proposed classifier shape

```json
{
  "matched": true,
  "confidence": "high",
  "reason": "goal_contains_selftest",
  "markers": ["selftest"],
  "fields": ["goal"],
  "safe_to_cancel": true
}
```

Suggested confidence:

- `high`: explicit selftest / telegram selftest / known validation metadata.
- `medium`: smoke, validation, `/tmp/opencode` markers.
- `low`: generic `test-ws` or weak marker-only matches.

Default cleanup should skip low-confidence items unless explicitly requested.

## Phases

### Phase 0 - Baseline capture

- Capture current queue active, cleanup dry-run, assistant list-workspaces, and Telegram queue/status behavior.
- Add failing/regression test for workspace count confusion.

### Phase 1 - Queue hygiene diagnostics

- Add structured validation artifact classifier.
- Add tests for high/medium/low/uncertain matches.
- Add `queue hygiene --json` or equivalent diagnostic output.

Suggested payload:

```json
{
  "active_count": 50,
  "actionable_count": 0,
  "validation_artifact_count": 50,
  "uncertain_count": 0,
  "recommendations": [
    {"command": "agentctl queue cleanup-validation --dry-run --json"}
  ]
}
```

### Phase 2 - Safer cleanup UX

- Wire classifier into `queue cleanup-validation`.
- Include per-item reason, fields, markers, confidence.
- Preserve dry-run non-mutation.
- Add optional confidence threshold if needed.

### Phase 3 - Operator queue views

- Keep raw `agentctl queue --json` complete.
- Prefer `queue hygiene` or `--exclude-validation` for human-facing surfaces.
- Update Telegram `/status`, `/queue`, and notifications to use the shared classifier.

### Phase 4 - Assistant payload consistency

- Preserve `action_result.result.count` as action count for compatibility.
- Add `action_count`.
- Add typed counts such as `workspace_count`, `profile_count`, `tool_count`, `queue_item_count`.
- Add regression test for burn-in workspace count issue.

### Phase 5 - Safe runbook phrase polish

- Expand only read-only runbook phrases based on dogfooding.
- Improve clarification wording for missing workspace/task/plan.
- Keep dangerous routes blocked.

## Validation

```bash
python3 -m unittest discover -s tests
agentctl smoke --json
agentctl doctor --json
agentctl selftest --json
agentctl queue active --json
agentctl queue cleanup-validation --dry-run --json
agentctl assistant-route "list workspaces" --json
agentctl assistant-exec "list workspaces" --json
agentctl assistant-route "run rm -rf /" --json
```

## Risks

- Over-cleaning real work.
- Breaking JSON consumers by changing count fields.
- Hiding debug evidence if raw queue views are filtered.
- Telegram local filtering could drift from CLI semantics.

## Definition of done

- Queue residue is classified and explainable.
- Telegram/operator views summarize residue without hiding raw CLI evidence.
- Assistant workspace count issue is fixed or clarified.
- Tests and health checks pass.
