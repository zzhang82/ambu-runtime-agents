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
