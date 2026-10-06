# Runtime Agents Design Draft

## What this is

This document captures the intended direction for `runtime-agents` after the current `v1.1.0` control-plane MVP. The goal is to make the next stages legible before we start refactoring code or adding major features.

The system already has real value: `agentctl` can run named agents, manage queue and plan state, schedule work, integrate with AMB, and expose a thin Telegram control surface. What it does not have yet is a clean source layout, a stable regression harness, profile-scoped tool governance, or a durable path from one-off tasks to reusable workflows.

This draft defines the target shape, the boundaries that should not move, and the staged roadmap to get there.

## Current state

Current live state:

```text
runtime-agents v1.1.0
live as user-level scripts/config/state
agentctl is still mostly a monolithic script
assistant-route exists but is brittle and rule-based
agentd is dumb by design
agentbot is thin by design
AMB integration is healthy
```

Today the live system is installed as:

```text
~/.local/bin/agentctl
~/.local/bin/agentd
~/.local/bin/agentbot
~/.config/runtime-agents/
~/.local/share/runtime-agents/
```

That was fine for the prototype. It is no longer a good long-term development model.

## North star

Build a local-first personal agent operating layer.

The product promise is simple:

```text
A personal local agent system that remembers, plans, executes, watches, learns, and improves without becoming an uncontrolled black box.
```

A successful version of this system should let the user say things like:

```text
check my NAS
watch Mac mini refurb
keep an eye on this repo
fix project health
summarize what needs attention
learn from yesterday’s work
create a reusable workflow from what worked
```

Under the hood, the system should translate that into a bounded execution path:

```text
profile -> policy/tool registry -> plan/schedule/watcher -> agentd execution
-> summaries -> memory candidates -> approved AMB writeback
-> learning session -> workflow/skill improvement
```

## Core architecture principle

Keep the boundaries sharp.

```text
agentctl
  owns contract, policy, state, queue, plans, schedules, profiles, watchers

agentd
  dumb worker loop
  no routing, no policy reimplementation, no planning

agentbot
  thin reception and notification layer
  no arbitrary shell
  no internal agentctl imports
  no independent orchestration

AMB
  memory authority
  durable learn/gotcha/procedure/domain records
  not a scheduler or worker runtime

OpenCode / Claude Code / Codex / Gemini
  development cockpit + backend workers
  not the product control layer

profiles
  domain-specific assistants with scoped tools, memory, and policy

runbooks
  bridge between human phrases and safe agentctl actions

skills and workflows
  reusable behavior layer
  tested and approved before trusted use
```

This is the main discipline for the project. If these boundaries blur, the system will become harder to trust and harder to evolve.

## Design assumptions

### AMB is the memory authority

AMB is the right place for durable memory. It already has the right shape for decisions, gotchas, procedures, domain notes, and signals. `runtime-agents` should consume and propose memory, not replace AMB.

The runtime side should treat memory as part of the operating loop:

```text
recall -> execute -> summarize -> propose -> approve -> write back
```

Writeback should stay explicit. The system should not automatically dump large summaries into memory.

### Tool governance has to be enforced, not implied

Once the system can combine private data, untrusted web input, and external notifications, prompt-only safety is not enough. The runtime needs local policy enforcement before tools or notifications leave the control layer.

The project should move toward context-aware tool governance with explicit trust levels, data classes, and approval boundaries.

### Natural language should map to runbooks, not raw freedom

The assistant surface should feel natural, but the execution layer should stay narrow. The right pattern is:

```text
human phrase -> runbook match -> structured intent -> allowlisted action
```

The system should not jump from a chat message directly to arbitrary model-driven orchestration.

## Product stage

The current system is best described as:

```text
runtime-agents v1.1.0
local personal-agent control-plane MVP
```

It already has:

```text
agentctl contract
agentd dumb daemon
agentbot thin Telegram layer
queue
schedules
plans
plan retry/skip/repair
summaries
AMB recall/writeback
assistant-route MVP
policy gates
append-oriented state
```

It is not yet:

