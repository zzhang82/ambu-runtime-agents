# runtime-agents Contract (v1.3.0)

## Commands
- agentctl
- agentd
- agentbot

## Config Paths
- ~/.config/runtime-agents/
- ~/.config/runtime-agents/runbooks/

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
- `assistant-exec` executes matched `read_only` actions directly.
- `assistant-exec` returns `pending_confirmation` for `workspace_write` runbooks.
- Runbooks may only render typed actions from the allowlist.
- Blocked action types include `shell`, `exec`, `bash`, `raw_command`, `python_eval`, and `arbitrary_agentctl`.

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
- `show_task`
- `show_logs`
- `show_plan`
- `submit_run`
- `submit_iterate`
- `create_plan`
- `repair_plan`
- `retry_plan_subtask`
- `retry_schedule`
- `pause`
- `resume`

## Version contract
- `agentctl version --json` reports contract `agentctl-v1.3.0`.
- The repo source is the authority for installed `agentctl` and `agentbot` behavior.
