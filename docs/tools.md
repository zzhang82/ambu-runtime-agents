# Local Tool Registry (v1.4.0)

Tools are first-class local metadata entries in runtime-agents.

## Config path
- `~/.config/runtime-agents/tools.yaml`

## Purpose
The local tool registry describes tool metadata such as:
- title and description
- kind
- enabled state
- command and args
- trust level
- data classes
- egress label
- capabilities
- workspace scope
- optional profile scope

This release is metadata-first:
- tools are visible, loadable, and validatable
- profiles can reference tool ids
- runtime egress enforcement and trust propagation are not enforced yet

## Commands
- `agentctl tool list --json`
- `agentctl tool show <id> --json`
- `agentctl tool validate --json`

## Validation rules
- tool definitions must be well-formed mappings
- capabilities must be known capability names or approved local-tool capability labels
- `enabled` defaults to `true` when omitted
- `profile_scope` is metadata-only in v1.4.0

## Notes
- `tools.yaml` is separate from `agents.yaml`
- `agents.yaml` remains the executable agent registry
