"""Execution substrate characterization helpers.

This module owns execution substrate characterization and OpenCode command
construction. OpenCode is the supported execution substrate.
"""

from __future__ import annotations

from typing import Any


INTENDED_PRIMARY_SUBSTRATE = "opencode"


def classify_agent_execution(agent_cfg: dict[str, Any]) -> dict[str, Any]:
    """Describe how an agent config will execute today."""
    tool = agent_cfg.get("tool")
    if tool == INTENDED_PRIMARY_SUBSTRATE:
        return {
            "execution_substrate": INTENDED_PRIMARY_SUBSTRATE,
            "tool": tool,
            "legacy_direct": False,
            "intended_primary_substrate": INTENDED_PRIMARY_SUBSTRATE,
        }
    raise ValueError(f"Unsupported execution substrate: {tool}")


def build_opencode_exec_command(
    model: str | None,
    prompt: str,
    *,
    autonomy: str = "read_only",
    opencode_agent: str | None = None,
    variant: str | None = None,
) -> list[str]:
    """Return the non-interactive OpenCode command contract."""
    cmd = ["opencode", "run"]
    if model:
        cmd += ["--model", model]
    if variant:
        cmd += ["--variant", variant]
    if opencode_agent:
        cmd += ["--agent", opencode_agent]
    cmd.append(prompt)
    return cmd
