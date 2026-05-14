# Changelog

## 1.3.0

- Made assistant routing runbook-first with packaged defaults under `src/runtime_agents/default_runbooks/` and local override support from `~/.config/runtime-agents/runbooks/`.
- Added validated runbook loading, placeholder rendering, typed-action allowlisting, and deterministic phrase matching through `runtime_agents.runbooks`.
- Added `agentctl runbook list/show/validate` and `agentctl assistant-exec --json` for data-driven routing and safe execution.
- Updated the Telegram assistant path to call `agentctl assistant-route` and `agentctl assistant-exec` instead of duplicating routing logic.
- Expanded regression coverage for runbook routing, assistant execution, and contract/version consistency.

## 1.2.0

- Extracted internal control model modules (`paths`, `state`, `models`, `policy`, `schedules`, `plans`, `assistant_router`).
- Refactored CLI to delegate to extracted internals while preserving command behavior.
- Added focused unit tests for extracted modules and maintained full CLI acceptance checks.

## 1.1.1

- Initial repo-backed packaging of the existing live runtime-agents install.
- Added editable install support.
- Added smoke checks and regression harness scaffolding.
