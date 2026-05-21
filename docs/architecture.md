# Architecture (v1.5.1)

runtime-agents is a local personal-agent control plane with deterministic assistant routing.

## Components

agentctl:
- owns the CLI contract
- owns state, policy, runbook validation, profile/tool validation, and assistant execution
- loads packaged default runbooks and config override runbooks
- loads packaged and config profile/tool registries
- routes through runbooks and delegates typed execution to `runtime_agents.actions`
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
- governed durable memory substrate
- MCP-compatible recall/writeback storage path

AMH:
- optional memory workflow and governance layer around AMB
- owns packet compilation, failure tracking, readiness checks, belief proposals, promotion workflows, and future adapter contracts
- must degrade safely when unavailable; current direct AMB recall/writeback remains the compatibility path while adapters mature

## Runbook routing model

Runbooks are declarative Markdown files with YAML frontmatter.

Sources:
- packaged defaults: `src/runtime_agents/default_runbooks/`
- local overrides/extensions: `~/.config/runtime-agents/runbooks/`

Loading rules:
- packaged runbooks load first
- local config runbooks override packaged runbooks by `id`
- invalid local runbooks are skipped during normal runtime load and surfaced by validation/doctor
- packaged runbook breakage is always treated as invalid
- action types are restricted to a typed allowlist
- blocked action types are rejected during validation
- strict validation fails if any invalid runbook exists

Validation surfaces:
- `agentctl runbook validate --json` reports invalid/skipped runbooks additively
- `agentctl runbook validate --strict --json` fails on any invalid runbook
- `agentctl doctor --json` exposes runbook health as flat checks

Matching rules:
- routing is deterministic phrase matching only
- placeholders are typed (`workspace`, `task_id`, `plan_id`, `schedule`, `id`, `text`)
- missing required inputs return `needs_clarification`
- dangerous phrases are blocked before runbook matching

## Profile and tool metadata layer

Profiles and tools are now first-class metadata surfaces.

Profiles:
- live in `profiles.yaml`
- reference agents, workspaces, memory namespaces, and allowed tool ids
- expose assistant-facing defaults for run and plan goals

Tools:
- live in `tools.yaml`
- describe local tool metadata such as trust level, egress label, capabilities, and profile scope

Release boundary for v1.5.1:
- profiles/tools remain the metadata source of truth
- `runtime_agents.guardrails` derives `context_state` from declared profile/tool/action metadata
- profile-aware CLI and action execution now emit auditable `policy_decisions`
- guardrail evaluation is deterministic and metadata-derived, not a full runtime content-flow tracker
- live tool-result trust propagation and deeper egress inspection are still future work

## Assistant execution model

`assistant-route`:
- normalizes the message
- applies the narrow dangerous-pattern block layer
- matches a runbook
- returns structured routing output

`assistant-exec`:
- parses and routes in `cli.py`
- delegates typed action execution to `runtime_agents.actions`
- executes matched `read_only` actions directly
- returns `pending_confirmation` for `workspace_write` actions
- keeps execution bounded to the typed action allowlist
- normalizes execution outcomes through `ActionResult`

This keeps routing data-driven while preserving a hard safety boundary around execution and a single executor boundary for future policy interception.

## Executor boundary

`runtime_agents.actions`:
- owns the typed action allowlist execution path
- returns explicit `ActionResult` values for success, confirmation, block, unsupported, and failure states
- uses dependency injection from `cli.py` so execution can be tested without coupling routing to CLI globals

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
- repo files, git history, tests, manifests, and release artifacts remain implementation and release authority over memory context
- AMB memory is context and governed durable storage, not release proof by itself
- AMH must not become a second durable memory store over AMB

## Release boundary
- v1.2.0 introduced the extracted control modules and initial runbook surface
- v1.3.x made runbooks the routing source of truth and extracted typed assistant execution
- v1.4.0 adds first-class profile and tool metadata surfaces
- v1.5.1 keeps the v1.5 guardrail and metadata architecture while adding queue lifecycle cleanup as a narrow operational release
- future releases can extend this with live tool-result trust propagation rather than reintroducing hardcoded intent branches
