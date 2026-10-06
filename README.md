<p align="center">
  <img src="assets/ambu-hero.png" alt="Ambu: The OpenCode Agent Supervisor" width="560">
</p>

# Ambu: The Supervisor for OpenCode Coding Agents

[![OpenCode: Compatible](https://img.shields.io/badge/OpenCode-Substrate%20Ready-blueviolet?style=flat-square&logo=terminal)](https://opencode.ai)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests: 274 Passing](https://img.shields.io/badge/Tests-274%20Passing-brightgreen?style=flat-square)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Version: 1.5.1](https://img.shields.io/badge/Version-v1.5.1-orange?style=flat-square)](CHANGELOG.md)
[![Stars](https://img.shields.io/github/stars/zzhang82/ambu-runtime-agents?style=flat-square&color=yellow)](https://github.com/zzhang82/ambu-runtime-agents)

**Ambu** (`agentctl`) is a supervisory control plane built specifically for [OpenCode](https://opencode.ai) coding agents. It routes natural language tasks to specialist personas, verifies workspace changes with automated test commands, and halts runaway retry loops before they burn API quota.

---

## The Problem with Raw Coding Agent Loops

Running autonomous coding agents directly inside a repository frequently hits three frustrating walls:

1. **Blind runaway loops**: When an agent encounters an environment bug or an impossible test constraint, it repeatedly retries up to your round limit—rewriting the same code, producing the exact same error, and burning through model quota.
2. **Arcane persona configuration**: OpenCode supports distinct specialist roles (`oracle`, `fixer`, `coder`, `designer`, `librarian`), but manually invoking them requires remembering custom CLI flags, configuration paths, and reasoning variants.
3. **Ungated permissions**: Agents run without safety gates, risking accidental `git push` commands, unintended deployments, secret leakage, or destructive file deletions.

**Ambu wraps `opencode run` as an intelligent supervisor:** it selects the right persona from your prompt, enforces policy guardrails, runs non-interactive execution, and validates every code modification against your test suite.

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
[Round 0] Running initial check: pytest tests/test_auth.py
          FAIL: test_token_expiration (AssertionError: 401 != 200)
          Fingerprint: sha256:7f4a3b8c (gap: execution)

[Round 1] Dispatching OpenCode agent (fixer · grok-4.7-build-fast)...
          Workspace modified. Re-running check...
          FAIL: test_token_expiration (AssertionError: 401 != 200)
          Fingerprint: sha256:7f4a3b8c [Seen 2x]

[HALT]    Identical blocker recurred >= 2 times.
          Status: BLOCKED (exit code 3)
          Stopped at Round 1. Prevented 4 runaway rounds. Quota saved.
```

---

## Architecture: The Michelin Kitchen Workflow

Ambu structures autonomous agent operations like a **Michelin-star kitchen brigade** (Brigade de Cuisine):

```
                        User Order Ticket
                               │
                        ┌──────▼──────┐
                        │ agentctl do │  (Head Chef / Order Dispatch)
                        └──────┬──────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   [ oracle ]             [ fixer / coder ]      [ designer / librarian ]
   Chef de Cuisine        Saucier / Line Cook    Pâtissier / Garde Manger
   (Architecture/Audit)   (Code Repair/Features) (UI Layout / Docs Prep)
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │  Dish / Workspace Patch
                        ┌──────▼──────────┐
                        │ agentctl iterate│  (The Pass / Expeditor)
                        ├─────────────────┤
                        │ - Run check cmd │
                        │ - Taste & audit │
                        │ - Hash errors   │
                        │ - Halt loops!   │
                        └──────┬──────────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
            [ Pass Plate ]            [ Stop Line ]
           Status: completed        Status: blocked (exit 3)
```

1. **Head Chef (`agentctl do`)**: Reads the incoming order ticket. Analyzes intent, detects negative constraints, and dispatches the work to the right specialist station.
2. **Kitchen Stations (OMO-Slim Roles)**:
   - **`oracle` (Chef de Cuisine)**: Architectural design, deep troubleshooting, security audits, and risk assessment (`read_only`).
   - **`fixer` (Saucier / Line Cook)**: Rapid bug fixes and bounded code patches (`workspace_write`).
   - **`coder` (Station Cook)**: Full feature implementation and new endpoint scaffolding (`workspace_write`).
   - **`designer` (Pâtissier)**: Visual presentation, UI/UX aesthetics, CSS layout, and responsive polish (`read_only`).
   - **`librarian` (Garde Manger)**: Cold pantry prep; retrieves documentation, library specs, and API references (`read_only`).
   - **`explorer` (Commis)**: Fast codebase reconnaissance, symbol search, and file discovery (`read_only`).
3. **The Pass (`agentctl iterate`)**: The expeditor station where no code leaves without passing rigorous acceptance criteria (`--check` and `--eval-artifact`).
   - If the dish fails, exact feedback is returned to the station.
   - **Anti-Loop**: If a station produces the exact same failure twice in a row, the pass halts immediately (`status: blocked`, exit code 3) to prevent burning API quota.
4. **Scullery & Hygiene (`agentctl doctor`)**: Verifies tool bindings, audits permissions, and keeps the workspace clean of stale artifacts.

### How Does a First-Time Installer Get These Roles & Models?

You do not need to configure complex YAML files just to get started:

- **Option A: Zero-Config with `oh-my-opencode-slim` (Recommended)**  
  If you already use [oh-my-opencode-slim](https://github.com/carlg/oh-my-opencode-slim), Ambu’s `slim_bridge` automatically inspects `~/.config/opencode/oh-my-opencode-slim.json`. It dynamically inherits your active preset's model assignments, reasoning variants (`xhigh`, `max`), and skill bindings with zero manual setup.
- **Option B: Out-of-the-Box Packaged Defaults (`default_agents.yaml`)**  
  On a fresh installation without OMO-Slim, Ambu ships with ready-to-use brigade defaults mapping stations to cost-effective model tiers:
  - **`review` tier (`oracle`)**: High-reasoning models (e.g. `gpt-6-astra`, `claude-sonnet`, `o1`).
  - **`implementation_ready` tier (`fixer`, `coder`)**: Fast, deterministic coding models (e.g. `grok-4.7-build-fast`, `gpt-5.5`).
  - **`design_planning` tier (`designer`)**: Multimodal / frontend styling models.
  - **`bounded_work` tier (`librarian`)**: High-throughput reference & retrieval models.
  - **`recon` tier (`explorer`)**: Low-cost, fast scanning models (e.g. `gemini-3.8-flash-high`).
- **Option C: Custom `agents.yaml`**  
  Create or customize `~/.config/runtime-agents/agents.yaml` to pin any specific local or API models configured in your OpenCode setup.

---

## 🧠 Shared Memory: Connecting with [Agent Memory Bridge (AMB)](https://github.com/zzhang82/Agent-Memory-Bridge)

In a Michelin kitchen, stations do not work in isolation. The brigade maintains a **Recipe Book & 86-Board (Incident Log)**: recording successful techniques, noting tricky ingredient quirks, and posting past mistakes so no cook repeats an error.

Ambu integrates natively with [Agent Memory Bridge (AMB)](https://github.com/zzhang82/Agent-Memory-Bridge) as its durable, governed memory layer:

<p align="center">
  <a href="https://github.com/zzhang82/Agent-Memory-Bridge">
    <img src="https://img.shields.io/badge/Memory%20Substrate-Agent--Memory--Bridge%20(AMB)-blueviolet?style=for-the-badge&logo=sqlite" alt="AMB Integration">
  </a>
</p>

### How Ambu + AMB Work Together

1. **Automatic Memory Recall Before Tasks**:  
   Whenever you run `agentctl do` or `agentctl iterate` inside a workspace, Ambu automatically queries AMB for stored gotchas, architectural decisions, and repository procedures matching your goal. Relevant records are prepended directly into the OpenCode agent's context prelude:
   ```text
   [Relevant Project Memory]
   Source: AMB record mem_8f2a1b9c (kind: gotcha)
   Claim: Auth token mock in tests requires setting TEST_JWT_SECRET environment variable.
   ```
2. **Cross-Station Mistake Sharing**:  
   If the `fixer` spends two rounds discovering that a database fixture requires a specific flag, that lesson can be stored to AMB (`agentMemoryBridge_store`). Tomorrow, when `coder` or `oracle` touches the same workspace, they inherit that insight on Round 0.
3. **Health & Verification**:  
   - `agentctl amb-health`: Inspects the active MCP stdio bridge connection and verifies memory tool availability.
   - `agentctl doctor`: Automatically validates that your AMB memory substrate is responsive.
   - `agentctl writeback`: Commits verified task outcomes, decisions, and lessons back into AMB after runs complete.

---

## Core Capabilities

### 1. Smart Intent Routing (`agentctl do`)
You don't need to remember arcane persona flags. Ambu uses word-boundary intent classification to route your prompt to the right kitchen station:

| Prompt Intent | Kitchen Station | Autonomy | Responsibility |
|---|---|---|---|
| *"Review database migrations for table lock risks"* | **`oracle`** | `read_only` | Architectural audit & diagnosis |
| *"Fix the broken auth login logic"* | **`fixer`** | `workspace_write` | Fast bug repair & patch |
| *"Implement the Stripe webhook billing endpoint"* | **`coder`** | `workspace_write` | Feature implementation |
| *"Make the navbar responsive with CSS layout"* | **`designer`** | `read_only` | UI/UX design & styling |
| *"Find documentation for Upstash Redis"* | **`librarian`** | `read_only` | Docs & reference research |

- **Negation Safety**: Prompts like *"Do not fix this, just review why it broke"* detect negation and immediately suppress write permissions.
- **Fail-Safe Fallback**: Any ambiguity or tied score strictly defaults to safe `read_only` (`oracle`).

### 2. Evidence-Bound Iteration (`agentctl iterate`)
- **Noise Normalization**: Strips wall-clock timings (`in 0.42s`), ISO timestamps, memory addresses (`0x7f...`), PIDs, and temp directories while preserving exact test failure line numbers.
- **Gap Diagnosis**: Categorizes failures using `stderr` and exit codes:
  - `execution`: Test assertion failures or Python tracebacks.
  - `environment`: Missing system dependencies or shell binary errors.
  - `check_rubric`: Invalid test commands (exit 126 / 127).
  - `transient`: Provider rate limits (429) or gateway timeouts.
- **Artifact Verification (`--eval-artifact`)**: Verifies that required output files exist and are non-empty before marking a task complete.

### 3. Policy Guardrails & Approvals
Ambu analyzes command prompts and agent capabilities before execution. High-risk actions (`git_push`, `deploy`, `secrets`, `global_config`, `destructive_delete`) are blocked unless explicitly passed with `--approve <capability>`.

---

## Requirements

- **Python**: `>= 3.10`
- **OpenCode CLI**: Installed and accessible in your `PATH` (`npm install -g opencode-ai`)
- **Authentication**: Uses your existing OpenCode authentication or gateway configuration.

---

## Installation

```bash
git clone https://github.com/zzhang82/ambu-runtime-agents.git
cd ambu-runtime-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify your installation:
```bash
agentctl doctor
agentctl selftest
```

---

## Quickstart

### Natural Language Task Dispatch
```bash
# Diagnostic review (auto-routes to oracle in read-only mode)
agentctl do "Review database schema for missing foreign key indexes"

# Code repair with automated test verification
agentctl do "Fix the broken user registration endpoint" --check "pytest tests/test_user.py"
```

### Bounded Iteration with Anti-Loop Protection
```bash
# Run up to 5 rounds, halting early if the same failure repeats twice
agentctl iterate coder "Fix payment receipt calculation" \
  --check "pytest tests/test_billing.py" \
  --max-rounds 5 \
  --max-same-failure 2
```

### Verifying Build Artifacts
```bash
# Require both a passing test and a non-empty build artifact
agentctl iterate coder "Compile frontend distribution" \
  --check "npm run build" \
  --eval-artifact "dist/bundle.js" \
  --max-rounds 3
```

### Dry-Run & Policy Preflight
```bash
# Inspect agent selection, guardrails, and model routing without running code
agentctl do "Push latest commit to production remote" --dry-run --json
```

---

## CLI Exit Codes

`agentctl iterate` and `agentctl do` return deterministic exit codes for CI/CD scripting:
- `0`: Task completed successfully (`completed`).
- `1`: Exhausted maximum rounds without passing (`failed`).
- `2`: Approval required or unauthorized capability detected.
- `3`: Halted early due to identical repeated blocker (`blocked`).

---

## Running Tests

Run the full automated test suite:
```bash
python3 -m unittest discover -s tests
```

---

## License

Released under the [MIT License](LICENSE). Copyright &copy; 2026 Frank Zhang.
