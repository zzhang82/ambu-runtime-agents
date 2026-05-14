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

`assistant-exec` now routes through `runtime_agents.actions`, which centralizes typed action execution while preserving the existing JSON contract.

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
