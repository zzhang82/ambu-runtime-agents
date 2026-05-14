from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from runtime_agents import paths as paths_mod

ALLOWED_ACTION_TYPES = {
    "status_overview",
    "list_workspaces",
    "list_runbooks",
    "list_queue",
    "list_plans",
    "list_schedules",
    "show_task",
    "show_logs",
    "show_plan",
    "submit_run",
    "submit_iterate",
    "create_plan",
    "repair_plan",
    "retry_plan_subtask",
    "retry_schedule",
    "pause",
    "resume",
}

BLOCKED_ACTION_TYPES = {"shell", "exec", "bash", "raw_command", "python_eval", "arbitrary_agentctl"}
ALLOWED_RISKS = {"read_only", "workspace_write", "blocked"}
INPUT_TYPES = {"workspace", "task_id", "plan_id", "schedule", "id", "text"}
PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
TASK_ID_PATTERN = re.compile(r"\b\d{8}-[0-9]{6}(?:-(?:iterate|queue|plan))?-[A-Za-z0-9_-]+\b")
PLAN_ID_PATTERN = re.compile(r"\b\d{8}-[0-9]{6}-plan-[A-Za-z0-9]+\b")


class RunbookValidationError(ValueError):
    pass


class RunbookMatchError(ValueError):
    pass


def packaged_runbooks_dir() -> Path:
    return Path(__file__).resolve().parent / "default_runbooks"


def config_runbooks_dir() -> Path:
    return paths_mod.config_home() / "runbooks"


def parse_runbook_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RunbookValidationError(f"{path.name}: empty file")
    if not text.startswith("---\n"):
        raise RunbookValidationError(f"{path.name}: missing YAML frontmatter")
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        raise RunbookValidationError(f"{path.name}: malformed YAML frontmatter")
    _, remainder = parts
    frontmatter_text = text[4 : len(text) - len(remainder) - 5]
    frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(frontmatter, dict):
        raise RunbookValidationError(f"{path.name}: frontmatter must be a mapping")
    body = remainder
    data = dict(frontmatter)
    data["body"] = body
    data["source_path"] = str(path)
    data["source_file"] = path.name
    return data


