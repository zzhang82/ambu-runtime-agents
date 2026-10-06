# runtime-agents v1.5.1 Burn-in

## Summary

`runtime-agents v1.5.1` is operational and internally consistent after the version reconciliation pass. The core control-plane surfaces worked during burn-in: profile and tool metadata loaded cleanly, guardrail evaluation produced understandable allow/block decisions, assistant routing matched the intended runbooks, and smoke/doctor/selftest all passed.

The main friction found during burn-in was not command failure. It was usability noise around queue lifecycle state: `queue active` exposed a large backlog of stale validation artifacts, and `queue cleanup-validation --dry-run` correctly identified them, but the amount of residue makes routine operational state look unhealthy until cleanup is explicitly run.

## Environment
- repo: `runtime-agents`
- version: `1.5.1`
- contract: `agentctl-v1.5.1`
- date: `2026-05-15T23:03:42-04:00`

## Checks Run

- `agentctl version --json`
- `agentctl profile list --json`
- `agentctl profile show runtime-dev --json`
- `agentctl tool list --json`
- `agentctl tool show repo_read --json`
- `agentctl guardrail list --json`
- `agentctl guardrail eval --profile runtime-dev --tool repo_read --action profile_run --json`
- `agentctl guardrail eval --profile shopping-watch --tool telegram_notify --action external_purchase --json`
- `agentctl profile run runtime-dev "inspect runtime-agents repo health and identify next safe work" --workspace test-ws --dry-run --json`
- `agentctl assistant-route "list profiles" --json`
- `agentctl assistant-route "show profile runtime-dev" --json`
- `agentctl assistant-exec "list workspaces" --json`
- `agentctl queue active --json`
- `agentctl queue cleanup-validation --dry-run --json`
- `agentctl smoke --json`
- `agentctl doctor --json`
- `agentctl selftest --json`

## What Worked

- Version surface was stable during burn-in: `agentctl version --json` reported `1.5.1` / `agentctl-v1.5.1`.
- Profile metadata loaded clearly:
  - `runtime-dev` resolved to planner by default
  - allowed tools were explicit: `repo_read`, `web_fetch`, `workspace_files`
  - approval and blocked capability lists were visible in `profile show`
- Tool metadata was concrete and readable:
  - `repo_read` clearly advertised `filesystem_read`, `project_source`, `trusted`, `workspace_scoped`
- Guardrails behaved as intended:
  - `runtime-dev + repo_read + profile_run` returned `allow`
  - `shopping-watch + telegram_notify + external_purchase` returned `block`
- Dry-run profile execution was useful:
  - returned `dry_run_ok`
  - showed selected agent, allowed tools, workspace, memory namespace, and policy decisions
- Assistant routing worked on simple operator prompts:
  - `list profiles` -> matched `list_profiles`
  - `show profile runtime-dev` -> matched `show_profile`
  - `list workspaces` -> executed successfully through `assistant-exec`
- Health surfaces were good:
  - `smoke --json` passed with `guardrails_ok`, `profiles_ok`, and `tools_ok`
  - `doctor --json` showed clean config/runbook/tool/profile/permission checks
  - `selftest --json` passed end-to-end

## Friction / Confusion

- Queue state is the main friction point.
  - `queue active --json` exposed a large backlog of old validation/selftest artifacts.
  - During this burn-in, `queue cleanup-validation --dry-run --json` reported `active_count: 50` and identified the same backlog as cleanup candidates.
- The system is functionally correct here, but the operator experience is noisy because a healthy repo can still look operationally messy until explicit cleanup happens.
- `assistant-exec "list workspaces"` returned two workspaces in the payload (`runtime-agents` and `test-ws`) while the summarized `action_result.result.count` was `1`. The command still worked, but that count field is potentially confusing.

## Output Quality Notes

- JSON outputs are generally strong: explicit, structured, and auditable.
- `profile show`, `tool show`, and guardrail eval payloads are particularly readable.
- `doctor --json` is comprehensive, but long; it is better for validation evidence than quick human scanning.
- `selftest --json` is valuable as a confidence surface, but it is very verbose for everyday use.
- Queue outputs are accurate but can become overwhelming when residue accumulates.

## Guardrail Notes

- The allow case was understandable:
  - `runtime-dev` + `repo_read` + `profile_run` produced `decision: allow`
  - reason: `no blocking guardrail matched`
