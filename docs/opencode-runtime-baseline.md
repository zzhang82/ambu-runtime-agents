# OpenCode Runtime Baseline

Status: Completed cleanup baseline. OpenCode is the only supported live execution substrate.

## Intended Direction

ADR 0001 makes OpenCode CLI the intended primary execution substrate:

- `runtime-agents` owns orchestration, policy, profiles/tools, runbook routing, queue/task state, and operator UX.
- OpenCode owns model/runtime execution.
- Direct provider-specific adapters were removed from live execution. Historical/quarantined docs may still mention old adapter work as prior context.

## Current Execution Surfaces

| Surface | Current behavior | Execution choice field | Baseline requirement |
| --- | --- | --- | --- |
| `agentctl run` | Loads `agents.yaml`, reads `agents.<name>.tool`, then builds an OpenCode command. | `agents.<name>.tool`, `agents.<name>.model`, optional `agents.<name>.opencode_agent`, optional `--model` | Preserve approvals and report substrate metadata in dry-run/run metadata. |
| `agentctl iterate` | Runs shell check first, then uses the same OpenCode command builder for each failed round. | `agents.<name>.tool`, `agents.<name>.model`, optional `agents.<name>.opencode_agent`, optional `--model`, `fallback_profiles` | Preserve approval and local-workspace safety gates before execution. |
| `agentctl submit` | Appends queue item with agent, mode, goal, cwd/workspace, memory options, check, and max rounds. | Queue item `agent`; later resolved by `run-next`. | Queue schema remains substrate-neutral. |
| `agentctl run-next` | Shells to `agentctl run` or `agentctl iterate` from queued item. | Queue item `agent` plus current `agents.yaml`. | Keep `tasks.jsonl`, `queue.jsonl`, run dirs, stdout/stderr, and metadata intact. |
| `agentd` | Loops over `agentctl run-next`. | None directly. | Must stay dumb; no OpenCode-specific daemon behavior. |
| `agentctl profile run` | Resolves profile/agent/workspace, evaluates guardrails, then delegates to `run`. | Profile `default_agent` or `--agent`; agent `tool`/`model`; optional selected profile tool only affects guardrails. | Profiles/tools stay policy metadata, not model routers. |
| `agentctl profile plan` | Creates plan metadata and subtask queue shape; does not execute runtime directly. | Plan subtask `agent`; later resolved by queue execution. | Keep profile/guardrail metadata above substrate. |
| `assistant-route` | Matches deterministic runbooks and returns typed actions. | No runtime choice. | Must not become a model/runtime router. |
| `assistant-exec` | Executes read-only typed actions or queues run/iterate actions. | Queued action `agent`; later resolved by `run-next`. | Preserve confirmation gates for workspace writes. |
| Telegram bot | Shells to `agentctl` commands for status, queueing, plans, logs, and assistant execution. | No direct runtime choice except submitted agent name. | Telegram remains control/conversation channel, not a direct OpenCode shell. |

## Current Config Fields

`agents.yaml` currently controls OpenCode execution:

- `tools.opencode.command`: doctor/config check for the OpenCode CLI.
- `agents.<agent>.tool`: must be `opencode` for supported live execution.
- `agents.<agent>.model`: model passed to OpenCode with `--model`.
- `agents.<agent>.opencode_agent`: optional OpenCode agent passed with `--agent`.
- `agents.<agent>.fallback_profiles`: optional OpenCode model fallback aliases.
- `agents.<agent>.autonomy`: still controls runtime-agents approval policy before execution.
- `agents.<agent>.approval_required`: capabilities that must be approved before execution.

Profiles and the tool registry remain policy metadata:

- `profiles.<profile>.default_agent` and `allowed_agents` select eligible agents.
- `profiles.<profile>.allowed_tools` feeds guardrail context and does not select the runtime executable.
- `tools.yaml` describes tool trust, egress, capabilities, and profile scope.

## Current Baseline Decisions

- `opencode` is the supported live execution substrate.
- Provider-specific direct adapter values are unsupported in `build_command`.
- The non-interactive OpenCode command shape is `opencode run --model <model> --agent <agent> <prompt>`.
- `run` and `iterate` dry-run output now reports `execution_substrate`, `legacy_direct`, and `intended_primary_substrate`.
- Run metadata records the same fields for real executions without changing artifact layout.

## Regression Coverage Added

`tests/test_execution_substrate.py` freezes the first safe slice:

- OpenCode substrate classification
- OpenCode command construction helper
- unsupported direct adapter command checks
- `agentctl run --dry-run` substrate metadata
- `agentctl inspect` substrate metadata

## Historical Cleanup

- Default test/runtime config now points at OpenCode.
- Direct runtime fixtures were removed.
- Doctor/selftest focus on OpenCode health rather than direct provider CLIs.
