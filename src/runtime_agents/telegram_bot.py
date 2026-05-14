#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import datetime as dt
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def config_home():
    return Path(os.environ.get("RUNTIME_AGENTS_CONFIG_HOME", str(Path.home() / ".config" / "runtime-agents"))).expanduser()


def state_home():
    return Path(os.environ.get("RUNTIME_AGENTS_STATE_HOME", str(Path.home() / ".local" / "share" / "runtime-agents"))).expanduser()


def resolve_agentctl_bin():
    return os.environ.get("RUNTIME_AGENTS_AGENTCTL_BIN") or shutil.which("agentctl") or str(Path.home() / ".local" / "bin" / "agentctl")


CONFIG_PATH = config_home() / "telegram.yaml"
STATE_DIR = state_home()
OFFSET_PATH = STATE_DIR / "telegram.offset"
LOG_PATH = STATE_DIR / "telegram.log"
NOTIFY_STATE_PATH = STATE_DIR / "telegram.notify-state.json"
SESSIONS_PATH = STATE_DIR / "telegram.sessions.json"
AGENTCTL = resolve_agentctl_bin()
MAX_TELEGRAM_CHARS = 3800
MAX_LOG_TAIL = 300
DEFAULT_LOG_TAIL = 80
TEST_COMMAND_ALLOWED_USER_ID = None


def ensure_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    if yaml is None:
        return {"telegram": {"enabled": False, "allowed_user_ids": [], "bot_token_env": "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN"}}
    if not CONFIG_PATH.exists():
        return {"telegram": {"enabled": False, "allowed_user_ids": [], "bot_token_env": "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN"}}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def telegram_config():
    cfg = load_config().get("telegram") or {}
    allowed = cfg.get("allowed_user_ids") or []
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "bot_token_env": cfg.get("bot_token_env") or "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN",
        "allowed_user_ids": [int(x) for x in allowed],
    }


def token_from_config(cfg):
    return os.environ.get(cfg.get("bot_token_env") or "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN")


def log_event(event):
    ensure_state()
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    try:
        LOG_PATH.chmod(0o600)
    except Exception:
        pass


