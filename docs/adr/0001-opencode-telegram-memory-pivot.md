# ADR 0001: OpenCode Execution, Telegram Main-Agent Loop, and Memory Harness Backbone

## Status

Accepted

## Date

2026-05-21

## Context

`runtime-agents` reached a trusted `v1.5.1` baseline after reconciling version drift and completing an initial burn-in pass.

The current repo used to contain earlier experimental `v1.6`-style self-improvement work:

- multi-runtime event ingestion for OpenCode, direct provider CLIs, and runtime-agents
- scheduling / scheduler commands for self-improvement scans
- SkillOps governance, lifecycle, eval, backup, and restore concepts

This work was useful context, but it also created architectural pressure. The project had to balance several direct runtime integrations, each with different log formats, model semantics, permissions, and fidelity levels. That made the system heavier than the actual product goal.

The product direction is shifting toward a simpler layered architecture:

```text
human
  <-> Telegram main agent / persona channel
        <-> runtime-agents control plane
              <-> opencode CLI execution substrate
              <-> AMH memory workflow / governance layer
                    <-> AMB governed durable memory substrate
```

The desired system is a persistent agent loop, not only a local CLI toolkit. Telegram is the practical always-on human channel. OpenCode already provides multi-model execution support, so `runtime-agents` does not need to directly balance provider-specific runtimes as first-class execution backends.

AMB is expected to remain the governed durable memory substrate for identity, persona, policy, belief records, signals, handoffs, and MCP-compatible memory access. Agent-Memory-Harness is expected to become the workflow and governance layer around AMB: packet compilation, failure tracking, readiness checks, belief proposals, promotion pipelines, and future adapter contracts.

## Decision

Adopt the following direction for future work.

### 1. Standardize execution on OpenCode CLI

`runtime-agents` should treat OpenCode CLI as the primary execution substrate.

```text
runtime-agents owns orchestration and policy.
opencode owns model/runtime execution.
```

Direct provider-specific runtime adapters are not the main architectural direction. If a model/provider needs to be used, route it through OpenCode first.

Direct runtime integration may still be considered later only when OpenCode cannot expose a required capability.

### 2. Promote Telegram from control wrapper to main-agent channel

Telegram should become the main human-facing agent loop:

```text
human
  <-> main agent/persona over Telegram
        -> delegates bounded work to subagents
        -> receives subagent feedback
        -> summarizes, asks, routes, and decides with the human
```

This does not mean Telegram can run arbitrary shell commands. The safety boundary remains:

- Telegram channels intent and confirmations
- `agentctl` validates, routes, and records actions
- OpenCode executes bounded tasks
- policy/guardrail checks stay explicit

The desired change is product shape: Telegram becomes the persistent conversation and channelling layer, not just a list of slash commands.

### 3. Treat AMB as substrate and Agent-Memory-Harness as workflow layer

AMB should remain the governed durable memory substrate.

AMB owns:

- durable governed memory records
- identity / persona / core policy / belief records
- signals and handoff state
- MCP-compatible source-of-truth storage and retrieval

Agent-Memory-Harness should own the operating workflow around AMB.

AMH owns:

- startup, task, and handoff packet compilation
- failure tracking
- runtime readiness and evidence checks
- belief governance proposals
- memory promotion / demotion pipelines
- future runtime adapter contracts

Runtime-agents should consume AMH workflows when available while preserving current AMB compatibility paths until AMH adapters are mature.

### 4. Reclassify multi-runtime self-improvement as experimental

The existing self-improvement / SkillOps work in the repo is not the next trusted release boundary by default.

It should be treated as experimental material that can be mined for ideas, especially:

- learning sessions
- skill candidate detection
- skill lifecycle concepts
- backup / restore safety

But the core roadmap should not continue to expand the old multi-runtime adapter model without an explicit decision.

## Consequences

### Benefits

- Reduces runtime integration overhead.
- Lets OpenCode handle multi-model/provider complexity.
- Makes Telegram the real always-on runtime loop instead of a sidecar bot.
- Gives AMB and Agent-Memory-Harness clear non-overlapping roles.
- Keeps `runtime-agents` focused on orchestration, policy, queue/task state, and operator UX.

### Costs

