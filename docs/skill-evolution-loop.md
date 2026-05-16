# Skill Evolution Loop

## Status

This note treats `runtime-agents v1.5.1` as the latest trusted closed release unless a clean git-backed `v1.6.0` release commit and acceptance evidence are proven.

Current rule:

1. Git commit history + working tree
2. `pyproject.toml`
3. `src/runtime_agents/cli.py` version output
4. tests
5. docs
6. `~/.config/runtime-agents/VERSION`
7. AMB / project memory

AMB and handoff memory are useful context, but they are not release authority.

## Existing External Skills

- `ljg-skill-mentor` - router / skill selector
- `repo-workflow-cartographer` - sensor / repeated pattern detection from agent logs
- `ljg-style-skill-sculptor` - forge / turns a candidate into a skill spec
- `session-bridge-assembler` - continuity / handoff recovery
- `version-sync-sculptor` - maintainer / version drift prevention
- `skill-deployment-verifier` - guardrail / deployment integrity check
- `repo-architecture-sensor` - foundation / map unknown repositories quickly

## Current External Loop

```text
agent logs
  -> runtime-self-improve scan
  -> runtime-self-improve suggest
  -> runtime-self-improve cluster
  -> sculptor brief
  -> forge
  -> deployment verify
  -> AMB memory
```

This loop already exists outside the core `runtime-agents` release surface and should be dogfooded there first.

## Current Runtime-Agents Baseline

Trusted baseline to dogfood before new major feature absorption:

- `v1.5.1`
- profiles + tools
- guardrails
- queue cleanup
- runbooks
- `agentctl` / `agentd` / `agentbot`
- AMB recall / writeback integration

## Integration Principle

Do not rebuild the skill system from scratch inside `runtime-agents` yet.

Instead:

1. Keep the current skill-maintainer loop as an external workflow.
2. Dogfood `runtime-agents v1.5.1` in real tasks.
3. Formalize the proven pieces later as typed control-plane concepts.

Candidate future typed states:

- `skill_candidate`
- `skill_brief`
- `skill_forge_run`
- `skill_deployment_check`
- `skill_status`

## Proposed Future Mapping

### Learning Sessions

Should wrap:

- `repo-workflow-cartographer`
- `runtime-self-improve scan`
- `runtime-self-improve suggest`
- `runtime-self-improve cluster`

Primary output:

- learning reports
- repeated-pattern evidence
- ranked skill candidates

### Skill Lifecycle

Should wrap:

- `ljg-style-skill-sculptor`

Primary output:

- candidate -> brief -> forge -> verify flow

### Skill Validation

Should wrap:

- `skill-deployment-verifier`

Primary output:

- deployment integrity evidence
- cross-store verification
- drift detection

### Release Maintenance

Should wrap:

- `version-sync-sculptor`

Primary output:

- version-surface consistency
- release authority checks
- changelog / manifest sync

### Profile / Runbook UX

Should borrow concepts from:

- `ljg-skill-mentor`

Primary output:

- better routing
- clearer operator affordances
- skill-aware workflow suggestions

## Suggested Roadmap

```text
Now:
  v1.5.1 dogfood / burn-in

Then:
  v1.6.0 Learning Sessions
    integrate scan/suggest/cluster
    output learning reports and skill candidates

Then:
  v1.7.0 Skill Lifecycle
    formalize candidate -> brief -> forge -> verify

Then:
  v1.8.0 Watchers
    use profiles and guardrails to monitor external state safely

Then:
  v1.9.0 Home NAS vertical slice
```

## Guardrails

- Do not treat AMB memory as release proof.
- Do not promote `v1.6.0` until git history, version surfaces, and acceptance evidence agree.
- Do not absorb large self-improvement features into the core control plane before burn-in validates the need.
- Prefer thin wrappers around proven external workflows before deeper platform integration.
