# Architecture Pivot Backlog

This folder tracks architecture-pivot planning notes for `docs/adr/0001-opencode-telegram-memory-pivot.md`.

The first pivot baseline is complete. Completed planning notes are archived under `docs/backlog/done/`.

## Current decision

The project is pivoting toward:

```text
human
  <-> Telegram main-agent/persona channel
        <-> runtime-agents control plane
              <-> OpenCode CLI execution substrate
              <-> AMH memory workflow/governance layer
                    <-> AMB governed durable memory substrate
```

## Suspended work

SkillOps Milestone 2P Restore Drill is suspended, not deleted. Revisit it after the pivot tracks reach an initial integrated baseline.

## Current active tracks

None. The initial integrated baseline has landed.

## Completed tracks

- `done/opencode-runtime.md` - OpenCode runtime characterization baseline.
- `done/telegram-main-agent.md` - Telegram assistant UX baseline.
- `done/memory-amh-amb.md` - AMB/AMH memory contract baseline.
- `done/queue-assistant-ux.md` - queue cleanup classification and assistant count clarity.
- `done/docs-roadmap-self-improvement.md` - docs alignment and self-improvement quarantine.

## Worktree convention

Completed branch/worktree names:

```text
track/opencode-runtime
track/telegram-main-agent
track/memory-amh-amb
track/queue-assistant-ux
track/docs-roadmap-self-improvement
```

Each track should start from the current trusted baseline and validate with at least:

```bash
python3 -m unittest discover -s tests
agentctl smoke --json
agentctl doctor --json
agentctl selftest --json
```

Add narrower validation from the individual backlog file.
