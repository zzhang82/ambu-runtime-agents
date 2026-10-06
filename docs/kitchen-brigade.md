# Architecture: The Michelin Kitchen Workflow

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

---

## 1. Brigade Roles & Stations

1. **Head Chef (`agentctl do`)**:
   Reads the incoming order ticket. Analyzes user intent, checks negative constraints (e.g. "do not fix, just review"), and dispatches the work to the right specialist station.
2. **Kitchen Stations (Specialist Roles)**:
   - **`oracle` (Chef de Cuisine)**: Architectural design, deep troubleshooting, security audits, and risk assessment (`read_only`).
   - **`fixer` (Saucier / Line Cook)**: Rapid bug fixes and bounded code patches (`workspace_write`).
   - **`coder` (Station Cook)**: Full feature implementation and new endpoint scaffolding (`workspace_write`).
   - **`designer` (Pâtissier)**: Visual presentation, UI/UX aesthetics, CSS layout, and responsive polish (`read_only`).
   - **`librarian` (Garde Manger)**: Cold pantry prep; retrieves documentation, library specs, and API references (`read_only`).
   - **`explorer` (Commis)**: Fast codebase reconnaissance, symbol search, and file discovery (`read_only`).
3. **The Pass (`agentctl iterate`)**:
   The expeditor station where no code leaves without passing rigorous acceptance criteria (`--check` and `--eval-artifact`).
   - If the dish fails, exact diagnostic feedback is returned to the station cook.
   - **Anti-Loop**: If a station produces the exact same failure twice in a row, the pass halts immediately (`status: blocked`, exit code 3) to prevent burning API quota.
4. **Scullery & Hygiene (`agentctl doctor`)**:
   Verifies tool bindings, audits permissions, and keeps the workspace clean of stale artifacts and failed queue residue.

---

## 2. Model Routing Tiers & Setup

First-time installers do not need complex YAML configuration to get started:

### Option A: Zero-Config with `oh-my-opencode-slim` (Recommended)
If you use [oh-my-opencode-slim](https://github.com/carlg/oh-my-opencode-slim), Ambu’s `slim_bridge` automatically inspects `~/.config/opencode/oh-my-opencode-slim.json`. It dynamically inherits your active preset's model assignments, reasoning variants (`xhigh`, `max`), and skill bindings with zero manual setup.

### Option B: Out-of-the-Box Packaged Defaults (`default_agents.yaml`)
On a fresh installation without OMO-Slim, Ambu automatically loads packaged brigade defaults mapping stations to cost-effective model tiers:
- **`review` tier (`oracle`)**: High-reasoning models (e.g. `gpt-6-astra`, `claude-sonnet`, `o1`).
- **`implementation_ready` tier (`fixer`, `coder`)**: Fast, deterministic coding models (e.g. `grok-4.7-build-fast`, `gpt-5.5`).
- **`design_planning` tier (`designer`)**: Multimodal / frontend styling models (`grok-4.7`).
- **`bounded_work` tier (`librarian`)**: High-throughput reference & retrieval models (`gpt-6-luna`).
- **`recon` tier (`explorer`)**: Low-cost, fast scanning models (`gemini-3.8-flash-high`).

### Option C: Custom `agents.yaml`
Create or customize `~/.config/runtime-agents/agents.yaml` to pin any specific local or API models configured in your OpenCode setup.
