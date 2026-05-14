#!/usr/bin/env python3
import argparse
import datetime as dt
import fcntl
import importlib.metadata
import json
import os
import re
import signal
import shutil
import subprocess
import sys
from pathlib import Path

from runtime_agents import actions as actions_mod
from runtime_agents import assistant_router as assistant_router_mod
from runtime_agents import guardrails as guardrails_mod
from runtime_agents import paths as paths_mod
from runtime_agents import plans as plans_mod
from runtime_agents import policy as policy_mod
from runtime_agents import profiles as profiles_mod
from runtime_agents import runbooks as runbooks_mod
from runtime_agents import schedules as schedules_mod
from runtime_agents import state as state_mod
from runtime_agents import tools_registry as tools_registry_mod
from runtime_agents.models import TASK_STATUSES as MODEL_TASK_STATUSES

try:
    from runtime_agents.amb_adapter import AMBAdapter
except ImportError:
    try:
        from amb_adapter import AMBAdapter
    except ImportError:
        AMBAdapter = None

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def config_home():
    return paths_mod.config_home()


def state_home():
    return paths_mod.state_home()


def resolve_agentctl_bin():
    return paths_mod.resolve_agentctl_bin()


def resolve_agentbot_bin():
    return paths_mod.resolve_agentbot_bin()


CONFIG_PATH = paths_mod.CONFIG_PATH
PROFILES_CONFIG_PATH = paths_mod.PROFILES_CONFIG_PATH
TOOLS_CONFIG_PATH = paths_mod.TOOLS_CONFIG_PATH
TELEGRAM_CONFIG_PATH = paths_mod.TELEGRAM_CONFIG_PATH
VERSION_PATH = paths_mod.VERSION_PATH
STATE_DIR = paths_mod.STATE_DIR
RUNS_DIR = paths_mod.RUNS_DIR
PLANS_DIR = paths_mod.PLANS_DIR
TASKS_JSONL = paths_mod.TASKS_JSONL
QUEUE_JSONL = paths_mod.QUEUE_JSONL
QUEUE_LOCK = paths_mod.QUEUE_LOCK
SCHEDULES_JSONL = paths_mod.SCHEDULES_JSONL
PAUSED_FILE = paths_mod.PAUSED_FILE
AGENTD_PID = paths_mod.AGENTD_PID
AGENTD_LOG = paths_mod.AGENTD_LOG
TELEGRAM_OFFSET = paths_mod.TELEGRAM_OFFSET
TELEGRAM_LOG = paths_mod.TELEGRAM_LOG
STATUS_VALUES = MODEL_TASK_STATUSES
MODEL_FALLBACK_PROFILES = {
    "sonnet": "claude-sonnet-4-6",
    "gpt54": "gpt-5.4",
    "gpt55": "gpt-5.5",
}
ITERATE_BLOCKED_CAPABILITIES = {
    "git_push",
    "deploy",
    "secrets",
    "global_config",
    "destructive_delete",
    "global_install",
}
PLAN_BLOCKED_CAPABILITIES = {
    "git_push",
    "deploy",
    "secrets",
    "global_config",
    "destructive_delete",
    "global_install",
}
TRANSIENT_MARKERS = (
    "429",
    "model_cooldown",
    "RESOURCE_EXHAUSTED",
    "Too Many Requests",
    "timeout",
    "temporarily unavailable",
    "rate limit",
    "gateway",
    "gateway unavailable",
    "connection reset",
    "resource exhausted",
)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_config():
    if yaml is None:
        raise SystemExit("PyYAML is required: python3 -m pip install --user pyyaml")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_telegram_config():
    if yaml is None:
        raise SystemExit("PyYAML is required: python3 -m pip install --user pyyaml")
    if not TELEGRAM_CONFIG_PATH.exists():
        return {"telegram": {"enabled": False, "bot_token_env": "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN", "allowed_user_ids": []}}
    with TELEGRAM_CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_tools_registry():
    return tools_registry_mod.load_tools()


def tools_by_id():
    return {item["id"]: item for item in load_tools_registry()}


def load_profiles_registry():
    config = load_config()
    return profiles_mod.load_profiles(agents=config.get("agents") or {}, workspaces=load_workspaces())


def profiles_by_id():
    return {item["id"]: item for item in load_profiles_registry()}


def validate_tools_registry(*, strict: bool = False):
    return tools_registry_mod.validate_tools(strict=strict)


def validate_profiles_registry(*, strict: bool = False):
    config = load_config()
    return profiles_mod.validate_profiles(strict=strict, agents=config.get("agents") or {}, workspaces=load_workspaces())


def telegram_cfg():
    cfg = (load_telegram_config().get("telegram") or {})
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "bot_token_env": cfg.get("bot_token_env") or "RUNTIME_AGENTS_TELEGRAM_BOT_TOKEN",
        "allowed_user_ids": cfg.get("allowed_user_ids") or [],
    }


def load_version():
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject_path.exists():
        text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if match:
            return match.group(1)
    try:
        return importlib.metadata.version("runtime-agents")
    except importlib.metadata.PackageNotFoundError:
        pass
    if VERSION_PATH.exists():
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    return "0.0.0-unknown"


def ensure_state():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def pid_is_running(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def task_id(agent):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = os.urandom(3).hex()
    return f"{stamp}-{agent}-{suffix}"


def iterate_task_id(agent):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = os.urandom(3).hex()
    return f"{stamp}-iterate-{agent}-{suffix}"


def queue_id():
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = os.urandom(3).hex()
    return f"{stamp}-queue-{suffix}"


def schedule_id(name):
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "-", name.strip()).strip("-")
    return safe or f"schedule-{os.urandom(3).hex()}"


def plan_id():
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = os.urandom(3).hex()
    return f"{stamp}-plan-{suffix}"


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def atomic_write_json(path, data):
    state_mod.atomic_write_json(path, data)


def print_json(data):
    print(json.dumps(data, indent=2, sort_keys=True))


def append_task(data):
    with TASKS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def append_queue(data):
    state_mod.append_jsonl(QUEUE_JSONL, data)
    state_mod.ensure_private_file(QUEUE_JSONL)


def append_schedule(data):
    state_mod.append_jsonl(SCHEDULES_JSONL, data)
    state_mod.ensure_private_file(SCHEDULES_JSONL)


def read_queue_events():
    return state_mod.read_jsonl(QUEUE_JSONL)


def read_schedule_events():
    return state_mod.read_jsonl(SCHEDULES_JSONL)


def latest_schedules():
    by_id = state_mod.latest_by_id(read_schedule_events(), "schedule_id")
    by_name = state_mod.latest_by_id(read_schedule_events(), "name")
    merged = {**by_name, **by_id}
    return merged


def schedule_by_name(name):
    schedules = latest_schedules()
    if name in schedules:
        return schedules[name]
    sid = schedule_id(name)
    return schedules.get(sid)


def latest_queue_items():
    latest = {}
    for event in read_queue_events():
        latest[event["queue_id"]] = {**latest.get(event["queue_id"], {}), **event}
    return latest


def queue_item_for_task_id(task_id_value):
    for item in latest_queue_items().values():
        if item.get("task_id") == task_id_value:
            return item
    return {}


def first_queued_item():
    latest = latest_queue_items()
    for qid, item in latest.items():
        if item.get("status") == "queued":
            return item
    return None


def queue_counts():
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for item in latest_queue_items().values():
        status = item.get("status")
        counts[status] = counts.get(status, 0) + 1
    return counts


def last_queue_task_id():
    last = None
    for event in read_queue_events():
        if event.get("task_id"):
            last = event.get("task_id")
    return last


class QueueLock:
    def __enter__(self):
        ensure_state()
        self.fh = QUEUE_LOCK.open("a+", encoding="utf-8")
        try:
            QUEUE_LOCK.chmod(0o600)
        except Exception:
            pass
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(json.dumps({"pid": os.getpid(), "locked_at": now_iso()}) + "\n")
        self.fh.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.fh.seek(0)
            self.fh.truncate()
            self.fh.flush()
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()


def extract_task_id(stdout):
    try:
        return json.loads(stdout).get("task_id")
    except Exception:
        return None


def read_tasks():
    if not TASKS_JSONL.exists():
        return []
    tasks = []
    with TASKS_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks


def latest_task(task_id_value):
    matches = [t for t in read_tasks() if t.get("task_id") == task_id_value]
    return matches[-1] if matches else None


def latest_tasks():
    latest = {}
    for task in read_tasks():
        latest[task["task_id"]] = task
    return latest


def parse_approved(values):
    approved = set()
    for value in values or []:
        for item in value.split(","):
            item = item.strip()
            if item:
                approved.add(item)
    return approved


def unauthorized_approvals(required, approved):
    return sorted(set(required) - set(approved))


def normalize_run_args(args):
    prompt = []
    tokens = list(args.prompt)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--dry-run":
            args.dry_run = True
        elif token == "--json":
            args.json = True
        elif token == "--fallback":
            args.fallback = True
        elif token == "--approve" and i + 1 < len(tokens):
            args.approve.append(tokens[i + 1])
            i += 1
        elif token.startswith("--approve="):
            args.approve.append(token.split("=", 1)[1])
        elif token == "--model" and i + 1 < len(tokens):
            args.model = tokens[i + 1]
            i += 1
        elif token.startswith("--model="):
            args.model = token.split("=", 1)[1]
        elif token == "--workspace" and i + 1 < len(tokens):
            args.workspace = tokens[i + 1]
            i += 1
        elif token.startswith("--workspace="):
            args.workspace = token.split("=", 1)[1]
        elif token == "--no-memory":
            args.no_memory = True
        elif token == "--memory-query" and i + 1 < len(tokens):
            args.memory_query = tokens[i + 1]
            i += 1
        elif token.startswith("--memory-query="):
            args.memory_query = token.split("=", 1)[1]
        elif token == "--memory-preview":
            args.memory_preview = True
        elif token == "--timeout" and i + 1 < len(tokens):
            args.timeout = int(tokens[i + 1])
            i += 1
        elif token.startswith("--timeout="):
            args.timeout = int(token.split("=", 1)[1])
        else:
            prompt.append(token)
        i += 1
    args.prompt = prompt
    return args


def normalize_iterate_args(args):
    goal = []
    tokens = list(args.goal)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--dry-run":
            args.dry_run = True
        elif token == "--json":
            args.json = True
        elif token == "--fallback":
            args.fallback = True
        elif token == "--check" and i + 1 < len(tokens):
            args.check = tokens[i + 1]
            i += 1
        elif token.startswith("--check="):
            args.check = token.split("=", 1)[1]
        elif token == "--max-rounds" and i + 1 < len(tokens):
            args.max_rounds = int(tokens[i + 1])
            i += 1
        elif token.startswith("--max-rounds="):
            args.max_rounds = int(token.split("=", 1)[1])
        elif token == "--check-timeout" and i + 1 < len(tokens):
            args.check_timeout = int(tokens[i + 1])
            i += 1
        elif token.startswith("--check-timeout="):
            args.check_timeout = int(token.split("=", 1)[1])
        elif token == "--tail" and i + 1 < len(tokens):
            args.tail = int(tokens[i + 1])
            i += 1
        elif token.startswith("--tail="):
            args.tail = int(token.split("=", 1)[1])
        elif token == "--timeout" and i + 1 < len(tokens):
            args.timeout = int(tokens[i + 1])
            i += 1
        elif token.startswith("--timeout="):
            args.timeout = int(token.split("=", 1)[1])
        elif token == "--approve" and i + 1 < len(tokens):
            args.approve.append(tokens[i + 1])
            i += 1
        elif token.startswith("--approve="):
            args.approve.append(token.split("=", 1)[1])
        elif token == "--model" and i + 1 < len(tokens):
            args.model = tokens[i + 1]
            i += 1
        elif token.startswith("--model="):
            args.model = token.split("=", 1)[1]
        elif token == "--workspace" and i + 1 < len(tokens):
            args.workspace = tokens[i + 1]
            i += 1
        elif token.startswith("--workspace="):
            args.workspace = token.split("=", 1)[1]
        elif token == "--no-memory":
            args.no_memory = True
        elif token == "--memory-query" and i + 1 < len(tokens):
            args.memory_query = tokens[i + 1]
            i += 1
        elif token.startswith("--memory-query="):
            args.memory_query = token.split("=", 1)[1]
        elif token == "--memory-preview":
            args.memory_preview = True
        else:
            goal.append(token)
        i += 1
    args.goal = goal
    return args


def normalize_submit_args(args):
    goal = []
    tokens = list(args.goal)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--check" and i + 1 < len(tokens):
            args.check = tokens[i + 1]
            i += 1
        elif token.startswith("--check="):
            args.check = token.split("=", 1)[1]
        elif token == "--max-rounds" and i + 1 < len(tokens):
            args.max_rounds = int(tokens[i + 1])
            i += 1
        elif token.startswith("--max-rounds="):
            args.max_rounds = int(token.split("=", 1)[1])
        elif token == "--cwd" and i + 1 < len(tokens):
            args.cwd = tokens[i + 1]
            i += 1
        elif token.startswith("--cwd="):
            args.cwd = token.split("=", 1)[1]
        elif token == "--workspace" and i + 1 < len(tokens):
            args.workspace = tokens[i + 1]
            i += 1
        elif token.startswith("--workspace="):
            args.workspace = token.split("=", 1)[1]
        elif token == "--no-memory":
            args.no_memory = True
        elif token == "--memory-query" and i + 1 < len(tokens):
            args.memory_query = tokens[i + 1]
            i += 1
        elif token.startswith("--memory-query="):
            args.memory_query = token.split("=", 1)[1]
        elif token == "--memory-preview":
            args.memory_preview = True
        else:
            goal.append(token)
        i += 1
    args.goal = goal
    return args


def detect_approvals(config, agent_cfg, prompt):
    required = sorted(set(agent_cfg.get("approval_required") or []))
    rules = config.get("capability_rules") or {}
    return policy_mod.detect_capabilities(prompt, allowed=required, patterns={k: (v or {}).get("patterns", []) for k, v in rules.items()})


def build_command(tool, model, prompt, profile=None, autonomy="read_only"):
    if tool == "codex":
        cmd = ["codex", "exec", "--skip-git-repo-check"]
        if profile:
            cmd += ["--profile", profile]
        else:
            cmd += ["-m", model]
        cmd += ["-c", 'approval_policy="never"']
        sandbox = "workspace-write" if autonomy == "workspace_write" else "read-only"
        cmd += ["-c", f'sandbox_mode="{sandbox}"']
        cmd.append(prompt)
        return cmd
    if tool == "claude":
        cmd = ["claude", "--bare", "-p"]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)
        return cmd
    if tool == "gemini":
        cmd = ["gemini"]
        if model:
            cmd += ["-m", model]
        cmd += ["-p", prompt]
        return cmd
    raise SystemExit(f"Unsupported tool: {tool}")


def run_command(cmd, cwd, timeout):
    started = now_iso()
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return {
        "started_at": started,
        "ended_at": now_iso(),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def run_shell_check(command, cwd, timeout):
    started = now_iso()
    proc = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return {
        "started_at": started,
        "ended_at": now_iso(),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def should_fallback(result):
    return policy_mod.classify_failure(result.get("stdout", ""), result.get("stderr", ""), result.get("returncode", 1)) == "transient_model_error"


def classify_failure_text(text):
    kind = policy_mod.classify_failure(text or "", "", 1)
    return (kind, kind is not None)


def classify_process_failure(returncode, stdout="", stderr=""):
    kind = policy_mod.classify_failure(stdout, stderr, returncode)
    return kind, kind is not None


def tail_text(text, limit=12000):
    if len(text) <= limit:
        return text
    return text[-limit:]


def tail_lines(text, count):
    if count is None:
        return text
    lines = text.splitlines()
    text = "\n".join(lines[-count:])
    return text + "\n" if text else ""


def load_json_file(path, default=None):
    return state_mod.read_json(path, default)


def iterate_round_summaries(run_dir):
    rounds_dir = Path(run_dir) / "rounds"
    summaries = []
    if not rounds_dir.exists():
        return summaries
    round_dirs = [p for p in rounds_dir.iterdir() if p.is_dir() and p.name.isdigit()]
    for rd in sorted(round_dirs, key=lambda p: int(p.name)):
        round_num = int(rd.name)
        data = load_json_file(rd / "result.json", {}) or {}
        if round_num == 0:
            check = data.get("check") or {}
            summaries.append({"round": 0, "kind": "initial_check", "check_passed": check.get("returncode") == 0, "exit_code": check.get("returncode")})
        else:
            check = data.get("check") or {}
            exit_code = check.get("returncode") if check else data.get("agent_returncode")
            summaries.append({"round": round_num, "kind": "agent_attempt", "check_passed": bool(check) and check.get("returncode") == 0, "exit_code": exit_code})
    return summaries


def execute_agent_attempts(agent_cfg, tool, model, prompt, autonomy, fallback, timeout, cwd=None):
    attempts = []
    profiles = [None]
    if fallback:
        profiles.extend(agent_cfg.get("fallback_profiles") or [])
    final = None
    for index, profile in enumerate(profiles, start=1):
        attempt_model = MODEL_FALLBACK_PROFILES.get(profile, model)
        cmd = build_command(tool, attempt_model, prompt, profile=profile if tool == "codex" else None, autonomy=autonomy)
        attempt = {
            "attempt": index,
            "profile": profile,
            "model": attempt_model,
            "command": cmd[:],
        }
        try:
            result = run_command(cmd, cwd or Path.cwd(), timeout)
        except subprocess.TimeoutExpired as exc:
            result = {
                "started_at": now_iso(),
                "ended_at": now_iso(),
                "returncode": 124,
                "stdout": exc.stdout or "",
                "stderr": f"timeout after {timeout}s",
            }
        attempt.update(result)
        attempts.append(attempt)
        if result["returncode"] == 0:
            final = attempt
            break
        if not fallback or not should_fallback(result):
            final = attempt
            break
    if final is None and attempts:
        final = attempts[-1]
    return attempts, final


def memory_config(config):
    cfg = config.get("memory") or {}
    return {
        "recall_enabled": cfg.get("recall_enabled", True),
        "recall_limit": int(cfg.get("recall_limit", 5)),
        "recall_max_chars": int(cfg.get("recall_max_chars", 4000)),
    }


def resolve_workspace_options(workspace_name):
    if not workspace_name:
        return None, None, None
    workspaces = load_workspaces()
    if workspace_name not in workspaces:
        raise SystemExit(f"Workspace '{workspace_name}' not found.")
    workspace_cfg = workspaces[workspace_name]
    cwd = Path(workspace_cfg["path"]).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        raise SystemExit(f"Invalid workspace cwd: {cwd}")
    return workspace_cfg, cwd, workspace_cfg.get("memory_namespace")


def build_memory_options(config, enabled=True, query=None, reason=None, limit=None, max_chars=None):
    cfg = memory_config(config)
    if limit is None:
        limit = cfg["recall_limit"]
    if max_chars is None:
        max_chars = cfg["recall_max_chars"]
    if not enabled:
        payload = {"enabled": False}
        if reason:
            payload["reason"] = reason
        return payload
    return {
        "enabled": bool(cfg["recall_enabled"]),
        "query": query,
        "limit": max(1, min(int(limit), 20)),
        "max_chars": max(200, min(int(max_chars), 20000)),
    }


def compact_memory_content(content, max_chars):
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 20)].rstrip() + "\n...[truncated]"


def infer_memory_label(item):
    tags = item.get("tags") or []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("kind:"):
            return tag.split(":", 1)[1]
    content = item.get("content") or ""
    if isinstance(content, str):
        for prefix in ("record_type:", "type:"):
            for line in content.splitlines()[:8]:
                if line.startswith(prefix):
                    return line.split(":", 1)[1].strip()
    return item.get("kind") or "memory"


def extract_field_from_content(content, field):
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            value = data.get(field)
            if value is None and field == "fix_or_decision":
                value = data.get("fix")
            return str(value).strip() if value is not None else None
        except Exception:
            pass
    prefix = f"{field}:"
    for line in content.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def memory_record_metadata(item):
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "kind": item.get("kind"),
        "tags": item.get("tags") or [],
    }


