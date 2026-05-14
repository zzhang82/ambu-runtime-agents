# Changelog

## 1.4.0

- Added first-class profile and local tool registries with separate `profiles.yaml` and `tools.yaml` config surfaces.
- Added `agentctl profile ...` and `agentctl tool ...` commands, plus profile-aware runbook/action support for deterministic assistant routing.
- Extended doctor/smoke/test coverage for profile and tool validation while keeping this release metadata-first with no new runtime guardrail enforcement.

## 1.3.1

- Extracted typed assistant action execution into `runtime_agents.actions` with an explicit `ActionResult` model while keeping `assistant-exec` payload behavior stable.
- Added normal vs strict runbook validation, including `agentctl runbook validate --strict` and surfaced invalid skipped runbooks in `agentctl doctor --json`.
- Added focused regression coverage for executor behavior, runbook validation policy, and `assistant-exec` contract handling.

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
