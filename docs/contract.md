# runtime-agents Contract (v1.2.0)

## Commands
- agentctl
- agentd
- agentbot

## Config Paths
- ~/.config/runtime-agents/

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

## Boundary Rules
- agentctl owns state and policy.
- agentd stays dumb.
- agentbot stays thin.
- AMB stays memory authority.
