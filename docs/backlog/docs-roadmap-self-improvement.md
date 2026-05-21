# Backlog: Docs Roadmap and Self-Improvement Experimental Quarantine

## Objective

Align docs with ADR 0001 and quarantine the older multi-runtime self-improvement / SkillOps prototype without deleting useful code.

## Facts and evidence

- Trusted baseline is `runtime-agents v1.5.1` / `agentctl-v1.5.1`.
- README and CHANGELOG still document broad self-improvement work from the untrusted `v1.6` direction.
- `self_improvement/runtime-self-improve.py` contains multi-runtime ingestion for opencode, Claude/CCR, Codex, Gemini, and runtime-agents.
- That script also includes mutating SkillOps behavior: staging, approvals, deploy, lock update, rollback, scheduler, and NAS backup paths.
- ADR 0001 accepts the OpenCode / Telegram / AMB+AMH pivot and marks old multi-runtime self-improvement as experimental.
- SkillOps 2P Restore Drill is suspended and should be revisited after the pivot tracks reach an initial baseline.

## Requirements

1. Make `v1.5.1` the clearly trusted release baseline.
2. Make ADR 0001 the source of truth for architecture pivot direction.
3. Split docs into trusted baseline, experimental prototype, and future candidate roadmap.
4. Mark self-improvement commands as experimental and risk-classified.
5. Preserve useful concepts without endorsing direct multi-runtime expansion.
6. Do not run mutating self-improvement, scheduler, backup, or skill deployment commands as part of docs validation.

## Non-goals

- Do not delete `self_improvement/runtime-self-improve.py`.
- Do not implement new Learning Sessions.
- Do not restart Watchers or NAS/Home work.
- Do not promote direct runtime adapters as primary path.
- Do not treat AMB/project memory as release authority.

## Phases

### Phase 0 - Source-of-truth alignment

- Add a roadmap note pointing to ADR 0001.
- State `v1.5.1` as trusted baseline.
- State old self-improvement/SkillOps work is experimental unless promoted by future ADR and release evidence.

### Phase 1 - README and CHANGELOG cleanup

- Split README self-improvement material into trusted baseline vs experimental prototype.
- Add warning near `runtime-self-improve.py` examples.
- Keep Unreleased changelog entries but mark them as quarantined prototype work.

### Phase 2 - Self-improvement quarantine doc

- Add command risk categories:
  - read-only/lower-risk inspection
  - local event writes
  - global skill store mutation
  - scheduler mutation
  - backup/NAS mutation
  - rollback mutation
- Document state paths:
  - `~/.runtime-agents/events/agent-runs.jsonl`
  - `~/.runtime-agents/staging/`
  - `~/.runtime-agents/approvals/`
  - `~/.runtime-agents/scheduler/`
  - `~/.config/opencode/skills/`
  - `/mnt/r/LLMData/SkillsBackUp/`

### Phase 3 - Architecture and contract alignment

- Update architecture docs for OpenCode execution, Telegram main-agent channel, AMH workflow layer, AMB substrate.
- Add “experimental surfaces not part of stable contract.”
- Ensure `runtime-self-improve.py` is not implied to be stable `agentctl` contract.

### Phase 4 - Learning-session prerequisites

- Define learning-signal exclusions:
  - selftest traffic
  - validation artifacts
  - queue cleanup noise
  - synthetic tests unless marked
- Defer scheduler automation until signal hygiene is proven.

### Phase 5 - Promotion checkpoint

- Decide by ADR whether any self-improvement concept graduates from quarantine.
- Decide whether direct runtime adapters are removed, wrapped, or kept legacy.
- Revisit suspended 2P Restore Drill.

## Validation

```bash
git status --short
python3 -m unittest discover -s tests
agentctl smoke --json
agentctl doctor --json
agentctl selftest --json
```

Avoid during this track unless explicitly approved:

```bash
python3 self_improvement/runtime-self-improve.py scheduler run-once
python3 self_improvement/runtime-self-improve.py backup create
python3 self_improvement/runtime-self-improve.py approvals apply
python3 self_improvement/runtime-self-improve.py rollback apply
```

## Risks

- Docs may imply an untrusted `v1.6.0`.
- Experimental commands can mutate global skill store or NAS backups.
- Scheduler/ingestion can pollute future learning signals.
- Deleting prototype code too early would lose useful design evidence.

## Definition of done

- README/CHANGELOG/docs clearly distinguish stable vs experimental.
- Self-improvement quarantine doc exists.
- ADR 0001 is linked from roadmap docs.
- Non-mutating validation passes.
