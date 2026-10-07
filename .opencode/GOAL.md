# Goal: Ambu Stabilization and Maintenance Baseline

## Project Scope & Objectives

Ambu (`ambu-runtime-agents`) is a focused CLI control plane for bounded, check-driven repair with OpenCode.

### Core Capabilities
1. **Bounded Iteration**: Runs a user-supplied verification command (`--check`), manages attempt loops, and halts early when identical failure fingerprints recur.
2. **Execution Integrity**: Guarantees process group termination on timeout or cancellation without leaving orphaned workers.
3. **Task Lineage & Identity**: Binds OpenCode session IDs to tasks with strict directory and time boundaries, preventing cross-workspace session ambiguity.
4. **Resumption with Contracts**: Resumes interrupted or rate-limited tasks while preserving original budgets, acceptance checks, and working directories.

### Non-Goals / Excluded Scope
- Ambu is not an operating system sandbox (permissions are preflight policy checks, not kernel-level isolation).
- Ambu does not implement a dynamic evaluators marketplace or autonomous multi-agent company daemon.
- Ambu is not a replacement for native OMO/Slim agent orchestration.

### Historical Context
Previous SkillOps / multi-runtime migration notes and restore drill checkpoints have been archived.