def recall_workspace_memory(namespace, query, memory_opts):
    if not namespace:
        return {"enabled": False, "reason": "no_memory_namespace"}, ""
    if not memory_opts.get("enabled"):
        return {"enabled": False, "reason": memory_opts.get("reason", "disabled")}, ""
    if AMBAdapter is None:
        return {"enabled": True, "namespace": namespace, "query": query, "limit": memory_opts.get("limit"), "max_chars": memory_opts.get("max_chars"), "error": "AMBAdapter import failed", "records": [], "injected": False}, ""
    limit = int(memory_opts.get("limit") or 5)
    max_chars = int(memory_opts.get("max_chars") or 4000)
    recall_meta = {"enabled": True, "namespace": namespace, "query": query, "limit": limit, "max_chars": max_chars, "records": [], "injected": False}
    try:
        result = AMBAdapter().recall(namespace, query or "", limit=limit, kind="memory")
        if not result.get("ok"):
            recall_meta["error"] = result.get("error") or "AMB recall failed"
            return recall_meta, ""
        response = result.get("response") or {}
        items = response.get("items") or []
    except Exception as exc:
        recall_meta["error"] = f"AMB recall failed: {exc}"
        return recall_meta, ""
    if not items:
        return recall_meta, ""

    prelude = [
        "Relevant project memory from Agent Memory Bridge",
        f"Namespace: {namespace}",
        "",
    ]
    used_chars = 0
    selected = []
    for idx, item in enumerate(items, start=1):
        content = compact_memory_content(item.get("content") or "", max_chars)
        label = infer_memory_label(item)
        title = item.get("title") or "Untitled memory"
        claim = extract_field_from_content(content, "claim") or content.splitlines()[0] if content else ""
        fix = extract_field_from_content(content, "fix_or_decision") or extract_field_from_content(content, "fix")
        block = [
            f"[{idx}] {label}: {title}",
            f"Claim: {claim}",
        ]
        if fix:
            block.append(f"Fix: {fix}")
        block.append(f"Source: AMB record {item.get('id')}")
        block.append("")
        block_text = "\n".join(block)
        if used_chars + len(block_text) > max_chars and selected:
            break
        selected.append(item)
        prelude.extend(block)
        used_chars += len(block_text)
        if used_chars >= max_chars:
            break
    prelude.extend([
        "Instructions:",
        "- Treat this memory as context, not absolute truth.",
        "- Prefer current repository files over stale memory.",
        "- Do not write new memory during this task.",
        "",
        "---",
        "Task:",
    ])
    recall_meta["records"] = [memory_record_metadata(item) for item in selected]
    recall_meta["injected"] = bool(selected)
    return recall_meta, "\n".join(prelude)


def apply_memory_prelude(prompt, namespace, query, memory_opts):
    recall_meta, prelude = recall_workspace_memory(namespace, query, memory_opts)
    if prelude:
        return f"{prelude}\n{prompt}", recall_meta
    return prompt, recall_meta


def recall_preview_payload(workspace_name, query, memory_opts=None):
    config = load_config()
    workspace_cfg, cwd, namespace = resolve_workspace_options(workspace_name)
    opts = memory_opts or build_memory_options(config, enabled=True, query=query)
    recall_meta, prelude = recall_workspace_memory(namespace, query, opts)
    return {
        "workspace": workspace_name,
        "cwd": str(cwd),
        "namespace": namespace,
        "query": query,
        "limit": opts.get("limit"),
        "max_chars": opts.get("max_chars"),
        "records": recall_meta.get("records") or [],
        "memory_recall": recall_meta,
        "prelude": prelude,
    }


def cron_field_matches(value, field):
    return schedules_mod.cron_field_matches(value, field)


def cron_matches_now(expr, when=None):
    return schedules_mod.cron_matches_now(expr, when)


def due_window_id(when=None):
    return schedules_mod.due_window_id(when)


def schedule_due(schedule, when=None):
    return schedules_mod.schedule_due(schedule, when)


def queue_item_from_schedule(schedule, when=None):
    when = when or dt.datetime.now().astimezone()
    qid = queue_id()
    return {
        "queue_id": qid,
        "status": "queued",
        "created_from": "schedule",
        "schedule_id": schedule.get("schedule_id"),
        "agent": schedule.get("agent"),
        "mode": schedule.get("type"),
        "goal": schedule.get("goal"),
        "cwd": schedule.get("cwd"),
        "workspace": schedule.get("workspace"),
        "memory_namespace": schedule.get("memory_namespace"),
        "memory": schedule.get("memory") or {"enabled": False, "reason": "schedule_missing_memory_options"},
        "check": schedule.get("check"),
        "max_rounds": schedule.get("max_rounds") if schedule.get("type") == "iterate" else None,
        "created_at": now_iso(),
        "due_at": when.isoformat(),
        "due_window": due_window_id(when),
        "started_at": None,
        "ended_at": None,
        "task_id": None,
    }


def plan_dir(plan_id_value):
    return PLANS_DIR / plan_id_value


def load_plan(plan_id_value):
    path = plan_dir(plan_id_value) / "plan.json"
    if not path.exists():
        raise SystemExit(f"Unknown plan id: {plan_id_value}")
    return load_json_file(path, {}) or {}


def save_plan(plan):
    pdir = plan_dir(plan["plan_id"])
    pdir.mkdir(parents=True, exist_ok=True)
    write_json(pdir / "plan.json", plan)


def update_plan_status_file(plan):
    write_json(plan_dir(plan["plan_id"]) / "status.json", derive_plan_status(plan))


def append_plan_event(plan_id_value, event):
    pdir = plan_dir(plan_id_value)
    pdir.mkdir(parents=True, exist_ok=True)
    payload = {"plan_id": plan_id_value, "created_at": now_iso(), **event}
    with (pdir / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")
    try:
        (pdir / "events.jsonl").chmod(0o600)
    except Exception:
        pass
    return payload


def read_plan_events(plan_id_value):
    path = plan_dir(plan_id_value) / "events.jsonl"
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def latest_plan_event(plan_id_value, subtask_id_value, event_type=None):
    matches = []
    for event in read_plan_events(plan_id_value):
        if str(event.get("subtask_id")) != str(subtask_id_value):
            continue
        if event_type and event.get("event") != event_type:
            continue
        matches.append(event)
    return matches[-1] if matches else None


def list_plans():
    if not PLANS_DIR.exists():
        return []
    plans = []
    for path in sorted(PLANS_DIR.iterdir()):
        if path.is_dir() and (path / "plan.json").exists():
            plans.append(load_json_file(path / "plan.json", {}) or {})
    return plans


def detect_plan_blocked_capabilities(config, plan):
    dummy_agent = {"approval_required": sorted(PLAN_BLOCKED_CAPABILITIES)}
    chunks = [plan.get("goal", "")]
    for subtask in plan.get("subtasks") or []:
        chunks.extend([subtask.get("goal", ""), subtask.get("check", "") or ""])
    return detect_approvals(config, dummy_agent, "\n".join(chunks))


def validate_plan_shape(plan):
    errors = []
    subtasks = plan.get("subtasks") or []
    if not subtasks:
        errors.append("plan must include at least one subtask")
    seen = set()
    previous = None
    for subtask in subtasks:
        sid = str(subtask.get("id"))
        if not sid:
            errors.append("subtask missing id")
        if sid in seen:
            errors.append(f"duplicate subtask id: {sid}")
        seen.add(sid)
        depends = subtask.get("depends_on") or []
        if depends not in ([], ([previous] if previous else [])):
            errors.append(f"subtask {sid} has unsupported dependency shape: {depends}")
        if subtask.get("agent") not in (load_config().get("agents") or {}):
            errors.append(f"subtask {sid} references unknown agent: {subtask.get('agent')}")
        if subtask.get("type") not in {"diagnose", "iterate", "review", "run"}:
            errors.append(f"subtask {sid} has unsupported type: {subtask.get('type')}")
        if subtask.get("type") in {"diagnose", "iterate"} and not subtask.get("check"):
            errors.append(f"subtask {sid} type {subtask.get('type')} requires check")
        previous = sid
    blocked = detect_plan_blocked_capabilities(load_config(), plan)
    if blocked:
        errors.append("dangerous capabilities blocked in plans: " + ",".join(blocked))
    return errors


def default_plan_for_goal(plan_id_value, workspace, memory_namespace, goal):
    return {
        "plan_id": plan_id_value,
        "workspace": workspace,
        "memory_namespace": memory_namespace,
        "goal": goal,
        "status": "draft",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "subtasks": [
            {
                "id": "1",
                "type": "diagnose",
                "agent": "planner",
                "goal": "Inspect the workspace for the big goal, identify current state, risks, and likely next actions. Do not edit files.",
                "check": "true",
                "max_rounds": 1,
                "depends_on": [],
            },
            {
                "id": "2",
                "type": "iterate",
                "agent": "coder",
                "goal": "Make the smallest safe workspace-local change that advances the approved goal. Stay within normal local edit and test boundaries.",
                "check": "true",
                "max_rounds": 1,
                "depends_on": ["1"],
            },
            {
                "id": "3",
                "type": "review",
                "agent": "reviewer",
                "goal": "Review the completed work for correctness, regressions, and risky behavior. Do not edit files.",
                "depends_on": ["2"],
            },
        ],
    }


def subtask_mode(subtask):
    return "iterate" if subtask.get("check") else "run"


def queue_item_from_plan_subtask(plan, subtask):
    workspace_cfg, cwd, memory_namespace = resolve_workspace_options(plan.get("workspace"))
    config = load_config()
    memory_options = build_memory_options(config, enabled=True, query=subtask.get("goal"))
    mode = subtask_mode(subtask)
    return {
        "queue_id": queue_id(),
        "status": "queued",
        "created_from": "plan",
        "plan_id": plan.get("plan_id"),
        "subtask_id": subtask.get("id"),
        "agent": subtask.get("agent"),
        "mode": mode,
        "goal": subtask.get("goal"),
        "cwd": str(cwd),
        "workspace": plan.get("workspace"),
        "memory_namespace": memory_namespace,
        "memory": memory_options,
        "check": subtask.get("check"),
        "max_rounds": subtask.get("max_rounds") if mode == "iterate" else None,
        "depends_on": subtask.get("depends_on") or [],
        "created_at": now_iso(),
        "started_at": None,
        "ended_at": None,
        "task_id": None,
    }


def queue_item_from_plan_retry(plan, subtask, failed_item):
    item = queue_item_from_plan_subtask(plan, subtask)
    item["created_from"] = "plan_retry"
    item["retry_of_queue_id"] = failed_item.get("queue_id") if failed_item else None
    item["retry_of_task_id"] = failed_item.get("task_id") if failed_item else None
    item["retry_created_at"] = now_iso()
    return item


def queue_items_for_plan_subtask(plan_id_value, subtask_id_value):
    items = []
    for item in latest_queue_items().values():
        if item.get("created_from") in {"plan", "plan_retry"} and item.get("plan_id") == plan_id_value and str(item.get("subtask_id")) == str(subtask_id_value):
            items.append(item)
    return items


def queue_item_for_plan_subtask(plan_id_value, subtask_id_value):
    items = queue_items_for_plan_subtask(plan_id_value, subtask_id_value)
    if items:
        return items[-1]
    return None


def failed_queue_item_for_plan_subtask(plan_id_value, subtask_id_value):
    for item in reversed(queue_items_for_plan_subtask(plan_id_value, subtask_id_value)):
        if item.get("status") == "failed":
            return item
    return None


def derive_plan_status(plan):
    status = plans_mod.derive_plan_status(plan, queue_item_for_plan_subtask, latest_plan_event)
    status["goal"] = plan.get("goal")
    status["workspace"] = plan.get("workspace")
    normalized = []
    for row in status.get("subtasks") or []:
        normalized.append({
            "id": row.get("subtask_id"),
            "queue_id": row.get("queue_id"),
            "task_id": row.get("task_id"),
            "status": row.get("status"),
            "reason": row.get("reason"),
        })
    status["subtasks"] = normalized
    if status.get("blocked_reason") and not status.get("reason"):
        status["reason"] = status.get("blocked_reason")
    if "blocked_reason" in status:
        status.pop("blocked_reason", None)
    return status


def append_schedule_result(schedule_id_value, queue_id_value, task_id_value, status, completed_at, failure_class=None, retry_recommended=False):
    append_schedule({
        "schedule_id": schedule_id_value,
        "updated_at": now_iso(),
        "last_task_id": task_id_value,
        "last_queue_id": queue_id_value,
        "last_status": status,
        "last_failure_class": failure_class,
        "last_retry_recommended": bool(retry_recommended),
        "last_completed_at": completed_at,
    })


def enrich_scheduled_task_metadata(task_id_value, item, failure_class=None, retry_recommended=False):
    if not task_id_value:
        return
    task = latest_task(task_id_value)
    if not task:
        return
    run_dir = Path(task["run_dir"])
    meta = load_json_file(run_dir / "metadata.json", task) or task
    meta["created_from"] = item.get("created_from")
    meta["schedule_id"] = item.get("schedule_id")
    meta["workspace"] = item.get("workspace")
    meta["memory_namespace"] = item.get("memory_namespace")
    if failure_class:
        meta["failure_class"] = failure_class
        meta["retry_recommended"] = bool(retry_recommended)
    elif meta.get("status") == "failed":
        meta.setdefault("retry_recommended", False)
    write_json(run_dir / "metadata.json", meta)
    append_task(meta)


def classify_task_failure(task_id_value):
    if not task_id_value:
        return None, False
    task = latest_task(task_id_value)
    if not task:
        return None, False
    run_dir = Path(task.get("run_dir") or "")
    chunks = []
    for name in ("stdout.log", "stderr.log", "result.json"):
        path = run_dir / name
        if path.exists():
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return classify_failure_text("\n".join(chunks))


def run_task(args):
    args = normalize_run_args(args)
    ensure_state()
    config = load_config()
    agents = config.get("agents") or {}
    if args.agent not in agents:
        raise SystemExit(f"Unknown agent: {args.agent}")
    agent_cfg = agents[args.agent]
    tool = agent_cfg["tool"]
    model = args.model or agent_cfg.get("model") or config.get("models", {}).get("primary")
    autonomy = agent_cfg.get("autonomy", "read_only")
    workspace_cfg, workspace_cwd, memory_namespace = resolve_workspace_options(getattr(args, "workspace", None))
    run_cwd = workspace_cwd or Path.cwd()
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        raise SystemExit("Prompt is required")

    memory_opts = build_memory_options(
        config,
        enabled=bool(getattr(args, "workspace", None)) and not getattr(args, "no_memory", False),
        query=getattr(args, "memory_query", None) or prompt,
        reason="no_memory_flag" if getattr(args, "no_memory", False) else ("non_workspace_task" if not getattr(args, "workspace", None) else None),
    )
    effective_prompt, memory_recall = apply_memory_prelude(prompt, memory_namespace, memory_opts.get("query") or prompt, memory_opts)
    if getattr(args, "memory_preview", False):
        print_json({
            "would_run": False,
            "workspace": getattr(args, "workspace", None),
            "cwd": str(run_cwd),
            "memory_recall": memory_recall,
            "prompt": effective_prompt,
        })
        return 0

    approvals = detect_approvals(config, agent_cfg, prompt)
    approved = parse_approved(getattr(args, "approve", []))
    unapproved = unauthorized_approvals(approvals, approved)
    if getattr(args, "dry_run", False):
        would_run = not unapproved
        print_json({
            "would_run": would_run,
            "status": "dry_run_ok" if would_run else "approval_required",
            "agent": args.agent,
            "tool": tool,
            "model": model,
            "autonomy": autonomy,
            "approval_capabilities": approvals,
            "unapproved_capabilities": unapproved,
            "fallback_profiles": agent_cfg.get("fallback_profiles") or [],
            "workspace": getattr(args, "workspace", None),
            "cwd": str(run_cwd),
            "memory_recall": memory_recall,
        })
        return 0 if would_run else 2

    tid = task_id(args.agent)
    run_dir = RUNS_DIR / tid
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "prompt.txt").write_text(effective_prompt + "\n", encoding="utf-8")

    base_meta = {
        "task_id": tid,
        "agent": args.agent,
        "tool": tool,
        "model": model,
        "status": "approval_required" if unapproved else "running",
        "started_at": now_iso(),
        "ended_at": None,
        "fallback_used": False,
        "approval_required": bool(approvals),
        "approval_capabilities": approvals,
        "approved_capabilities": sorted(approved),
        "unapproved_capabilities": unapproved,
        "autonomy": autonomy,
        "run_dir": str(run_dir),
        "cwd": str(run_cwd),
        "workspace": getattr(args, "workspace", None),
        "memory_namespace": memory_namespace,
        "memory_recall": memory_recall,
    }
    write_json(run_dir / "metadata.json", base_meta)
    append_task(base_meta)

    if unapproved:
        result = {
            "task_id": tid,
            "status": "approval_required",
            "approval_capabilities": approvals,
            "approved_capabilities": sorted(approved),
            "unapproved_capabilities": unapproved,
            "message": "Task blocked by MVP policy gate. Re-run with --approve <capability> to execute locally.",
        }
        write_json(run_dir / "result.json", result)
        print_json(result)
        return 2

    attempts, final = execute_agent_attempts(agent_cfg, tool, model, effective_prompt, autonomy, args.fallback, args.timeout, cwd=run_cwd)
    for attempt in attempts:
        index = attempt["attempt"]
        result = attempt
        (run_dir / f"attempt-{index}-stdout.log").write_text(result["stdout"], encoding="utf-8")
        (run_dir / f"attempt-{index}-stderr.log").write_text(result["stderr"], encoding="utf-8")
    if final is None:
        raise SystemExit("No execution attempts were made")
    (run_dir / "stdout.log").write_text(final["stdout"], encoding="utf-8")
    (run_dir / "stderr.log").write_text(final["stderr"], encoding="utf-8")
    status = "completed" if final["returncode"] == 0 else "failed"
    meta = {**base_meta, "status": status, "ended_at": now_iso(), "fallback_used": final["attempt"] > 1, "model": final["model"]}
    write_json(run_dir / "metadata.json", meta)
    result_summary = {"task_id": tid, "status": status, "returncode": final["returncode"], "attempts": attempts}
    write_json(run_dir / "result.json", result_summary)
    append_task(meta)
    print_json({"task_id": tid, "status": status, "model": final["model"], "run_dir": str(run_dir)})
    return final["returncode"]


