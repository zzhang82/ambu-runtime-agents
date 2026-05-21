# Goal: Architecture Pivot Tracks

## Current Status

The initial integrated architecture-pivot baseline is complete.

Completed tracks:
- OpenCode runtime characterization
- Telegram assistant baseline UX
- AMB/AMH memory contract
- Queue/assistant UX cleanup
- Docs roadmap and self-improvement quarantine

Next decision: decide whether to revisit the suspended SkillOps Milestone 2P Restore Drill now, or plan the next pivot slice from the completed baseline.

## Status of Previous Goal

SkillOps Milestone 2P - Restore Drill is **suspended**, not deleted.

Revisit it after the OpenCode runtime, Telegram main-agent, Memory Harness, self-improvement-experimental, and docs-roadmap tracks reach an initial integrated baseline.

Reason: the project is pivoting away from expanding the old multi-runtime SkillOps path, so the restore drill should not block the new architecture tracks. Backup/restore safety remains important and must be revisited once the new architecture clarifies which SkillOps surfaces remain relevant.

# Prior Goal: SkillOps Milestone 2P - Restore Drill

## Objective
Prove that the NAS backup system can successfully restore the SkillOps environment into a temporary directory and pass full integrity verification, ensuring disaster recovery reliability.

## Milestone 2P Requirements
1. **Extraction Test**: Extract the latest snapshot (`tar.gz`) from the NAS to `/tmp/skillops-restore-test`.
2. **Registry Integrity**: Verify that `skills.lock.json`, `skills.registry.json`, and `skills.evals.json` are present and readable.
3. **Skill Completeness**: Verify that core system skills (e.g., `skill-creator`, `skill-installer`) and project skills are correctly extracted.
4. **Verification Support**: Ensure the `runtime-self-improve.py` verifier can validate a custom path (e.g., the restored temp directory) against its internal lockfile.
5. **Mirror Audit**: Compare the restored content with the `latest/` rsync mirror on the NAS to ensure parity.
6. **Zero-Side-Effect Safety**: Confirm the restore process does not overwrite or modify the live global skill store at `~/.config/opencode/skills/`.

## Success Conditions
- Latest snapshot extracts without errors.
- All governance files (`lock`, `registry`, `evals`) are verified.
- The `runtime-self-improve.py` verifier returns a "PASS" for the restored directory.
- No accidental mutation of the production environment occurs.

## Constraints
- Do not add new features until the restore drill passes.
- Use `/tmp/skillops-restore-test` for the target path.
- Reference NAS path: `/mnt/r/LLMData/SkillsBackUp/`.
