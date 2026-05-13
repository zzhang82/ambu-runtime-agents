#!/usr/bin/env python3
import datetime as dt
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def state_home():
    return Path(os.environ.get("RUNTIME_AGENTS_STATE_HOME", str(Path.home() / ".local" / "share" / "runtime-agents"))).expanduser()


def resolve_agentctl_bin():
    return os.environ.get("RUNTIME_AGENTS_AGENTCTL_BIN") or shutil.which("agentctl") or str(Path.home() / ".local" / "bin" / "agentctl")


STATE_DIR = state_home()
PAUSED_FILE = STATE_DIR / "paused"
AGENTD_PID = STATE_DIR / "agentd.pid"
AGENTD_LOG = STATE_DIR / "agentd.log"

running = True


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log(message):
    line = f"{now_iso()} {message}\n"
    print(line, end="", flush=True)
    try:
        with AGENTD_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
        AGENTD_LOG.chmod(0o600)
    except Exception:
        pass


def stop(signum, frame):
    global running
    running = False
    log(f"agentd stopping signal={signum}")


def main():
    interval = float(os.environ.get("AGENTD_INTERVAL", "5"))
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    AGENTD_PID.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    AGENTD_PID.chmod(0o600)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log(f"agentd started pid={os.getpid()} interval={interval}")
    agentctl = resolve_agentctl_bin()
    while running:
        if PAUSED_FILE.exists():
            log("agentd paused")
            time.sleep(interval)
            continue
        proc = subprocess.run([agentctl, "run-next"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log(f"run-next returncode={proc.returncode} stdout={proc.stdout.strip()} stderr={proc.stderr.strip()}")
        time.sleep(interval)
    try:
        if AGENTD_PID.exists() and AGENTD_PID.read_text(encoding="utf-8").strip() == str(os.getpid()):
            AGENTD_PID.unlink()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