def iterate_cmd(args):
    args = normalize_iterate_args(args)
    ensure_state()
    config = load_config()
    agents = config.get("agents") or {}
    if args.agent not in agents:
        raise SystemExit(f"Unknown agent: {args.agent}")
    agent_cfg = agents[args.agent]
    tool = agent_cfg["tool"]
    model = args.model or agent_cfg.get("model") or config.get("models", {}).get("primary")
    autonomy = agent_cfg.get("autonomy", "read_only")
    workspace_cfg, workspace_cwd, memory_namespace = resolve_workspace_options(getattr(args, "workspace", None))
    run_cwd = workspace_cwd or Path.cwd()
    goal = " ".join(args.goal).strip()
    if not goal:
        raise SystemExit("Goal is required")
    if not args.check:
        raise SystemExit("--check is required")

    memory_opts = build_memory_options(
        config,
        enabled=bool(getattr(args, "workspace", None)) and not getattr(args, "no_memory", False),
        query=getattr(args, "memory_query", None) or goal,
        reason="no_memory_flag" if getattr(args, "no_memory", False) else ("non_workspace_task" if not getattr(args, "workspace", None) else None),
    )
    effective_goal, memory_recall = apply_memory_prelude(goal, memory_namespace, memory_opts.get("query") or goal, memory_opts)
    if getattr(args, "memory_preview", False):
        print_json({
            "would_run": False,
            "workspace": getattr(args, "workspace", None),
            "cwd": str(run_cwd),
            "memory_recall": memory_recall,
            "goal": effective_goal,
        })
        return 0

    policy_text = f"{goal}\n{args.check}"
    approvals = detect_approvals(config, agent_cfg, policy_text)
    blocked = sorted(set(approvals) & ITERATE_BLOCKED_CAPABILITIES)
    approved = parse_approved(args.approve)
    unapproved = unauthorized_approvals(approvals, approved)
    would_run = not blocked and not unapproved
    if args.dry_run:
        print_json({
            "would_run": would_run,
            "status": "dry_run_ok" if would_run else "approval_required",
            "agent": args.agent,
            "tool": tool,
            "model": model,
            "autonomy": autonomy,
            "goal": goal,
            "check": args.check,
            "max_rounds": args.max_rounds,
            "approval_capabilities": approvals,
            "blocked_capabilities": blocked,
            "unapproved_capabilities": unapproved,
            "workspace": getattr(args, "workspace", None),
            "cwd": str(run_cwd),
            "memory_recall": memory_recall,
            "note": "iterate v0.2 blocks push/deploy/secrets/global/destructive/global-install capabilities entirely" if blocked else "",
        })
        return 0 if would_run else 2
    if blocked or unapproved:
        tid = iterate_task_id(args.agent)
        run_dir = RUNS_DIR / tid
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "goal.txt").write_text(goal + "\n", encoding="utf-8")
        meta = {
            "task_id": tid,
            "mode": "iterate",
            "agent": args.agent,
            "tool": tool,
            "model": model,
            "status": "approval_required",
            "started_at": now_iso(),
            "ended_at": now_iso(),
            "goal": goal,
            "check": args.check,
            "max_rounds": args.max_rounds,
            "rounds": 0,
            "final_check_passed": False,
            "approval_required": True,
            "approval_capabilities": approvals,
            "approved_capabilities": sorted(approved),
            "blocked_capabilities": blocked,
            "unapproved_capabilities": unapproved,
            "autonomy": autonomy,
            "run_dir": str(run_dir),
            "cwd": str(run_cwd),
            "workspace": getattr(args, "workspace", None),
            "memory_namespace": memory_namespace,
            "memory_recall": memory_recall,
        }
        write_json(run_dir / "metadata.json", meta)
        write_json(run_dir / "result.json", meta)
        append_task(meta)
        print_json({
            "task_id": tid,
            "status": "approval_required",
            "approval_capabilities": approvals,
            "blocked_capabilities": blocked,
            "unapproved_capabilities": unapproved,
            "message": "iterate v0.2 is local-workspace only; blocked risky capabilities are not allowed inside iterate.",
        })
        return 2

    tid = iterate_task_id(args.agent)
    run_dir = RUNS_DIR / tid
    rounds_dir = run_dir / "rounds"
    run_dir.mkdir(parents=True, exist_ok=False)
    rounds_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "goal.txt").write_text(effective_goal + "\n", encoding="utf-8")
    started = now_iso()
    base_meta = {
        "task_id": tid,
        "mode": "iterate",
        "agent": args.agent,
        "tool": tool,
        "model": model,
        "status": "running",
        "started_at": started,
        "ended_at": None,
        "goal": goal,
        "check": args.check,
        "max_rounds": args.max_rounds,
        "rounds": 0,
        "final_check_passed": False,
        "fallback_used": False,
        "approval_required": False,
        "approval_capabilities": approvals,
        "approved_capabilities": sorted(approved),
        "unapproved_capabilities": [],
        "autonomy": autonomy,
        "run_dir": str(run_dir),
        "cwd": str(run_cwd),
        "workspace": getattr(args, "workspace", None),
        "memory_namespace": memory_namespace,
        "memory_recall": memory_recall,
    }
    write_json(run_dir / "metadata.json", base_meta)
    append_task(base_meta)

    round_results = []
    initial_dir = rounds_dir / "0"
    initial_dir.mkdir(parents=True, exist_ok=True)
    try:
        check_result = run_shell_check(args.check, run_cwd, args.check_timeout)
    except subprocess.TimeoutExpired as exc:
        check_result = {"started_at": now_iso(), "ended_at": now_iso(), "returncode": 124, "stdout": exc.stdout or "", "stderr": f"check timeout after {args.check_timeout}s"}
    (initial_dir / "check-stdout.log").write_text(check_result["stdout"], encoding="utf-8")
    (initial_dir / "check-stderr.log").write_text(check_result["stderr"], encoding="utf-8")
    write_json(initial_dir / "result.json", {"round": 0, "type": "initial_check", "check": check_result})
    if check_result["returncode"] == 0:
        meta = {**base_meta, "status": "completed", "ended_at": now_iso(), "rounds": 0, "final_check_passed": True}
        result = {"task_id": tid, "status": "completed", "agent": args.agent, "rounds": 0, "max_rounds": args.max_rounds, "check": args.check, "final_check_passed": True}
        if getattr(args, "tail", None) is not None:
            result["check_stdout_tail"] = tail_lines(check_result.get("stdout", ""), args.tail)
            result["check_stderr_tail"] = tail_lines(check_result.get("stderr", ""), args.tail)
        write_json(run_dir / "metadata.json", meta)
        write_json(run_dir / "result.json", result)
        append_task(meta)
        print_json(result)
        return 0

    final_status = "failed"
    final_check_passed = False
    fallback_used = False
    last_check = check_result
    for round_num in range(1, args.max_rounds + 1):
        rd = rounds_dir / str(round_num)
        rd.mkdir(parents=True, exist_ok=True)
        if autonomy == "read_only":
            action_instruction = "Analyze the failure and report the likely cause and next safe action. Do not edit files or attempt to fix the workspace."
        else:
            action_instruction = "Fix the workspace locally so the check passes. Do not push, deploy, edit global config, touch secrets, install global packages, or delete outside the workspace."
        prompt = f"""Goal:
{effective_goal}

Check command:
{args.check}

The check failed. {action_instruction}

Previous check stdout:
{tail_text(last_check.get('stdout', ''))}

Previous check stderr:
{tail_text(last_check.get('stderr', ''))}

Shared tool guidance: if your runtime exposes Agent Memory Bridge, Context7, or Playwright tools, use them as evidence lanes when relevant. Prefer Agent Memory Bridge for project/domain memory, Context7 for current library docs, and Playwright for browser/UI validation. Do not assume those tools exist; proceed with local files and commands when unavailable.
""".strip()
        (rd / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
        attempts, final_attempt = execute_agent_attempts(agent_cfg, tool, model, prompt, autonomy, args.fallback, args.timeout, cwd=run_cwd)
        for attempt in attempts:
            idx = attempt["attempt"]
            (rd / f"attempt-{idx}-stdout.log").write_text(attempt["stdout"], encoding="utf-8")
            (rd / f"attempt-{idx}-stderr.log").write_text(attempt["stderr"], encoding="utf-8")
        if final_attempt and final_attempt.get("attempt", 1) > 1:
            fallback_used = True
        if not final_attempt or final_attempt["returncode"] != 0:
            round_result = {"round": round_num, "agent_returncode": final_attempt.get("returncode") if final_attempt else None, "attempts": attempts, "check": None}
            write_json(rd / "result.json", round_result)
            round_results.append(round_result)
            break
        try:
            last_check = run_shell_check(args.check, run_cwd, args.check_timeout)
        except subprocess.TimeoutExpired as exc:
            last_check = {"started_at": now_iso(), "ended_at": now_iso(), "returncode": 124, "stdout": exc.stdout or "", "stderr": f"check timeout after {args.check_timeout}s"}
        (rd / "stdout.log").write_text(final_attempt["stdout"], encoding="utf-8")
        (rd / "stderr.log").write_text(final_attempt["stderr"], encoding="utf-8")
        (rd / "check-stdout.log").write_text(last_check["stdout"], encoding="utf-8")
        (rd / "check-stderr.log").write_text(last_check["stderr"], encoding="utf-8")
        round_result = {"round": round_num, "agent_returncode": final_attempt["returncode"], "attempts": attempts, "check": last_check}
        write_json(rd / "result.json", round_result)
        round_results.append(round_result)
        if last_check["returncode"] == 0:
            final_status = "completed"
            final_check_passed = True
            break

    rounds_count = len(round_results)
    meta = {**base_meta, "status": final_status, "ended_at": now_iso(), "rounds": rounds_count, "final_check_passed": final_check_passed, "fallback_used": fallback_used}
    result = {"task_id": tid, "status": final_status, "agent": args.agent, "rounds": rounds_count, "max_rounds": args.max_rounds, "check": args.check, "final_check_passed": final_check_passed}
    if getattr(args, "tail", None) is not None:
        result["check_stdout_tail"] = tail_lines(last_check.get("stdout", ""), args.tail)
        result["check_stderr_tail"] = tail_lines(last_check.get("stderr", ""), args.tail)
    write_json(run_dir / "metadata.json", meta)
    write_json(run_dir / "result.json", result)
    append_task(meta)
    print_json(result)
    return 0 if final_check_passed else 1


def submit_cmd(args):
    args = normalize_submit_args(args)
    ensure_state()
    config = load_config()
    agents = config.get("agents") or {}
    if args.agent not in agents:
        raise SystemExit(f"Unknown agent: {args.agent}")
    goal = " ".join(args.goal).strip()
    if not goal:
        raise SystemExit("Goal is required")

    qid = queue_id()
    cwd = Path.cwd().resolve()
    workspace_name = args.workspace
    memory_namespace = None

    if workspace_name and args.cwd:
        raise SystemExit("Error: --workspace and --cwd cannot be used together.")

    if workspace_name:
        workspaces = load_workspaces()
        if workspace_name not in workspaces:
            raise SystemExit(f"Workspace '{workspace_name}' not found.")
        workspace_cfg = workspaces[workspace_name]
        cwd = Path(workspace_cfg["path"]).expanduser().resolve()
        memory_namespace = workspace_cfg.get("memory_namespace")

    if args.cwd:
        cwd = Path(args.cwd).expanduser().resolve()

    if not cwd.exists() or not cwd.is_dir():
        raise SystemExit(f"Invalid cwd: {cwd}")

    memory_options = build_memory_options(
        config,
        enabled=bool(workspace_name) and not getattr(args, "no_memory", False),
        query=getattr(args, "memory_query", None),
        reason="no_memory_flag" if getattr(args, "no_memory", False) else ("non_workspace_task" if not workspace_name else None),
    )
    if getattr(args, "memory_preview", False):
        if not workspace_name:
            print_json({"workspace": None, "memory_recall": {"enabled": False, "reason": "non_workspace_task"}})
        else:
            query = memory_options.get("query") or goal
            print_json(recall_preview_payload(workspace_name, query, memory_options))
        return 0

    item = {
        "queue_id": qid,
        "status": "queued",
        "agent": args.agent,
        "mode": "iterate" if args.check else "run",
        "goal": goal,
        "cwd": str(cwd),
        "workspace": workspace_name,
        "memory_namespace": memory_namespace,
        "memory": memory_options,
        "check": args.check,
        "max_rounds": args.max_rounds if args.check else None,
        "created_at": now_iso(),
        "started_at": None,
        "ended_at": None,
        "task_id": None,
    }
    append_queue(item)
    print_json(item)
    return 0


def schedule_add_cmd(args):
    ensure_state()
    config = load_config()
    agents = config.get("agents") or {}
    if args.agent not in agents:
        raise SystemExit(f"Unknown agent: {args.agent}")
    if args.type not in {"run", "iterate"}:
        raise SystemExit("--type must be run or iterate")
    if args.type == "iterate" and not args.check:
        raise SystemExit("--check is required for iterate schedules")
    try:
        cron_matches_now(args.cron, dt.datetime.now().astimezone())
    except Exception as exc:
        raise SystemExit(f"Invalid cron: {exc}")
    sid = schedule_id(args.name)
    existing = schedule_by_name(args.name)
    if existing and not existing.get("removed"):
        raise SystemExit(f"Schedule already exists: {args.name}")
    workspace_cfg, cwd, memory_namespace = resolve_workspace_options(args.workspace)
    memory_options = build_memory_options(
        config,
        enabled=not getattr(args, "no_memory", False),
        query=getattr(args, "memory_query", None),
        reason="no_memory_flag" if getattr(args, "no_memory", False) else None,
    )
    record = {
        "schedule_id": sid,
        "name": args.name,
        "enabled": True,
        "removed": False,
        "workspace": args.workspace,
        "cwd": str(cwd),
        "memory_namespace": memory_namespace,
        "type": args.type,
        "agent": args.agent,
        "goal": args.goal,
        "check": args.check,
        "cron": args.cron,
        "timezone": "local",
        "max_rounds": args.max_rounds,
        "memory": memory_options,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "last_due_at": None,
        "last_due_window": None,
        "last_queue_id": None,
        "last_task_id": None,
    }
    append_schedule(record)
    print_json(record)
    return 0


def schedule_list_cmd(args):
    schedules = [s for s in latest_schedules().values() if not s.get("removed")]
    if args.json:
        print_json(schedules)
    else:
        for s in schedules:
            status = "enabled" if s.get("enabled", True) else "paused"
            print(f"{s.get('schedule_id')} {status} {s.get('cron')} {s.get('type')} {s.get('agent')} {s.get('workspace')} {s.get('goal')}")
    return 0


def schedule_show_cmd(args):
    schedule = schedule_by_name(args.name)
    if not schedule or schedule.get("removed"):
        raise SystemExit(f"Unknown schedule: {args.name}")
    print_json(schedule)
    return 0


def schedule_transition_cmd(args, action):
    schedule = schedule_by_name(args.name)
    if not schedule or schedule.get("removed"):
        raise SystemExit(f"Unknown schedule: {args.name}")
    update = {"schedule_id": schedule.get("schedule_id"), "name": schedule.get("name"), "updated_at": now_iso()}
    if action == "remove":
        update.update({"removed": True, "enabled": False, "removed_at": now_iso()})
    elif action == "pause":
        update.update({"enabled": False})
    elif action == "resume":
        update.update({"enabled": True})
    append_schedule(update)
    latest = schedule_by_name(args.name)
    print_json(latest)
    return 0


def schedule_remove_cmd(args):
    return schedule_transition_cmd(args, "remove")


def schedule_pause_cmd(args):
    return schedule_transition_cmd(args, "pause")


def schedule_resume_cmd(args):
    return schedule_transition_cmd(args, "resume")


def schedule_run_due_cmd(args):
    ensure_state()
    when = dt.datetime.now().astimezone()
    due = []
    skipped = []
    submitted = []
    for schedule in latest_schedules().values():
        if schedule.get("removed"):
            continue
        is_due, reason = schedule_due(schedule, when)
        if not is_due:
            skipped.append({"schedule_id": schedule.get("schedule_id"), "reason": reason})
            continue
        item = queue_item_from_schedule(schedule, when)
        due_item = {
            "schedule_id": schedule.get("schedule_id"),
            "name": schedule.get("name"),
            "would_submit": True,
            "due_window": item.get("due_window"),
            "queue_item": item,
        }
        due.append(due_item)
        if not args.dry_run:
            append_queue(item)
            update = {
                "schedule_id": schedule.get("schedule_id"),
                "name": schedule.get("name"),
                "updated_at": now_iso(),
                "last_due_at": when.isoformat(),
                "last_due_window": item.get("due_window"),
                "last_queue_id": item.get("queue_id"),
                "last_task_id": None,
            }
            append_schedule(update)
            submitted.append({"schedule_id": schedule.get("schedule_id"), "queue_id": item.get("queue_id"), "due_window": item.get("due_window")})
    payload = {"now": when.isoformat(), "dry_run": bool(args.dry_run), "due": due, "submitted": submitted, "skipped": skipped}
    if args.json or args.dry_run:
        print_json(payload)
    else:
        for row in submitted:
            print(f"submitted {row['schedule_id']} -> {row['queue_id']}")
        if not submitted:
            print("No due schedules submitted.")
    return 0


def schedule_retry_cmd(args):
    schedule = schedule_by_name(args.name)
    if not schedule or schedule.get("removed"):
        raise SystemExit(f"Unknown schedule: {args.name}")
    item = queue_item_from_schedule(schedule)
    item["created_from"] = "schedule_retry"
    item["retry_of_queue_id"] = schedule.get("last_queue_id")
    item["retry_of_task_id"] = schedule.get("last_task_id")
    append_queue(item)
    append_schedule({
        "schedule_id": schedule.get("schedule_id"),
        "name": schedule.get("name"),
        "updated_at": now_iso(),
        "last_retry_queue_id": item.get("queue_id"),
    })
    print_json({"schedule_id": schedule.get("schedule_id"), "queue_id": item.get("queue_id"), "queued": True, "item": item})
    return 0


def plan_create_cmd(args):
    ensure_state()
    goal = " ".join(args.goal).strip()
    if not goal:
        raise SystemExit("Goal is required")
    workspace_cfg, cwd, memory_namespace = resolve_workspace_options(args.workspace)
    pid = plan_id()
    plan = default_plan_for_goal(pid, args.workspace, memory_namespace, goal)
    errors = validate_plan_shape(plan)
    if errors:
        plan["status"] = "rejected"
        plan["validation_errors"] = errors
    pdir = plan_dir(pid)
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "goal.txt").write_text(goal + "\n", encoding="utf-8")
    save_plan(plan)
    update_plan_status_file(plan)
    print_json({"plan_id": pid, "status": plan.get("status"), "plan_dir": str(pdir), "validation_errors": plan.get("validation_errors", [])})
    return 0 if not errors else 2


def plan_show_cmd(args):
    plan = load_plan(args.plan_id)
    if args.json:
        print_json(plan)
    else:
        print_json(plan)
    return 0


def plan_list_cmd(args):
    plans = list_plans()
    if args.json:
        print_json(plans)
    else:
        for plan in plans:
            print(f"{plan.get('plan_id')} {plan.get('status')} {plan.get('workspace')} {plan.get('goal')}")
    return 0


def plan_review_cmd(args):
    plan = load_plan(args.plan_id)
    errors = validate_plan_shape(plan)
    risk = "high" if errors else "low"
    verdict = "reject" if errors else "approve"
    lines = [
        "# Plan Review",
        "",
        f"Verdict: {verdict}",
        "",
        "Issues:",
    ]
    if errors:
        lines.extend([f"- {e}" for e in errors])
    else:
        lines.append("- No blocking issues found in the plan contract.")
    lines.extend([
        "",
        "Recommended changes:",
        "- Keep execution sequential and inspect task summaries after each major step.",
        "",
        f"Risk level: {risk}",
        "",
    ])
    pdir = plan_dir(args.plan_id)
    (pdir / "review.md").write_text("\n".join(lines), encoding="utf-8")
    plan["status"] = "reviewed" if not errors else "rejected"
    plan["reviewed_at"] = now_iso()
    plan["review_verdict"] = verdict
    plan["validation_errors"] = errors
    plan["updated_at"] = now_iso()
    save_plan(plan)
    update_plan_status_file(plan)
    if args.json:
        print_json({"plan_id": args.plan_id, "status": plan["status"], "verdict": verdict, "errors": errors, "review": str(pdir / "review.md")})
    else:
        print((pdir / "review.md").read_text(encoding="utf-8"), end="")
    return 0 if not errors else 2


def plan_approve_cmd(args):
    plan = load_plan(args.plan_id)
    errors = validate_plan_shape(plan)
    if errors:
        raise SystemExit("Cannot approve invalid plan: " + "; ".join(errors))
    plan["status"] = "approved"
    plan["approved_at"] = now_iso()
    plan["approved_by"] = "local-user"
    plan["updated_at"] = now_iso()
    save_plan(plan)
    update_plan_status_file(plan)
    print_json({"plan_id": args.plan_id, "status": "approved", "approved_at": plan["approved_at"]})
    return 0


def plan_reject_cmd(args):
    plan = load_plan(args.plan_id)
    plan["status"] = "rejected"
    plan["rejected_at"] = now_iso()
    plan["updated_at"] = now_iso()
    save_plan(plan)
    update_plan_status_file(plan)
    print_json({"plan_id": args.plan_id, "status": "rejected"})
    return 0


def plan_enqueue_cmd(args):
    plan = load_plan(args.plan_id)
    if plan.get("status") != "approved":
        raise SystemExit(f"Plan must be approved before enqueue. Current status: {plan.get('status')}")
    errors = validate_plan_shape(plan)
    if errors:
        raise SystemExit("Cannot enqueue invalid plan: " + "; ".join(errors))
    queue_items = []
    for subtask in plan.get("subtasks") or []:
        if queue_item_for_plan_subtask(plan.get("plan_id"), subtask.get("id")):
            continue
        item = queue_item_from_plan_subtask(plan, subtask)
        append_queue(item)
        queue_items.append(item)
    plan["status"] = "enqueued"
    plan["enqueued_at"] = now_iso()
    plan["updated_at"] = now_iso()
    save_plan(plan)
    receipt = {"plan_id": args.plan_id, "status": "enqueued", "queue_items": queue_items}
    write_json(plan_dir(args.plan_id) / "enqueue.json", receipt)
    update_plan_status_file(plan)
    print_json(receipt)
    return 0


def plan_status_cmd(args):
    plan = load_plan(args.plan_id)
    status = derive_plan_status(plan)
    write_json(plan_dir(args.plan_id) / "status.json", status)
    if args.json:
        print_json(status)
    else:
        print_json(status)
    return 0


