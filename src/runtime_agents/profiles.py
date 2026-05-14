from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from runtime_agents import paths as paths_mod
from runtime_agents import policy as policy_mod
from runtime_agents import tools_registry as tools_registry_mod


class ProfileValidationError(ValueError):
    pass


def packaged_profiles_path() -> Path:
    return Path(__file__).resolve().parent / "default_profiles.yaml"


def config_profiles_path() -> Path:
    return paths_mod.config_home() / "profiles.yaml"


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ProfileValidationError(f"{path.name}: top-level YAML must be a mapping")
    return data


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ProfileValidationError(f"{field_name} must be a list of strings")
    return [item.strip() for item in value]


def validate_profile(
    profile_id: str,
    spec: dict[str, Any],
    *,
    agent_names: set[str],
    workspace_names: set[str],
    tool_ids: set[str],
) -> dict[str, Any]:
    if not profile_id or not isinstance(profile_id, str):
        raise ProfileValidationError("profile id must be a non-empty string")
    if not isinstance(spec, dict):
        raise ProfileValidationError(f"{profile_id}: profile definition must be a mapping")
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ProfileValidationError(f"{profile_id}: missing title")
    description = spec.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ProfileValidationError(f"{profile_id}: missing description")
    default_agent = spec.get("default_agent")
    if not isinstance(default_agent, str) or not default_agent.strip():
        raise ProfileValidationError(f"{profile_id}: missing default_agent")
    default_agent = default_agent.strip()
    if default_agent not in agent_names:
        raise ProfileValidationError(f"{profile_id}: unknown default_agent {default_agent}")
    allowed_agents = _normalize_string_list(spec.get("allowed_agents"), field_name=f"{profile_id}: allowed_agents")
    if not allowed_agents:
        raise ProfileValidationError(f"{profile_id}: allowed_agents must not be empty")
    unknown_agents = sorted(agent for agent in allowed_agents if agent not in agent_names)
    if unknown_agents:
        raise ProfileValidationError(f"{profile_id}: unknown allowed_agents {', '.join(unknown_agents)}")
    if default_agent not in allowed_agents:
        raise ProfileValidationError(f"{profile_id}: default_agent must be included in allowed_agents")
    workspace = spec.get("workspace")
    if workspace is not None and not isinstance(workspace, str):
        raise ProfileValidationError(f"{profile_id}: workspace must be a string or null")
    if workspace and workspace not in workspace_names:
        raise ProfileValidationError(f"{profile_id}: unknown workspace {workspace}")
    workspace_required = bool(spec.get("workspace_required", False))
    memory_namespace = spec.get("memory_namespace")
    if memory_namespace is not None and not isinstance(memory_namespace, str):
        raise ProfileValidationError(f"{profile_id}: memory_namespace must be a string or null")
    allowed_tools = _normalize_string_list(spec.get("allowed_tools"), field_name=f"{profile_id}: allowed_tools")
    unknown_tools = sorted(tool for tool in allowed_tools if tool not in tool_ids)
    if unknown_tools:
        raise ProfileValidationError(f"{profile_id}: unknown allowed_tools {', '.join(unknown_tools)}")
    blocked_capabilities = _normalize_string_list(spec.get("blocked_capabilities"), field_name=f"{profile_id}: blocked_capabilities")
    approval_required = _normalize_string_list(spec.get("approval_required"), field_name=f"{profile_id}: approval_required")
    known_capabilities = policy_mod.known_capabilities()
    unknown_caps = sorted(cap for cap in blocked_capabilities + approval_required if cap not in known_capabilities)
    if unknown_caps:
        raise ProfileValidationError(f"{profile_id}: unknown capabilities {', '.join(sorted(set(unknown_caps)))}")
    default_run_goal = spec.get("default_run_goal")
    if default_run_goal is not None and not isinstance(default_run_goal, str):
        raise ProfileValidationError(f"{profile_id}: default_run_goal must be a string or null")
    default_plan_goal = spec.get("default_plan_goal")
    if default_plan_goal is not None and not isinstance(default_plan_goal, str):
        raise ProfileValidationError(f"{profile_id}: default_plan_goal must be a string or null")
    normalized = dict(spec)
    normalized.update(
        {
            "id": profile_id,
            "title": title.strip(),
            "description": description.strip(),
            "default_agent": default_agent,
            "allowed_agents": allowed_agents,
            "workspace": workspace,
            "workspace_required": workspace_required,
            "memory_namespace": memory_namespace,
            "allowed_tools": allowed_tools,
            "blocked_capabilities": blocked_capabilities,
            "approval_required": approval_required,
            "default_run_goal": default_run_goal,
            "default_plan_goal": default_plan_goal,
        }
    )
    return normalized


