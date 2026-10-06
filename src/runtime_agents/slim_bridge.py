"""Bridge between oh-my-opencode-slim and runtime-agents (agentctl).

Discovers roles, models, reasoning variants, and tool/mcp bindings configured in
oh-my-opencode-slim.json and dynamically overlays them onto runtime-agents so
commands like `agentctl run oracle` or `agentctl iterate fixer` execute directly
in-role with correct model configurations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_SLIM_CONFIG_PATH = Path.home() / ".config" / "opencode" / "oh-my-opencode-slim.json"

WRITE_CAPABLE_ROLES = {"fixer", "coder", "build", "eli"}

ROUTING_FRAME_MAP = {
    "oracle": "review",
    "librarian": "bounded_work",
    "explorer": "recon",
    "designer": "design_planning",
    "fixer": "implementation_ready",
    "council": "orchestrator",
    "orchestrator": "orchestrator",
    "councillor": "review",
    "scout-flash": "recon",
    "jules": "bounded_work",
    "eli": "implementation_ready",
    "ren": "review",
    "klaus-validator": "review",
    "lucien": "bounded_work",
}

READ_ONLY_APPROVALS = [
    "workspace_write",
    "git_push",
    "deploy",
    "secrets",
    "global_config",
    "destructive_delete",
    "global_install",
]

WORKSPACE_WRITE_APPROVALS = [
    "git_push",
    "deploy",
    "secrets",
    "global_config",
    "destructive_delete",
    "global_install",
]


def resolve_slim_config_path(override_path: Path | str | None = None) -> Path:
    """Resolve the path to oh-my-opencode-slim.json."""
    if override_path:
        return Path(override_path).expanduser().resolve()
    env_path = os.environ.get("OPENCODE_SLIM_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_SLIM_CONFIG_PATH


def load_slim_config(path: Path | str | None = None) -> dict[str, Any] | None:
    """Load and parse oh-my-opencode-slim.json. Returns None if missing or invalid."""
    config_file = resolve_slim_config_path(path)
    if not config_file.is_file():
        return None
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_active_preset(slim_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the active preset name and its dictionary of role configurations."""
    preset_name = slim_data.get("preset", "cole-local")
    presets = slim_data.get("presets", {})
    if preset_name in presets and isinstance(presets[preset_name], dict):
        return preset_name, presets[preset_name]
    if presets and isinstance(presets, dict):
        first_key = next(iter(presets))
        if isinstance(presets[first_key], dict):
            return first_key, presets[first_key]
    return "unknown", {}


def discover_slim_agents(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Discover all agents and roles defined in the active slim preset.

    Produces a dictionary of runtime-agents compatible agent configurations.
    """
    slim_data = load_slim_config(path)
    if not slim_data:
        return {}

    disabled_agents = set(slim_data.get("disabled_agents") or [])
    preset_name, preset_roles = get_active_preset(slim_data)
    discovered: dict[str, dict[str, Any]] = {}

    for role_name, role_cfg in preset_roles.items():
        if not isinstance(role_cfg, dict) or role_name in disabled_agents:
            continue

        model = role_cfg.get("model")
        variant = role_cfg.get("variant")
        skills = role_cfg.get("skills", [])
        mcps = role_cfg.get("mcps", [])

        is_writer = role_name in WRITE_CAPABLE_ROLES
        autonomy = "workspace_write" if is_writer else "read_only"
        approvals = list(WORKSPACE_WRITE_APPROVALS if is_writer else READ_ONLY_APPROVALS)

        routing_frame = ROUTING_FRAME_MAP.get(role_name, "bounded_work" if is_writer else "review")

        discovered[role_name] = {
            "tool": "opencode",
            "model": model,
            "variant": variant,
            "opencode_agent": role_name,
            "routing_frame": routing_frame,
            "autonomy": autonomy,
            "approval_required": approvals,
            "skills": skills,
            "mcps": mcps,
            "source": f"slim:{preset_name}",
        }

    return discovered


def overlay_slim_agents(
    config: dict[str, Any],
    slim_path: Path | str | None = None,
) -> dict[str, Any]:
    """Overlay discovered slim agents onto a runtime-agents configuration.

    - Adds any Slim role that does not yet exist in config['agents'].
    - Enriches existing agents with Slim model/variant defaults if not explicitly set.
    """
    if not isinstance(config, dict):
        return config

    agents = dict(config.get("agents") or {})
    discovered = discover_slim_agents(slim_path)

    for role_name, slim_agent in discovered.items():
        if role_name not in agents:
            agents[role_name] = slim_agent
        else:
            existing = dict(agents[role_name])
            # If variant is set in Slim but not in agents.yaml, adopt it
            if "variant" not in existing and slim_agent.get("variant"):
                existing["variant"] = slim_agent["variant"]
            # If opencode_agent is missing or is generic 'build', align it with role name if recognized
            if existing.get("opencode_agent") in (None, "build") and role_name in ROUTING_FRAME_MAP:
                existing["opencode_agent"] = role_name
            agents[role_name] = existing

    enriched = dict(config)
    enriched["agents"] = agents
    return enriched