```text
repo-backed packaged project
profile-driven
tool-governed
watcher-capable
self-learning
skill/workflow evolving
natural assistant ready
```

## Roadmap

The roadmap should stay staged. Each phase should leave the system cleaner and more testable than the one before it.

```text
v1.1.1  Repo + packaging + regression harness
v1.2.0  Runbook-driven assistant router
v1.3.0  Agent Profiles + Local Tool Registry
v1.4.0  Context-aware Tool Guardrails
v1.5.0  Learning Sessions
v1.6.0  Skills + Workflows
v1.7.0  Watchers
v1.8.0  Home NAS Assistant vertical slice
v1.9.0  Shopping / restock watcher vertical slice
v2.0.0  Reception layer / natural assistant UX
v2.1.0  Market research swarm, alerts only
```

The order matters. Do not skip ahead to a natural Telegram assistant or market workflows before the repo, router, profile, and guardrail layers exist.

## Immediate milestone: v1.1.1 repo and regression stabilization

### Goal

Turn the current user-level installation into a reproducible, version-controlled, installable project without changing behavior.

### Why now

The system is already important enough that loose scripts in `~/.local/bin` are becoming a liability. We need a repo, package layout, install path, and regression tests before larger architectural work.

### Target repo shape

```text
runtime-agents/
  pyproject.toml
  README.md
  CHANGELOG.md
  src/runtime_agents/
    cli.py
    daemon.py
    telegram_bot.py
    amb_adapter.py
    config.py
    state.py
    policy.py
    queue.py
    schedules.py
    plans.py
    memory.py
    assistant_router.py
  tests/
  scripts/
  examples/
  docs/
```

Installed entrypoints remain:

```text
agentctl
agentd
agentbot
```

Live config and state remain outside the repo:

```text
~/.config/runtime-agents/
~/.local/share/runtime-agents/
```

### Migration rules

- First move should be mostly mechanical.
- Do not rewrite architecture during the extraction.
- Preserve config and state paths.
- Preserve CLI behavior unless a test exposes a real bug.
- Keep `agentd` dumb.
- Keep `agentbot` thin.

### Required work

1. Snapshot the live system.
2. Create the repo.
3. Move code into package layout with minimal logic change.
4. Add Python entrypoints.
5. Add editable install.
6. Add smoke tests and a regression harness.
7. Prove the installed package still passes the existing checks.

### Acceptance

These commands must pass after migration:

```bash
agentctl version --json
agentctl doctor
agentctl selftest
agentctl amb-health --json
agentctl telegram-status --json
```

And validation should end with no pending or running queue items.

## Next milestone: v1.2.0 runbook-driven assistant router

### Why

The current `assistant-route` is brittle because it is hardcoded and phrase-matched. It already misread at least one intent. That is a sign to replace ad hoc routing with a runbook model before natural-language usage expands.

### End state

```text
assistant message
  -> runbook matcher
  -> structured intent
  -> allowlisted action
  -> optional confirmation
  -> agentctl command
```

### Shape

Runbooks should live outside code so the behavior is inspectable and editable:

```text
~/.config/runtime-agents/runbooks/
```

A runbook should define:

- identity
- phrase patterns
- inputs
- risk level
- confirmation requirement
- action template
- success response template

### Acceptance

Examples that should work:

```text
what needs attention?
check workspace test-ws
fix tests in test-ws
repair it
show logs
```

The router must never become an arbitrary shell bridge.

## Profiles and tool registry

### Why

The future system needs domain-specific operating boundaries such as:

```text
home-nas
shopping-watch
market-research
runtime-dev
```

An agent is a role and tool/model choice. A profile is a domain boundary with scoped tools, memory namespace, approval rules, and notifications.

### Profile responsibilities

A profile should resolve:

```text
profile -> workspace -> memory namespace -> default agent -> allowed tools -> policy
```

### Tool registry responsibilities

The tool registry should record:

- tool kind
- trust level
- data classes
- egress type
- capability tags
- profile scope

This becomes the base for later guardrail decisions.

## Context-aware tool guardrails

### Why

Static capability gates are not enough once the system can combine:

- untrusted web content
- private local data
- external notifications