def _iter_sources() -> list[tuple[Path, str]]:
    return [
        (packaged_profiles_path(), "packaged"),
        (config_profiles_path(), "config"),
    ]


def inspect_profiles(*, strict: bool = False, agents: dict[str, Any] | None = None, workspaces: dict[str, Any] | None = None) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    loadable_by_id: dict[str, dict[str, Any]] = {}
    invalid_count = 0
    skipped_count = 0
    strict_ok = True
    agents = agents or {}
    workspaces = workspaces or {}
    tool_ids = {tool["id"] for tool in tools_registry_mod.load_tools()}
    agent_names = set(agents.keys())
    workspace_names = set(workspaces.keys())

    for path, source in _iter_sources():
        if not path.exists():
            continue
        try:
            raw = _load_yaml_file(path)
            items = raw.get("profiles") or {}
            if not isinstance(items, dict):
                raise ProfileValidationError(f"{path.name}: profiles must be a mapping")
            for profile_id, spec in items.items():
                try:
                    profile = validate_profile(
                        profile_id,
                        spec,
                        agent_names=agent_names,
                        workspace_names=workspace_names,
                        tool_ids=tool_ids,
                    )
                    profile["source"] = source
                    profile["source_path"] = str(path)
                    loadable_by_id[profile_id] = profile
                    records.append({
                        "id": profile_id,
                        "title": profile.get("title"),
                        "path": str(path),
                        "source": source,
                        "ok": True,
                        "loaded": True,
                        "skipped": False,
                        "error": "",
                        "warning": "",
                    })
                except Exception as exc:
                    invalid_count += 1
                    skipped_count += 1
                    is_packaged = source == "packaged"
                    records.append({
                        "id": profile_id,
                        "title": None,
                        "path": str(path),
                        "source": source,
                        "ok": False,
                        "loaded": False,
                        "skipped": True,
                        "error": str(exc),
                        "warning": "invalid packaged profile skipped during load" if is_packaged else "invalid config profile skipped during load",
                    })
                    if is_packaged or strict:
                        strict_ok = False
        except Exception as exc:
            invalid_count += 1
            skipped_count += 1
            is_packaged = source == "packaged"
            records.append({
                "id": None,
                "title": None,
                "path": str(path),
                "source": source,
                "ok": False,
                "loaded": False,
                "skipped": True,
                "error": str(exc),
                "warning": "invalid packaged profiles file" if is_packaged else "invalid config profiles file skipped during load",
            })
            if is_packaged or strict:
                strict_ok = False

    ok = strict_ok if strict else not any(item["source"] == "packaged" and not item["ok"] for item in records)
    warnings = [item["warning"] for item in records if item.get("warning")]
    return {
        "ok": ok,
        "strict": strict,
        "invalid_count": invalid_count,
        "skipped_count": skipped_count,
        "warnings": warnings,
        "profiles": records,
        "loadable": [loadable_by_id[key] for key in sorted(loadable_by_id.keys())],
    }


def load_profiles(*, agents: dict[str, Any] | None = None, workspaces: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return inspect_profiles(strict=False, agents=agents, workspaces=workspaces)["loadable"]


def validate_profiles(*, strict: bool = False, agents: dict[str, Any] | None = None, workspaces: dict[str, Any] | None = None) -> dict[str, Any]:
    inspected = inspect_profiles(strict=strict, agents=agents, workspaces=workspaces)
    return {
        "ok": inspected["ok"],
        "strict": strict,
        "invalid_count": inspected["invalid_count"],
        "skipped_count": inspected["skipped_count"],
        "warnings": inspected["warnings"],
        "profiles": inspected["profiles"],
    }
