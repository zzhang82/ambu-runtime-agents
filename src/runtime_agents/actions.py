from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime_agents import guardrails as guardrails_mod
from runtime_agents.models import ActionResult


DepMap = dict[str, Any]


def _execution_payload(route: dict[str, Any], result: ActionResult, execution: list[dict[str, Any]], *, preserve_matched_status: bool = False) -> dict[str, Any]:
    payload = dict(route)
    payload["status"] = route.get("status") if preserve_matched_status else result.status
    if result.message is not None:
        payload["message"] = result.message
    payload["action_result"] = result.to_payload()
    payload["execution"] = execution
    return payload


def _completed_route_payload(route: dict[str, Any], execution: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(route)
    payload["execution"] = execution
    payload["action_result"] = ActionResult.completed("assistant_exec", route.get("risk") or "read_only", _assistant_exec_counts(execution), route.get("message")).to_payload()
    return payload


def _assistant_exec_counts(execution: list[dict[str, Any]]) -> dict[str, int]:
    result = {"count": len(execution), "action_count": len(execution)}
    for item in execution:
        if isinstance(item.get("workspaces"), dict):
            result["workspace_count"] = len(item["workspaces"])
        if isinstance(item.get("profiles"), dict):
            result["profile_count"] = len(item["profiles"])
        if isinstance(item.get("tools"), dict):
            result["tool_count"] = len(item["tools"])
        if isinstance(item.get("items"), list):
            result["queue_item_count"] = len(item["items"])
    return result


def _failed_route_payload(route: dict[str, Any], result: ActionResult, execution: list[dict[str, Any]]) -> dict[str, Any]:
    return _execution_payload(route, result, execution)


def _pending_route_payload(route: dict[str, Any], result: ActionResult) -> dict[str, Any]:
    return _execution_payload(route, result, [], preserve_matched_status=False)


def _passthrough_route_payload(route: dict[str, Any]) -> dict[str, Any]:
    return dict(route)


def _route_result_payload(route: dict[str, Any], result: ActionResult, execution: list[dict[str, Any]]) -> dict[str, Any]:
    if result.status == "completed":
        return _completed_route_payload(route, execution)
    if result.status == "pending_confirmation":
        return _pending_route_payload(route, result)
    return _failed_route_payload(route, result, execution)


def _runbook_listing(load_runbooks: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "risk": item.get("risk"),
            "requires_confirmation": item.get("requires_confirmation"),
            "source": item.get("source"),
        }
        for item in load_runbooks()
    ]


