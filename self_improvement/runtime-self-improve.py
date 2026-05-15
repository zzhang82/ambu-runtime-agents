import json
import os
import sys
import glob
import argparse
import hashlib
import subprocess
import sqlite3
import shutil
from datetime import datetime, timedelta
from collections import Counter

try:
    import yaml
except ImportError:
    yaml = None

# --- CONSTANTS ---
GLOBAL_SKILLS_PATH = os.path.expanduser("~/.config/opencode/skills")
STAGING_DIR = os.path.expanduser("~/.runtime-agents/staging/")
APPROVALS_DIR = os.path.expanduser("~/.runtime-agents/approvals/")
SCHEDULER_DIR = os.path.expanduser("~/.runtime-agents/scheduler/")
SCHEDULER_STATE_PATH = os.path.join(SCHEDULER_DIR, "state.json")
SCHEDULER_LOG_PATH = os.path.join(SCHEDULER_DIR, "scheduler.log")
EVENTS_PATH = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
REGISTRY_PATH = os.path.join(GLOBAL_SKILLS_PATH, "skills.registry.json")

# --- UTILS ---

def get_dir_hash(path):
    if not os.path.exists(path):
        return None
    hash_sha256 = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        for names in sorted(files):
            if names.startswith(".git") or names == "skills.lock.json" or names == "skills.registry.json":
                continue
            filepath = os.path.join(root, names)
            try:
                with open(filepath, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_sha256.update(chunk)
            except:
                continue
    return hash_sha256.hexdigest()

def get_files_hash(files, workspace):
    hash_sha256 = hashlib.sha256()
    found = False
    for f in sorted(files):
        p = os.path.join(workspace, f)
        if os.path.exists(p):
            found = True
            with open(p, "rb") as f_in:
                for chunk in iter(lambda: f_in.read(4096), b""):
                    hash_sha256.update(chunk)
    return hash_sha256.hexdigest() if found else None

def get_skill_hash(skill_path):
    skill_md = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md):
        return None
    with open(skill_md, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def record_audit(data, message):
    if "audit_log" not in data:
        data["audit_log"] = []
    data["audit_log"].append({
        "timestamp": datetime.now().isoformat() + "Z",
        "message": message
    })

def log_scheduler(message):
    os.makedirs(SCHEDULER_DIR, exist_ok=True)
    with open(SCHEDULER_LOG_PATH, 'a') as f:
        f.write(f"[{datetime.now().isoformat()}] {message}\n")
    print(message)

# --- REGISTRY MANAGER ---

class RegistryManager:
    @staticmethod
    def load():
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, 'r') as f:
                return json.load(f)
        return {"schema_version": "0.1", "skills": {}}
    
    @staticmethod
    def save(data):
        with open(REGISTRY_PATH, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def set_state(skill_name, state, metadata=None):
        data = RegistryManager.load()
        if skill_name not in data["skills"]:
            data["skills"][skill_name] = {
                "version": "0.1.0",
                "last_verified_at": None,
                "supported_runtimes": ["opencode", "claude", "codex", "gemini"],
                "usage": {"last_seen_at": None, "invocation_count_30d": 0, "recommendation_count_30d": 0},
                "replacement": {"replaced_by": None, "reason": None},
                "deprecation": {"status": "active", "deprecated_at": None, "archive_after": None, "approval_id": None}
            }
        data["skills"][skill_name]["state"] = state
        if metadata:
            for key in ["usage", "replacement", "deprecation"]:
                if key in metadata:
                    if key not in data["skills"][skill_name]:
                        data["skills"][skill_name][key] = {}
                    data["skills"][skill_name][key].update(metadata[key])
            for key, val in metadata.items():
                if key not in ["usage", "replacement", "deprecation"]:
                    data["skills"][skill_name][key] = val
        if state in ["verified", "locked"]:
            data["skills"][skill_name]["last_verified_at"] = datetime.now().isoformat() + "Z"
        RegistryManager.save(data)

# --- ADAPTERS ---

class ClaudeCCRAdapter:
    def __init__(self, history_path="~/.claude/history.jsonl", projects_base="~/.claude/projects"):
        self.history_path = os.path.expanduser(history_path)
        self.projects_base = os.path.expanduser(projects_base)

    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.history_path):
            return events
        with open(self.history_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    data = json.loads(line)
                    sid = data.get("sessionId")
                    project_path = data.get("project", "")
                    session_file = os.path.join(self.projects_base, project_path.replace("/", "-"), f"{sid}.jsonl")
                    tools_used = []
                    if os.path.exists(session_file):
                        with open(session_file, 'r', encoding='utf-8') as sf:
                            for sline in sf:
                                try:
                                    sdata = json.loads(sline)
                                    if sdata.get("type") == "assistant":
                                        for item in sdata.get("message", {}).get("content", []):
                                            if isinstance(item, dict) and item.get("type") == "tool_use":
                                                tools_used.append(item.get("name"))
                                except Exception: continue
                    ts = data.get('timestamp')
                    ts_iso = datetime.fromtimestamp(ts/1000).isoformat() + "Z" if ts else None
                    events.append({
                        "schema_version": "0.1", "runtime": "claude", "session_id": sid,
                        "run_id": f"run_{ts}", "timestamp_start": ts_iso, "timestamp_end": ts_iso,
                        "workspace": project_path, "user_goal": data.get("display"), "outcome": "success", 
                        "tools_used": sorted(list(set(tools_used))), "tool_sequence": tools_used,
                        "summary": "Imported from Claude history"
                    })
                except Exception: continue
        return events

class GeminiAdapter:
    def __init__(self, base_path="~/.gemini/tmp"):
        self.base_path = os.path.expanduser(base_path)

    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.base_path): return events
        files = []
        for root, _, filenames in os.walk(self.base_path):
            for f in filenames:
                if f.startswith("session-") and f.endswith(".json"):
                    files.append(os.path.join(root, f))
        files.sort(key=os.path.getmtime, reverse=True)
        for file_path in files[:limit]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                event_data = {
                    "schema_version": "0.1", "runtime": "gemini", "session_id": data.get("sessionId"),
                    "run_id": data.get("sessionId"), "timestamp_start": data.get("startTime"),
                    "timestamp_end": data.get("lastUpdated"), "workspace": data.get("projectHash"),
                    "tools_used": [], "tool_sequence": [], "commands_run": [], "files_touched": [],
                    "memory_operations": [], "outcome": "completed"
                }
                for msg in data.get("messages", []):
                    if msg.get("type") == "user" and not event_data.get("user_goal"):
                        event_data["user_goal"] = msg.get("content", "").strip()
                    for tc in msg.get("toolCalls", []):
                        name = tc.get("name")
                        if name:
                            if name not in event_data["tools_used"]:
                                event_data["tools_used"].append(name)
                            event_data["tool_sequence"].append(name)
                            args = tc.get("args", {})
                            if name in ["execute_command", "bash"]:
                                cmd = args.get("command") or args.get("cmd")
                                if cmd:
                                    event_data["commands_run"].append(cmd)
                            elif name in ["write_file", "edit_file", "apply_patch"]:
                                path = args.get("file_path") or args.get("path")
                                if path:
                                    event_data["files_touched"].append(path)
                if event_data.get("session_id"):
                    events.append(event_data)
            except Exception:
                continue
        return events

