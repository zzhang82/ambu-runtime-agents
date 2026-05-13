# Architecture

runtime-agents is a local personal-agent control plane.

## Components

agentctl:
- owns CLI contract
- owns policy
- owns task/queue/schedule/plan state
- calls local runtime agents

agentd:
- dumb worker loop
- equivalent to run-next in a loop
- no routing or policy logic

agentbot:
- thin Telegram control plane
- calls agentctl subprocess
- no arbitrary shell
- no internal imports

AMB:
- memory authority
- recall/writeback via MCP stdio

## Current state artifacts
- tasks.jsonl
- queue.jsonl
- schedules.jsonl
- plans/
- runs/
