# Runtime Agents Project Notes

## Open todo
- `runtime-agents v1.5.1` is closed. Pause feature work and start real dogfooding before planning v1.6.
- Use the current system in real workflows first: `runtime-dev` profile, guardrail evals, profile run dry-runs, profile plans, and Telegram status/show/logs paths.
- Focus the next session on burn-in questions:
  - Are profiles understandable in real use?
  - Are guardrail decisions useful or noisy?
  - Does `profile run --dry-run` explain enough?
  - Do profile plans carry useful metadata?
  - Do runbooks map correctly?
  - Does queue cleanup solve validation leftovers safely?
  - Does `doctor` help debug real issues?
- Do not start watchers, learning sessions, skills, Home NAS work, or market agents until burn-in results justify a v1.6 direction.

## Recent release state
- `v1.5.0` closed with guardrail release commit `a3a06a6`.
- `v1.5.1` closed with:
  - `d7d0c87` Sync profile and tool registry defaults
  - `e5de996` Add queue lifecycle cleanup commands
- Live CLI contract/version at closeout: `agentctl-v1.5.1` / `1.5.1`.