class CodexAdapter:
    def __init__(self, sessions_base="~/.codex/sessions"):
        self.sessions_base = os.path.expanduser(sessions_base)

    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.sessions_base):
            return events
        files = []
        for root, _, filenames in os.walk(self.sessions_base):
            for f in filenames:
                if f.startswith("rollout-") and f.endswith(".jsonl"):
                    files.append(os.path.join(root, f))
        files.sort(key=os.path.getmtime, reverse=True)
        for file_path in files[:limit]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                event_data = {
                    "schema_version": "0.1", "runtime": "codex", "tools_used": [], "tool_sequence": [],
                    "commands_run": [], "files_touched": [], "memory_operations": [], "outcome": "completed"
                }
                for line in lines:
                    try:
                        data = json.loads(line)
                        ev_type = data.get("type")
                        payload = data.get("payload", {})
                        if ev_type == "session_meta":
                            event_data["session_id"] = payload.get("id")
                            event_data["run_id"] = payload.get("id")
                            event_data["timestamp_start"] = payload.get("timestamp")
                            event_data["workspace"] = payload.get("cwd")
                            instr = payload.get("base_instructions", {}).get("text", "")
                            if "Task:\n" in instr:
                                event_data["user_goal"] = instr.split("Task:\n")[-1].strip()
                        elif ev_type == "response_item":
                            ptype = payload.get("type")
                            if ptype == "message" and payload.get("role") == "user":
                                for c in payload.get("content", []):
                                    if isinstance(c, dict) and c.get("type") == "input_text":
                                        event_data["user_goal"] = c.get("text").strip()
                                    elif isinstance(c, str):
                                        event_data["user_goal"] = c.strip()
                            elif ptype == "function_call":
                                name = payload.get("name")
                                if name:
                                    if name not in event_data["tools_used"]:
                                        event_data["tools_used"].append(name)
                                    event_data["tool_sequence"].append(name)
                                    if name == "exec_command":
                                        args_raw = payload.get("arguments", "{}")
                                        args = args_raw if isinstance(args_raw, dict) else json.loads(args_raw)
                                        cmd = args.get("cmd")
                                        if cmd:
                                            event_data["commands_run"].append(cmd)
                    except Exception:
                        continue
                if "session_id" in event_data:
                    events.append(event_data)
            except Exception:
                continue
        return events