The runtime should track context state and make policy decisions using current execution context, not just command names.

### Minimum guardrail model

Track:

- whether untrusted input was seen
- whether private data was accessed
- whether external egress is requested
- which data classes are present
- which tool results are trusted, untrusted, sensitive, or blocked

Policy output should stay simple:

```text
allow
block
approval_required
quarantine
```

### Important rule

Untrusted input plus private data plus external send is a red-flag combination. The system should explicitly guard that path.

## Learning sessions

### Why

Learning should begin as a structured review loop, not as self-modifying automation.

The runtime should inspect recent work, summaries, failures, and memory candidates, then propose compact durable learnings for approval. It should not silently rewrite its own behavior or flood AMB.

### Learning session output

A learning session should produce:

- report
- proposed promotions
- proposed procedures
- proposed skills
- writeback receipts

### Rule

No automatic durable writeback without approval.

## Skills and workflows

These should remain separate from memory.

- **AMB procedure memory** stores durable how-to knowledge.
- **Workflow templates** define repeatable structured steps.
- **Skills** are executable implementations with tests and review.

The important rule is that executable behavior must be tested and approved before it becomes trusted.

## Watchers

### Why

Schedules are time-based. Watchers are state-change based.

The product direction includes practical watcher use cases:

```text
Mac mini refurb availability
Supreme restock
NAS disk threshold
backup stale state
market watchlist alerts
```

### Watcher requirements

A watcher needs:

- target
- interval
- extractor
- last state hash
- dedupe
- severity
- evidence snapshot
- notification policy

The system should notify on change, not on every poll.

## Vertical slices

### First vertical slice: Home NAS assistant

This is the best first proof because it is bounded, practical, and exercises nearly every core layer:

- profile
- tools
- schedules
- watchers
- summaries
- learning
- notifications
- repair plans

The first version should stay read-only by default and require approval for service restart, config changes, installs, deletes, and reboot.

### Second vertical slice: Shopping and restock watcher

This should remain notification-only.

Hard boundaries:

- no auto-purchase
- no credential use by default
- no CAPTCHA bypass
- no checkout flow

The point is safe structured alerting, not automation theater.

## Non-goals for now

Do not build these yet:

```text
Kubernetes orchestration
enterprise MCP registry
multi-user team dashboard
real-money autonomous trading
auto-buy restock bot
auto-approved generated skills
agentd planning logic
Telegram arbitrary shell
memory dumping of every chat
direct SQLite edits to AMB
```

These are either the wrong scale, the wrong risk level, or too early for the current architecture stage.

## Cross-cutting requirements

A few concerns apply across all milestones.

### Observability

The system should expose stats for task counts, success rate, durations, failure classes, model/tool use, memory recalls, writebacks, watcher checks, dedupe suppressions, and notifications.

### Cost control

Budgets should exist before watcher-heavy or research-heavy profiles become common.

### Secrets

Config should reference secrets indirectly. Secret material should not live inline in normal YAML where avoidable.

### Redaction

Anything sent externally, especially to Telegram, should be summarized and redacted first when private data or logs are involved.

### Backup and recovery

The runtime should eventually support backup and dry-run restore of config and state.

## Priority order

This is the working priority order:

```text
1. Repo/package/test stabilization
2. Runbook-driven assistant router
3. Agent Profiles + Tool Registry
4. Context-aware guardrails
5. Learning sessions
6. Skills/workflows
7. Watchers
8. Home NAS vertical slice
9. Shopping watcher vertical slice
10. Assistant UX polish
11. Market research alerts
```

If we keep this order, each phase builds on a stable base. If we skip around, we will end up debugging product behavior and platform behavior at the same time.

## Bottom line

`runtime-agents` should become a local-first personal agent operating system with bounded execution and explicit governance.

The key idea is not to make it more magical. The key idea is to make it more reusable without losing control.

That means:

- source-controlled code
- stable contract
- explicit profiles
- governed tools
- bounded plans, schedules, and watchers
- AMB-backed learning
- tested workflows and skills
- natural-language entry only after the action layer is trustworthy
