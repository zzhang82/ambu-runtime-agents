# Architecture (v1.3.0)

runtime-agents is a local personal-agent control plane with deterministic assistant routing.

## Components

agentctl:
- owns the CLI contract
- owns state, policy, runbook validation, and assistant execution
- loads packaged default runbooks and config override runbooks
- renders typed actions from matched runbooks
- is the source of truth for installed `agentctl` and `agentbot` behavior

agentd:
- dumb worker loop
- equivalent to `run-next` in a loop
- no routing or policy logic

agentbot:
- thin Telegram control plane
- shells out to `agentctl assistant-route` and `agentctl assistant-exec`
- keeps only lightweight session/confirmation state
- no arbitrary shell

AMB:
- memory authority
- recall/writeback via MCP stdio

## Runbook routing model

Runbooks are declarative Markdown files with YAML frontmatter.

Sources:
- packaged defaults: `src/runtime_agents/default_runbooks/`
- local overrides/extensions: `~/.config/runtime-agents/runbooks/`

Loading rules:
- packaged runbooks load first
- local config runbooks override packaged runbooks by `id`
- all runbooks must pass schema validation before use
- action types are restricted to a typed allowlist
- blocked action types are rejected during validation

Matching rules:
- routing is deterministic phrase matching only
- placeholders are typed (`workspace`, `task_id`, `plan_id`, `schedule`, `id`, `text`)
- missing required inputs return `needs_clarification`
- dangerous phrases are blocked before runbook matching

## Assistant execution model

`assistant-route`:
- normalizes the message
- applies the narrow dangerous-pattern block layer
- matches a runbook
- returns structured routing output

`assistant-exec`:
- executes matched `read_only` actions directly
- returns `pending_confirmation` for `workspace_write` actions
- keeps execution bounded to the typed action allowlist

This keeps routing data-driven while preserving a hard safety boundary around execution.

## Current state artifacts
- tasks.jsonl
- queue.jsonl
- schedules.jsonl
- plans/
- runs/
- telegram.sessions.json

## Design constraints
- no LLM router
- no arbitrary shell or Python embedded in runbooks
- no Telegram-specific business logic duplication
- no local runbook bypass of the action allowlist
- repo source must remain the authority for installed entrypoints

## Release boundary
- v1.2.0 introduced the extracted control modules and initial runbook surface
- v1.3.0 makes runbooks the routing source of truth
- future releases should extend typed actions and packaged runbooks rather than reintroducing hardcoded intent branches
