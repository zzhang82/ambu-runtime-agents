# Guardrails (v1.5.1)

`runtime-agents` v1.5.1 continues the metadata-derived context-aware guardrail layer introduced in v1.5.0.

## Scope

The v1.5 guardrail layer answers:
- what profile is this action running under?
- which tools were considered?
- which explicit tool was selected, if any?
- what trust level, data classes, egress, and capabilities are declared?
- is the request allowed, blocked, or approval-required?
- why?

This release does **not** yet track arbitrary tool result flows or live untrusted content propagation during execution.

## Core metadata

Serialized outputs use:
- `context_state`
- `policy_decisions`

`context_state` is derived from declared profile/tool/action metadata:
- profile
- workspace
- selected tool metadata
- tools_considered
- tool trust_level
- tool data_classes
- tool egress
- tool capabilities
- profile blocked_capabilities
- profile approval_required
- action type

## Built-in rules

v1.5.0 includes deterministic built-in rules for:
- blocking arbitrary shell and raw execution action types
- blocking unknown tools
- blocking tools outside profile `allowed_tools`
- blocking disabled tools
- blocking broker/order capabilities
- blocking purchase/checkout capabilities
- blocking untrusted + private + external send
- requiring approval for private external summaries
- blocking capabilities in `profile.blocked_capabilities`
- requiring approval for capabilities in `profile.approval_required`

Decision priority is deterministic:
- `block`
- `approval_required`
- `allow`

## CLI

- `agentctl guardrail list --json`
- `agentctl guardrail eval --profile <profile> --tool <tool> --action <action> --json`
- `agentctl profile run <profile> ... --dry-run --json`
- `agentctl profile plan <profile> ... --json`

## Example

An allow result returns the resolved decision plus `context_state` and `policy_decisions`.
A blocked result returns the same metadata with `decision: block` and the primary `rule_id`/`reason`.
