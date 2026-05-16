# runtime-agents

This repo is now the source of truth for the runtime-agents control plane.

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

`assistant-exec` now routes through `runtime_agents.actions`, which centralizes typed action execution while preserving the existing JSON contract.

## Self-Improvement / SkillOps Layer

This section documents in-repo self-improvement work. It should not be treated as proof of a trusted closed `v1.6.0` release unless git-backed acceptance evidence and synchronized version surfaces say so.

`runtime-agents` includes a local-first self-improvement system for observing agent runs, detecting repeated workflows, and safely turning them into reusable skills.

The system is event-driven, not a background listener by default. Runtimes such as opencode, Claude/CCR, Codex, Gemini, and runtime-agents emit or expose logs. These are normalized into `AgentRunEvent` records and stored locally.

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

## CLI examples

```bash
python3 self_improvement/runtime-self-improve.py ingest --runtime opencode --recent 20
python3 self_improvement/runtime-self-improve.py scan
python3 self_improvement/runtime-self-improve.py suggest
python3 self_improvement/runtime-self-improve.py schedule check
python3 self_improvement/runtime-self-improve.py skills verify
python3 self_improvement/runtime-self-improve.py backup status
```

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
