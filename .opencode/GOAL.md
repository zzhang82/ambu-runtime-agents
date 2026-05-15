# Goal: runtime-agents Self-Improvement Milestone 1B

## Objective
Implement the sensing and scanning layer of the self-improvement pipeline. Differentiate already-forged skills from candidates, upgrade history ingestion with tool-level detail, and focus on sensing reliability without auto-forging.

## Milestone 1B Requirements
1. **`runtime-self-improve scan`**:
    - Load events from `~/.runtime-agents/events/agent-runs.jsonl`.
    - Cluster `user_goal` patterns.
    - Match patterns against currently installed skills (e.g. `ljg-skill-mentor`, `repo-workflow-cartographer`).
    - Identify P0 candidates (patterns with 3+ occurrences not covered by existing skills).
2. **Adapter Upgrade**:
    - Improve `ClaudeCCRAdapter` to ingest MCP/tool-level data if possible.
    - Add `tools_used` or `mcp_ops` to the `AgentRunEvent` schema.
3. **Validation**:
    - Verify scanning accuracy against the ingested history.

## Success Conditions
- `runtime-self-improve scan` reports existing skills correctly.
- `runtime-self-improve scan` identifies new candidates with frequency counts.
- `ingest` now captures tool-level evidence when available.
- No auto-forging of skills (sensing only).
