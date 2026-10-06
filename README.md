<p align="center">
  <img src="assets/ambu-hero.png" alt="Ambu: The OpenCode Agent Supervisor" width="520">
</p>

# Ambu: The Supervisor for OpenCode Coding Agents

[![OpenCode: Ready](https://img.shields.io/badge/OpenCode-Substrate%20Ready-blueviolet?style=flat-square&logo=terminal)](https://opencode.ai)
[![Ecosystem: OMO--Slim](https://img.shields.io/badge/Ecosystem-oh--my--opencode--slim-purple?style=flat-square)](https://github.com/carlg/oh-my-opencode-slim)
[![Memory: AMB](https://img.shields.io/badge/Memory-Agent--Memory--Bridge-blue?style=flat-square)](https://github.com/zzhang82/Agent-Memory-Bridge)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests: 274 Passing](https://img.shields.io/badge/Tests-274%20Passing-brightgreen?style=flat-square)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

**Ambu** (`agentctl`) is a supervisory control plane built specifically for [OpenCode](https://opencode.ai) coding agents. It routes natural language tasks to specialist personas, verifies workspace changes with automated test commands, and halts runaway retry loops before they burn API quota.

---

## The Problem Ambu Solves

Running autonomous coding agents directly in a repository often hits three walls:
1. **Blind runaway loops**: Agents hitting an environment bug or impossible constraint retry repeatedly, producing identical errors and burning quota.
2. **Arcane persona configuration**: OpenCode supports specialist roles, but invoking them manually requires complex CLI flags and setup.
3. **Ungated permissions**: Agents run without safety guardrails, risking unintended git pushes, secret edits, or destructive file changes.

**Ambu wraps `opencode run` as an intelligent supervisor:** it auto-routes tasks to specialist stations, enforces policy guardrails, and validates every code modification against your test suite.

---

## Visual Demo: Anti-Loop Early Halt

When code changes fail to resolve an issue, Ambu hashes the normalized test failure output. If the identical blocker recurs, it halts early instead of burning rounds:

<p align="center">
  <img src="assets/ambu-iterate-demo.png" alt="Ambu Anti-Loop Demo" width="680">
</p>

```bash
$ agentctl iterate coder "Fix auth token expiration" \
    --check "pytest tests/test_auth.py" \
    --max-rounds 5 \
    --max-same-failure 2
```

```text
[Round 0] Evaluating initial check: pytest tests/test_auth.py
          FAIL: test_token_expiration (AssertionError: 401 != 200)
          Fingerprint: sha256:7f4a3b8c (gap: execution)
[Round 1] Dispatching OpenCode agent (fixer · grok-4.7-build-fast)...
          Workspace modified. Running verification check...
          FAIL: test_token_expiration (AssertionError: 401 != 200)
          Fingerprint: sha256:7f4a3b8c (seen 2x)
[HALT]    [ANTI-LOOP HALT] Identical blocker sha256:7f4a3b8c recurred 2 times.
          Status: BLOCKED (exit code 3) — Prevented 4 runaway rounds. Quota saved.
```

---

## Core Capabilities

### 1. Smart Intent Routing (`agentctl do`)
Ambu uses word-boundary intent classification to route prompts to the right specialist station:

| Prompt Intent | Specialist Station | Autonomy | Responsibility |
|---|---|---|---|
| *"Review database migrations for lock risks"* | **`oracle`** | `read_only` | Architectural audit & diagnosis |
| *"Fix the broken auth login logic"* | **`fixer`** | `workspace_write` | Fast bug repair & patch |
| *"Implement Stripe webhook billing endpoint"* | **`coder`** | `workspace_write` | Feature implementation |
| *"Make navbar responsive with CSS layout"* | **`designer`** | `read_only` | UI/UX design & styling |
| *"Find documentation for Upstash Redis"* | **`librarian`** | `read_only` | Docs & reference research |

- **Negation Safety**: *"Do not fix this, just review why it broke"* detects negation and suppresses write permissions.
- **Fail-Safe Fallback**: Any ambiguity or tied score strictly defaults to safe `read_only` (`oracle`).

### 2. Evidence-Bound Iteration (`agentctl iterate`)
- **Output Normalization**: Strips wall-clock timings (`in 0.42s`), ISO timestamps, memory addresses (`0x7f...`), PIDs, and temp directories while preserving exact test failure line numbers.
- **Gap Diagnosis**: Categorizes failures into `execution` (code bugs), `environment` (missing dependencies), `check_rubric` (invalid test command), and `transient` (rate limits).
- **Artifact Verification (`--eval-artifact`)**: Verifies required output files exist and are non-empty before marking a task complete.

### 3. Policy Guardrails & Approvals
High-risk actions (`git_push`, `deploy`, `secrets`, `global_config`, `destructive_delete`) are blocked unless explicitly passed with `--approve <capability>`.

---

## Ecosystem Integrations

- **[oh-my-opencode-slim (OMO)](https://github.com/carlg/oh-my-opencode-slim)**: Ambu's `slim_bridge` automatically inspects `~/.config/opencode/oh-my-opencode-slim.json`, inheriting model assignments, reasoning variants (`xhigh`, `max`), and skill bindings with zero manual setup.
- **[Agent Memory Bridge (AMB)](https://github.com/zzhang82/Agent-Memory-Bridge)**: Connects Ambu to durable memory. Pre-queries project gotchas before tasks, and shares discovered fixes across stations so no agent repeats a past mistake.
- **[Michelin Kitchen Brigade Guide](docs/kitchen-brigade.md)**: Detailed breakdown of the Head Chef, Expeditor Pass, and station roles.
- **[AMB Memory Integration Guide](docs/memory-amb.md)**: Deep guide on auto-recall mechanics and shared incident logs.

---

## Installation & Quickstart

```bash
git clone https://github.com/zzhang82/ambu-runtime-agents.git
cd ambu-runtime-agents
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
agentctl doctor
```

### Essential Commands
```bash
# Natural language dispatch (auto-routes to oracle in read-only mode)
agentctl do "Review database schema for missing foreign key indexes"

# Code repair with automated test verification
agentctl do "Fix the broken user registration endpoint" --check "pytest tests/test_user.py"

# Bounded iteration with anti-loop protection (exit code 3 if repeated failure)
agentctl iterate coder "Fix billing calculation" --check "pytest" --max-same-failure 2

# Inspect guardrails and routing without running
agentctl do "Push commit to production remote" --dry-run --json
```

---

## Testing & License

Run all 274 tests:
```bash
python3 -m unittest discover -s tests
```

Released under the [MIT License](LICENSE). Copyright &copy; 2026 Frank Zhang.