- The block case was also understandable and better than a single opaque denial:
  - `shopping-watch` + `telegram_notify` + `external_purchase` produced layered policy decisions
  - it showed both `approval_required` and `block` reasoning before settling on `block`
  - final blocking reasons included `block_external_purchase` and `profile_blocked_capability`
- This is good evidence that the guardrail system is understandable enough to dogfood.

## Profile / Tool Notes

- Profiles and tools are useful because they make the control plane legible before execution.
- `runtime-dev` feels like a practical default profile for the repo.
- Tool metadata provides real policy value:
  - `trust_level`
  - `data_classes`
  - `egress`
  - `workspace_scoped`
- The metadata-first approach appears to be working as intended in `v1.5.1`.

## Assistant Router Notes

- Simple routing commands matched correctly and returned the intended packaged/config runbooks.
- `assistant-route` outputs are compact and readable.
- `assistant-exec` correctly executed a read-only workspace listing path.
- The command path appears usable for common operational prompts, but more burn-in would be useful for ambiguous phrasing and multi-step intents.

## Queue Lifecycle Notes

- Queue lifecycle support is present and useful.
- The cleanup mechanism is doing real work:
  - `queue cleanup-validation --dry-run --json` correctly detected stale validation artifacts without mutating state.
- This validates the value of the `v1.5.1` release itself.
- The remaining issue is operator hygiene, not missing control-plane capability.

## Candidate v1.6 Directions

Supersession note: ADR 0001 and the pivot backlog now supersede the feature recommendation in this burn-in report. Treat the options below as historical burn-in observations, not an active `v1.6.0` release plan; feature choice is paused until the OpenCode runtime, Telegram main-agent, AMB/AMH memory, queue UX, and self-improvement quarantine tracks reach an initial integrated baseline.

### Learning Sessions
Pros:
- Best match for the historical documented skill-evolution direction before ADR 0001.
- Builds directly on AMB-governed durable records plus repeated workflow sensing rather than adding a new external integration surface.
- Burn-in suggests the control plane itself is stable enough to start capturing usage and friction systematically.

Cons:
- The current burn-in mostly tested operator surfaces, not yet a broad learning-session workflow.
- There is still queue-hygiene noise that could contaminate learning signals if not handled carefully.

Evidence:
- Stable profile/tool/guardrail surfaces mean the system can likely support a structured learning layer next.
- The project already has a documented external skill loop in `docs/skill-evolution-loop.md`.

### Watchers
Pros:
- Would extend the existing scheduling/queue model.
- Could turn some recurring operational checks into more proactive monitoring.

Cons:
- Burn-in did not reveal watchers as the highest-value missing surface.
- Existing queue residue suggests more automation could amplify noise before operator UX is further tightened.

Evidence:
- Scheduler/queue concepts exist, but the strongest observed friction was cleanup noise rather than missing watcher capability.

### Assistant UX polish
Pros:
- Directly addresses burn-in findings around scanability, verbosity, and small payload inconsistencies.
- Likely lower risk than a larger feature release.

Cons:
- Less strategically differentiated than Learning Sessions.
- Risks becoming cosmetic if not tied to real operator pain points.

Evidence:
- `doctor` and `selftest` are strong but verbose.
- `assistant-exec` workspace count/result presentation could be tightened.
- Queue outputs are accurate but operationally noisy.

## Recommendation

Do one more short dogfood cycle around real operator usage. The previous release bias toward **v1.6.0 Learning Sessions** is superseded by ADR 0001 and the pivot backlog; feature choice is paused until the pivot tracks produce an initial integrated baseline.

Reason:
- The control plane appears stable.
- The documented strategic direction now favors first clarifying the OpenCode runtime, Telegram main-agent, AMB/AMH memory, queue UX, and self-improvement quarantine tracks.
- Burn-in did not show a missing watcher capability as the main gap.
- The strongest immediate product issue is operational clarity and residue handling, which should be addressed before promoting any learning-session automation.

## Follow-up Tasks

- Decide whether `assistant-exec` workspace result counts should reflect all returned workspaces consistently.
- Improve queue/operator hygiene so stale validation artifacts do not dominate `queue active` by default.
- Consider a lighter-weight human summary mode for `doctor` and/or `selftest` outputs.
- Run another burn-in pass with more ambiguous assistant prompts and one or two real profile-driven workflows.
- Before any Learning Sessions release, define how queue residue and selftest traffic should be excluded from learning signals.