def plan_retry_cmd(args):
    plan = load_plan(args.plan_id)
    subtask = next((s for s in plan.get("subtasks") or [] if str(s.get("id")) == str(args.subtask_id)), None)
    if not subtask:
        raise SystemExit(f"Unknown subtask id: {args.subtask_id}")
    status = derive_plan_status(plan)
    row = next((r for r in status.get("subtasks") or [] if str(r.get("id")) == str(args.subtask_id)), None)
    if not row or row.get("status") not in {"failed", "blocked"}:
        raise SystemExit(f"Subtask {args.subtask_id} is not failed/blocked; current status: {(row or {}).get('status')}")
    failed_item = failed_queue_item_for_plan_subtask(args.plan_id, args.subtask_id)
    if not failed_item:
        raise SystemExit(f"Subtask {args.subtask_id} has no failed queue item to retry")
    item = queue_item_from_plan_retry(plan, subtask, failed_item)
    append_queue(item)
    event = append_plan_event(args.plan_id, {
        "event": "retry",
        "subtask_id": str(args.subtask_id),
        "queue_id": item.get("queue_id"),
        "retry_of_queue_id": failed_item.get("queue_id"),
        "retry_of_task_id": failed_item.get("task_id"),
    })
    plan["status"] = "running"
    plan["updated_at"] = now_iso()
    save_plan(plan)
    update_plan_status_file(plan)
    print_json({"plan_id": args.plan_id, "subtask_id": str(args.subtask_id), "queued": True, "queue_id": item.get("queue_id"), "item": item, "event": event})
    return 0


def plan_skip_cmd(args):
    reason = (args.reason or "").strip()
    if not reason:
        raise SystemExit("--reason is required")
    plan = load_plan(args.plan_id)
    subtask = next((s for s in plan.get("subtasks") or [] if str(s.get("id")) == str(args.subtask_id)), None)
    if not subtask:
        raise SystemExit(f"Unknown subtask id: {args.subtask_id}")
    event = append_plan_event(args.plan_id, {"event": "skip", "subtask_id": str(args.subtask_id), "reason": reason})
    plan["updated_at"] = now_iso()
    save_plan(plan)
    status = derive_plan_status(plan)
    write_json(plan_dir(args.plan_id) / "status.json", status)
    print_json({"plan_id": args.plan_id, "subtask_id": str(args.subtask_id), "status": "skipped", "reason": reason, "event": event})
    return 0


def plan_repair_cmd(args):
    plan = load_plan(args.plan_id)
    status = derive_plan_status(plan)
    suggestions = []
    if status.get("status") == "blocked" and status.get("blocked_on"):
        suggestions.append({
            "type": "retry_or_skip",
            "subtask_id": status.get("blocked_on"),
            "message": f"Inspect subtask {status.get('blocked_on')} logs, then run `agentctl plan retry {args.plan_id} {status.get('blocked_on')}` or `agentctl plan skip {args.plan_id} {status.get('blocked_on')} --reason \"...\"`.",
        })
    else:
        suggestions.append({"type": "status_review", "message": "No failed subtask is currently blocking this plan. Review status before changing recovery state."})
    for row in status.get("subtasks") or []:
        if row.get("status") == "failed" and row.get("task_id"):
            suggestions.append({"type": "inspect_task", "subtask_id": row.get("id"), "message": f"Run `agentctl show {row.get('task_id')} --json` and `agentctl logs {row.get('task_id')} --file stderr --tail 80`."})
    payload = {
        "plan_id": args.plan_id,
        "created_at": now_iso(),
        "status": status,
        "suggestions": suggestions,
        "applied": False,
        "enqueued": False,
        "executed": False,
    }
    pdir = plan_dir(args.plan_id)
    write_json(pdir / "repair.json", payload)
    lines = ["# Plan Repair Suggestions", "", f"Plan: {args.plan_id}", f"Status: {status.get('status')}", "", "## Suggestions", ""]
    for suggestion in suggestions:
        lines.append(f"- {suggestion.get('message')}")
    lines.extend(["", "These suggestions are advisory only. No plan, queue, or task state was changed.", ""])
    (pdir / "repair.md").write_text("\n".join(lines), encoding="utf-8")
    if args.json:
        print_json(payload)
    else:
        print((pdir / "repair.md").read_text(encoding="utf-8"), end="")
    return 0


def plan_summarize_cmd(args):
    plan = load_plan(args.plan_id)
    status = derive_plan_status(plan)
    counts = {}
    for row in status.get("subtasks") or []:
        counts[row.get("status")] = counts.get(row.get("status"), 0) + 1
    next_action = "No action required; plan is complete." if status.get("status") == "completed" else "Inspect status and continue manually."
    if status.get("status") == "blocked" and status.get("blocked_on"):
        next_action = f"Inspect subtask {status.get('blocked_on')} and choose `plan retry` or `plan skip --reason`."
    lines = [
        "# Plan Summary",
        "",
        f"Goal: {plan.get('goal')}",
        f"Workspace: {plan.get('workspace')}",
        f"Status: {status.get('status')}",
        f"Blocked on: {status.get('blocked_on') or '-'}",
        f"Reason: {status.get('reason') or '-'}",
        "",
        "## Counts",
        "",
        f"- Completed: {counts.get('completed', 0)}",
        f"- Failed: {counts.get('failed', 0)}",
        f"- Skipped: {counts.get('skipped', 0)}",
        f"- Blocked: {counts.get('blocked', 0)}",
        f"- Queued: {counts.get('queued', 0)}",
        f"- Pending: {counts.get('pending', 0)}",
        "",
        "## Subtasks",
        "",
    ]
    for row in status.get("subtasks") or []:
        lines.append(f"- {row.get('id')}: {row.get('status')} queue={row.get('queue_id') or '-'} task={row.get('task_id') or '-'}")
    lines.extend(["", "## Completed Work", ""])
    completed_any = False
    for row in status.get("subtasks") or []:
        if row.get("status") == "completed":
            lines.append(f"- Subtask {row.get('id')} completed.")
            completed_any = True
    if not completed_any:
        lines.append("- None.")
    lines.extend(["", "## Failed / Blocked Work", ""])
    failed_any = False
    for row in status.get("subtasks") or []:
        if row.get("status") in {"failed", "blocked", "skipped"}:
            suffix = f" reason={row.get('reason')}" if row.get("reason") else ""
            lines.append(f"- Subtask {row.get('id')} {row.get('status')}.{suffix}")
            failed_any = True
    if not failed_any:
        lines.append("- None.")
    lines.extend(["", "## Checks", ""])
    for subtask in plan.get("subtasks") or []:
        if subtask.get("check"):
            lines.append(f"- Subtask {subtask.get('id')}: `{subtask.get('check')}`")
    lines.extend(["", "## Task Summaries / Memory Candidates", ""])
    any_task_detail = False
    for row in status.get("subtasks") or []:
        task_id_value = row.get("task_id")
        if not task_id_value:
            continue
        task = latest_task(task_id_value)
        if not task:
            continue
        run_dir = Path(task.get("run_dir") or "")
        summary_json = load_json_file(run_dir / "summary.json", {}) or {}
        candidates = load_json_file(run_dir / "memory-candidates.json", []) or []
        lines.append(f"- Subtask {row.get('id')} task={task_id_value} summary={'yes' if summary_json else 'no'} memory_candidates={len(candidates)}")
        any_task_detail = True
    if not any_task_detail:
        lines.append("- No per-task summaries detected yet.")
    lines.extend(["", "## Files Changed", "", "- Not collected directly by plan summary; inspect per-task summaries/logs for workspace changes.", "", "## Next Actions", "", f"- {next_action}", ""])
    path = plan_dir(args.plan_id) / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    if args.json:
        print_json({"plan_id": args.plan_id, "summary": str(path), "status": status})
    else:
        print(path.read_text(encoding="utf-8"), end="")
    return 0


def queue_cmd(args):
    items = list(latest_queue_items().values())
    if args.json:
        print_json(items)
    else:
        for item in items:
            print(f"{item['queue_id']} {item.get('status')} {item.get('mode')} {item.get('agent')} {item.get('task_id') or '-'} {item.get('goal')}")
    return 0


def queue_show_cmd(args):
    item = latest_queue_items().get(args.queue_id)
    if not item:
        raise SystemExit(f"Unknown queue id: {args.queue_id}")
    print_json(item)
    return 0

def run_next_cmd(args):
    ensure_state()
    try:
        with QueueLock():
            item = first_queued_item()
            if not item:
                payload = {"status": "empty", "message": "No queued items"}
                print_json(payload)
                return 0
            if args.dry_run:
                print_json({"would_run": True, "item": item})
                return 0
            cwd = Path(item.get("cwd") or Path.cwd()).expanduser().resolve()
            if not cwd.exists() or not cwd.is_dir():
                append_queue({"queue_id": item["queue_id"], "status": "failed", "ended_at": now_iso(), "task_id": None, "returncode": 2, "error": f"Invalid queued cwd: {cwd}"})
                print_json({"queue_id": item["queue_id"], "status": "failed", "task_id": None, "returncode": 2, "stderr": f"Invalid queued cwd: {cwd}"})
                return 2
            started = {"queue_id": item["queue_id"], "status": "running", "started_at": now_iso(), "cwd": str(cwd)}
            append_queue(started)
            goal = item["goal"]
            memory_opts = item.get("memory") or {"enabled": False, "reason": "legacy_queue_item"}
            effective_goal, memory_recall = apply_memory_prelude(goal, item.get("memory_namespace"), memory_opts.get("query") or goal, memory_opts)

            if item.get("mode") == "iterate":
                cmd = [str(Path(__file__)), "iterate", item["agent"], effective_goal, "--check", item["check"], "--max-rounds", str(item.get("max_rounds") or 5), "--json", "--no-memory"]
            else:
                cmd = [str(Path(__file__)), "run", item["agent"], effective_goal, "--no-memory"]

            proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
            task_id_value = extract_task_id(proc.stdout)
            status = "completed" if proc.returncode == 0 else "failed"
            failure_class, retry_recommended = classify_process_failure(proc.returncode, proc.stdout, proc.stderr)
            if proc.returncode != 0 and not failure_class and task_id_value:
                failure_class, retry_recommended = classify_task_failure(task_id_value)
            done = {
                "queue_id": item["queue_id"],
                "status": status,
                "ended_at": now_iso(),
                "task_id": task_id_value,
                "returncode": proc.returncode,
                "cwd": str(cwd),
                "memory_recall": memory_recall,
            }
            if item.get("created_from") in {"plan", "plan_retry"} and item.get("plan_id"):
                done["created_from"] = item.get("created_from")
                done["plan_id"] = item.get("plan_id")
                done["subtask_id"] = item.get("subtask_id")
                if item.get("created_from") == "plan_retry":
                    done["retry_of_queue_id"] = item.get("retry_of_queue_id")
                    done["retry_of_task_id"] = item.get("retry_of_task_id")
            if item.get("created_from") in {"schedule", "schedule_retry"}:
                done["created_from"] = item.get("created_from")
                done["schedule_id"] = item.get("schedule_id")
                if failure_class:
                    done["failure_class"] = failure_class
                    done["retry_recommended"] = retry_recommended
            append_queue(done)
            if item.get("created_from") in {"schedule", "schedule_retry"} and item.get("schedule_id"):
                append_schedule_result(item.get("schedule_id"), item.get("queue_id"), task_id_value, status, done["ended_at"], failure_class, retry_recommended)
            if task_id_value:
                task = latest_task(task_id_value)
                if task:
                    run_dir = Path(task["run_dir"])
                    meta = load_json_file(run_dir / "metadata.json", task) or task
                    meta["workspace"] = item.get("workspace")
                    meta["memory_namespace"] = item.get("memory_namespace")
                    meta["memory_recall"] = memory_recall
                    if item.get("created_from") in {"schedule", "schedule_retry"}:
                        meta["created_from"] = item.get("created_from")
                        meta["schedule_id"] = item.get("schedule_id")
                        if failure_class:
                            meta["failure_class"] = failure_class
                            meta["retry_recommended"] = retry_recommended
                    if item.get("created_from") in {"plan", "plan_retry"}:
                        meta["created_from"] = item.get("created_from")
                        meta["plan_id"] = item.get("plan_id")
                        meta["subtask_id"] = item.get("subtask_id")
                        if item.get("created_from") == "plan_retry":
                            meta["retry_of_queue_id"] = item.get("retry_of_queue_id")
                            meta["retry_of_task_id"] = item.get("retry_of_task_id")
                    write_json(run_dir / "metadata.json", meta)
                    append_task(meta)
            print_json({"queue_id": item["queue_id"], "status": status, "task_id": task_id_value, "returncode": proc.returncode, "cwd": str(cwd), "memory_recall": memory_recall, "stdout": proc.stdout, "stderr": proc.stderr})
            return proc.returncode
    except BlockingIOError:
        print_json({"status": "locked", "message": "Another run-next/agentd worker holds queue.lock"})
        return 3


def cancel_queue_item(queue_id_value, reason="cancelled"):
    append_queue({"queue_id": queue_id_value, "status": "cancelled", "ended_at": now_iso(), "reason": reason})


def status_cmd(args):
    rows = list(latest_tasks().values())[-args.limit :]
    if args.json:
        print_json(rows)
        return 0
    for task in rows:
        print(f"{task['task_id']} {task.get('status')} {task.get('agent')} {task.get('model')}")
    return 0


def pause_cmd(args):
    ensure_state()
    PAUSED_FILE.write_text(json.dumps({"paused": True, "updated_at": now_iso()}) + "\n", encoding="utf-8")
    try:
        PAUSED_FILE.chmod(0o600)
    except Exception:
        pass
    print_json({"paused": True, "path": str(PAUSED_FILE)})
    return 0


def resume_cmd(args):
    ensure_state()
    if PAUSED_FILE.exists():
        PAUSED_FILE.unlink()
    print_json({"paused": False, "path": str(PAUSED_FILE)})
    return 0


def daemon_status_payload():
    ensure_state()
    pid = None
    if AGENTD_PID.exists():
        try:
            pid = int(AGENTD_PID.read_text(encoding="utf-8").strip())
        except Exception:
            pid = None
    counts = queue_counts()
    running = bool(pid and pid_is_running(pid))
    return {
        "daemon": True,
        "running": running,
        "paused": PAUSED_FILE.exists(),
        "pid": pid if running else None,
        "queue_pending": counts.get("queued", 0),
        "queue_running": counts.get("running", 0),
        "last_task_id": last_queue_task_id(),
        "pid_file": str(AGENTD_PID),
        "log_file": str(AGENTD_LOG),
    }


def daemon_status_cmd(args):
    payload = daemon_status_payload()
    if args.json:
        print_json(payload)
    else:
        for key in ("daemon", "running", "paused", "pid", "queue_pending", "queue_running", "last_task_id"):
            print(f"{key}: {payload.get(key)}")
    return 0


def agentd_once_cmd(args):
    if PAUSED_FILE.exists() and not args.ignore_pause:
        print_json({"status": "paused", "message": "paused file exists", "path": str(PAUSED_FILE)})
        return 0
    return run_next_cmd(argparse.Namespace(dry_run=False))