class RuntimeAgentsAdapter:
    def __init__(self, base_path):
        self.base_path = os.path.expanduser(base_path)

    def normalize(self, limit=50):
        events = []
        runs_path = os.path.join(self.base_path, "runs")
        if not os.path.exists(runs_path):
            return events
        run_dirs = sorted([d for d in glob.glob(os.path.join(runs_path, "*")) if os.path.isdir(d)], reverse=True)
        for run_dir in run_dirs[:limit]:
            meta_path = os.path.join(run_dir, "metadata.json")
            goal_path = os.path.join(run_dir, "goal.txt")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    goal = ""
                    if os.path.exists(goal_path):
                        goal = open(goal_path).read().strip()
                    event = {"schema_version": "0.1", "runtime": "runtime-agents", "session_id": meta.get("task_id"), "run_id": meta.get("task_id"), "timestamp_start": meta.get("started_at"), "timestamp_end": meta.get("ended_at"), "workspace": meta.get("cwd"), "user_goal": goal, "outcome": meta.get("status"), "agent": meta.get("agent"), "model": meta.get("model"), "summary": f"Imported from runtime-agents run {meta.get('task_id')}"}
                    res_path = os.path.join(run_dir, "result.json")
                    if os.path.exists(res_path):
                        res = json.load(open(res_path))
                        event["result_summary"] = res.get("message")
                        if "approval_capabilities" in res:
                            event["capabilities_requested"] = res["approval_capabilities"]
                    events.append(event)
                except Exception:
                    continue
        return events

class OpencodeAdapter:
    def __init__(self, db_path="~/.local/share/opencode/opencode.db"):
        self.db_path = os.path.expanduser(db_path)

    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.db_path):
            return events
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, path, model, time_created, time_updated FROM session ORDER BY time_created DESC LIMIT ?", (limit,))
            for sess in cursor.fetchall():
                sid, title, workspace, model_json, start_ts, end_ts = sess
                cursor.execute("SELECT data FROM part WHERE session_id = ? ORDER BY time_created", (sid,))
                parts = cursor.fetchall()
                tools_used, tool_sequence, commands_run, files_touched = [], [], [], []
                for p in parts:
                    try:
                        pdata = json.loads(p[0])
                        if pdata.get("type") == "tool":
                            tool = pdata.get("tool")
                            if tool:
                                if tool not in tools_used:
                                    tools_used.append(tool)
                                tool_sequence.append(tool)
                                input_data = pdata.get("state", {}).get("input", {})
                                if tool == "bash":
                                    cmd = input_data.get("command")
                                    if cmd:
                                        commands_run.append(cmd)
                                elif tool in ["write", "edit"]:
                                    path = input_data.get("filePath") or input_data.get("file_path")
                                    if path:
                                        files_touched.append(path)
                    except Exception:
                        continue
                events.append({
                    "schema_version": "0.1", "runtime": "opencode", "session_id": sid, "run_id": sid,
                    "timestamp_start": datetime.fromtimestamp(start_ts/1000).isoformat() + "Z",
                    "timestamp_end": datetime.fromtimestamp(end_ts/1000).isoformat() + "Z",
                    "workspace": workspace, "user_goal": title, "outcome": "completed",
                    "tools_used": sorted(list(set(tools_used))), "tool_sequence": tool_sequence,
                    "commands_run": commands_run, "files_touched": sorted(list(set(files_touched))),
                    "summary": f"Imported from opencode DB session {sid}"
                })
            conn.close()
        except Exception as e:
            print(f"Error: {e}")
        return events

