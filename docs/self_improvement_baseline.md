# Self-Improvement Quarantine Baseline

## Status

`runtime-agents v1.5.1` / `agentctl-v1.5.1` is the trusted release baseline.

`self_improvement/runtime-self-improve.py` is experimental/quarantined prototype material under ADR 0001. It is retained for design evidence, but it is not part of the stable `agentctl` contract and should not be treated as the next release boundary.

ADR source of truth: `docs/adr/0001-opencode-telegram-memory-pivot.md`.

## What Is Quarantined

The prototype includes multi-runtime and SkillOps surfaces that predate the ADR 0001 pivot:

- historical ingestion concepts for OpenCode, direct provider CLIs, and runtime-agents
- scan/suggest/recommend/cluster-style learning workflow concepts
- SkillOps staging, approvals, lifecycle, eval, deploy, lock, rollback, and restore concepts
- scheduler paths for recurring self-improvement work
- backup/NAS paths for skill-store recovery experiments

These ideas may be mined later, but only after a future ADR or explicit promotion checkpoint decides what belongs in the product.

## ADR 0001 Alignment

Current architecture direction:

- `runtime-agents` owns orchestration, policy, queue/task state, and operator UX
- OpenCode owns model/runtime execution
- Telegram evolves toward the main human-facing agent/persona channel
- AMB remains the governed durable memory substrate
- Agent-Memory-Harness becomes the workflow/governance layer around AMB

Direct provider-specific runtime adapters should not expand as the primary architecture path unless OpenCode cannot expose a required capability and a future decision records that exception.

## Command Risk Categories

Lower-risk inspection/read-only examples:

- `scan`
- `suggest`
- `recommend`
- `skills verify`
- `backup status`
- `scheduler status`
- `scheduler logs`

Local event/state writes:

- `ingest`
- commands that write `AgentRunEvent` records or staging proposals

Global skill-store mutation:

- `approvals apply`
- skill deployment, lifecycle state changes, lock updates, and controlled apply paths

Scheduler mutation:

- `scheduler run-once`
- `schedule run`
- commands that update scheduler state or create future automation residue

Backup/NAS mutation:

- `backup create`
- backup restore/verify workflows that touch backup destinations

Rollback mutation:

- `rollback apply`
- restore operations that rewrite files or lock state

## State Paths To Treat Carefully

- `~/.runtime-agents/events/agent-runs.jsonl`
- `~/.runtime-agents/staging/`
- `~/.runtime-agents/approvals/`
- `~/.runtime-agents/scheduler/`
- `~/.config/opencode/skills/`
- `/mnt/r/LLMData/SkillsBackUp/`

## Validation Rule

Docs-only changes may validate stable product surfaces with:

```bash
python3 -m unittest discover -s tests
agentctl smoke --json
agentctl doctor --json
agentctl selftest --json
```

Do not run mutating prototype commands during this quarantine track unless explicitly approved.