def agentd_start_cmd(args):
    ensure_state()
    existing = daemon_status_payload()
    if existing.get("running"):
        print_json(existing)
        return 0
    agentd_path = shutil.which("agentd")
    if not agentd_path:
        raise SystemExit("agentd not found on PATH")
    log = AGENTD_LOG.open("a", encoding="utf-8")
    proc = subprocess.Popen([agentd_path], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    AGENTD_PID.write_text(str(proc.pid) + "\n", encoding="utf-8")
    try:
        AGENTD_PID.chmod(0o600)
        AGENTD_LOG.chmod(0o600)
    except Exception:
        pass
    print_json({"started": True, "pid": proc.pid, "log_file": str(AGENTD_LOG)})
    return 0


def agentd_stop_cmd(args):
    payload = daemon_status_payload()
    pid = payload.get("pid")
    if not pid:
        print_json({"stopped": False, "running": False})
        return 0
    os.kill(pid, signal.SIGTERM)
    print_json({"stopped": True, "pid": pid})
    return 0


def show_cmd(args):
    task = latest_task(args.task_id)
    if not task:
        raise SystemExit(f"Unknown task id: {args.task_id}")
    if getattr(args, "summary", False):
        summary_path = Path(task["run_dir"]) / "summary.md"
        if not summary_path.exists():
            raise SystemExit(f"Summary not found for task {args.task_id}. Run `agentctl summarize {args.task_id}` first.")
        print(summary_path.read_text(encoding="utf-8"), end="")
        return 0
    if args.json:
        if task.get("mode") == "iterate":
            print_json({
                "task_id": task.get("task_id"),
                "status": task.get("status"),
                "type": "iterate",
                "agent": task.get("agent"),
                "goal": task.get("goal"),
                "check": task.get("check"),
                "rounds": iterate_round_summaries(task.get("run_dir")),
                "final_check_passed": task.get("final_check_passed"),
                "memory_recall": task.get("memory_recall"),
                "workspace": task.get("workspace"),
                "memory_namespace": task.get("memory_namespace"),
            })
        else:
            print_json(task)
    else:
        print_json(task)
    return 0


def inspect_cmd(args):
    config = load_config()
    agents = config.get("agents") or {}
    if args.agent not in agents:
        raise SystemExit(f"Unknown agent: {args.agent}")
    agent_cfg = agents[args.agent]
    payload = {
        "agent": args.agent,
        "tool": agent_cfg.get("tool"),
        "model": agent_cfg.get("model"),
        "autonomy": agent_cfg.get("autonomy"),
        "fallback_profiles": agent_cfg.get("fallback_profiles") or [],
        "approval_required": agent_cfg.get("approval_required") or [],
    }
    print_json(payload)
    return 0


def list_agents_cmd(args):
    config = load_config()
    agents = config.get("agents") or {}
    if args.json:
        print_json(agents)
    else:
        for name, agent_cfg in agents.items():
            print(f"{name} {agent_cfg.get('tool')} {agent_cfg.get('model')} {agent_cfg.get('autonomy')}")
    return 0


def logs_cmd(args):
    task = latest_task(args.task_id)
    if not task:
        raise SystemExit(f"Unknown task id: {args.task_id}")
    run_dir = Path(task["run_dir"])
    if args.round is not None:
        round_dir = run_dir / "rounds" / str(args.round)
        file_map = {
            "stdout": "stdout.log",
            "stderr": "stderr.log",
            "check-stdout": "check-stdout.log",
            "check-stderr": "check-stderr.log",
            "result": "result.json",
        }
        if args.file not in file_map:
            raise SystemExit(f"Unsupported --file for --round: {args.file}")
        path = round_dir / file_map[args.file]
    elif args.file == "stderr":
        path = run_dir / "stderr.log"
    elif args.file == "metadata":
        path = run_dir / "metadata.json"
    elif args.file == "result":
        path = run_dir / "result.json"
    else:
        path = run_dir / "stdout.log"
    text = path.read_text(encoding="utf-8")
    text = tail_lines(text, args.tail)
    if args.json:
        print_json({"task_id": args.task_id, "file": args.file, "path": str(path), "text": text})
    else:
        print(text, end="")
    return 0


def retry_cmd(args):
    task = latest_task(args.task_id)
    if not task:
        raise SystemExit(f"Unknown task id: {args.task_id}")
    prompt_path = Path(task["run_dir"]) / "prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    ns = argparse.Namespace(agent=task["agent"], prompt=[prompt], model=None, fallback=args.fallback, approve=args.approve, dry_run=False, timeout=args.timeout)
    return run_task(ns)


def doctor_cmd(args):
    ensure_state()
    checks = []

    def add(name, ok, detail=""):
        checks.append((name, ok, detail))

    add("config_exists", CONFIG_PATH.exists(), str(CONFIG_PATH))
    try:
        config = load_config()
        add("config_parses", isinstance(config, dict), "")
    except Exception as exc:
        config = {}
        add("config_parses", False, str(exc))

    runbook_validation = runbooks_mod.validate_runbooks(strict=False)
    strict_runbook_validation = runbooks_mod.validate_runbooks(strict=True)
    add("runbooks_loadable", runbook_validation.get("ok", False), f"invalid={runbook_validation.get('invalid_count', 0)} skipped={runbook_validation.get('skipped_count', 0)}")
    add("runbooks_invalid_count", runbook_validation.get("invalid_count", 0) == 0, str(runbook_validation.get("invalid_count", 0)))
    add("runbooks_strict_valid", strict_runbook_validation.get("ok", False), f"invalid={strict_runbook_validation.get('invalid_count', 0)} skipped={strict_runbook_validation.get('skipped_count', 0)}")
    for warning in runbook_validation.get("warnings") or []:
        add("runbooks_warning", False, warning)

    tool_validation = validate_tools_registry(strict=False)
    profile_validation = validate_profiles_registry(strict=False)
    add("tools_loadable", tool_validation.get("ok", False), f"invalid={tool_validation.get('invalid_count', 0)} skipped={tool_validation.get('skipped_count', 0)}")
    add("tools_invalid_count", tool_validation.get("invalid_count", 0) == 0, str(tool_validation.get("invalid_count", 0)))
    add("profiles_loadable", profile_validation.get("ok", False), f"invalid={profile_validation.get('invalid_count', 0)} skipped={profile_validation.get('skipped_count', 0)}")
    add("profiles_invalid_count", profile_validation.get("invalid_count", 0) == 0, str(profile_validation.get("invalid_count", 0)))
    for warning in tool_validation.get("warnings") or []:
        add("tools_warning", False, warning)
    for warning in profile_validation.get("warnings") or []:
        add("profiles_warning", False, warning)

    legacy_tools = config.get("tools") or {}
    agents = config.get("agents") or {}
    loaded_tool_ids = {item["id"] for item in load_tools_registry()}
    loaded_profile_ids = {item["id"] for item in load_profiles_registry()}
    add("tools_registry_present", bool(loaded_tool_ids), ",".join(sorted(loaded_tool_ids)))
    add("profiles_registry_present", bool(loaded_profile_ids), ",".join(sorted(loaded_profile_ids)))
    guardrail_rules = guardrails_mod.list_guardrail_rules().get("rules") or []
    add("guardrails_loadable", bool(guardrail_rules), str(len(guardrail_rules)))
    add("guardrails_rules_count", len(guardrail_rules) > 0, str(len(guardrail_rules)))
    try:
        runtime_dev = profiles_by_id().get("runtime-dev")
        runtime_tool = tools_by_id().get("workspace_files") or next(iter(tools_by_id().values()), None)
        context_state = guardrails_mod.build_context_state(
            profile_id="runtime-dev" if runtime_dev else None,
            workspace="test-ws" if runtime_dev else None,
            selected_tools=[runtime_tool] if runtime_tool else [],
            considered_tools=[runtime_tool] if runtime_tool else [],
            action="profile_run",
        )
        eval_payload = guardrails_mod.evaluate_guardrails(
            profile=runtime_dev,
            profile_id="runtime-dev" if runtime_dev else None,
            tool=runtime_tool,
            requested_tool_id=runtime_tool.get("id") if runtime_tool else None,
            action="profile_run",
            context_state=context_state,
        )
        add("guardrails_eval_smoke", eval_payload.get("decision") in {"allow", "approval_required", "block"}, eval_payload.get("decision") or "")
    except Exception as exc:
        add("guardrails_eval_smoke", False, str(exc))

    for profile in load_profiles_registry():
        allowed_tools = profile.get("allowed_tools") or []
        add(f"profile:{profile['id']}:tools", all(tool_id in loaded_tool_ids for tool_id in allowed_tools), ",".join(allowed_tools))

    for name, tool_cfg in legacy_tools.items():
        command = tool_cfg.get("command")
        add(f"tool:{name}", bool(command and shutil.which(command)), command or "missing command")

    for name, agent_cfg in agents.items():
        add(f"agent:{name}:tool", agent_cfg.get("tool") in legacy_tools, str(agent_cfg.get("tool")))
        add(f"agent:{name}:status_vocab", True, ",".join(sorted(STATUS_VALUES)))
        for profile_name in agent_cfg.get("fallback_profiles") or []:
            ok = profile_name in MODEL_FALLBACK_PROFILES or profile_name in (config.get("models") or {})
            add(f"agent:{name}:fallback:{profile_name}", ok, MODEL_FALLBACK_PROFILES.get(profile_name, ""))

    add("state_dir_writable", os.access(STATE_DIR, os.W_OK), str(STATE_DIR))
    add("runs_dir_writable", os.access(RUNS_DIR, os.W_OK), str(RUNS_DIR))
    try:
        with TASKS_JSONL.open("a", encoding="utf-8"):
            pass
        add("tasks_jsonl_writable", True, str(TASKS_JSONL))
    except Exception as exc:
        add("tasks_jsonl_writable", False, str(exc))
    try:
        with QUEUE_JSONL.open("a", encoding="utf-8"):
            pass
        add("queue_jsonl_writable", True, str(QUEUE_JSONL))
    except Exception as exc:
        add("queue_jsonl_writable", False, str(exc))
    try:
        with SCHEDULES_JSONL.open("a", encoding="utf-8"):
            pass
        SCHEDULES_JSONL.chmod(0o600)
        add("schedules_jsonl_writable", True, str(SCHEDULES_JSONL))
    except Exception as exc:
        add("schedules_jsonl_writable", False, str(exc))

    try:
        with QUEUE_LOCK.open("a", encoding="utf-8"):
            pass
        QUEUE_LOCK.chmod(0o600)
        add("queue_lock_writable", True, str(QUEUE_LOCK))
    except Exception as exc:
        add("queue_lock_writable", False, str(exc))

    try:
        proc = subprocess.run(["opencode-gateway-env"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        add("gateway_env_resolves", proc.returncode == 0, "masked" if proc.returncode == 0 else proc.stderr.strip())
    except Exception as exc:
        add("gateway_env_resolves", False, str(exc))

    try:
        proc = subprocess.run(["ccr", "status"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        add("ccr_reachable", proc.returncode == 0, "")
    except Exception as exc:
        add("ccr_reachable", False, str(exc))

    for path in (CONFIG_PATH, TASKS_JSONL, QUEUE_JSONL, QUEUE_LOCK, SCHEDULES_JSONL):
        if path.exists():
            mode = path.stat().st_mode & 0o777
            add(f"permissions:{path.name}", not bool(mode & 0o077), oct(mode))

    try:
        tg = telegram_cfg()
        add("telegram_config_exists", TELEGRAM_CONFIG_PATH.exists(), str(TELEGRAM_CONFIG_PATH))
        add("telegram_allowlist_configured", isinstance(tg.get("allowed_user_ids"), list), str(len(tg.get("allowed_user_ids") or [])))
        add("telegram_bot_token_env_name", bool(tg.get("bot_token_env")), tg.get("bot_token_env") or "")
        add("agentbot_exists", bool(shutil.which("agentbot") or (Path.home() / ".local" / "bin" / "agentbot").exists()), str(Path.home() / ".local" / "bin" / "agentbot"))
        if TELEGRAM_CONFIG_PATH.exists():
            mode = TELEGRAM_CONFIG_PATH.stat().st_mode & 0o777
            add("permissions:telegram.yaml", not bool(mode & 0o077), oct(mode))
    except Exception as exc:
        add("telegram_config_parses", False, str(exc))

    if AMBAdapter is None:
        add("amb:mcp_stdio", False, "AMBAdapter import failed")
    else:
        amb_health = AMBAdapter().health()
        add("amb:mcp_stdio", bool(amb_health.get("ok")), json.dumps(amb_health, sort_keys=True))

    if args.json:
        print_json([{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks])
    else:
        for name, ok, detail in checks:
            print(f"{name}: {'ok' if ok else 'fail'} {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1
def config_validate_cmd(args):
    config = load_config()
    errors = []
    if not isinstance(config.get("models"), dict):
        errors.append("models must be a mapping")
    tools = config.get("tools") or {}
    agents = config.get("agents") or {}
    if not tools:
        errors.append("tools must not be empty")
    if not agents:
        errors.append("agents must not be empty")
    for name, agent_cfg in agents.items():
        if agent_cfg.get("tool") not in tools:
            errors.append(f"agent {name} references unknown tool {agent_cfg.get('tool')}")
        if agent_cfg.get("autonomy") not in {"read_only", "workspace_write"}:
            errors.append(f"agent {name} has invalid autonomy {agent_cfg.get('autonomy')}")
        for profile in agent_cfg.get("fallback_profiles") or []:
            if profile not in MODEL_FALLBACK_PROFILES:
                errors.append(f"agent {name} has unknown fallback profile {profile}")
    payload = {"ok": not errors, "errors": errors, "config_path": str(CONFIG_PATH)}
    if args.json:
        print_json(payload)
    else:
        print("config: ok" if not errors else "config: fail")
        for error in errors:
            print(f"- {error}")
    return 0 if not errors else 1


def tool_list_cmd(args):
    items = load_tools_registry()
    payload = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "description": item.get("description"),
            "kind": item.get("kind"),
            "enabled": item.get("enabled"),
            "trust_level": item.get("trust_level"),
            "egress": item.get("egress"),
            "workspace_scoped": item.get("workspace_scoped"),
            "profile_scope": item.get("profile_scope") or [],
            "capabilities": item.get("capabilities") or [],
            "source": item.get("source"),
        }
        for item in items
    ]
    print_json(payload)
    return 0


def tool_show_cmd(args):
    item = tools_by_id().get(args.tool_id)
    if not item:
        raise SystemExit(f"Unknown tool: {args.tool_id}")
    print_json(item)
    return 0


def tool_validate_cmd(args):
    payload = validate_tools_registry(strict=False)
    print_json(payload)
    return 0 if payload.get("ok") else 1


def resolve_profile(profile_id, *, workspace_override=None, agent_override=None, require_workspace=False):
    profile = profiles_by_id().get(profile_id)
    if not profile:
        raise SystemExit(f"Unknown profile: {profile_id}")
    workspace = workspace_override if workspace_override is not None else profile.get("workspace")
    if require_workspace and profile.get("workspace_required") and not workspace:
        raise SystemExit(f"Profile '{profile_id}' requires --workspace or a pinned workspace.")
    workspace_cfg = None
    cwd = None
    memory_namespace = profile.get("memory_namespace")
    if workspace:
        workspace_cfg, cwd, workspace_memory_namespace = resolve_workspace_options(workspace)
        if not memory_namespace:
            memory_namespace = workspace_memory_namespace
    agent_name = agent_override or profile.get("default_agent")
    if agent_name not in (profile.get("allowed_agents") or []):
        raise SystemExit(f"Agent '{agent_name}' is not allowed for profile '{profile_id}'.")
    return {
        "profile": profile,
        "profile_id": profile_id,
        "agent": agent_name,
        "workspace": workspace,
        "workspace_cfg": workspace_cfg,
        "cwd": str(cwd) if cwd else None,
        "memory_namespace": memory_namespace,
        "allowed_tools": [tools_by_id()[tool_id] for tool_id in profile.get("allowed_tools") or [] if tool_id in tools_by_id()],
    }


def normalize_profile_goal_args(args, *, allow_timeout=False):
    goal = []
    tokens = list(args.goal)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--workspace" and i + 1 < len(tokens):
            args.workspace = tokens[i + 1]
            i += 1
        elif token.startswith("--workspace="):
            args.workspace = token.split("=", 1)[1]
        elif token == "--agent" and i + 1 < len(tokens):
            args.agent = tokens[i + 1]
            i += 1
        elif token.startswith("--agent="):
            args.agent = token.split("=", 1)[1]
        elif token == "--tool" and i + 1 < len(tokens):
            args.tool = tokens[i + 1]
            i += 1
        elif token.startswith("--tool="):
            args.tool = token.split("=", 1)[1]
        elif token == "--json":
            args.json = True
        elif token == "--dry-run":
            args.dry_run = True
        elif allow_timeout and token == "--timeout" and i + 1 < len(tokens):
            args.timeout = int(tokens[i + 1])
            i += 1
        elif allow_timeout and token.startswith("--timeout="):
            args.timeout = int(token.split("=", 1)[1])
        else:
            goal.append(token)
        i += 1
    args.goal = goal
    return args


def evaluate_profile_guardrails(*, resolved, action, tool_id=None):
    tool = None
    if tool_id:
        tool = tools_by_id().get(tool_id)
    context_state = guardrails_mod.build_context_state(
        profile_id=resolved.get("profile_id"),
        workspace=resolved.get("workspace"),
        selected_tools=[tool] if tool else [],
        considered_tools=resolved.get("allowed_tools") or [],
        action=action,
    )
    payload = guardrails_mod.evaluate_guardrails(
        profile=resolved.get("profile"),
        profile_id=resolved.get("profile_id"),
        tool=tool,
        requested_tool_id=tool_id,
        action=action,
        context_state=context_state,
    )
    payload["profile"] = resolved.get("profile_id")
    payload["tool"] = tool_id
    payload["action"] = action
    return payload


def guardrail_list_cmd(args):
    print_json(guardrails_mod.list_guardrail_rules())
    return 0


def guardrail_eval_cmd(args):
    resolved = resolve_profile(args.profile_id, workspace_override=args.workspace, agent_override=args.agent, require_workspace=False)
    payload = evaluate_profile_guardrails(resolved=resolved, action=args.action, tool_id=args.tool_id)
    print_json(payload)
    return 0 if payload.get("decision") == "allow" else 1


def profile_list_cmd(args):
    payload = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "description": item.get("description"),
            "default_agent": item.get("default_agent"),
            "allowed_agents": item.get("allowed_agents") or [],
            "workspace": item.get("workspace"),
            "workspace_required": item.get("workspace_required"),
            "allowed_tools": item.get("allowed_tools") or [],
            "source": item.get("source"),
        }
        for item in load_profiles_registry()
    ]
    print_json(payload)
    return 0


def profile_show_cmd(args):
    resolved = resolve_profile(args.profile_id)
    payload = dict(resolved["profile"])
    payload["resolved"] = {
        "agent": resolved["agent"],
        "workspace": resolved["workspace"],
        "cwd": resolved["cwd"],
        "memory_namespace": resolved["memory_namespace"],
        "tools": [tool.get("id") for tool in resolved["allowed_tools"]],
    }
    print_json(payload)
    return 0


def profile_validate_cmd(args):
    payload = validate_profiles_registry(strict=False)
    print_json(payload)
    return 0 if payload.get("ok") else 1


def profile_run_cmd(args):
    args = normalize_profile_goal_args(args, allow_timeout=True)
    resolved = resolve_profile(args.profile_id, workspace_override=args.workspace, agent_override=args.agent, require_workspace=True)
    goal = " ".join(args.goal).strip() or (resolved["profile"].get("default_run_goal") or "")
    if not goal:
        raise SystemExit("Goal is required")
    guardrail_payload = evaluate_profile_guardrails(resolved=resolved, action="profile_run", tool_id=getattr(args, "tool", None))
    if getattr(args, "dry_run", False):
        status = "dry_run_ok"
        exit_code = 0
        if guardrail_payload.get("decision") == "block":
            status = "blocked"
            exit_code = 2
        elif guardrail_payload.get("decision") == "approval_required":
            status = "approval_required"
            exit_code = 2
        print_json({
            "would_run": status == "dry_run_ok",
            "status": status,
            "profile": args.profile_id,
            "agent": resolved["agent"],
            "workspace": resolved["workspace"],
            "cwd": resolved["cwd"],
            "memory_namespace": resolved["memory_namespace"],
            "goal": goal,
            "allowed_tools": [tool.get("id") for tool in resolved.get("allowed_tools") or []],
            "tool": getattr(args, "tool", None),
            "context_state": guardrail_payload.get("context_state"),
            "policy_decisions": guardrail_payload.get("policy_decisions"),
            "decision": guardrail_payload.get("decision"),
            "rule_id": guardrail_payload.get("rule_id"),
            "reason": guardrail_payload.get("reason"),
        })
        return exit_code
    if guardrail_payload.get("decision") == "block":
        print_json({
            "status": "blocked",
            "profile": args.profile_id,
            "context_state": guardrail_payload.get("context_state"),
            "policy_decisions": guardrail_payload.get("policy_decisions"),
            "rule_id": guardrail_payload.get("rule_id"),
            "reason": guardrail_payload.get("reason"),
        })
        return 2
    if guardrail_payload.get("decision") == "approval_required":
        print_json({
            "status": "approval_required",
            "profile": args.profile_id,
            "context_state": guardrail_payload.get("context_state"),
            "policy_decisions": guardrail_payload.get("policy_decisions"),
            "rule_id": guardrail_payload.get("rule_id"),
            "reason": guardrail_payload.get("reason"),
        })
        return 2
    run_args = argparse.Namespace(
        agent=resolved["agent"],
        prompt=[goal],
        model=None,
        workspace=resolved["workspace"],
        no_memory=False,
        memory_query=None,
        memory_preview=False,
        fallback=False,
        approve=[],
        dry_run=False,
        timeout=args.timeout,
        json=True,
    )
    return run_task(run_args)


# v1.5.0 guardrails note: context_state is derived from declared profile/tool/action metadata,
# not from full runtime observation of tool results or arbitrary content propagation.




























































































def profile_plan_cmd(args):
    args = normalize_profile_goal_args(args, allow_timeout=False)
    resolved = resolve_profile(args.profile_id, workspace_override=args.workspace, agent_override=args.agent, require_workspace=True)
    goal = " ".join(args.goal).strip() or (resolved["profile"].get("default_plan_goal") or "")
    if not goal:
        raise SystemExit("Goal is required")
    if not resolved["workspace"]:
        raise SystemExit(f"Profile '{args.profile_id}' requires a workspace for planning.")
    guardrail_payload = evaluate_profile_guardrails(resolved=resolved, action="profile_plan", tool_id=getattr(args, "tool", None))
    if guardrail_payload.get("decision") == "block":
        print_json({
            "status": "blocked",
            "profile": args.profile_id,
            "context_state": guardrail_payload.get("context_state"),
            "policy_decisions": guardrail_payload.get("policy_decisions"),
            "rule_id": guardrail_payload.get("rule_id"),
            "reason": guardrail_payload.get("reason"),
        })
        return 2
    if guardrail_payload.get("decision") == "approval_required":
        print_json({
            "status": "approval_required",
            "profile": args.profile_id,
            "context_state": guardrail_payload.get("context_state"),
            "policy_decisions": guardrail_payload.get("policy_decisions"),
            "rule_id": guardrail_payload.get("rule_id"),
            "reason": guardrail_payload.get("reason"),
        })
        return 2
    pid = plan_id()
    plan = default_plan_for_goal(pid, resolved["workspace"], resolved["memory_namespace"], goal)
    plan["profile_id"] = args.profile_id
    plan["profile"] = {
        "default_agent": resolved["profile"].get("default_agent"),
        "allowed_agents": resolved["profile"].get("allowed_agents") or [],
        "allowed_tools": resolved["profile"].get("allowed_tools") or [],
    }
    plan["context_state"] = guardrail_payload.get("context_state")
    plan["policy_decisions"] = guardrail_payload.get("policy_decisions")
    errors = validate_plan_shape(plan)
    if errors:
        plan["status"] = "rejected"
        plan["validation_errors"] = errors
    pdir = plan_dir(pid)
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "goal.txt").write_text(goal + "\n", encoding="utf-8")
    save_plan(plan)
    update_plan_status_file(plan)
    print_json({
        "plan_id": pid,
        "status": plan.get("status"),
        "plan_dir": str(pdir),
        "profile_id": args.profile_id,
        "validation_errors": plan.get("validation_errors", []),
        "context_state": guardrail_payload.get("context_state"),
        "policy_decisions": guardrail_payload.get("policy_decisions"),
    })
    return 0 if not errors else 2


def telegram_status_payload():
    ensure_state()
    cfg = telegram_cfg()
    token_present = bool(os.environ.get(cfg.get("bot_token_env") or ""))
    agentbot_path = shutil.which("agentbot") or str(Path.home() / ".local" / "bin" / "agentbot")
    return {
        "enabled": cfg.get("enabled"),
        "config": str(TELEGRAM_CONFIG_PATH),
        "config_exists": TELEGRAM_CONFIG_PATH.exists(),
        "bot_token_env": cfg.get("bot_token_env"),
        "bot_token_present": token_present,
        "allowed_user_count": len(cfg.get("allowed_user_ids") or []),
        "agentbot": agentbot_path,
        "agentbot_exists": Path(agentbot_path).exists() or bool(shutil.which("agentbot")),
        "offset_file": str(TELEGRAM_OFFSET),
        "log_file": str(TELEGRAM_LOG),
    }


def telegram_status_cmd(args):
    payload = telegram_status_payload()
    if args.json:
        print_json(payload)
    else:
        for key in ("enabled", "config_exists", "bot_token_env", "bot_token_present", "allowed_user_count", "agentbot_exists", "offset_file", "log_file"):
            print(f"{key}: {payload.get(key)}")
    return 0


def run_agentbot_test(user_id, text):
    agentbot = shutil.which("agentbot") or str(Path.home() / ".local" / "bin" / "agentbot")
    return subprocess.run([agentbot, "--test-command", str(user_id), text], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


def telegram_test_cmd(args):
    cfg = telegram_cfg()
    allowed = (cfg.get("allowed_user_ids") or [123456789])[0]
    unauthorized = 0
    steps = []

    def add_step(name, ok, detail=""):
        steps.append({"name": name, "ok": ok, "detail": detail})

    proc = run_agentbot_test(unauthorized, "/status")
    add_step("unauthorized_status", proc.returncode == 0 and proc.stdout.strip() == "unauthorized" and "Daemon:" not in proc.stdout, proc.stdout.strip() or proc.stderr.strip())
    for name, command, expected in [
        ("status", "/status", ["Daemon:", "Queue:", "Plans:", "Schedules:"]),
        ("queue", "/queue", ["Queue", "Pending:", "Running:"]),
        ("plans", "/plans", ["Plans"]),
        ("schedules", "/schedules", ["Schedules"]),
        ("workspaces", "/workspaces", ["Workspaces", "test-ws"]),
    ]:
        proc = run_agentbot_test(allowed, command)
        add_step(name, proc.returncode == 0 and all(token in proc.stdout for token in expected), proc.stdout.strip() or proc.stderr.strip())
    proc = run_agentbot_test(allowed, "/logs missing-task-id")
    add_step("logs_tail_capped", proc.returncode == 0 and len(proc.stdout) < 4500, proc.stdout.strip() or proc.stderr.strip())
    for name, command, expected in [
        ("assistant_status", "what's going on?", ["Daemon:", "Queue:", "Plans:"]),
        ("assistant_check", "check test-ws", ["read-only health check", "Queued:"]),
        ("assistant_fix_confirm", "fix failing tests in test-ws", ["Reply YES", "create a plan"]),
        ("assistant_danger_refuse", "deploy the project", ["can't run deploy"]),
    ]:
        proc = run_agentbot_test(allowed, command)
        add_step(name, proc.returncode == 0 and all(token in proc.stdout for token in expected), proc.stdout.strip() or proc.stderr.strip())
        if name == "assistant_check":
            match = re.search(r"Queued: (\S+)", proc.stdout)
            if match:
                cancel_queue_item(match.group(1), "telegram assistant selftest cleanup")
    proc = run_agentbot_test(allowed, "/run test-ws planner telegram selftest run")
    qid = None
    if proc.returncode == 0:
        match = re.search(r"Queue: (\S+)", proc.stdout)
        qid = match.group(1) if match else None
    if qid:
        cancel_queue_item(qid, "telegram selftest cleanup")
    add_step("run_submit_queued", proc.returncode == 0 and bool(qid), proc.stdout.strip() or proc.stderr.strip())
    proc = run_agentbot_test(allowed, "/iterate test-ws planner telegram selftest iterate | false")
    iqid = None
    if proc.returncode == 0:
        match = re.search(r"Queue: (\S+)", proc.stdout)
        iqid = match.group(1) if match else None
    if iqid:
        cancel_queue_item(iqid, "telegram selftest cleanup")
    add_step("iterate_submit_queued", proc.returncode == 0 and bool(iqid), proc.stdout.strip() or proc.stderr.strip())
    plan_step = run_selftest_step("telegram_plan_create_seed", [str(Path(__file__)), "plan", "create", "--workspace", "test-ws", "telegram selftest blocked plan"])
    plan_id_value = None
    if plan_step["ok"]:
        try:
            plan_id_value = json.loads(plan_step["stdout"])["plan_id"]
            run_selftest_step("telegram_plan_review_seed", [str(Path(__file__)), "plan", "review", plan_id_value, "--json"])
            run_selftest_step("telegram_plan_approve_seed", [str(Path(__file__)), "plan", "approve", plan_id_value])
            enq = run_selftest_step("telegram_plan_enqueue_seed", [str(Path(__file__)), "plan", "enqueue", plan_id_value])
            data = json.loads(enq["stdout"])
            first = data["queue_items"][0]
            for extra in data.get("queue_items", [])[1:]:
                cancel_queue_item(extra.get("queue_id"), "telegram selftest cleanup")
            append_queue({"queue_id": first["queue_id"], "status": "failed", "ended_at": now_iso(), "task_id": "telegram-selftest-failed-task", "returncode": 1})
        except Exception:
            plan_id_value = None
    if plan_id_value:
        proc_plan = run_agentbot_test(allowed, f"/plan {plan_id_value}")
        add_step("blocked_plan_view", proc_plan.returncode == 0 and "Status: blocked" in proc_plan.stdout and "Blocked on:" in proc_plan.stdout, proc_plan.stdout.strip())
        proc_repair = run_agentbot_test(allowed, f"/plan_repair {plan_id_value}")
        add_step("plan_repair", proc_repair.returncode == 0 and "Plan repair" in proc_repair.stdout, proc_repair.stdout.strip())
        proc_retry = run_agentbot_test(allowed, f"/plan_retry {plan_id_value} 1")
        rqid = None
        if proc_retry.returncode == 0:
            match = re.search(r'"queue_id": "([^"]+)"', proc_retry.stdout)
            rqid = match.group(1) if match else None
        if rqid:
            cancel_queue_item(rqid, "telegram selftest cleanup")
        if plan_id_value:
            append_plan_event(plan_id_value, {"event": "skip", "subtask_id": "1", "reason": "telegram selftest cleanup"})
        add_step("plan_retry", proc_retry.returncode == 0 and "plan_retry" in proc_retry.stdout, proc_retry.stdout.strip())
    else:
        add_step("blocked_plan_view", False, "failed to seed blocked plan")
        add_step("plan_repair", False, "failed to seed blocked plan")
        add_step("plan_retry", False, "failed to seed blocked plan")
    before = daemon_status_payload().get("paused")
    proc_pause = run_agentbot_test(allowed, "/pause")
    paused = daemon_status_payload().get("paused")
    proc_resume = run_agentbot_test(allowed, "/resume")
    resumed = not daemon_status_payload().get("paused")
    add_step("pause_resume", proc_pause.returncode == 0 and proc_resume.returncode == 0 and paused and resumed, f"before={before} paused={paused} resumed={resumed}")
    ok = all(step["ok"] for step in steps)
    if args.json:
        print_json({"ok": ok, "steps": steps})
    else:
        for step in steps:
            print(f"{step['name']}: {'ok' if step['ok'] else 'fail'}")
            if not step["ok"]:
                print(step.get("detail") or "")
        print("agentctl telegram-test: ok" if ok else "agentctl telegram-test: fail")
    return 0 if ok else 1


def extract_workspace_from_text(text):
    workspaces = load_workspaces()
    return assistant_router_mod.extract_workspace_from_text(text, list(workspaces.keys()))


def latest_blocked_plan_id():
    for plan in reversed(list_plans()):
        status = derive_plan_status(plan)
        if status.get("status") == "blocked":
            return plan.get("plan_id")
    return None


def latest_failed_schedule_id():
    for sched in reversed(list(latest_schedules().values())):
        if sched.get("removed"):
            continue
        if sched.get("last_status") == "failed" or sched.get("last_retry_recommended"):
            return sched.get("schedule_id") or sched.get("name")
    return None


def route_assistant_message(message, session=None):
    workspaces = load_workspaces()
    return assistant_router_mod.route_assistant_message(
        message,
        session=session,
        workspace_names=list(workspaces.keys()),
        latest_blocked_plan_id=latest_blocked_plan_id(),
        latest_failed_schedule_id=latest_failed_schedule_id(),
    )


def assistant_route_cmd(args):
    tokens = list(args.message)
    cleaned = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--json":
            args.json = True
        elif token == "--session-json" and i + 1 < len(tokens):
            args.session_json = tokens[i + 1]
            i += 1
        elif token.startswith("--session-json="):
            args.session_json = token.split("=", 1)[1]
        else:
            cleaned.append(token)
        i += 1
    message = " ".join(cleaned).strip()
    if not message:
        raise SystemExit("Message is required")
    session = {}
    if args.session_json:
        try:
            session = json.loads(args.session_json)
        except Exception as exc:
            raise SystemExit(f"Invalid --session-json: {exc}")
    payload = route_assistant_message(message, session=session)
    print_json(payload)
    return 0


def runbook_list_cmd(args):
    runbook_items = runbooks_mod.load_runbooks()
    payload = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "risk": item.get("risk"),
            "requires_confirmation": item.get("requires_confirmation"),
            "description": item.get("description"),
            "source": item.get("source"),
            "source_file": item.get("source_file"),
            "phrases": item.get("phrases") or [],
        }
        for item in runbook_items
    ]
    print_json(payload)
    return 0


def runbook_show_cmd(args):
    for item in runbooks_mod.load_runbooks():
        if item.get("id") == args.runbook_id:
            payload = dict(item)
            payload["actions"] = item.get("actions") or []
            payload["inputs"] = item.get("inputs") or {}
            payload["response"] = item.get("response") or {}
            print_json(payload)
            return 0
    raise SystemExit(f"Unknown runbook: {args.runbook_id}")


def runbook_validate_cmd(args):
    payload = runbooks_mod.validate_runbooks(strict=bool(getattr(args, "strict", False)))
    print_json(payload)
    return 0 if payload.get("ok") else 1


def retry_plan_subtask_action(plan_id_value, subtask_id_value):
    plan = load_plan(plan_id_value)
    subtask = next((s for s in plan.get("subtasks") or [] if str(s.get("id")) == str(subtask_id_value)), None)
    if not subtask:
        raise ValueError(f"Unknown subtask id: {subtask_id_value}")
    status = derive_plan_status(plan)
    row = next((r for r in status.get("subtasks") or [] if str(r.get("id")) == str(subtask_id_value)), None)
    if not row or row.get("status") not in {"failed", "blocked"}:
        raise ValueError(f"Subtask {subtask_id_value} is not failed/blocked; current status: {(row or {}).get('status')}")
    failed_item = failed_queue_item_for_plan_subtask(plan_id_value, subtask_id_value)
    if not failed_item:
        raise ValueError(f"Subtask {subtask_id_value} has no failed queue item to retry")
    item = queue_item_from_plan_retry(plan, subtask, failed_item)
    append_queue(item)
    event = append_plan_event(
        plan_id_value,
        {
            "event": "retry",
            "subtask_id": str(subtask_id_value),
            "queue_id": item.get("queue_id"),
            "retry_of_queue_id": failed_item.get("queue_id"),
            "retry_of_task_id": failed_item.get("task_id"),
        },
    )
    plan["status"] = "running"
    plan["updated_at"] = now_iso()
    save_plan(plan)
    update_plan_status_file(plan)
    return {"plan_id": plan_id_value, "subtask_id": str(subtask_id_value), "queued": True, "queue_id": item.get("queue_id"), "item": item, "event": event}


def assistant_exec_cmd(args):
    tokens = list(args.message)
    cleaned = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--json":
            args.json = True
        elif token == "--session-json" and i + 1 < len(tokens):
            args.session_json = tokens[i + 1]
            i += 1
        elif token.startswith("--session-json="):
            args.session_json = token.split("=", 1)[1]
        else:
            cleaned.append(token)
        i += 1
    message = " ".join(cleaned).strip()
    if not message:
        raise SystemExit("Message is required")
    session = {}
    if args.session_json:
        try:
            session = json.loads(args.session_json)
        except Exception as exc:
            raise SystemExit(f"Invalid --session-json: {exc}")
    payload = route_assistant_message(message, session=session)
    deps = {
        "append_queue": append_queue,
        "append_schedule": append_schedule,
        "daemon_status_payload": daemon_status_payload,
        "default_plan_for_goal": default_plan_for_goal,
        "derive_plan_status": derive_plan_status,
        "ensure_state": ensure_state,
        "latest_queue_items": latest_queue_items,
        "latest_schedules": latest_schedules,
        "latest_task": latest_task,
        "list_plans": list_plans,
        "load_config": load_config,
        "load_plan": load_plan,
        "load_profiles_registry": load_profiles_registry,
        "load_runbooks": runbooks_mod.load_runbooks,
        "load_tools_registry": load_tools_registry,
        "load_workspaces": load_workspaces,
        "now_iso": now_iso,
        "paused_file": PAUSED_FILE,
        "plan_dir": plan_dir,
        "plan_id": plan_id,
        "profiles_by_id": profiles_by_id,
        "queue_id": queue_id,
        "queue_item_from_schedule": queue_item_from_schedule,
        "resolve_profile": resolve_profile,
        "resolve_workspace_options": resolve_workspace_options,
        "retry_plan_subtask": retry_plan_subtask_action,
        "save_plan": save_plan,
        "schedule_by_name": schedule_by_name,
        "tools_by_id": tools_by_id,
        "update_plan_status_file": update_plan_status_file,
    }
    result = actions_mod.execute_route(payload, dry_run=False, deps=deps)
    print_json(result)
    return 0


def _runbook_parser(sub):
    runbook = sub.add_parser("runbook")
    runbook_sub = runbook.add_subparsers(dest="runbook_cmd", required=True)

    runbook_list = runbook_sub.add_parser("list")
    runbook_list.add_argument("--json", action="store_true")
    runbook_list.set_defaults(func=runbook_list_cmd)

    runbook_show = runbook_sub.add_parser("show")
    runbook_show.add_argument("runbook_id")
    runbook_show.add_argument("--json", action="store_true")
    runbook_show.set_defaults(func=runbook_show_cmd)

    runbook_validate = runbook_sub.add_parser("validate")
    runbook_validate.add_argument("--json", action="store_true")
    runbook_validate.add_argument("--strict", action="store_true")
    runbook_validate.set_defaults(func=runbook_validate_cmd)
    return runbook


def health_cmd(args):
    checks = []

    def sanitize(text):
        text = re.sub(r"(API_KEY=)'[^']+'", r"\1'***'", text)
        text = re.sub(r"(Bearer )[^\s']+", r"\1***", text)
        return text

    def check(name, cmd, timeout=60):
        try:
            proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            ok = proc.returncode == 0
            detail = (proc.stdout or proc.stderr).strip().splitlines()[-1:] or [""]
            checks.append((name, ok, sanitize(detail[0])))
        except Exception as exc:
            checks.append((name, False, str(exc)))

    check("gateway-env", ["opencode-gateway-env"])
    check("ccr", ["ccr", "status"])
    if args.deep:
        check("codex:gpt-5.5", ["codex", "exec", "--skip-git-repo-check", "-c", 'approval_policy="never"', "-c", 'sandbox_mode="read-only"', "-m", "gpt-5.5", "Reply exactly OK"])
        check("claude:gpt-5.5", ["claude", "--bare", "-p", "Reply exactly OK"], timeout=120)
        check("gemini:gpt-5.5", ["gemini", "-m", "gpt-5.5", "-p", "Reply exactly OK"])
    else:
        for command in ("codex", "claude", "gemini"):
            checks.append((f"command:{command}", shutil.which(command) is not None, shutil.which(command) or "missing"))

    if args.json:
        print_json([{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks])
    else:
        for name, ok, detail in checks:
            print(f"{name}: {'ok' if ok else 'fail'} {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def run_selftest_step(name, cmd, expect_code=0):
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    ok = proc.returncode == expect_code
    return {
        "name": name,
        "ok": ok,
        "returncode": proc.returncode,
        "expected_returncode": expect_code,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def selftest_cmd(args):
    steps = []
    agentctl = resolve_agentctl_bin()
    agentctl_cmd = agentctl if isinstance(agentctl, list) else [agentctl]
    steps.append(run_selftest_step("doctor", [*agentctl_cmd, "doctor"]))
    steps.append(run_selftest_step("config_validate", [*agentctl_cmd, "config", "validate"]))
    steps.append(run_selftest_step("tool_list_json", [*agentctl_cmd, "tool", "list", "--json"]))
    steps.append(run_selftest_step("tool_show_web_fetch", [*agentctl_cmd, "tool", "show", "web_fetch", "--json"]))
    steps.append(run_selftest_step("tool_validate_json", [*agentctl_cmd, "tool", "validate", "--json"]))
    steps.append(run_selftest_step("guardrail_list", [*agentctl_cmd, "guardrail", "list", "--json"]))
    steps.append(run_selftest_step("guardrail_eval_allow", [*agentctl_cmd, "guardrail", "eval", "--profile", "runtime-dev", "--tool", "repo_read", "--action", "profile_run", "--json"]))
    steps.append(run_selftest_step("guardrail_eval_unknown_tool", [*agentctl_cmd, "guardrail", "eval", "--profile", "runtime-dev", "--tool", "missing-tool", "--action", "profile_run", "--json"], expect_code=1))
    steps.append(run_selftest_step("guardrail_eval_block_purchase", [*agentctl_cmd, "guardrail", "eval", "--profile", "runtime-dev", "--action", "external_purchase", "--json"], expect_code=1))
    steps.append(run_selftest_step("profile_list_json", [*agentctl_cmd, "profile", "list", "--json"]))
    steps.append(run_selftest_step("profile_show_runtime_dev", [*agentctl_cmd, "profile", "show", "runtime-dev", "--json"]))
    steps.append(run_selftest_step("profile_validate_json", [*agentctl_cmd, "profile", "validate", "--json"]))
    steps.append(run_selftest_step("profile_run_dry_run", [*agentctl_cmd, "profile", "run", "runtime-dev", "inspect", "repo", "status", "--workspace", "test-ws", "--dry-run", "--json"]))
    profile_plan_step = run_selftest_step("profile_plan", [*agentctl_cmd, "profile", "plan", "runtime-dev", "improve", "tests", "--workspace", "test-ws", "--json"])
    steps.append(profile_plan_step)
    if profile_plan_step["ok"]:
        try:
            profile_plan_payload = json.loads(profile_plan_step["stdout"])
            profile_plan_id = profile_plan_payload.get("plan_id")
            if profile_plan_id:
                profile_plan_status = run_selftest_step("profile_plan_show", [*agentctl_cmd, "plan", "show", profile_plan_id, "--json"])
                steps.append(profile_plan_status)
        except Exception as exc:
            steps.append({"name": "profile_plan_show", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": str(exc)})
    else:
        steps.append({"name": "profile_plan_show", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "profile plan failed"})
    steps.append(run_selftest_step("inspect_coder", [*agentctl_cmd, "inspect", "coder"]))
    steps.append(run_selftest_step("dry_run_git_push_blocks", [*agentctl_cmd, "run", "coder", "Please git push this change", "--dry-run"], expect_code=2))
    steps.append(run_selftest_step("dry_run_git_push_approved", [*agentctl_cmd, "run", "coder", "Please git push this change", "--approve", "git_push", "--dry-run"]))
    steps.append(run_selftest_step("dry_run_partial_approval_blocks", [*agentctl_cmd, "run", "coder", "Please git push and deploy this change", "--approve", "git_push", "--dry-run"], expect_code=2))
    steps.append(run_selftest_step("iterate_dry_run_blocks_push", [*agentctl_cmd, "iterate", "coder", "push when tests pass", "--check", "true", "--dry-run"], expect_code=2))
    steps.append(run_selftest_step("iterate_check_passes_without_agent", [*agentctl_cmd, "iterate", "planner", "Do nothing", "--check", "true", "--max-rounds", "1"], expect_code=0))
    iter_step = run_selftest_step("iterate_json_tail", [*agentctl_cmd, "iterate", "planner", "Do nothing", "--check", "true", "--max-rounds", "1", "--json", "--tail", "1"], expect_code=0)
    steps.append(iter_step)
    iter_task_id = None
    if iter_step["ok"]:
        try:
            iter_task_id = json.loads(iter_step["stdout"])["task_id"]
        except Exception:
            iter_task_id = None
    if iter_task_id:
        steps.append(run_selftest_step("iterate_show_rounds", [*agentctl_cmd, "show", iter_task_id, "--json"]))
        steps.append(run_selftest_step("iterate_logs_round0_result", [*agentctl_cmd, "logs", iter_task_id, "--round", "0", "--file", "result"]))
    else:
        steps.append({"name": "iterate_show_rounds", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing iterate task id"})
        steps.append({"name": "iterate_logs_round0_result", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing iterate task id"})
    submit_step = run_selftest_step("queue_submit", [*agentctl_cmd, "submit", "planner", "selftest queued noop", "--check", "true", "--max-rounds", "1", "--cwd", str(Path.cwd())])
    steps.append(submit_step)
    queue_id_value = None
    if submit_step["ok"]:
        try:
            queue_id_value = json.loads(submit_step["stdout"])["queue_id"]
        except Exception:
            queue_id_value = None
    if queue_id_value:
        steps.append(run_selftest_step("queue_show", [*agentctl_cmd, "queue", "show", queue_id_value, "--json"]))
        steps.append(run_selftest_step("queue_list_json", [*agentctl_cmd, "queue", "--json"]))
        cancel_queue_item(queue_id_value, "selftest cleanup")
    else:
        steps.append({"name": "queue_show", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing queue id"})
        steps.append({"name": "queue_list_json", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing queue id"})
    schedule_name = "selftest-schedule"
    existing_schedule = schedule_by_name(schedule_name)
    if existing_schedule and not existing_schedule.get("removed"):
        append_schedule({"schedule_id": existing_schedule.get("schedule_id"), "name": schedule_name, "enabled": False, "removed": True, "removed_at": now_iso(), "updated_at": now_iso()})
    schedule_add_step = run_selftest_step("schedule_add", [*agentctl_cmd, "schedule", "add", schedule_name, "--workspace", "test-ws", "--type", "run", "--agent", "planner", "--goal", "selftest scheduled noop", "--cron", "* * * * *"])
    steps.append(schedule_add_step)
    if schedule_add_step["ok"]:
        steps.append(run_selftest_step("schedule_show", [*agentctl_cmd, "schedule", "show", schedule_name, "--json"]))
        steps.append(run_selftest_step("schedule_list_json", [*agentctl_cmd, "schedule", "list", "--json"]))
        steps.append(run_selftest_step("schedule_run_due_dry_run", [*agentctl_cmd, "schedule", "run-due", "--dry-run", "--json"]))
        schedule_retry_step = run_selftest_step("schedule_retry", [*agentctl_cmd, "schedule", "retry", schedule_name])
        if schedule_retry_step["ok"]:
            try:
                schedule_retry_payload = json.loads(schedule_retry_step["stdout"])
                if schedule_retry_payload.get("queue_id"):
                    cancel_queue_item(schedule_retry_payload.get("queue_id"), "selftest cleanup")
            except Exception as exc:
                schedule_retry_step["ok"] = False
                schedule_retry_step["stderr"] = str(exc)
        steps.append(schedule_retry_step)
        steps.append(run_selftest_step("schedule_remove", [*agentctl_cmd, "schedule", "remove", schedule_name]))
    else:
        steps.append({"name": "schedule_show", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "schedule add failed"})
        steps.append({"name": "schedule_list_json", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "schedule add failed"})
        steps.append({"name": "schedule_run_due_dry_run", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "schedule add failed"})
        steps.append({"name": "schedule_retry", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "schedule add failed"})
        steps.append({"name": "schedule_remove", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "schedule add failed"})
    plan_step = run_selftest_step("plan_create", [*agentctl_cmd, "plan", "create", "--workspace", "test-ws", "selftest plan goal"])
    steps.append(plan_step)
    plan_id_value = None
    if plan_step["ok"]:
        try:
            plan_id_value = json.loads(plan_step["stdout"])["plan_id"]
        except Exception:
            plan_id_value = None
    if plan_id_value:
        steps.append(run_selftest_step("plan_show", [*agentctl_cmd, "plan", "show", plan_id_value, "--json"]))
        steps.append(run_selftest_step("plan_review", [*agentctl_cmd, "plan", "review", plan_id_value, "--json"]))
        steps.append(run_selftest_step("plan_approve", [*agentctl_cmd, "plan", "approve", plan_id_value]))
        enqueue_step = run_selftest_step("plan_enqueue", [*agentctl_cmd, "plan", "enqueue", plan_id_value])
        steps.append(enqueue_step)
        failed_subtask_id = "1"
        if enqueue_step["ok"]:
            try:
                enq = json.loads(enqueue_step["stdout"])
                failed_queue_id = enq["queue_items"][0]["queue_id"]
                for extra_item in enq.get("queue_items", [])[1:]:
                    cancel_queue_item(extra_item.get("queue_id"), "selftest cleanup")
                append_queue({"queue_id": failed_queue_id, "status": "failed", "ended_at": now_iso(), "task_id": "selftest-plan-failed-task", "returncode": 1})
                steps.append({"name": "plan_mark_failed", "ok": True, "returncode": 0, "expected_returncode": 0, "stdout": failed_queue_id, "stderr": ""})
            except Exception as exc:
                steps.append({"name": "plan_mark_failed", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": str(exc)})
        else:
            steps.append({"name": "plan_mark_failed", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "plan enqueue failed"})
        blocked_step = run_selftest_step("plan_status_blocked", [*agentctl_cmd, "plan", "status", plan_id_value, "--json"])
        if blocked_step["ok"]:
            try:
                blocked_payload = json.loads(blocked_step["stdout"])
                blocked_step["ok"] = blocked_payload.get("status") == "blocked" and blocked_payload.get("blocked_on") == failed_subtask_id
                if not blocked_step["ok"]:
                    blocked_step["stderr"] = "status did not report blocked/blocked_on"
            except Exception as exc:
                blocked_step["ok"] = False
                blocked_step["stderr"] = str(exc)
        steps.append(blocked_step)
        retry_step = run_selftest_step("plan_retry", [*agentctl_cmd, "plan", "retry", plan_id_value, failed_subtask_id])
        if retry_step["ok"]:
            try:
                retry_payload = json.loads(retry_step["stdout"])
                retry_step["ok"] = retry_payload.get("item", {}).get("created_from") == "plan_retry"
                if retry_payload.get("queue_id"):
                    cancel_queue_item(retry_payload.get("queue_id"), "selftest cleanup")
                if not retry_step["ok"]:
                    retry_step["stderr"] = "retry item missing created_from=plan_retry"
            except Exception as exc:
                retry_step["ok"] = False
                retry_step["stderr"] = str(exc)
        steps.append(retry_step)
        steps.append(run_selftest_step("plan_skip", [*agentctl_cmd, "plan", "skip", plan_id_value, failed_subtask_id, "--reason", "selftest skip failed subtask"]))
        steps.append(run_selftest_step("plan_repair", [*agentctl_cmd, "plan", "repair", plan_id_value, "--json"]))
        steps.append(run_selftest_step("plan_status", [*agentctl_cmd, "plan", "status", plan_id_value, "--json"]))
        steps.append(run_selftest_step("plan_summarize", [*agentctl_cmd, "plan", "summarize", plan_id_value, "--json"]))
    else:
        for name in ("plan_show", "plan_review", "plan_approve", "plan_enqueue", "plan_mark_failed", "plan_status_blocked", "plan_retry", "plan_skip", "plan_repair", "plan_status", "plan_summarize"):
            steps.append({"name": name, "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing plan id"})
    steps.append(run_selftest_step("plan_danger_blocks", [*agentctl_cmd, "plan", "create", "--workspace", "test-ws", "push and deploy this project"], expect_code=2))
    pause_step = run_selftest_step("pause", [*agentctl_cmd, "pause"])
    steps.append(pause_step)
    steps.append(run_selftest_step("daemon_status_json", [*agentctl_cmd, "daemon-status", "--json"]))
    steps.append(run_selftest_step("agentd_once_paused", [*agentctl_cmd, "agentd-once"], expect_code=0))
    steps.append(run_selftest_step("resume", [*agentctl_cmd, "resume"]))
    run_step = run_selftest_step("run_planner_ready", [*agentctl_cmd, "run", "planner", "Reply exactly READY_SELFTEST"], expect_code=0)
    steps.append(run_step)
    task_id_value = None
    if run_step["ok"]:
        try:
            task_id_value = json.loads(run_step["stdout"])["task_id"]
        except Exception:
            task_id_value = None
    if task_id_value:
        steps.append(run_selftest_step("show_task", [*agentctl_cmd, "show", task_id_value, "--json"]))
        steps.append(run_selftest_step("logs_task", [*agentctl_cmd, "logs", task_id_value]))
        steps.append(run_selftest_step("summarize_task", [*agentctl_cmd, "summarize", task_id_value, "--json"]))
        steps.append(run_selftest_step("memory_candidates_task", [*agentctl_cmd, "memory-candidates", task_id_value, "--json"]))
    else:
        steps.append({"name": "show_task", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing task id"})
        steps.append({"name": "logs_task", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing task id"})
        steps.append({"name": "summarize_task", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing task id"})
        steps.append({"name": "memory_candidates_task", "ok": False, "returncode": None, "expected_returncode": 0, "stdout": "", "stderr": "missing task id"})
    ok = all(step["ok"] for step in steps)
    if args.json:
        print_json({"ok": ok, "steps": steps})
    else:
        for step in steps:
            print(f"{step['name']}: {'ok' if step['ok'] else 'fail'}")
            if not step["ok"] and step.get("stderr"):
                print(step["stderr"])
        print("agentctl selftest: ok" if ok else "agentctl selftest: fail")
    return 0 if ok else 1


def smoke_cmd(args):
    ensure_state()
    tool_validation = validate_tools_registry(strict=True)
    profile_validation = validate_profiles_registry(strict=True)
    guardrail_rules = guardrails_mod.list_guardrail_rules().get("rules") or []
    payload = {
        "version": load_version(),
        "config_exists": CONFIG_PATH.exists(),
        "config_path": str(CONFIG_PATH),
        "state_path": str(STATE_DIR),
        "runs_dir": str(RUNS_DIR),
        "plans_dir": str(PLANS_DIR),
        "queue_path": str(QUEUE_JSONL),
        "amb_adapter_importable": AMBAdapter is not None,
        "agentbot_bin": resolve_agentbot_bin(),
        "agentbot_resolves": bool(resolve_agentbot_bin()),
        "tools_ok": bool(tool_validation.get("ok")),
        "profiles_ok": bool(profile_validation.get("ok")),
        "guardrails_ok": bool(guardrail_rules),
        "guardrails_rules_count": len(guardrail_rules),
        "tools_invalid_count": int(tool_validation.get("invalid_count", 0)),
        "profiles_invalid_count": int(profile_validation.get("invalid_count", 0)),
    }
    ok = payload["config_exists"] and payload["amb_adapter_importable"] and payload["tools_ok"] and payload["profiles_ok"] and payload["guardrails_ok"]
    if args.json:
        print_json({"ok": ok, **payload})
    else:
        print(f"smoke: {'ok' if ok else 'fail'}")
        print(f"config: {payload['config_path']}")
        print(f"state: {payload['state_path']}")
    return 0 if ok else 1


def version_cmd(args):
    payload = {
        "version": load_version(),
        "contract": "agentctl-v1.5.0",
        "daemon": True,
        "telegram": True,
        "config": str(CONFIG_PATH),
        "state": str(STATE_DIR),
    }
    if args.json:
        print_json(payload)
    else:
        print(f"runtime-agents {payload['version']} ({payload['contract']})")
        print("daemon: true")
        print("telegram: true")
    return 0


def amb_health_cmd(args):
    if AMBAdapter is None:
        payload = {"amb": {"ok": False, "error": "AMBAdapter import failed"}}
        if args.json:
            print_json(payload)
        else:
            print("amb: fail AMBAdapter import failed")
        return 1
    health = AMBAdapter().health()
    payload = {"amb": health}
    if args.json:
        print_json(payload)
    else:
        print(f"amb: {'ok' if health.get('ok') else 'fail'} {health.get('mode')} {health.get('error') or ''}")
        if health.get("tools"):
            print("tools: " + ", ".join(health.get("tools") or []))
    return 0 if health.get("ok") else 1



# v0.5.0 and v0.6.0 additions
WORKSPACES_PATH = config_home() / "workspaces.yaml"

def load_workspaces():
    if not WORKSPACES_PATH.exists():
        return {}
    if yaml is None:
        raise SystemExit("PyYAML is required: python3 -m pip install --user pyyaml")
    try:
        with WORKSPACES_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            print(f"Error: {WORKSPACES_PATH} is not a valid dictionary.", file=sys.stderr)
            return {}
        for name, ws in data.items():
            if not isinstance(ws, dict) or "path" not in ws:
                print(f"Error: Workspace '{name}' is malformed.", file=sys.stderr)
        return data
    except Exception as e:
        print(f"Error loading workspaces: {e}", file=sys.stderr)
        return {}

def save_workspaces(data):
    if yaml is None:
        raise SystemExit("PyYAML is required: python3 -m pip install --user pyyaml")
    WORKSPACES_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACES_PATH.write_text(yaml.safe_dump(data, indent=2, sort_keys=True), encoding="utf-8")

def workspace_add_cmd(args):
    workspaces = load_workspaces()
    if args.name in workspaces:
        print(f"Workspace '{args.name}' already exists. Use a different name.", file=sys.stderr)
        return 1
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        print(f"Error: Path '{path}' is not a valid directory.", file=sys.stderr)
        return 1
    workspaces[args.name] = {
        "path": str(path),
        "memory_namespace": args.memory_namespace or f"project:{args.name}",
    }
    save_workspaces(workspaces)
    print_json({args.name: workspaces[args.name]})
    return 0

def workspace_list_cmd(args):
    workspaces = load_workspaces()
    if args.json:
        print_json(workspaces)
    else:
        for name, ws in workspaces.items():
            print(f"{name}: {ws.get('path')}")
    return 0

def workspace_show_cmd(args):
    workspaces = load_workspaces()
    if args.name not in workspaces:
        print(f"Workspace '{args.name}' not found.", file=sys.stderr)
        return 1
    workspace = workspaces[args.name]
    if args.json:
        print_json({args.name: workspace})
    else:
        print(f"name: {args.name}")
        for key, value in workspace.items():
            print(f"{key}: {value}")
    return 0

def generate_memory_candidates(task, run_dir):
    candidates = []
    stderr_path = run_dir / "stderr.log"
    if task.get("status") == "failed" and stderr_path.exists():
        stderr = stderr_path.read_text(encoding="utf-8")
        if "FileNotFoundError" in stderr and "goal.txt" in stderr:
            candidates.append({
                "record_type": "gotcha",
                "title": "Summarize command assumes goal.txt exists for all task types",
                "claim": "The `summarize` command fails for `run` tasks because it only looks for `goal.txt` which is only created by `iterate` tasks.",
                "trigger": "Running `agentctl summarize` on a `run` task.",
                "symptom": "FileNotFoundError for goal.txt",
                "fix": "The `summarize` command should check the task mode and read from `prompt.txt` for `run` tasks and `goal.txt` for `iterate` tasks.",
                "confidence": "observed",
                "writeback_recommended": True
            })
    return candidates


def memory_candidate_id(task_id_value, index):
    safe_task = re.sub(r"[^A-Za-z0-9_.:-]+", "-", task_id_value or "task").strip("-")
    return f"{safe_task}:cand-{index + 1}"


def normalize_memory_candidates(candidates, task, run_dir, namespace=None):
    normalized = []
    task_id_value = task.get("task_id")
    for index, candidate in enumerate(candidates or []):
        item = dict(candidate)
        item.setdefault("candidate_id", memory_candidate_id(task_id_value, index))
        item.setdefault("task_id", task_id_value)
        item.setdefault("source", "memory-candidates.json")
        item.setdefault("source_summary", str(run_dir / "summary.json"))
        item.setdefault("generated_at", now_iso())
        if namespace:
            item.setdefault("namespace", namespace)
        item.setdefault("decision", "approved" if item.get("writeback_recommended") else "pending")
        normalized.append(item)
    return normalized


def load_memory_candidates_for_task(task, run_dir, namespace=None):
    candidates_path = run_dir / "memory-candidates.json"
    if not candidates_path.exists():
        return [], candidates_path
    candidates = load_json_file(candidates_path, []) or []
    normalized = normalize_memory_candidates(candidates, task, run_dir, namespace=namespace)
    if normalized != candidates:
        atomic_write_json(candidates_path, normalized)
    return normalized, candidates_path


def write_memory_candidates(run_dir, candidates):
    atomic_write_json(run_dir / "memory-candidates.json", candidates)


def candidates_selected_for_writeback(candidates):
    return [
        c for c in candidates
        if c.get("candidate_id")
        and c.get("writeback_recommended") is True
        and c.get("decision", "approved") == "approved"
    ]


def memory_candidates_cmd(args):
    task = latest_task(args.task_id)
    if not task:
        raise SystemExit(f"Unknown task id: {args.task_id}")
    run_dir = Path(task["run_dir"])
    queue_item = latest_queue_items().get(task.get("queue_id")) or queue_item_for_task_id(args.task_id)
    namespace = queue_item.get("memory_namespace")
    candidates, candidates_path = load_memory_candidates_for_task(task, run_dir, namespace=namespace)
    if not candidates_path.exists():
        raise SystemExit(f"No memory candidates found for task {args.task_id}. Run `agentctl summarize {args.task_id}` first.")

    action = "list"
    target_id = None
    if args.approve and args.reject:
        raise SystemExit("Use only one of --approve or --reject.")
    if args.approve:
        action = "approve"
        target_id = args.approve
    if args.reject:
        action = "reject"
        target_id = args.reject

    changed = False
    if target_id:
        matched = False
        for candidate in candidates:
            if candidate.get("candidate_id") == target_id:
                matched = True
                candidate["decision"] = "approved" if action == "approve" else "rejected"
                candidate["writeback_recommended"] = action == "approve"
                candidate["decision_at"] = now_iso()
                changed = True
                break
        if not matched:
            raise SystemExit(f"Unknown candidate id for task {args.task_id}: {target_id}")
    if changed:
        write_memory_candidates(run_dir, candidates)

    payload = {
        "task_id": args.task_id,
        "namespace": namespace,
        "candidates_file": str(candidates_path),
        "count": len(candidates),
        "writeback_selected_count": len(candidates_selected_for_writeback(candidates)),
        "candidates": candidates,
    }
    if args.json or action != "list":
        print_json(payload)
    else:
        for candidate in candidates:
            print(f"{candidate.get('candidate_id')} {candidate.get('decision')} writeback={candidate.get('writeback_recommended')} {candidate.get('title')}")
    return 0


def recall_preview_cmd(args):
    config = load_config()
    opts = build_memory_options(
        config,
        enabled=not getattr(args, "no_memory", False),
        query=args.query,
        reason="no_memory_flag" if getattr(args, "no_memory", False) else None,
    )
    payload = recall_preview_payload(args.workspace, args.query, opts)
    if args.json:
        print_json(payload)
    else:
        print(payload.get("prelude") or "No memory would be injected.")
    return 0

def summarize_cmd(args):
    task = latest_task(args.task_id)
    if not task:
        raise SystemExit(f"Unknown task id: {args.task_id}")
    run_dir = Path(task["run_dir"])
    queue_item = latest_queue_items().get(task.get("queue_id")) or queue_item_for_task_id(args.task_id)
    goal_text = ""
    if task.get("mode") == "iterate":
        goal_text = task.get("goal") or (run_dir / "goal.txt").read_text(encoding="utf-8").strip()
    else:
        prompt_path = run_dir / "prompt.txt"
        if prompt_path.exists():
            goal_text = prompt_path.read_text(encoding="utf-8").strip()
    summary = {
        "task_id": task.get("task_id"),
        "queue_id": task.get("queue_id") or queue_item.get("queue_id"),
        "type": task.get("mode", "run"),
        "status": task.get("status"),
        "workspace": queue_item.get("workspace"),
        "cwd": task.get("cwd"),
        "memory_namespace": queue_item.get("memory_namespace"),
        "agent": task.get("agent"),
        "tool": task.get("tool"),
        "model": task.get("model"),
        "goal": goal_text,
        "check": task.get("check"),
        "final_check_passed": task.get("final_check_passed"),
        "rounds": task.get("rounds"),
        "files_changed": [],
        "risks": [],
        "next_action": "none",
        "memory_recall": task.get("memory_recall"),
    }
    memory_candidates = normalize_memory_candidates(generate_memory_candidates(task, run_dir), task, run_dir, namespace=summary.get("memory_namespace"))
    summary["memory_candidates"] = memory_candidates
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "memory-candidates.json").write_text(json.dumps(memory_candidates, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_md_parts = [
        f"# Task Summary: {summary['task_id']}",
        "",
        f"- **Status:** {summary['status']}",
        f"- **Workspace:** {summary['workspace'] or 'N/A'}",
        f"- **Agent:** {summary['agent']}",
        f"- **Model:** {summary['model']}",
        f"- **Goal:** {summary['goal']}",
        f"- **Check:** {summary['check'] or 'N/A'}",
        "",
        "## Result",
        f"The task finished with status: **{summary['status']}**.",
        "",
        "## Memory Recall",
        f"- **Enabled:** {bool((summary.get('memory_recall') or {}).get('enabled'))}",
        f"- **Injected:** {bool((summary.get('memory_recall') or {}).get('injected'))}",
        f"- **Records:** {len((summary.get('memory_recall') or {}).get('records') or [])}",
        f"- **Error:** {(summary.get('memory_recall') or {}).get('error') or 'N/A'}",
        "",
        "## Logs",
        f"- [metadata.json](metadata.json)",
        f"- [prompt.txt](prompt.txt)",
        f"- [stdout.log](stdout.log)",
        f"- [stderr.log](stderr.log)",
        "",
        "## Memory Candidates",
    ]
    if memory_candidates:
        for candidate in memory_candidates:
            summary_md_parts.append(f"- **{candidate.get('record_type', 'candidate').title()}:** {candidate.get('title')}")
    else:
        summary_md_parts.append("No memory candidates were identified.")
    (run_dir / "summary.md").write_text("\n".join(summary_md_parts), encoding="utf-8")
    print(f"Summary written to {run_dir}")
    if args.json:
        print_json(summary)
    else:
        print("\n".join(summary_md_parts))
    return 0

def writeback_cmd(args):
    task = latest_task(args.task_id)
    if not task:
        raise SystemExit(f"Unknown task id: {args.task_id}")
    run_dir = Path(task["run_dir"])
    queue_item = latest_queue_items().get(task.get("queue_id")) or queue_item_for_task_id(args.task_id)
    namespace = queue_item.get("memory_namespace")
    if not namespace:
        raise SystemExit(f"Task {args.task_id} has no memory_namespace. Cannot write back.")
    writeback_path = run_dir / "writeback.json"
    if writeback_path.exists():
        existing = load_json_file(writeback_path, {}) or {}
        if existing.get("status") == "completed" and existing.get("records"):
            payload = {
                "status": "skipped",
                "reason": "already_written",
                "writeback_file": str(writeback_path),
                "records": existing.get("records") or [],
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Writeback already completed for task {args.task_id}: {writeback_path}")
            return 0
    candidates_path = run_dir / "memory-candidates.json"
    if not candidates_path.exists():
        print(f"No memory candidates found for task {args.task_id}. Run `summarize` first.")
        return 1
    candidates, _ = load_memory_candidates_for_task(task, run_dir, namespace=namespace)
    recommended = candidates_selected_for_writeback(candidates)
    if args.dry_run:
        print_json({
            "would_write": bool(recommended),
            "namespace": namespace,
            "count": len(recommended),
            "candidates": recommended,
            "rules": [
                "only candidates with candidate_id are eligible",
                "writeback_recommended must be true",
                "decision must be approved",
                "full summaries are never written back",
                "existing writeback receipts are skipped",
            ],
        })
        return 0
    if not recommended:
        writeback_receipt = {
            "task_id": args.task_id,
            "namespace": namespace,
            "status": "completed",
            "records": []
        }
        (run_dir / "writeback.json").write_text(json.dumps(writeback_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.json:
            print_json(writeback_receipt)
        else:
            print(f"No recommended memory candidates for task {args.task_id}.")
        return 0
    if AMBAdapter is None:
        raise SystemExit("AMBAdapter not available. Cannot perform writeback.")
    adapter = AMBAdapter()
    results = []
    for candidate in recommended:
        content_payload = {k: v for k, v in candidate.items() if k not in ["writeback_recommended", "decision"]}
        result = adapter.store(
            namespace=namespace,
            kind="memory",
            content=content_payload,
            tags=[
                f"kind:{candidate.get('record_type')}",
                namespace,
                "source:runtime-agents",
                f"task:{args.task_id}",
                f"candidate:{candidate.get('candidate_id')}"
            ],
            actor="runtime-agents",
            source_app="agentctl",
            source_client="runtime-agents",
            source_model=task.get("model"),
            client_session_id=f"task:{args.task_id}",
            client_workspace=queue_item.get("workspace"),
            client_transport="stdio",
            session_id=args.task_id,
            correlation_id=queue_item.get("queue_id") or args.task_id,
            title=candidate.get("title"),
        )
        if result is not None:
            result["candidate_id"] = candidate.get("candidate_id")
        if args.verify and result and result.get("ok") and result.get("id"):
            verify = adapter.recall(namespace, candidate.get("title") or candidate.get("claim") or result.get("id"), limit=10)
            items = ((verify.get("response") or {}).get("items") or []) if verify.get("ok") else []
            result["verified"] = any(item.get("id") == result.get("id") for item in items if isinstance(item, dict))
        results.append(result)
    failed = [r for r in results if not r or not r.get("ok")]
    writeback_receipt = {
        "task_id": args.task_id,
        "namespace": namespace,
        "status": "failed" if failed else "completed",
        "records": results
    }
    (run_dir / "writeback.json").write_text(json.dumps(writeback_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print_json(writeback_receipt)
    else:
        if failed:
            print(f"Writeback failed for {len(failed)} of {len(results)} records in namespace '{namespace}'.")
        else:
            print(f"Successfully wrote {len(results)} records to namespace '{namespace}'.")
    return 1 if failed else 0

def main():
    parser = argparse.ArgumentParser(prog="agentctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("agent")
    run.add_argument("prompt", nargs=argparse.REMAINDER)
    run.add_argument("--model")
    run.add_argument("--workspace")
    run.add_argument("--no-memory", action="store_true")
    run.add_argument("--memory-query")
    run.add_argument("--memory-preview", action="store_true")
    run.add_argument("--fallback", action="store_true")
    run.add_argument("--approve", action="append", default=[], metavar="CAPABILITY")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--timeout", type=int, default=600)
    run.set_defaults(func=run_task)

    status = sub.add_parser("status")
    status.add_argument("--limit", type=int, default=10)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=status_cmd)

    logs = sub.add_parser("logs")
    logs.add_argument("task_id")
    logs.add_argument("--file", choices=["stdout", "stderr", "metadata", "result", "check-stdout", "check-stderr"], default="stdout")
    logs.add_argument("--round", type=int)
    logs.add_argument("--tail", type=int)
    logs.add_argument("--json", action="store_true")
    logs.set_defaults(func=logs_cmd)

    show = sub.add_parser("show")
    show.add_argument("task_id")
    show.add_argument("--json", action="store_true")
    show.add_argument("--summary", action="store_true")
    show.set_defaults(func=show_cmd)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("agent")
    inspect.set_defaults(func=inspect_cmd)

    list_agents = sub.add_parser("list-agents")
    list_agents.add_argument("--json", action="store_true")
    list_agents.set_defaults(func=list_agents_cmd)

    retry = sub.add_parser("retry")
    retry.add_argument("task_id")
    retry.add_argument("--fallback", action="store_true")
    retry.add_argument("--approve", action="append", default=[], metavar="CAPABILITY")
    retry.add_argument("--timeout", type=int, default=600)
    retry.set_defaults(func=retry_cmd)

    submit = sub.add_parser("submit")
    submit.add_argument("agent")
    submit.add_argument("goal", nargs=argparse.REMAINDER)
    submit.add_argument("--check")
    submit.add_argument("--max-rounds", type=int, default=5)
    submit.add_argument("--cwd")
    submit.add_argument("--workspace")
    submit.add_argument("--no-memory", action="store_true")
    submit.add_argument("--memory-query")
    submit.add_argument("--memory-preview", action="store_true")
    submit.set_defaults(func=submit_cmd)

    queue = sub.add_parser("queue")
    queue.add_argument("--json", action="store_true")
    queue_sub = queue.add_subparsers(dest="queue_cmd")
    queue_show = queue_sub.add_parser("show")
    queue_show.add_argument("queue_id")
    queue_show.add_argument("--json", action="store_true")
    queue_show.set_defaults(func=queue_show_cmd)
    queue.set_defaults(func=queue_cmd)

    run_next = sub.add_parser("run-next")
    run_next.add_argument("--dry-run", action="store_true")
    run_next.set_defaults(func=run_next_cmd)

    schedule = sub.add_parser("schedule")
    schedule_sub = schedule.add_subparsers(dest="schedule_cmd", required=True)

    schedule_add = schedule_sub.add_parser("add")
    schedule_add.add_argument("name")
    schedule_add.add_argument("--workspace", required=True)
    schedule_add.add_argument("--type", choices=["run", "iterate"], required=True)
    schedule_add.add_argument("--agent", required=True)
    schedule_add.add_argument("--goal", required=True)
    schedule_add.add_argument("--cron", required=True)
    schedule_add.add_argument("--check")
    schedule_add.add_argument("--max-rounds", type=int, default=1)
    schedule_add.add_argument("--no-memory", action="store_true")
    schedule_add.add_argument("--memory-query")
    schedule_add.set_defaults(func=schedule_add_cmd)

    schedule_list = schedule_sub.add_parser("list")
    schedule_list.add_argument("--json", action="store_true")
    schedule_list.set_defaults(func=schedule_list_cmd)

    schedule_show = schedule_sub.add_parser("show")
    schedule_show.add_argument("name")
    schedule_show.add_argument("--json", action="store_true")
    schedule_show.set_defaults(func=schedule_show_cmd)

    schedule_remove = schedule_sub.add_parser("remove")
    schedule_remove.add_argument("name")
    schedule_remove.set_defaults(func=schedule_remove_cmd)

    schedule_pause = schedule_sub.add_parser("pause")
    schedule_pause.add_argument("name")
    schedule_pause.set_defaults(func=schedule_pause_cmd)

    schedule_resume = schedule_sub.add_parser("resume")
    schedule_resume.add_argument("name")
    schedule_resume.set_defaults(func=schedule_resume_cmd)

    schedule_retry = schedule_sub.add_parser("retry")
    schedule_retry.add_argument("name")
    schedule_retry.set_defaults(func=schedule_retry_cmd)

    schedule_due = schedule_sub.add_parser("run-due")
    schedule_due.add_argument("--dry-run", action="store_true")
    schedule_due.add_argument("--json", action="store_true")
    schedule_due.set_defaults(func=schedule_run_due_cmd)

    pause = sub.add_parser("pause")
    pause.set_defaults(func=pause_cmd)

    resume = sub.add_parser("resume")
    resume.set_defaults(func=resume_cmd)

    daemon_status = sub.add_parser("daemon-status")
    daemon_status.add_argument("--json", action="store_true")
    daemon_status.set_defaults(func=daemon_status_cmd)

    agentd_once = sub.add_parser("agentd-once")
    agentd_once.add_argument("--ignore-pause", action="store_true")
    agentd_once.set_defaults(func=agentd_once_cmd)

    agentd_start = sub.add_parser("agentd-start")
    agentd_start.set_defaults(func=agentd_start_cmd)

    agentd_stop = sub.add_parser("agentd-stop")
    agentd_stop.set_defaults(func=agentd_stop_cmd)

    health = sub.add_parser("health")
    health.add_argument("--deep", action="store_true")
    health.add_argument("--json", action="store_true")
    health.set_defaults(func=health_cmd)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=doctor_cmd)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_cmd", required=True)
    config_validate = config_sub.add_parser("validate")
    config_validate.add_argument("--json", action="store_true")
    config_validate.set_defaults(func=config_validate_cmd)

    guardrail = sub.add_parser("guardrail")
    guardrail_sub = guardrail.add_subparsers(dest="guardrail_cmd", required=True)
    guardrail_list = guardrail_sub.add_parser("list")
    guardrail_list.add_argument("--json", action="store_true")
    guardrail_list.set_defaults(func=guardrail_list_cmd)
    guardrail_eval = guardrail_sub.add_parser("eval")
    guardrail_eval.add_argument("--profile", dest="profile_id", required=True)
    guardrail_eval.add_argument("--tool", dest="tool_id")
    guardrail_eval.add_argument("--action", required=True)
    guardrail_eval.add_argument("--workspace")
    guardrail_eval.add_argument("--agent")
    guardrail_eval.add_argument("--json", action="store_true")
    guardrail_eval.set_defaults(func=guardrail_eval_cmd)

    tool = sub.add_parser("tool")
    tool_sub = tool.add_subparsers(dest="tool_cmd", required=True)
    tool_list = tool_sub.add_parser("list")
    tool_list.add_argument("--json", action="store_true")
    tool_list.set_defaults(func=tool_list_cmd)
    tool_show = tool_sub.add_parser("show")
    tool_show.add_argument("tool_id")
    tool_show.add_argument("--json", action="store_true")
    tool_show.set_defaults(func=tool_show_cmd)
    tool_validate = tool_sub.add_parser("validate")
    tool_validate.add_argument("--json", action="store_true")
    tool_validate.set_defaults(func=tool_validate_cmd)

    profile = sub.add_parser("profile")
    profile_sub = profile.add_subparsers(dest="profile_cmd", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true")
    profile_list.set_defaults(func=profile_list_cmd)
    profile_show = profile_sub.add_parser("show")
    profile_show.add_argument("profile_id")
    profile_show.add_argument("--json", action="store_true")
    profile_show.set_defaults(func=profile_show_cmd)
    profile_validate = profile_sub.add_parser("validate")
    profile_validate.add_argument("--json", action="store_true")
    profile_validate.set_defaults(func=profile_validate_cmd)
    profile_run = profile_sub.add_parser("run")
    profile_run.add_argument("profile_id")
    profile_run.add_argument("goal", nargs=argparse.REMAINDER)
    profile_run.add_argument("--workspace")
    profile_run.add_argument("--agent")
    profile_run.add_argument("--tool")
    profile_run.add_argument("--dry-run", action="store_true")
    profile_run.add_argument("--timeout", type=int, default=600)
    profile_run.add_argument("--json", action="store_true")
    profile_run.set_defaults(func=profile_run_cmd)
    profile_plan = profile_sub.add_parser("plan")
    profile_plan.add_argument("profile_id")
    profile_plan.add_argument("goal", nargs=argparse.REMAINDER)
    profile_plan.add_argument("--workspace")
    profile_plan.add_argument("--agent")
    profile_plan.add_argument("--tool")
    profile_plan.add_argument("--json", action="store_true")
    profile_plan.set_defaults(func=profile_plan_cmd)

    selftest = sub.add_parser("selftest")
    selftest.add_argument("--json", action="store_true")
    selftest.set_defaults(func=selftest_cmd)

    smoke = sub.add_parser("smoke")
    smoke.add_argument("--json", action="store_true")
    smoke.set_defaults(func=smoke_cmd)

    _runbook_parser(sub)

    version = sub.add_parser("version")
    version.add_argument("--json", action="store_true")
    version.set_defaults(func=version_cmd)

    plan = sub.add_parser("plan")
    plan_sub = plan.add_subparsers(dest="plan_cmd", required=True)

    plan_create = plan_sub.add_parser("create")
    plan_create.add_argument("goal", nargs=argparse.REMAINDER)
    plan_create.add_argument("--workspace", required=True)
    plan_create.set_defaults(func=plan_create_cmd)

    plan_show = plan_sub.add_parser("show")
    plan_show.add_argument("plan_id")
    plan_show.add_argument("--json", action="store_true")
    plan_show.set_defaults(func=plan_show_cmd)

    plan_list = plan_sub.add_parser("list")
    plan_list.add_argument("--json", action="store_true")
    plan_list.set_defaults(func=plan_list_cmd)

    plan_review = plan_sub.add_parser("review")
    plan_review.add_argument("plan_id")
    plan_review.add_argument("--json", action="store_true")
    plan_review.set_defaults(func=plan_review_cmd)

    plan_approve = plan_sub.add_parser("approve")
    plan_approve.add_argument("plan_id")
    plan_approve.set_defaults(func=plan_approve_cmd)

    plan_reject = plan_sub.add_parser("reject")
    plan_reject.add_argument("plan_id")
    plan_reject.set_defaults(func=plan_reject_cmd)

    plan_enqueue = plan_sub.add_parser("enqueue")
    plan_enqueue.add_argument("plan_id")
    plan_enqueue.set_defaults(func=plan_enqueue_cmd)

    plan_status = plan_sub.add_parser("status")
    plan_status.add_argument("plan_id")
    plan_status.add_argument("--json", action="store_true")
    plan_status.set_defaults(func=plan_status_cmd)

    plan_retry = plan_sub.add_parser("retry")
    plan_retry.add_argument("plan_id")
    plan_retry.add_argument("subtask_id")
    plan_retry.set_defaults(func=plan_retry_cmd)

    plan_skip = plan_sub.add_parser("skip")
    plan_skip.add_argument("plan_id")
    plan_skip.add_argument("subtask_id")
    plan_skip.add_argument("--reason", required=True)
    plan_skip.set_defaults(func=plan_skip_cmd)

    plan_repair = plan_sub.add_parser("repair")
    plan_repair.add_argument("plan_id")
    plan_repair.add_argument("--json", action="store_true")
    plan_repair.set_defaults(func=plan_repair_cmd)

    plan_summarize = plan_sub.add_parser("summarize")
    plan_summarize.add_argument("plan_id")
    plan_summarize.add_argument("--json", action="store_true")
    plan_summarize.set_defaults(func=plan_summarize_cmd)

    recall_preview = sub.add_parser("recall-preview")
    recall_preview.add_argument("query")
    recall_preview.add_argument("--workspace", required=True)
    recall_preview.add_argument("--json", action="store_true")
    recall_preview.add_argument("--no-memory", action="store_true")
    recall_preview.set_defaults(func=recall_preview_cmd)

    workspace = sub.add_parser("workspace")
    ws_sub = workspace.add_subparsers(dest="ws_cmd", required=True)

    ws_add = ws_sub.add_parser("add")
    ws_add.add_argument("name")
    ws_add.add_argument("path")
    ws_add.add_argument("--memory-namespace")
    ws_add.set_defaults(func=workspace_add_cmd)

    ws_list = ws_sub.add_parser("list")
    ws_list.add_argument("--json", action="store_true")
    ws_list.set_defaults(func=workspace_list_cmd)

    ws_show = ws_sub.add_parser("show")
    ws_show.add_argument("name")
    ws_show.add_argument("--json", action="store_true")
    ws_show.set_defaults(func=workspace_show_cmd)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("task_id")
    summarize.add_argument("--json", action="store_true")
    summarize.set_defaults(func=summarize_cmd)

    memory_candidates = sub.add_parser("memory-candidates")
    memory_candidates.add_argument("task_id")
    memory_candidates.add_argument("--json", action="store_true")
    memory_candidates.add_argument("--approve")
    memory_candidates.add_argument("--reject")
    memory_candidates.set_defaults(func=memory_candidates_cmd)

    writeback = sub.add_parser("writeback")
    writeback.add_argument("task_id")
    writeback.add_argument("--dry-run", action="store_true")
    writeback.add_argument("--json", action="store_true")
    writeback.add_argument("--verify", action="store_true")
    writeback.set_defaults(func=writeback_cmd)

    amb_health = sub.add_parser("amb-health")
    amb_health.add_argument("--json", action="store_true")
    amb_health.set_defaults(func=amb_health_cmd)

    telegram_status = sub.add_parser("telegram-status")
    telegram_status.add_argument("--json", action="store_true")
    telegram_status.set_defaults(func=telegram_status_cmd)

    telegram_test = sub.add_parser("telegram-test")
    telegram_test.add_argument("--json", action="store_true")
    telegram_test.set_defaults(func=telegram_test_cmd)

    assistant_route = sub.add_parser("assistant-route")
    assistant_route.add_argument("message", nargs=argparse.REMAINDER)
    assistant_route.add_argument("--json", action="store_true")
    assistant_route.add_argument("--session-json")
    assistant_route.set_defaults(func=assistant_route_cmd)

    assistant_exec = sub.add_parser("assistant-exec")
    assistant_exec.add_argument("message", nargs=argparse.REMAINDER)
    assistant_exec.add_argument("--json", action="store_true")
    assistant_exec.add_argument("--session-json")
    assistant_exec.set_defaults(func=assistant_exec_cmd)

    iterate = sub.add_parser("iterate")
    iterate.add_argument("agent")
    iterate.add_argument("goal", nargs=argparse.REMAINDER)
    iterate.add_argument("--check")
    iterate.add_argument("--max-rounds", type=int, default=5)
    iterate.add_argument("--model")
    iterate.add_argument("--workspace")
    iterate.add_argument("--no-memory", action="store_true")
    iterate.add_argument("--memory-query")
    iterate.add_argument("--memory-preview", action="store_true")
    iterate.add_argument("--fallback", action="store_true")
    iterate.add_argument("--approve", action="append", default=[], metavar="CAPABILITY")
    iterate.add_argument("--dry-run", action="store_true")
    iterate.add_argument("--json", action="store_true")
    iterate.add_argument("--tail", type=int)
    iterate.add_argument("--timeout", type=int, default=600)
    iterate.add_argument("--check-timeout", type=int, default=300)
    iterate.set_defaults(func=iterate_cmd)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