def load_sessions():
    if not SESSIONS_PATH.exists():
        return {}
    try:
        data = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_sessions(sessions):
    ensure_state()
    SESSIONS_PATH.write_text(json.dumps(sessions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        SESSIONS_PATH.chmod(0o600)
    except Exception:
        pass


def user_session(user_id):
    return load_sessions().get(str(user_id), {})


def update_user_session(user_id, **updates):
    sessions = load_sessions()
    key = str(user_id)
    current = sessions.get(key, {})
    for k, v in updates.items():
        if v is not None:
            current[k] = v
    sessions[key] = current
    save_sessions(sessions)
    return current


def run_agentctl(args, timeout=60):
    proc = subprocess.run([AGENTCTL] + args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    data = None
    if proc.stdout.strip():
        try:
            data = json.loads(proc.stdout)
        except Exception:
            data = None
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "json": data}


def safe_text(text, limit=MAX_TELEGRAM_CHARS):
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + "\n...[truncated]"


def command_name(text):
    first = (text or "").strip().split(maxsplit=1)[0]
    return first.split("@", 1)[0]


def is_allowed(user_id, cfg):
    if TEST_COMMAND_ALLOWED_USER_ID is not None and int(user_id or 0) == int(TEST_COMMAND_ALLOWED_USER_ID):
        return True
    return int(user_id or 0) in set(cfg.get("allowed_user_ids") or [])


def format_help():
    return """runtime-agents Telegram Control Plane

Read/control:
/status /queue /plans /schedules /workspaces
/show <task_id>
/logs <task_id> [tail]
/pause /resume

Submit:
/run <workspace> <agent> <goal>
/iterate <workspace> <agent> <goal> | <check>
/plan_create <workspace> <big goal>

Plan recovery:
/plan <plan_id>
/plan_repair <plan_id>
/plan_retry <plan_id> <subtask_id>
/plan_skip <plan_id> <subtask_id> | <reason>
/plan_approve <plan_id>
/plan_enqueue <plan_id>

Schedules:
/schedule <name>
/schedule_retry <name>
""".strip()


def fmt_counts(items, key="status"):
    counts = {}
    for item in items or []:
        value = item.get(key)
        counts[value] = counts.get(value, 0) + 1
    return counts


def is_internal_selftest_text(text):
    lowered = str(text or "").lower()
    return "selftest" in lowered or "telegram selftest" in lowered


def is_internal_plan(plan):
    return is_internal_selftest_text(plan.get("goal"))


def handle_status():
    version = run_agentctl(["version", "--json"])["json"] or {}
    daemon = run_agentctl(["daemon-status", "--json"])["json"] or {}
    queue = run_agentctl(["queue", "--json"])["json"] or []
    plans = [p for p in (run_agentctl(["plan", "list", "--json"])["json"] or []) if not is_internal_plan(p)]
    schedules = run_agentctl(["schedule", "list", "--json"])["json"] or []
    q = fmt_counts(queue)
    p = fmt_counts(plans)
    enabled_schedules = len([s for s in schedules if s.get("enabled", True) and not s.get("removed")])
    last = daemon.get("last_task_id") or "none"
    return f"""runtime-agents v{version.get('version', 'unknown')}
Daemon: {'running' if daemon.get('running') else 'stopped'}
Paused: {str(bool(daemon.get('paused'))).lower()}
Queue: {q.get('queued', 0)} pending / {q.get('running', 0)} running
Plans: {p.get('blocked', 0)} blocked / {p.get('running', 0)} running / {p.get('completed', 0)} completed
Schedules: {enabled_schedules} enabled
Last task: {last}""".strip()


def handle_queue():
    items = run_agentctl(["queue", "--json"])["json"] or []
    pending = [i for i in items if i.get("status") == "queued"]
    running = [i for i in items if i.get("status") == "running"]
    recent = [i for i in items if i.get("status") not in {"queued", "running"}][-5:]
    lines = ["Queue", "", "Pending:"]
    if pending:
        for idx, item in enumerate(pending[:10], start=1):
            lines.append(f"{idx}. {item.get('queue_id')} {item.get('agent')} @ {item.get('workspace') or item.get('cwd') or '-'}")
            lines.append(f"   {item.get('goal')}")
    else:
        lines.append("none")
    lines.extend(["", "Running:"])
    if running:
        for item in running[:10]:
            lines.append(f"- {item.get('queue_id')} {item.get('agent')} -> {item.get('task_id') or '-'}")
    else:
        lines.append("none")
    lines.extend(["", "Recent:"])
    if recent:
        for item in recent:
            extra = ""
            if item.get("failure_class"):
                extra = f" {item.get('failure_class')}"
            if item.get("retry_recommended"):
                extra += " retry recommended"
            lines.append(f"- {item.get('queue_id')} {item.get('status')} -> task {item.get('task_id') or '-'}{extra}")
    else:
        lines.append("none")
    return safe_text("\n".join(lines))


def handle_plans(status_filter=None):
    all_plans = [p for p in (run_agentctl(["plan", "list", "--json"])["json"] or []) if not is_internal_plan(p)]
    rows = []
    for plan in all_plans:
        status = run_agentctl(["plan", "status", plan.get("plan_id"), "--json"])["json"] or plan
        if status_filter and status.get("status") != status_filter:
            continue
        rows.append((plan, status))
    title = f"Plans ({status_filter})" if status_filter else "Plans"
    lines = [title]
    if not rows:
        lines.append("none")
    for plan, status in rows[-10:]:
        blocked = f" blocked_on={status.get('blocked_on')}" if status.get("blocked_on") else ""
        lines.append(f"- {plan.get('plan_id')} {status.get('status')}{blocked} {plan.get('goal')}")
    return safe_text("\n".join(lines))


def handle_schedules():
    schedules = run_agentctl(["schedule", "list", "--json"])["json"] or []
    lines = ["Schedules"]
    if not schedules:
        lines.append("none")
    for sched in schedules[:20]:
        enabled = "enabled" if sched.get("enabled", True) and not sched.get("removed") else "disabled"
        last = sched.get("last_status") or "never"
        lines.append(f"- {sched.get('name') or sched.get('schedule_id')} {enabled} last={last}")
    return safe_text("\n".join(lines))


def handle_workspaces():
    workspaces = run_agentctl(["workspace", "list", "--json"])["json"] or {}
    lines = ["Workspaces"]
    if not workspaces:
        lines.append("none")
    for name, ws in workspaces.items():
        lines.append(f"- {name}: {ws.get('path')} ({ws.get('memory_namespace')})")
    return safe_text("\n".join(lines))


def handle_plan(plan_id):
    status = run_agentctl(["plan", "status", plan_id, "--json"])
    if not status["ok"]:
        return safe_text(status["stderr"] or status["stdout"] or "plan status failed")
    data = status["json"] or {}
    lines = [f"Plan: {data.get('goal')}", f"Status: {data.get('status')}"]
    if data.get("blocked_on"):
        lines.append(f"Blocked on: subtask {data.get('blocked_on')}")
    lines.extend(["", "Subtasks:"])
    for row in data.get("subtasks") or []:
        lines.append(f"{row.get('id')}. {row.get('status')} - task {row.get('task_id') or '-'}")
    lines.extend(["", "Next action:"])
    if data.get("status") == "blocked":
        lines.append(f"Run /plan_repair {plan_id}")
    else:
        lines.append("Use /plan_repair for suggestions or inspect task summaries.")
    return safe_text("\n".join(lines))


def handle_show(task_id):
    summary = run_agentctl(["summarize", task_id, "--json"])
    if not summary["ok"]:
        shown = run_agentctl(["show", task_id, "--json"])
        if not shown["ok"]:
            return safe_text(shown["stderr"] or shown["stdout"] or summary["stderr"] or "show failed")
        data = shown["json"] or {}
    else:
        data = summary["json"] or {}
    lines = ["Task Summary", f"Status: {data.get('status')}", f"Workspace: {data.get('workspace') or 'N/A'}", f"Agent: {data.get('agent')}", f"Goal: {data.get('goal') or data.get('task_id')}", f"Result: {data.get('status')}", f"Next action: {data.get('next_action') or 'Use /logs ' + task_id + ' for raw logs.'}", "", f"Use /logs {task_id} for raw logs."]
    return safe_text("\n".join(lines))


def handle_logs(parts):
    if len(parts) < 2:
        return "Usage: /logs <task_id> [tail]"
    task_id = parts[1]
    tail = DEFAULT_LOG_TAIL
    if len(parts) >= 3:
        try:
            tail = min(MAX_LOG_TAIL, max(1, int(parts[2])))
        except ValueError:
            return "Usage: /logs <task_id> [tail]"
    result = run_agentctl(["logs", task_id, "--tail", str(tail), "--json"])
    if not result["ok"]:
        return safe_text(result["stderr"] or result["stdout"] or "logs failed")
    text = (result["json"] or {}).get("text") or ""
    return safe_text(f"Logs: {task_id} (last {tail} lines)\n\n{text}")


def handle_submit_run(parts):
    if len(parts) < 4:
        return "Usage: /run <workspace> <agent> <goal>"
    workspace, agent = parts[1], parts[2]
    goal = " ".join(parts[3:]).strip()
    result = run_agentctl(["submit", "--workspace", workspace, agent, goal])
    if not result["ok"]:
        return safe_text(result["stderr"] or result["stdout"] or "run submit failed")
    data = result["json"] or {}
    return f"Queued run\nQueue: {data.get('queue_id')}\nWorkspace: {workspace}\nAgent: {agent}"


def handle_submit_iterate(text):
    prefix, _, rest = text.partition(" ")
    tokens = rest.split(maxsplit=2)
    if len(tokens) < 3 or "|" not in tokens[2]:
        return "Usage: /iterate <workspace> <agent> <goal> | <check>"
    workspace, agent, body = tokens
    goal, check = [x.strip() for x in body.rsplit("|", 1)]
    if not goal or not check:
        return "Usage: /iterate <workspace> <agent> <goal> | <check>"
    result = run_agentctl(["submit", "--workspace", workspace, agent, goal, "--check", check, "--max-rounds", "1"])
    if not result["ok"]:
        return safe_text(result["stderr"] or result["stdout"] or "iterate submit failed")
    data = result["json"] or {}
    return f"Queued iterate\nQueue: {data.get('queue_id')}\nWorkspace: {workspace}\nAgent: {agent}\nCheck: {check}"


def handle_simple_agentctl(label, args):
    result = run_agentctl(args)
    if not result["ok"]:
        return safe_text(result["stderr"] or result["stdout"] or f"{label} failed")
    return safe_text(f"{label}\n{json.dumps(result['json'], indent=2, sort_keys=True) if result['json'] is not None else result['stdout']}")


def execute_assistant_action(action, user_id):
    payload = run_agentctl(["assistant-exec", action.get("_message", ""), "--json", "--session-json", json.dumps(user_session(user_id))])
    if not payload["ok"]:
        return safe_text(payload["stderr"] or payload["stdout"] or "assistant action failed")
    data = payload["json"] or {}
    if data.get("status") == "pending_confirmation":
        return data.get("message") or "This needs confirmation."
    execution = data.get("execution") or []
    if not execution:
        return data.get("message") or "I don't have a safe action for that yet."
    rendered = []
    for item in execution:
        action_type = item.get("type")
        if action_type == "status_overview":
            daemon = item.get("daemon") or {}
            queue = item.get("queue") or []
            plans = item.get("plans") or []
            schedules = item.get("schedules") or []
            q = fmt_counts(queue)
            p = fmt_counts(plans)
            enabled_schedules = len([s for s in schedules if s.get("enabled", True) and not s.get("removed")])
            rendered.append(f"runtime-agents\nDaemon: {'running' if daemon.get('running') else 'stopped'}\nPaused: {str(bool(daemon.get('paused'))).lower()}\nQueue: {q.get('queued', 0)} pending / {q.get('running', 0)} running\nPlans: {p.get('blocked', 0)} blocked / {p.get('running', 0)} running / {p.get('completed', 0)} completed\nSchedules: {enabled_schedules} enabled\nLast task: {daemon.get('last_task_id') or 'none'}")
        elif action_type == "list_workspaces":
            workspaces = item.get("workspaces") or {}
            lines = ["Workspaces"]
            if not workspaces:
                lines.append("none")
            for name, ws in workspaces.items():
                lines.append(f"- {name}: {ws.get('path')} ({ws.get('memory_namespace')})")
            rendered.append("\n".join(lines))
        elif action_type == "list_runbooks":
            lines = ["Runbooks"]
            runbooks = item.get("runbooks") or []
            if not runbooks:
                lines.append("none")
            for runbook in runbooks:
                lines.append(f"- {runbook.get('id')}: {runbook.get('title')}")
            rendered.append("\n".join(lines))
        elif action_type == "list_queue":
            rendered.append(handle_queue())
        elif action_type == "list_plans":
            rendered.append(handle_plans())
        elif action_type == "list_schedules":
            rendered.append(handle_schedules())
        elif action_type == "show_task":
            task = item.get("task") or {}
            task_id = task.get("task_id")
            rendered.append(handle_show(task_id) if task_id else "I don't know which task yet.")
        elif action_type == "show_logs":
            text = (item.get("stdout") or "") + (("\n" + item.get("stderr")) if item.get("stderr") else "")
            rendered.append(safe_text(text or "No logs found."))
        elif action_type == "show_plan":
            plan = item.get("plan") or {}
            rendered.append(f"Plan: {plan.get('goal')}\nStatus: {plan.get('status')}")
        elif action_type == "repair_plan":
            plan_id = item.get("plan_id")
            rendered.append(f"Repair prepared for plan {plan_id}.")
        elif action_type == "retry_schedule":
            rendered.append(f"Retried schedule.\nQueued: {item.get('queue_id')}")
        elif action_type == "submit_run":
            queued = item.get("item") or {}
            rendered.append(f"Queued run\nQueue: {item.get('queue_id')}\nWorkspace: {queued.get('workspace')}\nAgent: {queued.get('agent')}")
        elif action_type == "submit_iterate":
            queued = item.get("item") or {}
            rendered.append(f"Queued iterate\nQueue: {item.get('queue_id')}\nWorkspace: {queued.get('workspace')}\nAgent: {queued.get('agent')}\nCheck: {queued.get('check')}")
        elif action_type == "create_plan":
            rendered.append(f"Plan created\nPlan: {item.get('plan_id')}\nStatus: {item.get('status')}")
        elif action_type == "pause":
            rendered.append("Paused")
        elif action_type == "resume":
            rendered.append("Resumed")
    update_user_session(
        user_id,
        last_intent=data.get("runbook_id"),
        last_workspace=(data.get("inputs") or {}).get("workspace"),
        last_plan_id=(data.get("inputs") or {}).get("plan_id"),
        last_task_id=(data.get("inputs") or {}).get("task_id"),
        last_schedule=(data.get("inputs") or {}).get("schedule"),
    )
    return safe_text("\n\n".join(rendered))


def handle_assistant_text(text, user_id):
    if (text or "").strip().lower() in {"hi", "hello", "hey"}:
        return "Hi — I’m your runtime-agents assistant. Ask me: what's going on?, list workspaces, what is blocked?, or fix tests in test-ws."
    session = user_session(user_id)
    route = run_agentctl(["assistant-route", text, "--json", "--session-json", json.dumps(session)])
    if not route["ok"]:
        return safe_text(route["stderr"] or route["stdout"] or "assistant route failed")
    payload = route["json"] or {}
    if payload.get("status") == "blocked":
        return payload.get("message") or "I can't do that from Telegram."
    if payload.get("status") == "needs_clarification":
        return payload.get("question") or "I need one more detail first."
    if payload.get("requires_confirmation"):
        actions = payload.get("actions") or []
        pending = dict(actions[0]) if actions else None
        if pending is not None:
            pending["_message"] = text
        update_user_session(user_id, pending_action=pending, last_workspace=payload.get("workspace"), last_plan_id=payload.get("plan_id"), last_intent=payload.get("intent"))
        return payload.get("confirm_message") or payload.get("message") or "This needs confirmation. Reply YES to proceed."
    action = {"_message": text}
    return execute_assistant_action(action, user_id)


def handle_confirmation(text, user_id):
    lowered = (text or "").strip().lower()
    if lowered not in {"yes", "y", "confirm", "proceed", "ok"}:
        return None
    session = user_session(user_id)
    action = session.get("pending_action")
    if not action:
        return None
    update_user_session(user_id, pending_action={})
    return execute_assistant_action(action, user_id)


def handle_command(text, user_id):
    cfg = telegram_config()
    if not is_allowed(user_id, cfg):
        return "unauthorized"
    text = (text or "").strip()
    if not text:
        return format_help()
    confirmed = handle_confirmation(text, user_id)
    if confirmed is not None:
        return confirmed
    parts = text.split()
    cmd = command_name(text)
    if not cmd.startswith("/"):
        return handle_assistant_text(text, user_id)
    if cmd in {"/start", "/help"}:
        return format_help()
    if cmd == "/status":
        return handle_status()
    if cmd == "/queue":
        return handle_queue()
    if cmd == "/plans":
        return handle_plans()
    if cmd == "/schedules":
        return handle_schedules()
    if cmd == "/workspaces":
        return handle_workspaces()
    if cmd == "/pause":
        return handle_simple_agentctl("Paused", ["pause"])
    if cmd == "/resume":
        return handle_simple_agentctl("Resumed", ["resume"])
    if cmd == "/show":
        return handle_show(parts[1]) if len(parts) >= 2 else "Usage: /show <task_id>"
    if cmd == "/logs":
        return handle_logs(parts)
    if cmd == "/run":
        return handle_submit_run(parts)
    if cmd == "/iterate":
        return handle_submit_iterate(text)
    if cmd == "/plan_create":
        if len(parts) < 3:
            return "Usage: /plan_create <workspace> <big goal>"
        result = run_agentctl(["plan", "create", "--workspace", parts[1], " ".join(parts[2:])])
        if not result["ok"]:
            return safe_text(result["stderr"] or result["stdout"] or "plan create failed")
        data = result["json"] or {}
        return f"Plan created\nPlan: {data.get('plan_id')}\nStatus: {data.get('status')}"
    if cmd == "/plan":
        return handle_plan(parts[1]) if len(parts) >= 2 else "Usage: /plan <plan_id>"
    if cmd == "/plan_repair":
        return handle_simple_agentctl("Plan repair", ["plan", "repair", parts[1], "--json"]) if len(parts) >= 2 else "Usage: /plan_repair <plan_id>"
    if cmd == "/plan_retry":
        return handle_simple_agentctl("Plan retry", ["plan", "retry", parts[1], parts[2]]) if len(parts) >= 3 else "Usage: /plan_retry <plan_id> <subtask_id>"
    if cmd == "/plan_skip":
        body = text.split(maxsplit=2)
        if len(body) < 3 or "|" not in body[2]:
            return "Usage: /plan_skip <plan_id> <subtask_id> | <reason>"
        plan_id, rest = body[1], body[2]
        subtask_id, reason = [x.strip() for x in rest.split("|", 1)]
        return handle_simple_agentctl("Plan skip", ["plan", "skip", plan_id, subtask_id, "--reason", reason])
    if cmd == "/plan_approve":
        return handle_simple_agentctl("Plan approve", ["plan", "approve", parts[1]]) if len(parts) >= 2 else "Usage: /plan_approve <plan_id>"
    if cmd == "/plan_enqueue":
        return handle_simple_agentctl("Plan enqueue", ["plan", "enqueue", parts[1]]) if len(parts) >= 2 else "Usage: /plan_enqueue <plan_id>"
    if cmd == "/schedule":
        return handle_simple_agentctl("Schedule", ["schedule", "show", parts[1], "--json"]) if len(parts) >= 2 else "Usage: /schedule <name>"
    if cmd == "/schedule_retry":
        return handle_simple_agentctl("Schedule retry", ["schedule", "retry", parts[1]]) if len(parts) >= 2 else "Usage: /schedule_retry <name>"
    if cmd in {"/exec", "/shell", "/bash", "/run_shell", "/approve"}:
        return "unsupported in Telegram v1.0"
    return "Unknown command. Use /help."


def notification_events():
    state = {}
    if NOTIFY_STATE_PATH.exists():
        try:
            state = json.loads(NOTIFY_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    seen = set(state.get("seen") or [])
    started_at = state.get("started_at") or dt.datetime.now(dt.timezone.utc).isoformat()
    events = []
    queue = run_agentctl(["queue", "--json"])["json"] or []
    for item in queue:
        if is_internal_selftest_text(item.get("goal")) or is_internal_selftest_text(item.get("task_id")):
            continue
        if item.get("ended_at") and item.get("ended_at") < started_at:
            continue
        key = f"queue:{item.get('queue_id')}:{item.get('status')}:{item.get('task_id')}"
        if key in seen:
            continue
        if item.get("status") == "failed":
            events.append((key, f"Task failed\nQueue: {item.get('queue_id')}\nTask: {item.get('task_id') or '-'}\nNext: /logs {item.get('task_id') or '<task_id>'}"))
        elif item.get("created_from") in {"schedule", "schedule_retry"} and item.get("status") == "completed":
            events.append((key, f"Scheduled task completed\nSchedule: {item.get('schedule_id')}\nTask: {item.get('task_id') or '-'}"))
        elif item.get("retry_recommended"):
            events.append((key, f"Scheduled task failed\nSchedule: {item.get('schedule_id')}\nFailure class: {item.get('failure_class')}\nRetry recommended: true\nRun: /schedule_retry {item.get('schedule_id')}"))
        elif item.get("status") == "approval_required":
            events.append((key, f"Approval required\nQueue: {item.get('queue_id')}\nDangerous approvals are not supported in Telegram v1.0."))
    for plan in run_agentctl(["plan", "list", "--json"])["json"] or []:
        if is_internal_plan(plan):
            continue
        if plan.get("updated_at") and plan.get("updated_at") < started_at:
            continue
        status = run_agentctl(["plan", "status", plan.get("plan_id"), "--json"])["json"] or {}
        key = f"plan:{plan.get('plan_id')}:{status.get('status')}:{status.get('blocked_on')}"
        if key in seen:
            continue
        if status.get("status") == "blocked":
            events.append((key, f"Plan blocked\nPlan: {status.get('goal')}\nBlocked on subtask {status.get('blocked_on')}\nNext: /plan_repair {plan.get('plan_id')}"))
        elif status.get("status") == "completed":
            events.append((key, f"Plan completed\nPlan: {status.get('goal')}\nPlan id: {plan.get('plan_id')}"))
    daemon = run_agentctl(["daemon-status", "--json"])["json"] or {}
    previous_daemon_running = state.get("last_daemon_running")
    key = f"daemon:stopped:{daemon.get('pid') or 'none'}"
    if key not in seen and previous_daemon_running is True and not daemon.get("running"):
        events.append((key, "agentd stopped\nUse /status for details."))
    for key, _ in events:
        seen.add(key)
    if events or state.get("started_at") != started_at or state.get("last_daemon_running") != bool(daemon.get("running")):
        ensure_state()
        NOTIFY_STATE_PATH.write_text(json.dumps({"started_at": started_at, "last_daemon_running": bool(daemon.get("running")), "seen": sorted(seen)[-500:]}, indent=2) + "\n", encoding="utf-8")
    return [message for _, message in events]


def send_message(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": safe_text(text)}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def get_updates(token, offset=None):
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=40) as resp:
        return json.loads(resp.read().decode())


def read_offset():
    try:
        return int(OFFSET_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_offset(offset):
    ensure_state()
    OFFSET_PATH.write_text(str(offset) + "\n", encoding="utf-8")
    try:
        OFFSET_PATH.chmod(0o600)
    except Exception:
        pass


def run_poll_loop():
    cfg = telegram_config()
    if not cfg.get("enabled"):
        raise SystemExit("Telegram is disabled in telegram.yaml")
    token = token_from_config(cfg)
    if not token:
        raise SystemExit(f"Missing bot token env: {cfg.get('bot_token_env')}")
    if not NOTIFY_STATE_PATH.exists():
        ensure_state()
        NOTIFY_STATE_PATH.write_text(json.dumps({"started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "seen": []}, indent=2) + "\n", encoding="utf-8")
    offset = read_offset()
    while True:
        try:
            updates = get_updates(token, offset=offset)
            for update in updates.get("result") or []:
                offset = int(update.get("update_id")) + 1
                write_offset(offset)
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                user = message.get("from") or {}
                text = message.get("text") or ""
                response = handle_command(text, user.get("id"))
                send_message(token, chat.get("id"), response)
                log_event({"update_id": update.get("update_id"), "user_id": user.get("id"), "command": command_name(text), "handled": True})
            for user_id in cfg.get("allowed_user_ids") or []:
                for event in notification_events():
                    send_message(token, user_id, event)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log_event({"error": str(exc)})
            time.sleep(5)


def main():
    global TEST_COMMAND_ALLOWED_USER_ID
    if len(sys.argv) >= 3 and sys.argv[1] == "--test-command":
        user_id = int(sys.argv[2])
        if user_id != 0:
            TEST_COMMAND_ALLOWED_USER_ID = user_id
        text = " ".join(sys.argv[3:])
        print(handle_command(text, user_id))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--notifications-json":
        print(json.dumps(notification_events(), indent=2, sort_keys=True))
        return 0
    return run_poll_loop()


if __name__ == "__main__":
    raise SystemExit(main())
