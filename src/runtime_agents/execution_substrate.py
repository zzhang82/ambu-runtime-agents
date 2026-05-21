"""Execution substrate characterization helpers.

This module is intentionally descriptive for now. The OpenCode pivot needs a
stable baseline before defaults move away from legacy direct adapters.
"""

from __future__ import annotations

from typing import Any


LEGACY_DIRECT_TOOLS = {"codex", "claude", "gemini"}
INTENDED_PRIMARY_SUBSTRATE = "opencode"


def classify_agent_execution(agent_cfg: dict[str, Any]) -> dict[str, Any]:
    """Describe how an existing agent config will execute today."""
    tool = agent_cfg.get("tool")
    if tool in LEGACY_DIRECT_TOOLS:
        return {
            "execution_substrate": f"legacy-direct:{tool}",
            "tool": tool,
            "legacy_direct": True,
            "intended_primary_substrate": INTENDED_PRIMARY_SUBSTRATE,
        }
    if tool == INTENDED_PRIMARY_SUBSTRATE:
        return {
            "execution_substrate": INTENDED_PRIMARY_SUBSTRATE,
            "tool": tool,
            "legacy_direct": False,
            "intended_primary_substrate": INTENDED_PRIMARY_SUBSTRATE,
        }
    return {
        "execution_substrate": f"unknown:{tool}" if tool else "unknown",
        "tool": tool,
        "legacy_direct": False,
        "intended_primary_substrate": INTENDED_PRIMARY_SUBSTRATE,
    }


def build_opencode_exec_command(model: str | None, prompt: str, *, autonomy: str = "read_only") -> list[str]:
    """Return the intended non-interactive OpenCode command contract.

    Phase 0 does not route live execution through this command yet. The shape is
    captured here so Phase 1 can attach a fake executable test without guessing.
    """
    cmd = ["opencode", "run", "--print"]
    if model:
        cmd += ["--model", model]
    if autonomy == "workspace_write":
        cmd += ["--permission", "edit"]
    else:
        cmd += ["--permission", "read"]
    cmd.append(prompt)
    return cmd
