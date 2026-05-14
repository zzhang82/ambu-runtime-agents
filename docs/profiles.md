# Profiles (v1.4.0)

Profiles are the domain boundary for assistant-facing work in runtime-agents.

## Config path
- `~/.config/runtime-agents/profiles.yaml`

## Purpose
A profile binds together:
- default agent
- allowed agents
- allowed tool ids
- optional pinned workspace
- optional memory namespace
- capability metadata for blocked/approval-required categories
- default run and plan goals

This release is metadata-first:
- profiles are visible, loadable, and validatable
- profile-aware commands and runbooks resolve profile metadata
- runtime trust propagation and context-aware tool guardrails are not enforced yet

## Commands
- `agentctl profile list --json`
- `agentctl profile show <id> --json`
- `agentctl profile validate --json`
- `agentctl profile run <profile> [--workspace <ws>] [--agent <agent>] <goal...> --dry-run --json`
- `agentctl profile plan <profile> [--workspace <ws>] [--agent <agent>] <goal...> --json`

## Validation rules
- `default_agent` must exist in `agents.yaml`
- every `allowed_agents` entry must exist in `agents.yaml`
- `default_agent` must be included in `allowed_agents`
- `allowed_tools` must reference known tool ids
- pinned `workspace` must reference a known workspace when set
- `blocked_capabilities` and `approval_required` must use known capability names

## Notes
- `--agent` overrides are only accepted when the agent is included in `allowed_agents`
- `profile run --dry-run` is the minimum safe verification path for this release
