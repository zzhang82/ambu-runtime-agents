# Project Model Routing Policy

## Purpose

This project-local routing file overrides the global Goal Runner routing for the architecture-pivot planning phase.

The main Goal Runner owns final decisions, patches, validation, commits, and `.opencode/goal-progress.md`. Subagents provide bounded evidence or draft plans only.

## Pivot Planning Route

For independent backlog-planning and implementation work under `docs/backlog/`, use the default available subagent model unless a future task explicitly requests model binding.

Current session note: do not create a hard `opencode.json` provider/model override for these worktrees. Use default subagent routing and keep the main Goal Runner responsible for final review.

## Backlog Tracks

Use default subagent routing for first-pass drafts and bounded implementation on these independent tracks:

- `track/opencode-runtime`
- `track/telegram-main-agent`
- `track/memory-amh-amb`
- `track/queue-assistant-ux`
- `track/docs-roadmap-self-improvement`

## Review Rule

Each subagent draft must be reviewed by the main Goal Runner before it becomes accepted repo guidance.

Required review checks:

- aligns with ADR 0001
- does not revive direct multi-runtime expansion as primary direction
- does not bypass Telegram/agentctl/OpenCode safety boundaries
- does not make AMH a second memory store over AMB
- includes facts/evidence, requirements, non-goals, risks, validation, and dependencies
- avoids implementation changes unless explicitly assigned to a feature worktree

## Fallback

If model-specific routing is needed later, update this file and verify the provider config before adding any hard OpenCode config. GPT-5.5/Cole remains reserved for synthesis, final decisions, and validation review.