# --- HANDLERS ---

class ApplyHandlers:
    @staticmethod
    def forge_skill(approval, staging_dir):
        target = approval["action"]["target"]
        skill_dir = os.path.join(staging_dir, target)
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {target}\ndescription: forged via {approval['approval_id']}\n---\n")
        RegistryManager.set_state(target, "staged")
        return True, f"Forged skill {target} in staging"

    @staticmethod
    def deploy_skill(approval, staging_dir, global_store):
        target = approval["action"]["target"]
        src, dst = os.path.join(staging_dir, target), os.path.join(global_store, target)
        if not os.path.exists(src):
            return False, f"Source not found."
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        RegistryManager.set_state(target, "deployed")
        subprocess.run(["python3", sys.argv[0], "skills", "verify", "--all"], check=True)
        RegistryManager.set_state(target, "verified")
        return True, f"Deployed skill {target}"

    @staticmethod
    def update_skills_lock(approval, global_store):
        subprocess.run(["python3", sys.argv[0], "skills", "lock", "--path", global_store], check=True)
        reg = RegistryManager.load()
        for sname, sdata in reg["skills"].items():
            if sdata["state"] == "verified":
                RegistryManager.set_state(sname, "locked")
        return True, "Updated lockfile"

class RollbackHandlers:
    @staticmethod
    def rollback_skill_deploy(approval, global_store):
        target = approval["action"]["target"]
        target_path = os.path.join(global_store, target)
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
            RegistryManager.set_state(target, "rolled_back")
            return True, f"Removed {target}"
        return False, f"Skill not found"

    @staticmethod
    def rollback_skills_lock(approval, global_store):
        subprocess.run(["git", "checkout", "skills.lock.json"], cwd=global_store, check=True)
        return True, "Reverted lockfile"

# --- MAIN ---

