# Shared Memory: Connecting with Agent Memory Bridge (AMB)

In a professional kitchen, stations do not work in isolation. The brigade maintains a **Recipe Book & 86-Board (Incident Log)**: recording successful techniques, noting tricky ingredient quirks, and posting past mistakes so no cook repeats an error.

Ambu integrates natively with [Agent Memory Bridge (AMB)](https://github.com/zzhang82/Agent-Memory-Bridge) as its durable, governed memory layer.

---

## 1. How Ambu + AMB Work Together

### Automatic Memory Recall Before Tasks
Whenever you run `agentctl do` or `agentctl iterate` inside a workspace, Ambu automatically queries AMB for stored gotchas, architectural decisions, and repository procedures matching your goal. Relevant records are prepended directly into the OpenCode agent's context prelude:

```text
[Relevant Project Memory]
Source: AMB record mem_8f2a1b9c (kind: gotcha)
Claim: Auth token mock in tests requires setting TEST_JWT_SECRET environment variable.
```

### Cross-Station Mistake Sharing
If `fixer` spends two rounds discovering that a database fixture requires a specific flag, that lesson can be stored to AMB (`agentMemoryBridge_store`). Tomorrow, when `coder` or `oracle` touches the same workspace, they inherit that insight on Round 0.

---

## 2. Health & Verification Commands

- **`agentctl amb-health`**: Inspects the active MCP stdio bridge connection and verifies memory tool availability.
- **`agentctl doctor`**: Automatically validates that your AMB memory substrate is responsive.
- **`agentctl writeback`**: Commits verified task outcomes, decisions, and lessons back into AMB after runs complete.