def _normalize_inputs(inputs: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    inputs = inputs or {}
    if not isinstance(inputs, dict):
        raise RunbookValidationError("inputs must be a mapping")
    normalized: dict[str, dict[str, Any]] = {}
    for name, spec in inputs.items():
        if not isinstance(spec, dict):
            raise RunbookValidationError(f"input '{name}' must be a mapping")
        input_type = spec.get("type")
        if input_type not in INPUT_TYPES:
            raise RunbookValidationError(f"input '{name}' has unsupported type: {input_type}")
        normalized[name] = {
            "type": input_type,
            "required": bool(spec.get("required", False)),
        }
    return normalized


def _placeholders_in_value(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(PLACEHOLDER_PATTERN.findall(value))
    if isinstance(value, list):
        names: set[str] = set()
        for item in value:
            names.update(_placeholders_in_value(item))
        return names
    if isinstance(value, dict):
        names: set[str] = set()
        for item in value.values():
            names.update(_placeholders_in_value(item))
        return names
    return set()


def validate_runbook(runbook: dict[str, Any]) -> dict[str, Any]:
    runbook_id = runbook.get("id")
    if not runbook_id or not isinstance(runbook_id, str):
        raise RunbookValidationError("missing id")
    title = runbook.get("title")
    if not title or not isinstance(title, str):
        raise RunbookValidationError(f"{runbook_id}: missing title")
    risk = runbook.get("risk")
    if risk not in ALLOWED_RISKS:
        raise RunbookValidationError(f"{runbook_id}: unknown risk {risk}")
    phrases = runbook.get("phrases")
    if not isinstance(phrases, list) or not phrases or not all(isinstance(p, str) and p.strip() for p in phrases):
        raise RunbookValidationError(f"{runbook_id}: phrases must be a non-empty list of strings")
    actions = runbook.get("actions")
    if not isinstance(actions, list) or not actions:
        raise RunbookValidationError(f"{runbook_id}: missing actions")
    response = runbook.get("response") or {}
    if response and not isinstance(response, dict):
        raise RunbookValidationError(f"{runbook_id}: response must be a mapping")
    inputs = _normalize_inputs(runbook.get("inputs"))

    for action in actions:
        if not isinstance(action, dict):
            raise RunbookValidationError(f"{runbook_id}: each action must be a mapping")
        action_type = action.get("type")
        if action_type in BLOCKED_ACTION_TYPES:
            raise RunbookValidationError(f"{runbook_id}: blocked action type {action_type}")
        if action_type not in ALLOWED_ACTION_TYPES:
            raise RunbookValidationError(f"{runbook_id}: unsupported action type {action_type}")

    placeholders = set()
    for phrase in phrases:
        placeholders.update(PLACEHOLDER_PATTERN.findall(phrase))
    placeholders.update(_placeholders_in_value(actions))
    placeholders.update(_placeholders_in_value(response))
    unknown = sorted(name for name in placeholders if name not in inputs)
    if unknown:
        raise RunbookValidationError(f"{runbook_id}: unknown placeholders {', '.join(unknown)}")
    for name in placeholders:
        if name not in inputs:
            raise RunbookValidationError(f"{runbook_id}: missing input schema for {name}")

    normalized = dict(runbook)
    normalized["inputs"] = inputs
    normalized["requires_confirmation"] = bool(runbook.get("requires_confirmation", False))
    normalized["description"] = str(runbook.get("description") or "")
    normalized["response"] = response or {}
    normalized["phrases"] = [phrase.strip() for phrase in phrases]
    normalized["actions"] = actions
    return normalized


def load_runbook_from_path(path: Path) -> dict[str, Any]:
    return validate_runbook(parse_runbook_file(path))


def load_runbooks() -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for directory, source in ((packaged_runbooks_dir(), "packaged"), (config_runbooks_dir(), "config")):
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            try:
                runbook = load_runbook_from_path(path)
            except RunbookValidationError:
                continue
            runbook["source"] = source
            by_id[runbook["id"]] = runbook
    return [by_id[key] for key in sorted(by_id.keys())]


def render_template(value: Any, inputs: dict[str, str]) -> Any:
    if isinstance(value, str):
        return PLACEHOLDER_PATTERN.sub(lambda match: str(inputs.get(match.group(1), match.group(0))), value)
    if isinstance(value, list):
        return [render_template(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, inputs) for key, item in value.items()}
    return value


def compile_phrase_template(phrase: str, input_specs: dict[str, dict[str, Any]], workspace_names: list[str] | None = None) -> tuple[re.Pattern[str], list[str]]:
    workspace_names = workspace_names or []
    parts: list[str] = []
    placeholders: list[str] = []
    cursor = 0
    for match in PLACEHOLDER_PATTERN.finditer(phrase):
        literal = phrase[cursor:match.start()]
        parts.append(re.escape(literal))
        name = match.group(1)
        placeholders.append(name)
        spec = input_specs[name]
        if spec["type"] == "workspace" and workspace_names:
            pattern = "|".join(sorted((re.escape(name) for name in workspace_names), key=len, reverse=True))
            parts.append(f"(?P<{name}>{pattern})")
        elif spec["type"] == "task_id":
            parts.append(f"(?P<{name}>[A-Za-z0-9_.:-]+)")
        elif spec["type"] == "plan_id":
            parts.append(f"(?P<{name}>[A-Za-z0-9_.:-]+)")
        elif spec["type"] == "schedule":
            parts.append(f"(?P<{name}>[A-Za-z0-9_.:-]+)")
        else:
            parts.append(f"(?P<{name}>.+?)")
        cursor = match.end()
    parts.append(re.escape(phrase[cursor:]))
    pattern = "^" + "".join(parts).replace(r"\ ", r"\s+") + "$"
    return re.compile(pattern, re.IGNORECASE), placeholders


def extract_default_value(input_name: str, input_spec: dict[str, Any], text: str, session: dict[str, Any], workspace_names: list[str], latest_blocked_plan_id: str | None, latest_failed_schedule_id: str | None) -> str | None:
    lowered = text.lower()
    input_type = input_spec["type"]
    if input_type == "workspace":
        from runtime_agents.assistant_router import extract_workspace_from_text

        return extract_workspace_from_text(lowered, workspace_names) or session.get("last_workspace")
    if input_type == "task_id":
        match = TASK_ID_PATTERN.search(text)
        return match.group(0) if match else session.get("last_task_id")
    if input_type == "plan_id":
        match = PLAN_ID_PATTERN.search(text)
        return match.group(0) if match else session.get("last_plan_id") or latest_blocked_plan_id
    if input_type == "schedule":
        if session.get("last_schedule"):
            return session.get("last_schedule")
        tokens = [token.strip("?!.,") for token in lowered.split() if token.strip("?!.,")]
        for token in tokens:
            if token not in {"retry", "schedule", "schedules"}:
                return token
        return latest_failed_schedule_id
    if input_type == "id":
        return session.get("last_id")
    return None


def match_runbook(message: str, *, session: dict[str, Any] | None = None, workspace_names: list[str] | None = None, latest_blocked_plan_id: str | None = None, latest_failed_schedule_id: str | None = None) -> dict[str, Any] | None:
    text = (message or "").strip()
    session = session or {}
    workspace_names = workspace_names or []
    for runbook in load_runbooks():
        input_specs = runbook["inputs"]
        for phrase in runbook["phrases"]:
            pattern, _placeholders = compile_phrase_template(phrase, input_specs, workspace_names=workspace_names)
            match = pattern.match(text)
            extracted: dict[str, str] = {}
            if match:
                extracted = {key: value.strip() for key, value in match.groupdict().items() if value is not None}
            else:
                if any(PLACEHOLDER_PATTERN.findall(phrase)):
                    continue
                normalized_text = re.sub(r"\s+", " ", text.lower().rstrip("?!."))
                normalized_phrase = re.sub(r"\s+", " ", phrase.lower().rstrip("?!."))
                if normalized_text != normalized_phrase:
                    continue
            missing_required = []
            for name, spec in input_specs.items():
                if name not in extracted or not extracted[name]:
                    fallback = extract_default_value(name, spec, text, session, workspace_names, latest_blocked_plan_id, latest_failed_schedule_id)
                    if fallback:
                        extracted[name] = fallback
                if spec.get("required") and not extracted.get(name):
                    missing_required.append(name)
            if missing_required:
                return {
                    "status": "needs_clarification",
                    "runbook_id": runbook["id"],
                    "title": runbook["title"],
                    "risk": runbook["risk"],
                    "requires_confirmation": runbook["requires_confirmation"],
                    "missing_inputs": missing_required,
                    "question": f"Which {missing_required[0].replace('_', ' ')}?",
                }
            actions = [render_template(action, extracted) for action in runbook["actions"]]
            message_text = runbook["response"].get("matched") or runbook["response"].get("queued") or runbook["description"] or runbook["title"]
            return {
                "status": "matched",
                "runbook_id": runbook["id"],
                "title": runbook["title"],
                "risk": runbook["risk"],
                "requires_confirmation": runbook["requires_confirmation"],
                "inputs": extracted,
                "actions": actions,
                "message": render_template(message_text, extracted),
                "confirm_message": render_template(runbook["response"].get("confirm") or "", extracted) if runbook["response"].get("confirm") else "",
                "source": runbook.get("source"),
            }
    return None


def validate_runbooks() -> dict[str, Any]:
    payload = []
    overall_ok = True
    seen_ids: set[str] = set()
    for directory, source in ((packaged_runbooks_dir(), "packaged"), (config_runbooks_dir(), "config")):
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            try:
                runbook = load_runbook_from_path(path)
                duplicate = runbook["id"] in seen_ids and source == "packaged"
                payload.append({
                    "id": runbook["id"],
                    "title": runbook["title"],
                    "file": path.name,
                    "path": str(path),
                    "source": source,
                    "ok": not duplicate,
                    "error": "duplicate id" if duplicate else "",
                })
                if not duplicate:
                    seen_ids.add(runbook["id"])
                overall_ok = overall_ok and not duplicate
            except Exception as exc:
                payload.append({
                    "id": None,
                    "title": None,
                    "file": path.name,
                    "path": str(path),
                    "source": source,
                    "ok": False,
                    "error": str(exc),
                })
                overall_ok = False
    return {"ok": overall_ok, "runbooks": payload}
