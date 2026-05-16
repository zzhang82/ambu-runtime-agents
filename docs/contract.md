# runtime-agents Contract (v1.5.1)

## Commands
- agentctl
- agentd
- agentbot

## Config Paths
- ~/.config/runtime-agents/
- ~/.config/runtime-agents/runbooks/
- ~/.config/runtime-agents/profiles.yaml
- ~/.config/runtime-agents/tools.yaml

## State Paths
- ~/.local/share/runtime-agents/

## Environment Overrides
- RUNTIME_AGENTS_CONFIG_HOME
- RUNTIME_AGENTS_STATE_HOME
- RUNTIME_AGENTS_AGENTCTL_BIN

## Stable JSON Commands
- agentctl version --json
- agentctl smoke --json
- agentctl doctor --json
- agentctl selftest --json
- agentctl telegram-status --json
- agentctl amb-health --json
- agentctl runbook list --json
- agentctl runbook show <runbook_id> --json
- agentctl runbook validate --json
- agentctl runbook validate --strict --json
- agentctl tool list --json
- agentctl tool show <tool_id> --json
- agentctl tool validate --json
- agentctl profile list --json
- agentctl profile show <profile_id> --json
- agentctl profile validate --json
- agentctl profile run <profile_id> <goal...> --dry-run --json
- agentctl profile plan <profile_id> <goal...> --json
- agentctl guardrail list --json
- agentctl guardrail eval --profile <profile_id> --tool <tool_id> --action <action> --json
- agentctl assistant-route <message> --json
- agentctl assistant-exec <message> --json

## Assistant route payload
- `status`: `matched | needs_clarification | unsupported | blocked`
- `runbook_id`: matched runbook identifier or `null`
- `title`: human-readable runbook title
- `risk`: `read_only | workspace_write | blocked`
- `requires_confirmation`: boolean
- `inputs`: extracted typed inputs when matched
- `actions`: rendered typed actions
- `message` or `question`: user-facing explanation

## Assistant execution boundary
- `assistant-exec` delegates typed action execution through `runtime_agents.actions`.
- `assistant-exec` executes matched `read_only` actions directly.
- `assistant-exec` returns `pending_confirmation` for `workspace_write` runbooks.
- `assistant-exec` includes an `action_result` payload that reports executor outcome without replacing the existing route/execution shape.
- Runbooks may only render typed actions from the allowlist.
- Blocked action types include `shell`, `exec`, `bash`, `raw_command`, `python_eval`, and `arbitrary_agentctl`.

## Runbook validation policy
- Normal load skips invalid local runbooks so one bad override does not crash runtime routing.
- `agentctl runbook validate --json` reports `invalid_count`, `skipped_count`, and `warnings` while succeeding when packaged defaults remain valid.
- `agentctl runbook validate --strict --json` fails if any invalid runbook exists.
- `agentctl doctor --json` surfaces runbook loadability and strict-validity checks in the standard flat check list.

## Action result model
- Typed execution is normalized through `ActionResult` with statuses `completed`, `pending_confirmation`, `blocked`, `unsupported`, and `failed`.
- Successful read-only assistant execution preserves the matched route payload and appends `execution` plus `action_result`.
- Non-success executor outcomes change top-level `status` only when execution is actually blocked, unsupported, failed, or awaiting confirmation.

## Boundary Rules
- agentctl owns state, policy, runbook validation, and assistant execution.
- agentd stays dumb.
- agentbot stays thin and shells out to agentctl.
- AMB stays memory authority.
- Packaged runbooks are defaults; config runbooks may override by id but cannot bypass the typed-action allowlist.
- Assistant routing is deterministic and does not use an LLM router.

## Runbook sources
- Packaged defaults: `src/runtime_agents/default_runbooks/`
- Local overrides/extensions: `~/.config/runtime-agents/runbooks/`
- Local config overrides packaged defaults with the same runbook id.

## Allowed assistant action types
- `status_overview`
- `list_workspaces`
- `list_runbooks`
- `list_queue`
- `list_plans`
- `list_schedules`
- `list_profiles`
- `show_profile`
- `list_tools`
- `show_tool`
- `show_task`
- `show_logs`
- `show_plan`
- `submit_run`
- `submit_iterate`
- `create_plan`
- `profile_run`
- `profile_plan`
- `repair_plan`
- `retry_plan_subtask`
- `retry_schedule`
- `pause`
- `resume`

## Guardrail metadata contract
- `context_state` is derived from declared profile/tool/action metadata in v1.5.0.
- `context_state` includes profile, workspace, aggregated data classes, capabilities, `tools_considered`, and explicit `tool_trace` only for selected tools.
- `policy_decisions` is the stable serialized field name for guardrail decisions.
- Guardrail decision priority is deterministic: `block` > `approval_required` > `allow`.
- Unknown tools and tools outside `profile.allowed_tools` are blocked.
- v1.5.0 does not yet track arbitrary tool-result trust propagation or live content flow during execution.

## Version contract
- `agentctl version --json` reports the installed `runtime-agents` package version.
- `agentctl version --json` reports contract `agentctl-v1.5.1`.
- The repo source is the authority for installed `agentctl` and `agentbot` behavior.
- Config-home `VERSION` may exist for local runtime metadata, but it is not the public release version source of truth.
