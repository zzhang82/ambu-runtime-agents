from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from runtime_agents import paths as paths_mod
from runtime_agents import policy as policy_mod

ALLOWED_TOOL_KINDS = {"builtin", "mcp", "cli", "service"}
ALLOWED_TRUST_LEVELS = {"trusted", "untrusted_input", "untrusted_output", "mixed"}
ALLOWED_EGRESS = {"none", "local_only", "public_web", "private_network", "mixed", "telegram", "email", "web", "broker"}
LOCAL_TOOL_CAPABILITIES = {"web_read", "filesystem_read", "filesystem_write", "browser_read", "browser_write", "api_call", "mcp_use"}


class ToolValidationError(ValueError):
    pass


def packaged_tools_path() -> Path:
    return Path(__file__).resolve().parent / "default_tools.yaml"


def config_tools_path() -> Path:
    return paths_mod.config_home() / "tools.yaml"


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ToolValidationError(f"{path.name}: top-level YAML must be a mapping")
    return data


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ToolValidationError(f"{field_name} must be a list of strings")
    return [item.strip() for item in value]


def _tool_capabilities() -> set[str]:
    return policy_mod.known_capabilities() | LOCAL_TOOL_CAPABILITIES


def validate_tool(tool_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    if not tool_id or not isinstance(tool_id, str):
        raise ToolValidationError("tool id must be a non-empty string")
    if not isinstance(spec, dict):
        raise ToolValidationError(f"{tool_id}: tool definition must be a mapping")
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ToolValidationError(f"{tool_id}: missing title")
    description = spec.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ToolValidationError(f"{tool_id}: missing description")
    kind = spec.get("kind") or "builtin"
    if kind not in ALLOWED_TOOL_KINDS:
        raise ToolValidationError(f"{tool_id}: unsupported kind {kind}")
    enabled = bool(spec.get("enabled", True))
    command = spec.get("command")
    if command is not None and not isinstance(command, str):
        raise ToolValidationError(f"{tool_id}: command must be a string or null")
    args = spec.get("args") or []
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ToolValidationError(f"{tool_id}: args must be a list of strings")
    trust_level = spec.get("trust_level") or "trusted"
    if trust_level not in ALLOWED_TRUST_LEVELS:
        raise ToolValidationError(f"{tool_id}: unsupported trust_level {trust_level}")
    egress = spec.get("egress") or "none"
    if egress not in ALLOWED_EGRESS:
        raise ToolValidationError(f"{tool_id}: unsupported egress {egress}")
    capabilities = _normalize_string_list(spec.get("capabilities"), field_name=f"{tool_id}: capabilities")
    unknown_capabilities = sorted(cap for cap in capabilities if cap not in _tool_capabilities())
    if unknown_capabilities:
        raise ToolValidationError(f"{tool_id}: unknown capabilities {', '.join(unknown_capabilities)}")
    data_classes = _normalize_string_list(spec.get("data_classes"), field_name=f"{tool_id}: data_classes")
    profile_scope = _normalize_string_list(spec.get("profile_scope"), field_name=f"{tool_id}: profile_scope")
    workspace_scoped = bool(spec.get("workspace_scoped", False))
    normalized = dict(spec)
    normalized.update(
        {
            "id": tool_id,
            "title": title.strip(),
            "description": description.strip(),
            "kind": kind,
            "enabled": enabled,
            "command": command,
            "args": args,
            "trust_level": trust_level,
            "egress": egress,
            "capabilities": capabilities,
            "data_classes": data_classes,
            "profile_scope": profile_scope,
            "workspace_scoped": workspace_scoped,
        }
    )
    return normalized


def _iter_sources() -> list[tuple[Path, str]]:
    return [
        (packaged_tools_path(), "packaged"),
        (config_tools_path(), "config"),
    ]


def inspect_tools(*, strict: bool = False) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    loadable_by_id: dict[str, dict[str, Any]] = {}
    invalid_count = 0
    skipped_count = 0
    strict_ok = True

    for path, source in _iter_sources():
        if not path.exists():
            continue
        try:
            raw = _load_yaml_file(path)
            items = raw.get("tools") or {}
            if not isinstance(items, dict):
                raise ToolValidationError(f"{path.name}: tools must be a mapping")
            for tool_id, spec in items.items():
                try:
                    tool = validate_tool(tool_id, spec)
                    tool["source"] = source
                    tool["source_path"] = str(path)
                    loadable_by_id[tool_id] = tool
                    records.append({
                        "id": tool_id,
                        "title": tool.get("title"),
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
                        "id": tool_id,
                        "title": None,
                        "path": str(path),
                        "source": source,
                        "ok": False,
                        "loaded": False,
                        "skipped": True,
                        "error": str(exc),
                        "warning": "invalid packaged tool skipped during load" if is_packaged else "invalid config tool skipped during load",
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
                "warning": "invalid packaged tools file" if is_packaged else "invalid config tools file skipped during load",
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
        "tools": records,
        "loadable": [loadable_by_id[key] for key in sorted(loadable_by_id.keys())],
    }


def load_tools() -> list[dict[str, Any]]:
    return inspect_tools(strict=False)["loadable"]


def validate_tools(*, strict: bool = False) -> dict[str, Any]:
    inspected = inspect_tools(strict=strict)
    return {
        "ok": inspected["ok"],
        "strict": strict,
        "invalid_count": inspected["invalid_count"],
        "skipped_count": inspected["skipped_count"],
        "warnings": inspected["warnings"],
        "tools": inspected["tools"],
    }
