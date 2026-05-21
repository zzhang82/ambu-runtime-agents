# Backlog: Telegram Main-Agent Channel

## Objective

Evolve `agentbot` from a slash-command control wrapper into the main human-facing agent/persona channel while preserving the `agentctl` safety boundary.

## Facts and evidence

- Current Telegram code lives in `src/runtime_agents/telegram_bot.py`.
- Current bot shells out to `agentctl`; it does not execute arbitrary shell directly.
- Existing commands include `/status`, `/queue`, `/plans`, `/schedules`, `/workspaces`, `/show`, `/logs`, `/run`, `/iterate`, and plan recovery commands.
- Non-slash messages already route through `agentctl assistant-route` and `agentctl assistant-exec`.
- Session state already tracks lightweight fields such as last workspace/task/plan/schedule and pending confirmation.
- Dangerous slash commands like shell/exec surfaces are blocked.
- Burn-in showed assistant routing works for simple prompts, but more ambiguous and multi-turn prompts need dogfooding.

## Requirements

1. Keep slash commands for deterministic operator control.
2. Make non-slash Telegram messages feel like a main-agent conversation.
3. Preserve allowlisted user access.
4. Preserve confirmation flow for write-like actions.
5. Preserve explicit rejection of arbitrary shell/exec commands.
6. Keep action execution auditable through `agentctl` state/logs.
7. Add concise summaries and next-action suggestions for status, queue, plans, failures, and blocked work.
8. Use local Telegram session state only for ephemeral UI context until AMH contract is ready.
9. Do not store durable persona or learning state in `telegram.sessions.json`.

## Non-goals

- Do not add an LLM router in this track.
- Do not move policy ownership into `telegram_bot.py`.
- Do not duplicate action business logic that belongs in `runtime_agents.actions`.
- Do not bypass `assistant-route` / `assistant-exec`.
- Do not require AMH for the first Telegram main-agent baseline.

## Phases

### Phase 0 - Baseline Telegram behavior

- Capture current outputs for `/help`, `/status`, `/queue`, `/workspaces`, natural `list workspaces`, and blocked `/exec`.
- Add or verify tests for unauthorized users, confirmation handling, and blocked shell-like commands.

Validation:

```bash
python src/runtime_agents/telegram_bot.py --test-command 1 /help
python src/runtime_agents/telegram_bot.py --test-command 1 /status
python src/runtime_agents/telegram_bot.py --test-command 1 "list workspaces"
python src/runtime_agents/telegram_bot.py --test-command 1 /exec ls
agentctl assistant-route "list workspaces" --json
agentctl assistant-exec "list workspaces" --json
```

### Phase 1 - Conversation UX polish

- Improve help/greeting to encourage natural prompts.
- Add short main-agent summaries around existing typed actions.
- Add “suggested next action” text for status, queue, and plan states.
- Keep slash commands as fallback.

Acceptance:

- Natural prompts give useful short responses.
- No new execution authority is introduced.

### Phase 2 - Multi-turn continuity

- Use existing session fields consistently for follow-ups like “show logs,” “repair it,” or “retry that.”
- Ask one clarification question when context is missing.
- Add reset/forget-context affordance if needed.

### Phase 3 - Actionable notifications

- Rewrite notifications as main-agent prompts with safe suggested replies.
- Store enough ephemeral context for follow-up.
- Keep notification dedupe and selftest filtering.

### Phase 4 - Profile-aware delegation

- Make profile run/plan flows discoverable through Telegram.
- Summarize guardrail decisions before execution.
- Prefer dry-run or plan-first behavior for ambiguous/risky goals.

## Risks

- Telegram could become an unsafe command channel if direct execution branches are added.
- Telegram-specific logic could drift from CLI semantics.
- Queue residue could make the bot look noisy unless coordinated with queue hygiene.
- Durable memory needs could creep in before AMH contract exists.

## Dependencies

- `agentctl assistant-route` and `assistant-exec`.
- Existing runbooks/action allowlist.
- Queue hygiene track for cleaner status/queue summaries.
- OpenCode runtime track for future subagent delegation consistency.
- AMH/AMB track for future durable persona/session memory.

## Definition of done for first baseline

- Phases 0-2 complete.
- Safety tests prove shell/exec remains blocked.
- Telegram feels usable for status/inspection/follow-up without new authority.
- Smoke, doctor, selftest, and Telegram test-command checks pass.
