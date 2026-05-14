import re

from runtime_agents import runbooks as runbooks_mod


DANGEROUS_PATTERNS = ("deploy", "git push", "push to", "secret", "delete everything", "rm -rf", "global config", "global install")


def extract_workspace_from_text(text, workspace_names):
    for name in workspace_names:
        if re.search(rf"\b{re.escape(name)}\b", text):
            return name
    match = re.search(r"\b([A-Za-z0-9_.:-]+-ws)\b", text)
    return match.group(1) if match else None


def _legacy_fields(payload):
    inputs = payload.get("inputs") or {}
    mapped = dict(payload)
    mapped["intent"] = payload.get("runbook_id")
    mapped["reply"] = payload.get("message") or payload.get("question") or ""
    mapped["workspace"] = inputs.get("workspace")
    mapped["task_id"] = inputs.get("task_id")
    mapped["plan_id"] = inputs.get("plan_id")
    mapped["schedule"] = inputs.get("schedule")
    if payload.get("status") == "needs_clarification":
        mapped["reply_style"] = "clarify"
    elif payload.get("requires_confirmation"):
        mapped["reply_style"] = "confirm"
    elif payload.get("risk") == "read_only":
        mapped["reply_style"] = "summary"
    else:
        mapped["reply_style"] = "queued"
    return mapped


def route_assistant_message(message, session=None, workspace_names=None, latest_blocked_plan_id=None, latest_failed_schedule_id=None):
    text = (message or "").strip()
    lowered = text.lower()
    session = session or {}
    workspace_names = workspace_names or []

    if any(p in lowered for p in DANGEROUS_PATTERNS):
        return {
            "status": "blocked",
            "runbook_id": None,
            "title": "Blocked request",
            "risk": "blocked",
            "requires_confirmation": False,
            "actions": [],
            "message": "I can't run deploy, git push, secrets, destructive, global config, or global install actions from assistant mode.",
            "intent": "refuse_dangerous",
            "reply": "I can't run deploy, git push, secrets, destructive, global config, or global install actions from assistant mode.",
            "reply_style": "summary",
        }

    matched = runbooks_mod.match_runbook(
        text,
        session=session,
        workspace_names=workspace_names,
        latest_blocked_plan_id=latest_blocked_plan_id,
        latest_failed_schedule_id=latest_failed_schedule_id,
    )
    if matched:
        return _legacy_fields(matched)

    return {
        "status": "unsupported",
        "runbook_id": None,
        "title": "Unsupported request",
        "risk": "read_only",
        "requires_confirmation": False,
        "actions": [],
        "message": "I don't have a supported runbook for that yet.",
        "intent": "unsupported",
        "reply": "I don't have a supported runbook for that yet.",
        "reply_style": "summary",
    }
