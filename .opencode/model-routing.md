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

Each subagent should use `skillops-mentor` as a routing preflight before choosing deeper skills. The preflight must scan the skill registry rather than loading all skills, then name any primary/supporting skill it actually needs.

Subagent SkillOps preflight prompt:

```text
Use skillops-mentor first. Run the registry scan. Choose only the minimum skills needed for this track. Do not load every skill. Do not use deprecated skills. If the task is implementation, prefer repo/source inspection and tests over skill memory. If the task mutates files, state the approval/validation path.
```

Required review checks:

- aligns with ADR 0001
- does not revive direct multi-runtime expansion as primary direction
- does not bypass Telegram/agentctl/OpenCode safety boundaries
- does not make AMH a second memory store over AMB
- includes facts/evidence, requirements, non-goals, risks, validation, and dependencies
- avoids implementation changes unless explicitly assigned to a feature worktree

## Fallback

If model-specific routing is needed later, update this file and verify the provider config before adding any hard OpenCode config. GPT-5.5/Cole remains reserved for synthesis, final decisions, and validation review.