def execute_action(action: dict[str, Any], route: dict[str, Any] | None = None, *, dry_run: bool = False, deps: DepMap | None = None) -> ActionResult:
    del dry_run
    deps = deps or {}
    route = route or {}
    action_type = action.get("type") or "unknown"
    risk = route.get("risk") or "read_only"

    try:
        if action_type == "status_overview":
            return ActionResult.completed(
                action_type,
                risk,
                {
                    "type": action_type,
                    "daemon": deps["daemon_status_payload"](),
                    "queue": list(deps["latest_queue_items"]().values()),
                    "plans": deps["list_plans"](),
                    "schedules": [s for s in deps["latest_schedules"]().values() if not s.get("removed")],
                },
            )
        if action_type == "list_workspaces":
            return ActionResult.completed(action_type, risk, {"type": action_type, "workspaces": deps["load_workspaces"]()})
        if action_type == "list_runbooks":
            return ActionResult.completed(action_type, risk, {"type": action_type, "runbooks": _runbook_listing(deps["load_runbooks"])})
        if action_type == "list_queue":
            return ActionResult.completed(action_type, risk, {"type": action_type, "items": list(deps["latest_queue_items"]().values())})
        if action_type == "list_plans":
            items = deps["list_plans"]()
            status_filter = action.get("status")
            if status_filter:
                items = [item for item in items if deps["derive_plan_status"](item).get("status") == status_filter]
            return ActionResult.completed(action_type, risk, {"type": action_type, "plans": items})
        if action_type == "list_schedules":
            return ActionResult.completed(
                action_type,
                risk,
                {"type": action_type, "schedules": [s for s in deps["latest_schedules"]().values() if not s.get("removed")]},
            )
        if action_type == "list_profiles":
            return ActionResult.completed(action_type, risk, {"type": action_type, "profiles": deps["load_profiles_registry"]()})
        if action_type == "show_profile":
            profile = deps["profiles_by_id"]().get(action.get("profile_id"))
            if not profile:
                return ActionResult.failed(action_type, risk, f"Unknown profile: {action.get('profile_id')}")
            return ActionResult.completed(action_type, risk, {"type": action_type, "profile": profile})
        if action_type == "list_tools":
            return ActionResult.completed(action_type, risk, {"type": action_type, "tools": deps["load_tools_registry"]()})
        if action_type == "show_tool":
            tool = deps["tools_by_id"]().get(action.get("tool_id"))
            if not tool:
                return ActionResult.failed(action_type, risk, f"Unknown tool: {action.get('tool_id')}")
            return ActionResult.completed(action_type, risk, {"type": action_type, "tool": tool})
        if action_type == "show_task":
            task = deps["latest_task"](action.get("task_id"))
            if not task:
                return ActionResult.failed(action_type, risk, f"Unknown task id: {action.get('task_id')}")
            return ActionResult.completed(action_type, risk, {"type": action_type, "task": task})
        if action_type == "show_logs":
            task = deps["latest_task"](action.get("task_id"))
            if not task:
                return ActionResult.failed(action_type, risk, f"Unknown task id: {action.get('task_id')}")
            run_dir = Path(task["run_dir"])
            return ActionResult.completed(
                action_type,
                risk,
                {
                    "type": action_type,
                    "task_id": action.get("task_id"),
                    "stdout": (run_dir / "stdout.log").read_text(encoding="utf-8") if (run_dir / "stdout.log").exists() else "",
                    "stderr": (run_dir / "stderr.log").read_text(encoding="utf-8") if (run_dir / "stderr.log").exists() else "",
                },
            )
        if action_type == "show_plan":
            return ActionResult.completed(action_type, risk, {"type": action_type, "plan": deps["load_plan"](action.get("plan_id"))})
        if action_type == "repair_plan":
            plan = deps["load_plan"](action.get("plan_id"))
            return ActionResult.completed(
                action_type,
                risk,
                {"type": action_type, "plan_id": action.get("plan_id"), "status": deps["derive_plan_status"](plan)},
            )
        if action_type == "retry_plan_subtask":
            retry = deps["retry_plan_subtask"](action.get("plan_id"), str(action.get("subtask_id")))
            return ActionResult.completed(action_type, risk, {"type": action_type, **retry})
        if action_type == "retry_schedule":
            schedule = deps["schedule_by_name"](action.get("schedule"))
            if not schedule or schedule.get("removed"):
                return ActionResult.failed(action_type, risk, f"Unknown schedule: {action.get('schedule')}")
            item = deps["queue_item_from_schedule"](schedule)
            item["created_from"] = "schedule_retry"
            item["retry_of_queue_id"] = schedule.get("last_queue_id")
            item["retry_of_task_id"] = schedule.get("last_task_id")
            deps["append_queue"](item)
            deps["append_schedule"](
                {
                    "schedule_id": schedule.get("schedule_id"),
                    "name": schedule.get("name"),
                    "updated_at": deps["now_iso"](),
                    "last_retry_queue_id": item.get("queue_id"),
                }
            )
            return ActionResult.completed(
                action_type,
                risk,
                {"type": action_type, "schedule_id": schedule.get("schedule_id"), "queue_id": item.get("queue_id"), "queued": True},
            )
        if action_type == "pause":
            deps["ensure_state"]()
            deps["paused_file"].write_text(json.dumps({"paused": True, "updated_at": deps["now_iso"]()}) + "\n", encoding="utf-8")
            return ActionResult.completed(action_type, risk, {"type": action_type, "paused": True})
        if action_type == "resume":
            deps["ensure_state"]()
            if deps["paused_file"].exists():
                deps["paused_file"].unlink()
            return ActionResult.completed(action_type, risk, {"type": action_type, "paused": False})
        if action_type == "submit_run":
            config = deps["load_config"]()
            agents = config.get("agents") or {}
            agent_name = action.get("agent") or "planner"
            if agent_name not in agents:
                return ActionResult.failed(action_type, risk, f"Unknown agent: {agent_name}")
            workspace = action.get("workspace")
            _, cwd, memory_namespace = deps["resolve_workspace_options"](workspace)
            item = {
                "queue_id": deps["queue_id"](),
                "status": "queued",
                "agent": agent_name,
                "mode": "run",
                "goal": action.get("goal") or "",
                "cwd": str(cwd),
                "workspace": workspace,
                "memory_namespace": memory_namespace,
                "memory": {"enabled": True},
                "check": None,
                "max_rounds": None,
                "created_at": deps["now_iso"](),
                "started_at": None,
                "ended_at": None,
                "task_id": None,
            }
            deps["append_queue"](item)
            return ActionResult.completed(action_type, risk, {"type": action_type, "queue_id": item.get("queue_id"), "queued": True, "item": item})
        if action_type == "submit_iterate":
            config = deps["load_config"]()
            agents = config.get("agents") or {}
            agent_name = action.get("agent") or "planner"
            if agent_name not in agents:
                return ActionResult.failed(action_type, risk, f"Unknown agent: {agent_name}")
            workspace = action.get("workspace")
            _, cwd, memory_namespace = deps["resolve_workspace_options"](workspace)
            item = {
                "queue_id": deps["queue_id"](),
                "status": "queued",
                "agent": agent_name,
                "mode": "iterate",
                "goal": action.get("goal") or "",
                "cwd": str(cwd),
                "workspace": workspace,
                "memory_namespace": memory_namespace,
                "memory": {"enabled": True},
                "check": action.get("check"),
                "max_rounds": int(action.get("max_rounds") or 1),
                "created_at": deps["now_iso"](),
                "started_at": None,
                "ended_at": None,
                "task_id": None,
            }
            deps["append_queue"](item)
            return ActionResult.completed(action_type, risk, {"type": action_type, "queue_id": item.get("queue_id"), "queued": True, "item": item})
        if action_type == "create_plan":
            pid = deps["plan_id"]()
            workspace = action.get("workspace")
            memory_namespace = deps["resolve_workspace_options"](workspace)[2]
            plan = deps["default_plan_for_goal"](pid, workspace, memory_namespace, action.get("goal") or "")
            pdir = deps["plan_dir"](pid)
            pdir.mkdir(parents=True, exist_ok=False)
            (pdir / "goal.txt").write_text((action.get("goal") or "") + "\n", encoding="utf-8")
            deps["save_plan"](plan)
            deps["update_plan_status_file"](plan)
            return ActionResult.completed(action_type, risk, {"type": action_type, "plan_id": pid, "status": plan.get("status")})
        if action_type == "profile_run":
            resolved = deps["resolve_profile"](
                action.get("profile_id"),
                workspace_override=action.get("workspace"),
                agent_override=action.get("agent"),
            )
            selected_tool_id = action.get("tool")
            selected_tool = deps["tools_by_id"]().get(selected_tool_id) if selected_tool_id else None
            context_state = guardrails_mod.build_context_state(
                profile_id=action.get("profile_id"),
                workspace=resolved.get("workspace"),
                selected_tools=[selected_tool] if selected_tool else [],
                considered_tools=resolved.get("allowed_tools") or [],
                action=action_type,
            )
            guardrail_payload = guardrails_mod.evaluate_guardrails(
                profile=resolved.get("profile"),
                profile_id=action.get("profile_id"),
                tool=selected_tool,
                requested_tool_id=selected_tool_id,
                action=action_type,
                context_state=context_state,
            )
            if guardrail_payload.get("decision") == "block":
                return ActionResult.blocked(action_type, risk, guardrail_payload.get("reason"))
            if guardrail_payload.get("decision") == "approval_required":
                return ActionResult.pending_confirmation(action_type, risk, guardrail_payload.get("reason"))
            payload = {
                "type": action_type,
                "profile_id": action.get("profile_id"),
                "agent": resolved.get("agent"),
                "workspace": resolved.get("workspace"),
                "cwd": resolved.get("cwd"),
                "memory_namespace": resolved.get("memory_namespace"),
                "goal": action.get("goal") or resolved.get("profile", {}).get("default_run_goal") or "",
                "allowed_tools": [tool.get("id") for tool in resolved.get("allowed_tools") or []],
                "context_state": guardrail_payload.get("context_state"),
                "policy_decisions": guardrail_payload.get("policy_decisions"),
            }
            return ActionResult.completed(action_type, risk, payload)
        if action_type == "profile_plan":
            resolved = deps["resolve_profile"](
                action.get("profile_id"),
                workspace_override=action.get("workspace"),
                agent_override=action.get("agent"),
            )
            selected_tool_id = action.get("tool")
            selected_tool = deps["tools_by_id"]().get(selected_tool_id) if selected_tool_id else None
            context_state = guardrails_mod.build_context_state(
                profile_id=action.get("profile_id"),
                workspace=resolved.get("workspace"),
                selected_tools=[selected_tool] if selected_tool else [],
                considered_tools=resolved.get("allowed_tools") or [],
                action=action_type,
            )
            guardrail_payload = guardrails_mod.evaluate_guardrails(
                profile=resolved.get("profile"),
                profile_id=action.get("profile_id"),
                tool=selected_tool,
                requested_tool_id=selected_tool_id,
                action=action_type,
                context_state=context_state,
            )
            if guardrail_payload.get("decision") == "block":
                return ActionResult.blocked(action_type, risk, guardrail_payload.get("reason"))
            if guardrail_payload.get("decision") == "approval_required":
                return ActionResult.pending_confirmation(action_type, risk, guardrail_payload.get("reason"))
            goal = action.get("goal") or resolved.get("profile", {}).get("default_plan_goal") or ""
            if not goal:
                return ActionResult.failed(action_type, risk, "Goal is required")
            if not resolved.get("workspace"):
                return ActionResult.failed(action_type, risk, f"Profile '{action.get('profile_id')}' requires a workspace for planning.")
            pid = deps["plan_id"]()
            plan = deps["default_plan_for_goal"](pid, resolved.get("workspace"), resolved.get("memory_namespace"), goal)
            plan["profile_id"] = action.get("profile_id")
            plan["profile"] = {
                "default_agent": resolved.get("profile", {}).get("default_agent"),
                "allowed_agents": resolved.get("profile", {}).get("allowed_agents") or [],
                "allowed_tools": resolved.get("profile", {}).get("allowed_tools") or [],
            }
            plan["context_state"] = guardrail_payload.get("context_state")
            plan["policy_decisions"] = guardrail_payload.get("policy_decisions")
            pdir = deps["plan_dir"](pid)
            pdir.mkdir(parents=True, exist_ok=False)
            (pdir / "goal.txt").write_text(goal + "\n", encoding="utf-8")
            deps["save_plan"](plan)
            deps["update_plan_status_file"](plan)
            return ActionResult.completed(action_type, risk, {"type": action_type, "plan_id": pid, "status": plan.get("status"), "profile_id": action.get("profile_id"), "context_state": guardrail_payload.get("context_state"), "policy_decisions": guardrail_payload.get("policy_decisions")})
        return ActionResult.unsupported(action_type, risk, f"Assistant action is not enabled for assistant-exec: {action_type}")
    except Exception as exc:
        return ActionResult.failed(action_type, risk, str(exc))


def execute_route(route: dict[str, Any], *, dry_run: bool = False, deps: DepMap | None = None) -> dict[str, Any]:
    if route.get("status") != "matched":
        return _passthrough_route_payload(route)

    if route.get("risk") == "workspace_write":
        result = ActionResult.pending_confirmation(
            "assistant_exec",
            route.get("risk") or "workspace_write",
            route.get("confirm_message") or route.get("message") or "Confirmation required.",
        )
        return _route_result_payload(route, result, [])

    execution: list[dict[str, Any]] = []
    for action in route.get("actions") or []:
        result = execute_action(action, route, dry_run=dry_run, deps=deps)
        if result.result is not None:
            execution.append(result.result)
        if not result.ok:
            return _route_result_payload(route, result, execution)

    final = ActionResult.completed("assistant_exec", route.get("risk") or "read_only", _assistant_exec_counts(execution), route.get("message"))
    return _route_result_payload(route, final, execution)
