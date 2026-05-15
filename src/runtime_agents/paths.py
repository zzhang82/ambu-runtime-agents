import os
import shutil
import sys
from pathlib import Path


def config_home() -> Path:
    return Path(os.environ.get("RUNTIME_AGENTS_CONFIG_HOME", str(Path.home() / ".config" / "runtime-agents"))).expanduser()


def state_home() -> Path:
    return Path(os.environ.get("RUNTIME_AGENTS_STATE_HOME", str(Path.home() / ".local" / "share" / "runtime-agents"))).expanduser()


def resolve_agentctl_bin() -> str | list[str]:
    configured = os.environ.get("RUNTIME_AGENTS_AGENTCTL_BIN")
    if configured:
        return configured
    project_root = Path(__file__).resolve().parents[2]
    if Path.cwd().resolve() == project_root:
        return [sys.executable, "-m", "runtime_agents.cli"]
    return shutil.which("agentctl") or sys.argv[0]


def resolve_agentbot_bin() -> str:
    return os.environ.get("RUNTIME_AGENTS_AGENTBOT_BIN") or shutil.which("agentbot") or str(Path.home() / ".local" / "bin" / "agentbot")


CONFIG_PATH = config_home() / "agents.yaml"
PROFILES_CONFIG_PATH = config_home() / "profiles.yaml"
TOOLS_CONFIG_PATH = config_home() / "tools.yaml"
TELEGRAM_CONFIG_PATH = config_home() / "telegram.yaml"
VERSION_PATH = config_home() / "VERSION"

STATE_DIR = state_home()
RUNS_DIR = STATE_DIR / "runs"
PLANS_DIR = STATE_DIR / "plans"
TASKS_JSONL = STATE_DIR / "tasks.jsonl"
QUEUE_JSONL = STATE_DIR / "queue.jsonl"
QUEUE_LOCK = STATE_DIR / "queue.lock"
SCHEDULES_JSONL = STATE_DIR / "schedules.jsonl"
PAUSED_FILE = STATE_DIR / "paused"
AGENTD_PID = STATE_DIR / "agentd.pid"
AGENTD_LOG = STATE_DIR / "agentd.log"
TELEGRAM_OFFSET = STATE_DIR / "telegram.offset"
TELEGRAM_LOG = STATE_DIR / "telegram.log"

SELF_IMPROVE_HOME = Path.home() / ".runtime-agents"
EVENTS_JSONL = SELF_IMPROVE_HOME / "events" / "agent-runs.jsonl"
