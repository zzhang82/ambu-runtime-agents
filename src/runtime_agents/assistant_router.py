import re


DANGEROUS_PATTERNS = ("deploy", "git push", "push to", "secret", "delete everything", "rm -rf", "global config", "global install")


def extract_workspace_from_text(text, workspace_names):
    for name in workspace_names:
        if re.search(rf"\b{re.escape(name)}\b", text):
            return name
    match = re.search(r"\b([A-Za-z0-9_.:-]+-ws)\b", text)
    return match.group(1) if match else None


def route_assistant_message(message, session=None, workspace_names=None, latest_blocked_plan_id=None, latest_failed_schedule_id=None):
    text = (message or "").strip()
    lowered = text.lower()
    session = session or {}
    workspace_names = workspace_names or []

    if any(p in lowered for p in DANGEROUS_PATTERNS):
        return {
            "intent": "refuse_dangerous",
            "risk": "blocked",
            "requires_confirmation": False,
            "actions": [],
            "reply": "I can't run deploy, git push, secrets, destructive, global config, or global install actions from Telegram v1.1. I can help create a review plan instead.",
        }

    normalized = lowered.rstrip("?!.")
    if normalized in {"what's going on", "whats going on", "status", "what is going on", "what needs attention", "what should i do next"} or "blocked" in lowered and "what" in lowered:
        return {"intent": "status_overview", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "status_overview"}], "reply_style": "summary"}
    if "queue" in lowered:
        return {"intent": "list_queue", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "list_queue"}], "reply_style": "summary"}
    if "running" in lowered and "plan" in lowered:
        return {"intent": "list_plans", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "list_plans", "status": "running"}], "reply_style": "summary"}
    if "schedule" in lowered and "retry" not in lowered and "fail" not in lowered:
        return {"intent": "list_schedules", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "list_schedules"}], "reply_style": "summary"}
    if "plan" in lowered and "repair" not in lowered and "approve" not in lowered:
        return {"intent": "list_plans", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "list_plans"}], "reply_style": "summary"}

    workspace = extract_workspace_from_text(lowered, workspace_names) or session.get("last_workspace")
    if lowered.startswith("check") or "health" in lowered:
        workspace = workspace or "test-ws"
        return {"intent": "repo_health_check", "workspace": workspace, "mode": "diagnose", "check": "pytest -q", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "submit_iterate", "workspace": workspace, "agent": "planner", "goal": "Check repo health. Analyze failures only. Do not edit files.", "check": "pytest -q", "max_rounds": 1}], "reply_style": "queued"}
    if "fix" in lowered or "failing test" in lowered or "failing tests" in lowered:
        workspace = workspace or "test-ws"
        return {"intent": "fix_issue", "workspace": workspace, "goal": "Fix failing tests", "risk": "workspace_write", "requires_confirmation": True, "actions": [{"type": "create_plan", "workspace": workspace, "goal": "Fix failing tests"}], "reply_style": "confirm"}
    if "repair" in lowered:
        plan_id_value = session.get("last_plan_id") or latest_blocked_plan_id
        return {"intent": "plan_recovery", "plan_id": plan_id_value, "action": "repair", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "repair_plan", "plan_id": plan_id_value}], "reply_style": "summary"}
    if "retry" in lowered and "schedule" in lowered:
        schedule = session.get("last_schedule") or latest_failed_schedule_id
        return {"intent": "schedule_recovery", "schedule": schedule, "action": "retry", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "retry_schedule", "schedule": schedule}], "reply_style": "queued"}
    if "show logs" in lowered or lowered == "logs" or lowered == "show logs":
        task_id_value = session.get("last_task_id")
        return {"intent": "show_logs", "task_id": task_id_value, "risk": "safe", "requires_confirmation": False, "actions": [{"type": "show_task", "task_id": task_id_value}], "reply_style": "summary"}
    return {"intent": "status_overview", "risk": "safe", "requires_confirmation": False, "actions": [{"type": "status_overview"}], "reply_style": "summary", "note": "fallback_status"}
