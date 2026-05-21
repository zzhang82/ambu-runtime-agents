# Backlog: AMB Substrate and AMH Workflow Layer

Status: Done for initial baseline. Merged in `5a86920 Document AMB and AMH memory contract`.

## Objective

Define and implement the memory boundary where AMB is the governed durable memory substrate and Agent-Memory-Harness (AMH) is the workflow/governance layer around AMB.

## Corrected model

```text
runtime-agents
  -> AMH memory workflow/governance layer
        -> AMB governed durable memory substrate
```

AMB stores governed records. AMH decides how agents recall, compile, propose, promote, audit, and validate memory use.

## Facts and evidence

- Current docs still say “AMB memory authority” in places.
- ADR 0001 originally described AMH as backbone and AMB as status/staging; this should be corrected to avoid split-brain memory authority.
- Current code already has `amb_adapter.py`, AMB health, recall, store, memory prelude, writeback candidates, and writeback receipts.
- Current recall prelude warns that memory is context and repo files win.
- Current writeback flow already has primitive governance: dry-run, candidate filters, approval flag, no full summaries, receipts, and optional verification.
- Profiles/workspaces already support `memory_namespace`.
- `AgentRunEvent` already captures `memory_operations`.

## Requirements

1. Reconcile terminology:
   - AMB = durable governed substrate / MCP-compatible source of truth.
   - AMH = workflow, readiness, packet compilation, failure tracking, belief governance, promotion pipeline.
   - runtime local state = operational queue/task/plan/run/session state.
   - repo/git/tests = implementation and release authority.
2. Preserve existing AMB recall/writeback behavior while AMH adapters mature.
3. Define AMH integration contract before broad implementation.
4. Add explicit authority classes for memory records/candidates.
5. Make recall and writeback policy decisions visible in JSON.
6. Keep AMH optional at first; degraded mode must be safe.
7. Do not store raw transcripts, secrets, credentials, or unverified release claims as durable memory.

## Non-goals

- Do not build Telegram persona memory here.
- Do not make AMH a second durable memory database over AMB.
- Do not start Learning Sessions yet.
- Do not require AMH for base `agentctl` operation until adapters are stable.
- Do not treat AMB memory as release proof.

## Proposed authority classes

- `context_hint` - useful but must be verified.
- `handoff` - session/task continuity, not proof.
- `status` - operational snapshot, may be stale.
- `procedure` - reusable rule or workflow.
- `decision` - human/project decision with date/scope.
- `belief_proposal` - candidate belief awaiting promotion.
- `release_evidence` - only valid with git/test/version evidence.
- `persona_preference` - user/operator preference, not implementation truth.
- `sensitive_excluded` - marker for content that must not be written.

## Phases

### Phase 0 - Docs/terminology reconciliation

- Patch ADR 0001 to reflect AMB substrate / AMH workflow layer.
- Update architecture/contract docs to remove ambiguous “AMB memory authority” wording.
- Add authority model.

Validation:

```bash
agentctl smoke --json
agentctl doctor --json
```

### Phase 1 - AMH/AMB interface spec

- Define JSON examples for recall request/decision, memory candidate, writeback decision, receipt, and audit event.
- Define fallback modes: `amh_unavailable`, `amb_unavailable`, `namespace_missing`, `policy_denied`, `verification_failed`.
- Define namespace policy and resolution order.

### Phase 2 - Extract memory policy module

- Move existing memory option and decision logic out of CLI where practical.
- Preserve current CLI flags and JSON fields.
- Add tests for no-memory, missing namespace, recall disabled, AMB unavailable, and max limit clamping.

### Phase 3 - Governed recall visibility

- Add versioned recall decision object.
- Show namespace, selected records, authority labels, reason, and degraded mode.
- Preserve `--memory-preview` and existing `memory_recall` metadata.

### Phase 4 - Governed writeback

- Formalize current writeback rules.
- Add per-candidate dry-run reasons.
- Require authority class for new candidates.
- Preserve legacy candidate compatibility and writeback receipts.

### Phase 5 - AMH adapter boundary

- Decide transport: subprocess, MCP, local module, or HTTP/local service.
- Add config-driven AMH boundary with safe fallback.
- Add fake AMH tests.
- Add health output without requiring AMH for ordinary commands.

## Risks

- Terminology drift can cause split-brain memory architecture.
- Memory may be treated as truth over current repo files.
- Writeback could persist secrets or unverified claims if policy is too loose.
- AMH dependency could break normal workflows if made mandatory too early.

## Dependencies

- Existing AMB adapter and AMB MCP config.
- AMH adapter contract maturity.
- Telegram track for future persona/session use.
- OpenCode track for future execution telemetry.

## Definition of done for first baseline

- Docs clearly state AMB/AMH/runtime local state boundaries.
- AMH interface spec exists with examples.
- Existing AMB behavior remains compatible.
- Tests, smoke, doctor, selftest, and `amb-health` pass.
