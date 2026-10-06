# Backlog: OpenCode Runtime Consolidation

Status: Done for initial baseline. Merged in `5025474 Characterize OpenCode runtime substrate`; later cleanup removed live direct provider CLI execution paths.

## Objective

Make OpenCode CLI the explicit primary execution substrate for `runtime-agents` while preserving the existing control-plane responsibilities: orchestration, policy, profiles/tools, runbook routing, queue/task state, and operator UX.

## Facts and evidence

- ADR 0001 is accepted and says OpenCode should own model/runtime execution while `runtime-agents` owns orchestration and policy.
- Current `agentctl` execution now uses OpenCode as the supported live substrate.
- The repo has profile/tool/guardrail metadata from `v1.5.1`; that metadata should stay above the execution substrate.
- `assistant-route` and `assistant-exec` are deterministic and typed; they should not become model routers.
- `agentd` is intentionally dumb and should keep shelling through `agentctl run-next` rather than learning OpenCode-specific behavior.
- Existing event capture can record tools, stdout/stderr, files touched, commands run, memory operations, and run artifacts.

## Requirements

1. Add or formalize an OpenCode execution adapter/path.
2. Make OpenCode the documented default execution substrate.
3. Remove active direct provider CLI support unless a future ADR reverses this.
4. Preserve current queue/task/run artifacts:
   - `tasks.jsonl`
   - `queue.jsonl`
   - `runs/<task_id>/metadata.json`
   - `runs/<task_id>/result.json`
   - stdout/stderr logs
5. Preserve approval and guardrail boundaries before execution.
6. Record in task metadata when OpenCode was the execution substrate.
7. Do not depend on hidden OpenCode internals or private chain-of-thought.
8. Prefer hermetic tests with fake OpenCode executable over tests that require a live provider.

## Non-goals

- Do not build a new direct multi-runtime router.
- Do not expand direct provider-specific adapters.
- Do not make Telegram a direct OpenCode shell.
- Do not solve AMH integration in this track.
- Do not reintroduce direct provider-specific adapters without a future ADR.

## Phases

### Phase 0 - Baseline current execution surfaces

- Inventory `run`, `iterate`, `run-next`, `agentd`, profile run/plan, assistant execution, and Telegram submission paths.
- Record which config fields currently choose runtime/tool/model.
- Add regression tests for current substrate behavior before changing defaults.

Baseline artifact:

- `docs/opencode-runtime-baseline.md`

Regression artifact:

- `tests/test_execution_substrate.py`

Validation:

```bash
python3 -m unittest discover -s tests
agentctl version --json
agentctl smoke --json
agentctl selftest --json
agentctl profile validate --json
agentctl tool validate --json
```

### Phase 1 - Add explicit OpenCode command construction

- Define the non-interactive OpenCode invocation contract.
- Add fake OpenCode fixture for unit tests.
- Verify stdout/stderr capture, exit code handling, timeout behavior, and run metadata.
- Ensure parse logic can capture OpenCode tool-use markers when present.

Acceptance:

- A test config can run an OpenCode-backed agent through `agentctl run`.
- OpenCode-backed execution tests pass.

### Phase 2 - Make OpenCode the default packaged substrate

- Update default agent config to prefer OpenCode.
- Update doctor/selftest so OpenCode is primary health check.
- Remove direct provider CLI checks from primary health paths.
- Update README and architecture docs.

Acceptance:

- Fresh default config validates with OpenCode as expected substrate.
- Missing direct provider CLIs does not fail health if OpenCode is healthy.

### Phase 3 - Remove direct runtime adapters

- Remove direct adapter code from live execution.
- Keep tests proving direct provider tool values are unsupported.
- Stop presenting direct adapters as primary docs path.

### Phase 4 - OpenCode-aware telemetry and UX

- Add metadata fields for execution substrate and configured model/profile.
- Improve `show`, `logs`, and run summaries for OpenCode-backed tasks.
- Add doctor diagnostics for missing/broken OpenCode setup.

## Risks

- OpenCode CLI may not map cleanly onto current autonomy modes.
- Renaming `tool` to `execution_substrate` could create config churn.
- Reintroducing direct adapters could undermine the pivot.
- Removing direct adapters can break local configs that still reference old tools; update configs to `opencode`.

## Dependencies

- OpenCode CLI non-interactive command contract.
- Current `agents.yaml` shape and OpenCode migration policy.
- `track/docs-roadmap-self-improvement` for docs alignment.
- `track/telegram-main-agent` for future delegation UX.

## Definition of done

- OpenCode is default documented execution substrate.
- `agentctl run`, `iterate`, `run-next`, and profile dry-run work with OpenCode-backed config.
- Direct adapters are gone from live execution and explicitly unsupported.
- Test suite, smoke, doctor, and selftest pass.