def main():
    parser = argparse.ArgumentParser(description="Runtime Self-Improvement CLI")
    subparsers = parser.add_subparsers(dest="command")

    ing_p = subparsers.add_parser("ingest")
    ing_p.add_argument("--runtime", choices=["claude", "opencode", "runtime-agents", "codex", "gemini"], required=True)
    ing_p.add_argument("--recent", type=int, default=50)

    subparsers.add_parser("scan")
    subparsers.add_parser("suggest")

    sk_p = subparsers.add_parser("skills")
    sk_s = sk_p.add_subparsers(dest="skill_command")
    sk_s.add_parser("status")
    
    sk_lock = sk_s.add_parser("lock")
    sk_lock.add_argument("--path")
    
    sk_ver = sk_s.add_parser("verify")
    sk_ver.add_argument("--all", action="store_true")
    sk_ver.add_argument("--path")
    
    lc_p = sk_s.add_parser("lifecycle")
    lc_s = lc_p.add_subparsers(dest="lifecycle_command")
    lc_s.add_parser("list")
    lc_s.add_parser("verify")
    lc_s.add_parser("init-all")
    
    l_sh = lc_s.add_parser("show")
    l_sh.add_argument("skill")
    
    l_st = lc_s.add_parser("set-state")
    l_st.add_argument("skill")
    l_st.add_argument("state")
    
    dp_p = sk_s.add_parser("deprecation")
    dp_s = dp_p.add_subparsers(dest="deprecation_command")
    dp_s.add_parser("scan")
    dp_s.add_parser("recommend")
    dp_pl = dp_s.add_parser("plan")
    dp_pl.add_argument("skill")
    
    ev_p = sk_s.add_parser("eval")
    ev_s = ev_p.add_subparsers(dest="eval_command")
    ev_s.add_parser("list")
    ev_r = ev_s.add_parser("run")
    ev_r.add_argument("skill", nargs="?")
    ev_r.add_argument("--core", action="store_true")

    hooks_p = subparsers.add_parser("hooks")
    hooks_s = hooks_p.add_subparsers(dest="hook_command")
    h_pr = hooks_s.add_parser("post-run")
    h_pr.add_argument("--goal", required=True)
    
    subparsers.add_parser("recommend")
    
    e_root = subparsers.add_parser("events")
    e_sub = e_root.add_subparsers(dest="event_command")
    e_v = e_sub.add_parser("validate")
    e_v.add_argument("--recent", type=int, default=20)
    e_v.add_argument("--runtime")
    
    sc_root = subparsers.add_parser("schedule")
    sc_sub = sc_root.add_subparsers(dest="schedule_command")
    sc_sub.add_parser("check")
    sc_sub.add_parser("run")
    
    ap_root = subparsers.add_parser("approvals")
    ap_sub = ap_root.add_subparsers(dest="approval_command")
    ap_sub.add_parser("list")
    
    ap_sh = ap_sub.add_parser("show")
    ap_sh.add_argument("approval_id")
    
    ap_ap = ap_sub.add_parser("approve")
    ap_ap.add_argument("approval_id")
    
    ap_rj = ap_sub.add_parser("reject")
    ap_rj.add_argument("approval_id")
    
    ap_ly = ap_sub.add_parser("apply")
    ap_ly.add_argument("approval_id")
    
    ap_t = ap_sub.add_parser("create-test")
    ap_t.add_argument("--action", default="forge_skill")
    ap_t.add_argument("--target", default="test-skill")

    rb_root = subparsers.add_parser("rollback")
    rb_sub = rb_root.add_subparsers(dest="rollback_command")
    rb_sub.add_parser("list")
    rb_pl = rb_sub.add_parser("plan")
    rb_pl.add_argument("approval_id")
    rb_ap = rb_sub.add_parser("apply")
    rb_ap.add_argument("approval_id")

    so_root = subparsers.add_parser("scheduler")
    so_s = so_root.add_subparsers(dest="scheduler_command")
    so_s.add_parser("install")
    so_s.add_parser("status")
    so_s.add_parser("logs")
    so_ro = so_s.add_parser("run-once")
    so_ro.add_argument("--workspace")

    bk_root = subparsers.add_parser("backup")
    bk_s = bk_root.add_subparsers(dest="backup_command")
    bk_s.add_parser("status")
    bk_c = bk_s.add_parser("create")
    bk_c.add_argument("--target", required=True)
    bk_c.add_argument("--path", default="/mnt/r/LLMData/SkillsBackUp/")
    bk_v = bk_s.add_parser("verify")
    bk_v.add_argument("--target", default="nas")
    bk_v.add_argument("--path", default="/mnt/r/LLMData/SkillsBackUp/")
    bk_rp = bk_s.add_parser("restore-plan")
    bk_rp.add_argument("--target", default="nas")
    bk_rp.add_argument("--path", default="/mnt/r/LLMData/SkillsBackUp/")

    args = parser.parse_args()

    if args.command == "ingest":
        adapters = {"claude": ClaudeCCRAdapter(), "gemini": GeminiAdapter(), "codex": CodexAdapter(), "runtime-agents": RuntimeAgentsAdapter("~/.local/share/runtime-agents"), "opencode": OpencodeAdapter()}
        if args.runtime in adapters:
            events = adapters[args.runtime].normalize(50)
            if events:
                os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)
                with open(EVENTS_PATH, 'a', encoding='utf-8') as f:
                    for ev in events: f.write(json.dumps(ev) + "\n")
                print(f"Ingested {len(events)}")

    elif args.command == "skills":
        if args.skill_command == "lifecycle":
            reg_data = RegistryManager.load()
            if args.lifecycle_command == "init-all":
                for d in os.listdir(GLOBAL_SKILLS_PATH):
                    if os.path.isdir(os.path.join(GLOBAL_SKILLS_PATH, d)) and not d.startswith("."):
                        if d not in reg_data["skills"]: RegistryManager.set_state(d, "locked")
                print("Initialized.")
            elif args.lifecycle_command == "list":
                for sname, sdata in sorted(reg_data["skills"].items()): print(f"{sname:<30} {sdata['state']}")
            elif args.lifecycle_command == "verify":
                lock_file = os.path.join(GLOBAL_SKILLS_PATH, "skills.lock.json")
                lock_data = json.load(open(lock_file)); locked_skills = lock_data.get("skills", {})
                current_skills = [d for d in os.listdir(GLOBAL_SKILLS_PATH) if os.path.isdir(os.path.join(GLOBAL_SKILLS_PATH, d)) and not d.startswith(".")]
                errors = 0
                for s in current_skills:
                    sdata = reg_data["skills"].get(s)
                    if not sdata:
                        print(f"MISSING: {s}"); errors += 1
                    elif sdata["state"] == "locked" and s not in locked_skills:
                        print(f"NO LOCK: {s}"); errors += 1
                if errors == 0: print("Lifecycle OK.")
                else: sys.exit(1)
        elif args.skill_command == "lock":
            lock_file = os.path.join(GLOBAL_SKILLS_PATH, "skills.lock.json")
            lock_data = {"schema_version": "0.1", "skills": {}}
            for d in os.listdir(GLOBAL_SKILLS_PATH):
                if os.path.isdir(os.path.join(GLOBAL_SKILLS_PATH, d)) and not d.startswith("."):
                    h = get_skill_hash(os.path.join(GLOBAL_SKILLS_PATH, d))
                    if h: lock_data["skills"][d] = {"hash": h, "locked_at": datetime.now().isoformat() + "Z"}
            with open(lock_file, "w") as f:
                json.dump(lock_data, f, indent=2)
            print(f"Locked {len(lock_data['skills'])} skills.")
        elif args.skill_command == "verify":
            lock_file = os.path.join(GLOBAL_SKILLS_PATH, "skills.lock.json")
            lock_data = json.load(open(lock_file)); locked_skills = lock_data.get("skills", {})
            for d in os.listdir(GLOBAL_SKILLS_PATH):
                if os.path.isdir(os.path.join(GLOBAL_SKILLS_PATH, d)) and not d.startswith("."):
                    h = get_skill_hash(os.path.join(GLOBAL_SKILLS_PATH, d))
                    if d not in locked_skills or locked_skills[d]["hash"] != h: print(f"[!] {d} DRIFTED")
                    else: print(f"[+] {d} VERIFIED")

    elif args.command == "scheduler":
        if args.scheduler_command == "run-once":
            log_scheduler("--- Start ---")
            for rt in ["claude", "opencode", "runtime-agents", "codex", "gemini"]:
                log_scheduler(f"Ingesting {rt}...")
                subprocess.run(["python3", sys.argv[0], "ingest", "--runtime", rt], capture_output=True)
            log_scheduler("Schedule run...")
            subprocess.run(["python3", sys.argv[0], "schedule", "run", "--workspace", args.workspace or os.getcwd()])
            log_scheduler("--- End ---")

    elif args.command == "schedule":
        state_path, policy_path = SCHEDULER_STATE_PATH, "/home/zzs333/code/runtime-agents/self_improvement/policy/scheduling_policy.yaml"
        if not os.path.exists(policy_path): return
        policy = yaml.safe_load(open(policy_path)) if yaml else {}
        state = {"schema_version": "0.1", "last_scan_at": None, "last_skill_verify_hash": None}
        if os.path.exists(state_path): state.update(json.load(open(state_path)))
        scan_events, last_ts = [], None
        if os.path.exists(EVENTS_PATH):
            with open(EVENTS_PATH, "r") as f:
                for line in f:
                    try:
                        ev = json.loads(line); ts = ev.get("timestamp_start")
                        if ts:
                            last_ts = ts; is_hf = ev.get("tool_sequence") and ev.get("outcome")
                            if not state.get("last_scan_at") or ts > state["last_scan_at"]:
                                if is_hf: scan_events.append(ev)
                    except: continue
        skills_hash = get_dir_hash(GLOBAL_SKILLS_PATH)
        actions_due = []
        if len(scan_events) >= 20: actions_due.append({"action": "runtime-self-improve scan"})
        if skills_hash != state["last_skill_verify_hash"]: actions_due.append({"action": "skills verify"})
        if args.schedule_command == "run":
            if skills_hash: state["last_skill_verify_hash"] = skills_hash
            if any(a["action"] == "runtime-self-improve scan" for a in actions_due): state["last_scan_at"] = last_ts
            os.makedirs(os.path.dirname(state_path), exist_ok=True); json.dump(state, open(state_path, "w"), indent=2)

    elif args.command == "backup":
        bk_path = getattr(args, "path", "/mnt/r/LLMData/SkillsBackUp/")
        if args.backup_command == "status":
            print(f"# Backup Status\nNAS Path: {bk_path}")
            if os.path.exists(bk_path):
                snaps = glob.glob(os.path.join(bk_path, "snapshots", "*.tar.gz"))
                print(f"Snapshots: {len(snaps)}")
                if snaps: print(f"Latest: {max(snaps, key=os.path.getmtime)}")
            else: print("NAS path not found.")
        elif args.backup_command == "create":
            print(f"Creating NAS backup at {bk_path}...")
            os.makedirs(os.path.join(bk_path, "snapshots"), exist_ok=True); os.makedirs(os.path.join(bk_path, "latest"), exist_ok=True); os.makedirs(os.path.join(bk_path, "checksums"), exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S"); snap_file = os.path.join(bk_path, "snapshots", f"skillstore-{ts}.tar.gz")
            subprocess.run(["tar", "--exclude", ".git", "--exclude", "*.db", "--exclude", "*.sqlite", "--exclude", "*.log", "--exclude", "__pycache__", "-czf", snap_file, "skills"], cwd=os.path.dirname(GLOBAL_SKILLS_PATH), check=True)
            sha = hashlib.sha256(open(snap_file, "rb").read()).hexdigest()
            with open(os.path.join(bk_path, "checksums", f"skillstore-{ts}.sha256"), "w") as f: f.write(sha)
            subprocess.run(["rsync", "-rv", "--delete", "--no-perms", "--no-owner", "--no-group", "--no-t", "--omit-dir-times", "--exclude", ".git/", "--exclude", "*.db", "--exclude", "*.sqlite", "--exclude", "*.log", "--exclude", "__pycache__/", GLOBAL_SKILLS_PATH + "/", os.path.join(bk_path, "latest/skills/")], check=True)
            print(f"Backup complete: {snap_file}")
        elif args.backup_command == "verify":
            print(f"Verifying NAS backup at {bk_path}...")
            l_skills = os.path.join(bk_path, "latest/skills")
            if os.path.exists(l_skills): print(f"[+] Latest mirror found: {len(os.listdir(l_skills))} items.")
            snaps = sorted(glob.glob(os.path.join(bk_path, "snapshots", "*.tar.gz")))
            if snaps:
                latest_snap = snaps[-1]; ts = os.path.basename(latest_snap).split("-")[1].split(".")[0]
                c_file = os.path.join(bk_path, "checksums", f"skillstore-{ts}.sha256")
                if os.path.exists(c_file):
                    expected = open(c_file).read().strip(); actual = hashlib.sha256(open(latest_snap, "rb").read()).hexdigest()
                    if expected == actual: print(f"[+] Checksum verified: {os.path.basename(latest_snap)}")
                    else: print(f"[!] Checksum MISMATCH: {latest_snap}")

if __name__ == "__main__":
    main()
