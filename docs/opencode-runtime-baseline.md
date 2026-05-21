# OpenCode Runtime Baseline

Status: Phase 0 characterization for the OpenCode runtime consolidation track.

## Intended Direction

ADR 0001 makes OpenCode CLI the intended primary execution substrate:

- `runtime-agents` owns orchestration, policy, profiles/tools, runbook routing, queue/task state, and operator UX.
- OpenCode owns model/runtime execution.
- Direct Codex, Claude, and Gemini adapters remain legacy compatibility until migration tests and docs prove a safe default switch.

## Current Execution Surfaces

| Surface | Current behavior | Execution choice field | Baseline requirement |
| --- | --- | --- | --- |
| `agentctl run` | Loads `agents.yaml`, reads `agents.<name>.tool`, then builds a direct runtime command. | `agents.<name>.tool`, `agents.<name>.model`, optional `--model` | Preserve direct compatibility and report substrate metadata in dry-run/run metadata. |
| `agentctl iterate` | Runs shell check first, then uses the same direct runtime command builder for each failed round. | `agents.<name>.tool`, `agents.<name>.model`, optional `--model`, `fallback_profiles` | Preserve approval and local-workspace safety gates before execution. |
| `agentctl submit` | Appends queue item with agent, mode, goal, cwd/workspace, memory options, check, and max rounds. | Queue item `agent`; later resolved by `run-next`. | Queue schema remains substrate-neutral. |
| `agentctl run-next` | Shells to `agentctl run` or `agentctl iterate` from queued item. | Queue item `agent` plus current `agents.yaml`. | Keep `tasks.jsonl`, `queue.jsonl`, run dirs, stdout/stderr, and metadata intact. |
| `agentd` | Loops over `agentctl run-next`. | None directly. | Must stay dumb; no OpenCode-specific daemon behavior. |
| `agentctl profile run` | Resolves profile/agent/workspace, evaluates guardrails, then delegates to `run`. | Profile `default_agent` or `--agent`; agent `tool`/`model`; optional selected profile tool only affects guardrails. | Profiles/tools stay policy metadata, not model routers. |
| `agentctl profile plan` | Creates plan metadata and subtask queue shape; does not execute runtime directly. | Plan subtask `agent`; later resolved by queue execution. | Keep profile/guardrail metadata above substrate. |
| `assistant-route` | Matches deterministic runbooks and returns typed actions. | No runtime choice. | Must not become a model/runtime router. |
| `assistant-exec` | Executes read-only typed actions or queues run/iterate actions. | Queued action `agent`; later resolved by `run-next`. | Preserve confirmation gates for workspace writes. |
| Telegram bot | Shells to `agentctl` commands for status, queueing, plans, logs, and assistant execution. | No direct runtime choice except submitted agent name. | Telegram remains control/conversation channel, not a direct OpenCode shell. |

## Current Config Fields

`agents.yaml` currently controls direct runtime execution:

- `tools.<tool>.command`: doctor/config compatibility check for direct CLIs.
- `agents.<agent>.tool`: current executable adapter id, usually `codex`, `claude`, or `gemini`.
- `agents.<agent>.model`: model passed to the direct adapter command.
- `agents.<agent>.fallback_profiles`: optional direct-runtime fallback model aliases.
- `agents.<agent>.autonomy`: maps to read-only vs workspace-write command permissions/sandboxing.
- `agents.<agent>.approval_required`: capabilities that must be approved before execution.

Profiles and the tool registry remain policy metadata:

- `profiles.<profile>.default_agent` and `allowed_agents` select eligible agents.
- `profiles.<profile>.allowed_tools` feeds guardrail context and does not select the runtime executable.
- `tools.yaml` describes tool trust, egress, capabilities, and profile scope.

## Phase 0 Baseline Decisions

- Direct `codex`, `claude`, and `gemini` tool values are characterized as `legacy-direct:<tool>`.
- `opencode` is recorded as the intended primary substrate, but defaults are not switched in this slice.
- The intended non-interactive OpenCode command shape is captured as `opencode run --print --model <model> --permission read|edit <prompt>` for Phase 1 fake-executable tests.
- `run` and `iterate` dry-run output now reports `execution_substrate`, `legacy_direct`, and `intended_primary_substrate`.
- Run metadata records the same fields for real executions without changing artifact layout.

## Regression Coverage Added

`tests/test_execution_substrate.py` freezes the first safe slice:

- legacy direct adapter classification for `codex`, `claude`, and `gemini`
- intended OpenCode command construction helper
- unchanged existing direct adapter command shapes
- `agentctl run --dry-run` substrate metadata
- `agentctl inspect` substrate metadata

## Not Done Yet

- No default agent config points at OpenCode yet.
- No direct adapter has been removed, renamed, or hidden.
- Doctor/selftest still check the existing legacy direct runtime environment.
- OpenCode fake executable coverage belongs to Phase 1, after this baseline is accepted.