- Existing README/self-improvement docs describe an older multi-runtime direction and need follow-up cleanup.
- The active Goal Mode objective, SkillOps Milestone 2P Restore Drill, may need to be reaffirmed or superseded.
- Some existing self-improvement scheduler and adapter code may become deprecated or moved behind an experimental boundary.
- Telegram design must avoid becoming an unsafe arbitrary command channel.

### Risks

- Moving too fast on Telegram could bypass the guardrail model if the command/execution boundary is not kept explicit.
- Dropping direct runtime adapters could lose useful telemetry until OpenCode exposes equivalent data.
- Memory responsibilities could become confused unless AMB substrate, AMH workflow/governance, and runtime local state are clearly separated.

## Immediate Implications

The current Goal Mode objective is suspended:

```text
SkillOps Milestone 2P - Restore Drill
```

Reason:

- The architecture is pivoting away from expanding the old multi-runtime SkillOps path.
- The restore drill is still valuable, but it should not block the OpenCode / Telegram / Memory Harness tracks.
- The restore drill should be revisited after the pivot tracks clarify which SkillOps backup/restore surfaces remain relevant.

Revisit condition:

```text
Revisit Milestone 2P after the OpenCode runtime, Telegram main-agent, Memory Harness, self-improvement-experimental, and docs-roadmap tracks reach an initial integrated baseline.
```

Rejected alternatives:

1. **Finish 2P first**: rejected for now because it would spend more time proving recovery for a subsystem that may be reshaped by the pivot.
2. **Delete 2P entirely**: rejected because backup/restore safety remains important and should be revisited once the new architecture stabilizes.

No implementation track should treat the old SkillOps backup/restore design as final until this revisit happens.

## Implementation Status

The initial integrated pivot baseline has landed.

Completed tracks:

```text
track/memory-amh-amb
  -> merged as 5a86920 Document AMB and AMH memory contract
  -> added docs/memory-amh-amb-contract.md and reconciled architecture/contract terminology

track/opencode-runtime
  -> merged as 5025474 Characterize OpenCode runtime substrate
  -> characterized old direct adapters and recorded OpenCode as intended substrate

direct runtime cleanup
  -> removed live direct provider CLI execution and self-improvement ingestion adapters after the initial baseline
  -> OpenCode is now the supported live execution substrate

track/docs-roadmap-self-improvement
  -> merged as 5686e5c Quarantine self-improvement prototype in docs
  -> aligned README/CHANGELOG/docs with ADR 0001 and quarantined old self-improvement work

track/queue-assistant-ux
  -> merged as 433438b Clarify queue cleanup and assistant counts
  -> added structured validation-artifact classification and assistant typed counts

track/telegram-main-agent
  -> merged as 0ab4769 Improve Telegram assistant baseline UX
  -> improved Telegram assistant copy/tests without expanding execution authority
```

Validation after merge included unit tests, smoke, doctor, selftest, AMB health, assistant count checks, queue cleanup dry-run, and Telegram safety checks.

## Completed Worktree Tracks

The accepted split work proceeded by track:

```text
track/opencode-runtime
  - made OpenCode the explicit execution substrate
  - removed live direct provider CLI execution paths after baseline validation

track/telegram-main-agent
  - evolve agentbot from slash-command control to main-agent conversation loop
  - preserve confirmation and policy boundaries

track/memory-amh-amb
  - define AMH as workflow/governance layer over AMB
  - keep AMB as governed durable memory substrate
  - separate AMH, AMB, and runtime local state responsibilities
  - define packet compilation, evidence checks, and promotion workflows

track/self-improvement-experimental
  - mark old multi-runtime SkillOps/scheduler work as experimental
  - salvage learning-session concepts after the new backbone is clear

track/docs-roadmap
  - update README, architecture, contract, and burn-in docs to reflect accepted direction
```

## References

- `docs/burn-in-v1.5.1.md`
- `docs/skill-evolution-loop.md`
- `docs/architecture.md`
- `docs/contract.md`
- `self_improvement/runtime-self-improve.py`
- Agent-Memory-Harness: `https://github.com/zzhang82/Agent-Memory-Harness`
- Steve Yegge, “Welcome to Gas Town”: `https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04`
