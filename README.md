# runtime-agents

This repo is now the source of truth for the runtime-agents control plane.

Trusted release baseline: `runtime-agents v1.5.1` / `agentctl-v1.5.1`.

Current architecture direction is governed by `docs/adr/0001-opencode-telegram-memory-pivot.md`: `runtime-agents` owns orchestration and policy, OpenCode owns model/runtime execution, Telegram evolves toward the main human-facing agent channel, AMB remains the governed durable memory substrate, and Agent-Memory-Harness is the workflow/governance layer around AMB.

The older multi-runtime self-improvement and SkillOps prototype under `self_improvement/` is experimental/quarantined. It is retained as design evidence, but it is not part of the trusted `agentctl` contract and is not proof of a closed `v1.6.0` release.

Current unreleased CrewOS company-loop work is a v2 activation-ready surface, not a closed package release. The safe boundary is:
- `agentctl company-status --json` reports company-loop readiness, Crew bindings, daemon heartbeat, queue, schedule, workspace, and Telegram posture.
- `agentctl company-dispatch <goal...> --dry-run --json` plans a Cole-gated specialist workflow only. It must not enqueue work, start daemons, create schedules, or write AMB records.
- `agentctl company-activate` defaults to dry-run and requires `--live --yes` before it can create the bounded `crewos-company-review` Cole-manager schedule. It blocks live activation when active queued work exists. `--start-daemon` is a separate explicit flag.
- `company-dispatch` remains dry-run-only in v2; live specialist dispatch requires a future acceptance-tested path.

Installed commands:
- agentctl
- agentd
- agentbot

Live config:
- ~/.config/runtime-agents/

Live state:
- ~/.local/share/runtime-agents/

Development install uses a repo-local virtualenv:
- .venv/

Do not edit ~/.local/bin/agentctl directly anymore.
Edit src/runtime_agents/cli.py, then reinstall/test.

## Development workflow

Runbook validation now has two modes:
- `agentctl runbook validate --json` keeps runtime-friendly semantics and reports skipped invalid local runbooks.
- `agentctl runbook validate --strict --json` fails if any invalid runbook exists.

v1.5.0 adds metadata-derived context-aware guardrails on top of the profile and tool registry surfaces:
- `agentctl tool list|show|validate --json`
- `agentctl profile list|show|validate --json`
- `agentctl profile run <profile> ... --dry-run --json`
- `agentctl profile plan <profile> ... --json`
- `agentctl guardrail list --json`
- `agentctl guardrail eval --profile <profile> --tool <tool> --action <action> --json`

`agentctl version --json` reports the installed package version. Packaged defaults for profiles, tools, and runbooks ship with the artifact, and `runtime-dev` requires a workspace unless one is pinned in config.

`context_state` in v1.5 is derived from declared profile/tool/action metadata. It does not yet track arbitrary tool result flows or live untrusted content propagation.

## CPA-aware model routing

`agentctl model` exposes the configured CPA/OpenCode catalog and routing evidence. CPA gateway credentials are resolved at runtime from environment variables or the existing OpenCode config and are never written to state.

```bash
agentctl model refresh --json
agentctl model status --json
agentctl model catalog-check --json
agentctl model recommend --agent designer --json
agentctl model recommend --agent fixer --json
```

`refresh` stores a sanitized mode-600 snapshot in `RUNTIME_AGENTS_STATE_HOME`. When `model_routing.required: true`, every `agentctl run` and `agentctl iterate` refreshes routing evidence, resolves the agent's role frame, pins one eligible model, and automatically tries later approved candidates only after a transient model failure. Failed models enter bounded local cooldown so the next subagent does not immediately select the same exhausted route.

The weekly quota widget is explicitly OpenAI/Codex-scoped and cannot exclude Gemini, Claude, or xAI. Unknown provider quota is surfaced as unknown rather than guessed. `agentctl model recommend` remains a read-only preview of the same policy used by enforced task preflight.

`assistant-exec` now routes through `runtime_agents.actions`, which centralizes typed action execution while preserving the existing JSON contract.

## Experimental Self-Improvement / SkillOps Prototype

This section documents quarantined in-repo prototype work. It should not be treated as proof of a trusted closed `v1.6.0` release unless git-backed acceptance evidence and synchronized version surfaces say so.

`self_improvement/runtime-self-improve.py` includes a local-first self-improvement prototype for observing agent runs, detecting repeated workflows, and turning them into reusable skills.

Prototype status:
- experimental and quarantined by ADR 0001
- not part of the stable `agentctl-v1.5.1` CLI contract
- not the default roadmap direction for execution integration
- useful as design evidence for future ADR-approved work
- mutating commands can affect local event state, scheduler state, global skill-store files, rollback state, or backup/NAS paths

The system is event-driven, not a background listener by default. The supported live execution/log path is OpenCode plus runtime-agents local run state. Older direct provider CLI ingestion was removed from the active prototype after ADR 0001.

Core flow:

```text
runtime logs / events
  → AgentRunEvent
  → scan
  → suggest
  → approval
  → controlled apply
  → verification
  → rollback if needed
  → lifecycle registry
  → backup
```

Key guarantees:
- No raw transcript dumping by default.
- No automatic skill forging.
- No automatic deployment.
- No automatic lockfile update.
- Mutating actions require approval.
- Skill store changes are verified against `skills.lock.json`.
- Rollback uses Git and lockfile state as file truth.

## Inspection and Status Prototype Examples

Use these only as prototype examples. Do not treat them as stable release commands. `ingest` can write local event state, so it is listed separately from lower-risk inspection/status commands.

```bash
python3 self_improvement/runtime-self-improve.py scan
python3 self_improvement/runtime-self-improve.py suggest
python3 self_improvement/runtime-self-improve.py schedule check
python3 self_improvement/runtime-self-improve.py skills verify
python3 self_improvement/runtime-self-improve.py backup status
```

Local event/state write prototype example:

```bash
python3 self_improvement/runtime-self-improve.py ingest --runtime opencode --recent 20
```

Avoid mutating prototype commands unless a future ADR and release plan explicitly promotes them:

```bash
python3 self_improvement/runtime-self-improve.py scheduler run-once
python3 self_improvement/runtime-self-improve.py backup create
python3 self_improvement/runtime-self-improve.py approvals apply
python3 self_improvement/runtime-self-improve.py rollback apply
```

See `docs/self_improvement_baseline.md` for the quarantine note and command risk categories.

### Event model

The normalized event format is `AgentRunEvent`. It captures structural metadata such as:
- runtime
- session ID
- user goal
- tool sequence
- commands run
- files touched
- memory operations
- outcome
- friction points

It does not require storing full transcripts.

## Development workflow

```bash
cd ~/code/runtime-agents
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
python -m unittest discover -s tests
agentctl smoke --json
agentctl selftest --json
```

See `docs/contract.md` for the CLI/runtime contract and `docs/architecture.md` for component boundaries.
