# Architecture Pivot Backlog

This folder contains implementation-ready planning notes for the accepted architecture pivot in `docs/adr/0001-opencode-telegram-memory-pivot.md`.

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

## Tracks

- `opencode-runtime.md` - make OpenCode the explicit execution substrate.
- `telegram-main-agent.md` - evolve Telegram from command wrapper to main-agent channel.
- `memory-amh-amb.md` - define AMB/AMH/runtime memory boundaries.
- `queue-assistant-ux.md` - improve queue hygiene and assistant/operator scanability.
- `docs-roadmap-self-improvement.md` - quarantine old self-improvement work and align docs.

## Worktree convention

Suggested branch/worktree names:

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
