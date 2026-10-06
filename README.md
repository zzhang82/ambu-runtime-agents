<p align="center">
  <img src="assets/ambu-hero.png" alt="Ambu: Personal Agent Control Plane" width="640">
</p>

# Ambu: Personal Agent Control Plane

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://python.org)
[![Tests: 274 Passing](https://img.shields.io/badge/Tests-274%20Passing-success.svg)](tests/)

**Ambu** (`runtime-agents`) is a local-first control plane for personal AI coding agents. It provides intent-based auto-dispatch, policy guardrails, model quota routing, and deterministic anti-loop verification loops for autonomous workflows.

---

## Why Ambu?

Running autonomous coding agents directly often leads to three common failure modes:
1. **Blind retry loops**: An agent hitting an impossible constraint or environment bug repeatedly burns API quota without making progress.
2. **Role confusion**: Users have to manually remember and configure arcane specialist agent names (`oracle`, `fixer`, `eli`, `librarian`).
3. **Ungated permissions**: Agents can inadvertently run destructive commands, access secrets, or execute unauthorized git pushes.

**Ambu** sits between the user and coding runtimes (such as [OpenCode](https://opencode.ai)), providing an intelligent, supervisory control layer that enforces safety, tracks evidence, and stops runaway loops.

---

## Key Features

### 🎯 Smart Intent Routing (`agentctl do`)
Run tasks in plain natural language without memorizing specialist names. Ambu automatically analyzes prompt intent, respects explicit negations, and selects the right specialist role:
- *"Review database migrations for table lock risks"* &rarr; **`oracle`** (`read_only`)
- *"Fix failing auth login tests"* &rarr; **`fixer`** (`workspace_write`)
- *"Find documentation for Upstash Redis"* &rarr; **`librarian`** (`read_only`)
- *"Make navbar responsive with CSS styling"* &rarr; **`designer`** (`read_only`)
- *"Implement billing invoice endpoint"* &rarr; **`eli`** (`workspace_write`)

### 🔄 Anti-Loop Verification (`agentctl iterate`)
An evidence-bound retry engine that tests code modifications deterministically:
- **Output Normalization**: Strips wall-clock timings, timestamps, memory addresses, and ephemeral paths while preserving source line numbers and test counts.
- **Blocker Fingerprinting**: SHA-256 hashes failure output. If the identical blocker recurs $\ge 2$ times, Ambu halts early (`status: blocked`, exit code `3`) rather than burning model quota.
- **Gap Classification**: Categorizes failures into `execution` (code bugs), `environment` (missing binaries), `check_rubric` (invalid test command), and `transient` (rate limits).
- **Evaluation Artifacts**: Verifies required files exist and are non-empty with `--eval-artifact`.

### 🛡️ Policy Guardrails & Capability Approvals
Detects high-risk operations (git pushes, deployments, secret file modifications, global configuration changes, destructive deletions) before commands run. Safe actions run automatically; dangerous actions require explicit approval flags (`--approve git_push`).

### ⚡ Quota-Aware Model Routing
Dynamically monitors model health and catalog availability. If a provider experiences rate limits or cooldowns, Ambu falls back cleanly through pre-approved model candidates.

---

## Installation

### From Source

```bash
git clone https://github.com/zzhang82/ambu-runtime-agents.git
cd ambu-runtime-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify your setup:
```bash
agentctl doctor
agentctl selftest
```

---

## Quickstart

### 1. Smart Dispatch
```bash
# Auto-detects 'review' intent and routes to oracle (read-only)
agentctl do "Review the database migrations for table lock risks"

# Auto-detects 'fix' intent and pairs with verification check
agentctl do "Fix the broken auth login logic" --check "pytest tests/test_auth.py"
```

### 2. Verified Iteration Loop
Run an agent in a bounded loop until a check passes, with anti-loop protection:
```bash
agentctl iterate coder "Fix authorization tests" \
  --check "pytest tests/test_auth.py" \
  --max-rounds 5 \
  --max-same-failure 2
```

Require output artifacts in addition to passing tests:
```bash
agentctl iterate coder "Build application package" \
  --check "npm test" \
  --eval-artifact "dist/bundle.js" \
  --max-rounds 3
```

### 3. Dry-Run & Policy Inspection
Inspect agent selection, model routing, and approval requirements without executing:
```bash
agentctl do "Deploy changes to production server" --dry-run --json
```

---

## Architecture Overview

```
                      User Prompt / CLI
                             │
                      ┌──────▼──────┐
                      │ agentctl do │
                      └──────┬──────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [ Smart Intent Router ]            [ Policy Guardrails ]
   - Strict word-boundary matching    - Capability permissions
   - Action vs symptom distinction    - Path containment check
   - Fail-safe read-only fallback     - Explicit approvals gate
            │                                 │
            └────────────────┬────────────────┘
                             │
                   ┌─────────▼─────────┐
                   │  Execution Engine │
                   └─────────┬─────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   agentctl run (single)             agentctl iterate (loop)
            │                                 │
            │                        ┌────────▼────────┐
            │                        │   loop_engine   │
            │                        ├─────────────────┤
            │                        │ - Normalization │
            │                        │ - Fingerprint   │
            │                        │ - Anti-loop CAS │
            │                        │ - Gap diagnose  │
            │                        └────────┬────────┘
            │                                 │
            └────────────────┬────────────────┘
                             ▼
                 [ OpenCode / Runtime Bridge ]
                 - In-role execution (mode: all)
                 - Model variant & reasoning control
```

---

## Configuration

Configuration resides in `~/.config/runtime-agents/`:
- `agents.yaml`: Specialist roles, autonomy levels, default models, and capability rules.
- `tools.yaml`: Tool registry definitions.
- `profiles.yaml`: Workflow profiles for common tasks.

---

## Testing

Run the full unit and integration test suite:
```bash
python3 -m unittest discover -s tests
```

---

## License

Released under the [MIT License](LICENSE). Copyright &copy; 2026 Frank Zhang.
