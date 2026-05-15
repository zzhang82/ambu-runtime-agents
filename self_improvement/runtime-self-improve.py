import json
import os
import sys
import glob
import argparse
import hashlib
import subprocess
import sqlite3
import shutil
from datetime import datetime
from collections import Counter

try:
    import yaml
except ImportError:
    yaml = None

# --- CONSTANTS ---
GLOBAL_SKILLS_PATH = os.path.expanduser("~/.config/opencode/skills/")
STAGING_DIR = os.path.expanduser("~/.runtime-agents/staging/")
APPROVALS_DIR = os.path.expanduser("~/.runtime-agents/approvals/")
SCHEDULER_STATE_PATH = os.path.expanduser("~/.runtime-agents/scheduler/state.json")
EVENTS_PATH = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
REGISTRY_PATH = os.path.join(GLOBAL_SKILLS_PATH, "skills.registry.json")

# --- UTILS ---

def get_dir_hash(path):
    if not os.path.exists(path): return None
    hash_sha256 = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        for names in sorted(files):
            if names.startswith(".git") or names == "skills.lock.json" or names == "skills.registry.json": continue
            filepath = os.path.join(root, names)
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""): hash_sha256.update(chunk)
    return hash_sha256.hexdigest()

def get_files_hash(files, workspace):
    hash_sha256 = hashlib.sha256()
    found = False
    for f in sorted(files):
        p = os.path.join(workspace, f)
        if os.path.exists(p):
            found = True
            with open(p, "rb") as f_in:
                for chunk in iter(lambda: f_in.read(4096), b""): hash_sha256.update(chunk)
    return hash_sha256.hexdigest() if found else None

def get_skill_hash(skill_path):
    skill_md = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md): return None
    with open(skill_md, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

def record_audit(data, message):
    if "audit_log" not in data: data["audit_log"] = []
    data["audit_log"].append({"timestamp": datetime.now().isoformat() + "Z", "message": message})

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
            # Deep merge for usage/replacement/deprecation if provided
            for key in ["usage", "replacement", "deprecation"]:
                if key in metadata:
                    if key not in data["skills"][skill_name]: data["skills"][skill_name][key] = {}
                    data["skills"][skill_name][key].update(metadata[key])
            # Standard fields
            for key, val in metadata.items():
                if key not in ["usage", "replacement", "deprecation"]:
                    data["skills"][skill_name][key] = val
        
        if state in ["verified", "locked"]:
            data["skills"][skill_name]["last_verified_at"] = datetime.now().isoformat() + "Z"
        RegistryManager.save(data)

# --- ADAPTERS ---

class ClaudeCCRAdapter:
    def __init__(self, history_path, projects_base="~/.claude/projects"):
        self.history_path = os.path.expanduser(history_path)
        self.projects_base = os.path.expanduser(projects_base)
    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.history_path): return events
        with open(self.history_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    data = json.loads(line)
                    session_id, project_path = data.get("sessionId"), data.get("project", "")
                    proj_dir_name = project_path.replace("/", "-")
                    session_file = os.path.join(self.projects_base, proj_dir_name, f"{session_id}.jsonl")
                    tools_used = []
                    if os.path.exists(session_file):
                        with open(session_file, 'r', encoding='utf-8') as sf:
                            for sline in sf:
                                try:
                                    sdata = json.loads(sline)
                                    if sdata.get("type") == "assistant":
                                        for item in sdata.get("message", {}).get("content", []):
                                            if isinstance(item, dict) and item.get("type") == "tool_use": tools_used.append(item.get("name"))
                                except Exception: continue
                    ts = data.get('timestamp')
                    ts_iso = datetime.fromtimestamp(ts/1000).isoformat() + "Z" if ts else None
                    events.append({
                        "schema_version": "0.1", "runtime": "claude", "session_id": session_id,
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
                if f.startswith("session-") and f.endswith(".json"): files.append(os.path.join(root, f))
        files.sort(key=os.path.getmtime, reverse=True)
        for file_path in files[:limit]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
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
                            if name not in event_data["tools_used"]: event_data["tools_used"].append(name)
                            event_data["tool_sequence"].append(name)
                            args = tc.get("args", {})
                            if name in ["execute_command", "bash"]:
                                cmd = args.get("command") or args.get("cmd")
                                if cmd: event_data["commands_run"].append(cmd)
                            elif name in ["write_file", "edit_file", "apply_patch"]:
                                path = args.get("file_path") or args.get("path")
                                if path: event_data["files_touched"].append(path)
                            elif "memory" in name.lower() or "recall" in name.lower():
                                event_data["memory_operations"].append({"type": name, "timestamp": tc.get("timestamp")})
                if event_data.get("session_id"): events.append(event_data)
            except Exception: continue
        return events

class CodexAdapter:
    def __init__(self, sessions_base="~/.codex/sessions"):
        self.sessions_base = os.path.expanduser(sessions_base)
    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.sessions_base): return events
        files = []
        for root, _, filenames in os.walk(self.sessions_base):
            for f in filenames:
                if f.startswith("rollout-") and f.endswith(".jsonl"): files.append(os.path.join(root, f))
        files.sort(key=os.path.getmtime, reverse=True)
        for file_path in files[:limit]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f: lines = f.readlines()
                event_data = {
                    "schema_version": "0.1", "runtime": "codex", "tools_used": [], "tool_sequence": [],
                    "commands_run": [], "files_touched": [], "memory_operations": [], "outcome": "completed"
                }
                for line in lines:
                    try:
                        data = json.loads(line)
                        ev_type, payload = data.get("type"), data.get("payload", {})
                        if ev_type == "session_meta":
                            event_data["session_id"] = payload.get("id"); event_data["run_id"] = payload.get("id")
                            event_data["timestamp_start"] = payload.get("timestamp"); event_data["workspace"] = payload.get("cwd")
                            instr = payload.get("base_instructions", {}).get("text", "")
                            if "Task:\n" in instr: event_data["user_goal"] = instr.split("Task:\n")[-1].strip()
                        elif ev_type == "response_item":
                            ptype = payload.get("type")
                            if ptype == "message" and payload.get("role") == "user":
                                for c in payload.get("content", []):
                                    if isinstance(c, dict) and c.get("type") == "input_text": event_data["user_goal"] = c.get("text").strip()
                                    elif isinstance(c, str): event_data["user_goal"] = c.strip()
                            elif ptype == "function_call":
                                name = payload.get("name")
                                if name:
                                    if name not in event_data["tools_used"]: event_data["tools_used"].append(name)
                                    event_data["tool_sequence"].append(name)
                                    if name == "exec_command":
                                        args = payload.get("arguments", "{}")
                                        if isinstance(args, str):
                                            try: args = json.loads(args)
                                            except: pass
                                        cmd = args.get("cmd")
                                        if cmd: event_data["commands_run"].append(cmd)
                                    if "memory" in name.lower() or "recall" in name.lower():
                                        event_data["memory_operations"].append({"type": name, "timestamp": data.get("timestamp")})
                        elif ev_type == "task_complete":
                            event_data["timestamp_end"] = datetime.fromtimestamp(payload.get("completed_at", 0)).isoformat() + "Z"
                    except: continue
                if "session_id" in event_data: events.append(event_data)
            except Exception: continue
        return events

class RuntimeAgentsAdapter:
    def __init__(self, base_path):
        self.base_path = os.path.expanduser(base_path)
    def normalize(self, limit=50):
        events = []
        runs_path = os.path.join(self.base_path, "runs")
        if not os.path.exists(runs_path): return events
        run_dirs = sorted([d for d in glob.glob(os.path.join(runs_path, "*")) if os.path.isdir(d)], reverse=True)
        for run_dir in run_dirs[:limit]:
            meta_path, goal_path = os.path.join(run_dir, "metadata.json"), os.path.join(run_dir, "goal.txt")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f: meta = json.load(f)
                    goal = ""
                    if os.path.exists(goal_path):
                        with open(goal_path, 'r', encoding='utf-8') as f: goal = f.read().strip()
                    event = {
                        "schema_version": "0.1", "runtime": "runtime-agents", "session_id": meta.get("task_id"),
                        "run_id": meta.get("task_id"), "timestamp_start": meta.get("started_at"),
                        "timestamp_end": meta.get("ended_at"), "workspace": meta.get("cwd"),
                        "user_goal": goal, "outcome": meta.get("status"), "agent": meta.get("agent"),
                        "model": meta.get("model"), "summary": f"Imported from runtime-agents run {meta.get('task_id')}"
                    }
                    res_path = os.path.join(run_dir, "result.json")
                    if os.path.exists(res_path):
                        with open(res_path, 'r', encoding='utf-8') as f: res = json.load(f)
                        event["result_summary"] = res.get("message")
                        if "approval_capabilities" in res: event["capabilities_requested"] = res["approval_capabilities"]
                    events.append(event)
                except Exception: continue
        return events

class OpencodeAdapter:
    def __init__(self, db_path="~/.local/share/opencode/opencode.db"):
        self.db_path = os.path.expanduser(db_path)
    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.db_path): return events
        try:
            conn = sqlite3.connect(self.db_path); cursor = conn.cursor()
            cursor.execute("SELECT id, title, path, model, time_created, time_updated FROM session ORDER BY time_created DESC LIMIT ?", (limit,))
            for sess in cursor.fetchall():
                sid, title, workspace, model_json, start_ts, end_ts = sess
                cursor.execute("SELECT data FROM part WHERE session_id = ? ORDER BY time_created", (sid,))
                parts = cursor.fetchall(); tools_used, tool_sequence, commands_run, files_touched, memory_ops = [], [], [], [], []
                for p in parts:
                    try:
                        pdata = json.loads(p[0])
                        if pdata.get("type") == "tool":
                            tool = pdata.get("tool")
                            if tool:
                                if tool not in tools_used: tools_used.append(tool)
                                tool_sequence.append(tool)
                                input_data = pdata.get("state", {}).get("input", {})
                                if tool == "bash":
                                    cmd = input_data.get("command")
                                    if cmd: commands_run.append(cmd)
                                elif tool in ["write", "edit"]:
                                    path = input_data.get("filePath") or input_data.get("file_path")
                                    if path: files_touched.append(path)
                                elif tool == "agentMemoryBridge":
                                    memory_ops.append({"type": "recall" if "recall" in pdata.get("title", "").lower() else "operation", "timestamp": datetime.fromtimestamp(pdata.get("time", {}).get("start", 0)/1000).isoformat() + "Z"})
                    except Exception: continue
                events.append({
                    "schema_version": "0.1", "runtime": "opencode", "session_id": sid, "run_id": sid,
                    "timestamp_start": datetime.fromtimestamp(start_ts/1000).isoformat() + "Z",
                    "timestamp_end": datetime.fromtimestamp(end_ts/1000).isoformat() + "Z",
                    "workspace": workspace, "user_goal": title, "outcome": "completed",
                    "tools_used": sorted(list(set(tools_used))), "tool_sequence": tool_sequence,
                    "commands_run": commands_run, "files_touched": sorted(list(set(files_touched))),
                    "memory_operations": memory_ops, "summary": f"Imported from opencode DB session {sid}"
                })
            conn.close()
        except Exception as e: print(f"Error: {e}")
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
        return True, f"Forged skill {target} in staging: {skill_dir}"
    @staticmethod
    def deploy_skill(approval, staging_dir, global_store):
        target = approval["action"]["target"]
        src, dst = os.path.join(staging_dir, target), os.path.join(global_store, target)
        if not os.path.exists(src): return False, f"Source {src} not found in staging."
        if os.path.exists(dst): shutil.rmtree(dst)
        shutil.copytree(src, dst)
        RegistryManager.set_state(target, "deployed")
        subprocess.run(["python3", sys.argv[0], "skills", "verify", "--all"], check=True)
        RegistryManager.set_state(target, "verified")
        return True, f"Deployed skill {target} to {dst}"
    @staticmethod
    def update_skills_lock(approval, global_store):
        subprocess.run(["python3", sys.argv[0], "skills", "lock", "--path", global_store], check=True)
        reg = RegistryManager.load()
        for sname, sdata in reg["skills"].items():
            if sdata["state"] == "verified":
                RegistryManager.set_state(sname, "locked")
        return True, "Updated skills.lock.json and promoted verified skills to locked"

    @staticmethod
    def deprecate_skill(approval):
        target = approval["action"]["target"]
        RegistryManager.set_state(target, "deprecated", {
            "deprecation": {
                "status": "deprecated",
                "deprecated_at": datetime.now().isoformat() + "Z",
                "approval_id": approval["approval_id"]
            }
        })
        return True, f"Set {target} to deprecated state in registry"

class RollbackHandlers:
    @staticmethod
    def rollback_skill_deploy(approval, global_store):
        target = approval["action"]["target"]
        target_path = os.path.join(global_store, target)
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
            RegistryManager.set_state(target, "rolled_back")
            return True, f"Removed deployed skill {target}"
        return False, f"Skill {target} not found"
    @staticmethod
    def rollback_skills_lock(approval, global_store):
        subprocess.run(["git", "checkout", "skills.lock.json"], cwd=global_store, check=True)
        return True, "Reverted lockfile"
    @staticmethod
    def store_amb_recovery_gotcha(approval):
        return True, "AMB recovery record created"

# --- MAIN ---

def main():
    parser = argparse.ArgumentParser(description="Runtime Self-Improvement CLI")
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--runtime", choices=["claude", "opencode", "runtime-agents", "codex", "gemini"], required=True)
    ingest_parser.add_argument("--recent", type=int, default=50)

    subparsers.add_parser("scan")
    subparsers.add_parser("suggest")

    skills_p = subparsers.add_parser("skills")
    skills_sub = skills_p.add_subparsers(dest="skill_command")
    skills_sub.add_parser("status")
    skills_sub.add_parser("lock").add_argument("--path")
    skills_v = skills_sub.add_parser("verify")
    skills_v.add_argument("--all", action="store_true"); skills_v.add_argument("--path")

    # Lifecycle commands (Milestone 2K)
    lifecycle_p = skills_sub.add_parser("lifecycle")
    lifecycle_sub = lifecycle_p.add_subparsers(dest="lifecycle_command")
    lifecycle_sub.add_parser("list")
    lifecycle_show = lifecycle_sub.add_parser("show"); lifecycle_show.add_argument("skill")
    lifecycle_set = lifecycle_sub.add_parser("set-state"); lifecycle_set.add_argument("skill"); lifecycle_set.add_argument("state")
    lifecycle_dep = lifecycle_sub.add_parser("deprecate"); lifecycle_dep.add_argument("skill")
    lifecycle_arc = lifecycle_sub.add_parser("archive"); lifecycle_arc.add_argument("skill")
    lifecycle_sub.add_parser("verify")
    lifecycle_sub.add_parser("init-all")

    # Deprecation commands (Milestone 2M)
    deprecation_p = skills_sub.add_parser("deprecation")
    deprecation_sub = deprecation_p.add_subparsers(dest="deprecation_command")
    deprecation_sub.add_parser("scan")
    deprecation_sub.add_parser("recommend")
    dep_plan = deprecation_sub.add_parser("plan"); dep_plan.add_argument("skill")
    
    archive_p = skills_sub.add_parser("archive")
    archive_sub = archive_p.add_subparsers(dest="archive_command")
    arc_plan = archive_sub.add_parser("plan"); arc_plan.add_argument("skill")

    # Eval commands (Milestone 2L)
    eval_p = skills_sub.add_parser("eval")
    eval_sub = eval_p.add_subparsers(dest="eval_command")
    eval_sub.add_parser("list")
    eval_run = eval_sub.add_parser("run"); eval_run.add_argument("skill", nargs="?", help="Skill to evaluate or --core")
    eval_run.add_argument("--core", action="store_true", help="Run evals for all core skills")
    eval_sub.add_parser("report")

    hooks_p = subparsers.add_parser("hooks")
    hooks_s = hooks_p.add_subparsers(dest="hook_command")
    hooks_s.add_parser("post-run").add_argument("--goal", required=True)
    hooks_s.add_parser("session-start").add_argument("--workspace")

    recommend_p = subparsers.add_parser("recommend")
    recommend_p.add_argument("--workspace", default=os.getcwd()); recommend_p.add_argument("--runtime", default="opencode")
    recommend_p.add_argument("--goal"); recommend_p.add_argument("--recent", type=int)

    events_p = subparsers.add_parser("events")
    events_s = events_p.add_subparsers(dest="event_command")
    events_v = events_s.add_parser("validate")
    events_v.add_argument("--recent", type=int, default=20); events_v.add_argument("--runtime")

    schedule_p = subparsers.add_parser("schedule")
    schedule_s = schedule_p.add_subparsers(dest="schedule_command")
    schedule_s.add_parser("check").add_argument("--workspace", default=os.getcwd())
    schedule_r = schedule_s.add_parser("run"); schedule_r.add_argument("--workspace", default=os.getcwd()); schedule_r.add_argument("--dry-run", action="store_true")

    approvals_p = subparsers.add_parser("approvals")
    approvals_s = approvals_p.add_subparsers(dest="approval_command")
    approvals_s.add_parser("list")
    approvals_s.add_parser("show").add_argument("approval_id")
    approvals_s.add_parser("approve").add_argument("approval_id")
    approvals_s.add_parser("reject").add_argument("approval_id")
    approvals_s.add_parser("apply").add_argument("approval_id")
    approvals_t = approvals_s.add_parser("create-test"); approvals_t.add_argument("--action", default="forge_skill"); approvals_t.add_argument("--target", default="test-skill")

    rollback_p = subparsers.add_parser("rollback")
    rollback_s = rollback_p.add_subparsers(dest="rollback_command")
    rollback_s.add_parser("list")
    rollback_s.add_parser("plan").add_argument("approval_id")
    rollback_s.add_parser("apply").add_argument("approval_id")

    args = parser.parse_args()

    if args.command == "skills":
        if args.skill_command == "lifecycle":
            reg_data = RegistryManager.load()
            if args.lifecycle_command == "init-all":
                current_skills = [d for d in os.listdir(GLOBAL_SKILLS_PATH) if os.path.isdir(os.path.join(GLOBAL_SKILLS_PATH, d)) and not d.startswith(".")]
                for s in current_skills:
                    if s not in reg_data["skills"]: RegistryManager.set_state(s, "locked")
                print(f"Initialized registry for {len(current_skills)} skills.")
            elif args.lifecycle_command == "list":
                print(f"{'Skill':<30} {'State':<15} {'Last Verified'}")
                print("-" * 80)
                for sname, sdata in sorted(reg_data["skills"].items()):
                    print(f"{sname:<30} {sdata['state']:<15} {sdata.get('last_verified_at', 'never')}")
            elif args.lifecycle_command == "show":
                s = reg_data["skills"].get(args.skill)
                if s: print(json.dumps(s, indent=2))
                else: print("Skill not found.")
            elif args.lifecycle_command == "set-state":
                RegistryManager.set_state(args.skill, args.state)
                print(f"Set {args.skill} to {args.state}.")
            elif args.lifecycle_command == "verify":
                lock_file = os.path.join(GLOBAL_SKILLS_PATH, "skills.lock.json")
                with open(lock_file, "r") as f: lock_data = json.load(f); locked_skills = lock_data.get("skills", {})
                current_skills = [d for d in os.listdir(GLOBAL_SKILLS_PATH) if os.path.isdir(os.path.join(GLOBAL_SKILLS_PATH, d)) and not d.startswith(".")]
                print("Verifying Skill Lifecycle Consistency...")
                errors = 0
                for s in current_skills:
                    sdata = reg_data["skills"].get(s)
                    if not sdata: print(f"[!] {s:<30} MISSING from registry"); errors += 1
                    elif sdata["state"] == "locked" and s not in locked_skills: print(f"[!] {s:<30} Marked LOCKED but not in lockfile"); errors += 1
                    else: print(f"[+] {s:<30} OK ({sdata.get('state')})")
                if errors == 0: print("\nLifecycle verification PASSED.")
                else: print(f"\nLifecycle verification FAILED with {errors} issues."); sys.exit(1)
        elif args.skill_command == "deprecation":
            reg_data = RegistryManager.load()
            if args.deprecation_command == "scan":
                print("Scanning skill usage from events...")
                usage_counts = Counter()
                last_seen = {}
                if os.path.exists(EVENTS_PATH):
                    with open(EVENTS_PATH, "r") as f:
                        for line in f:
                            try:
                                ev = json.loads(line)
                                ts = ev.get("timestamp_start")
                                for s in ev.get("skills_invoked", []):
                                    usage_counts[s] += 1
                                    if s not in last_seen or ts > last_seen[s]: last_seen[s] = ts
                            except: continue
                
                for sname in reg_data["skills"]:
                    RegistryManager.set_state(sname, reg_data["skills"][sname]["state"], {
                        "usage": {
                            "invocation_count_30d": usage_counts[sname],
                            "last_seen_at": last_seen.get(sname)
                        }
                    })
                print(f"Usage scan complete. Updated registry.")

            elif args.deprecation_command == "recommend":
                print("# Skill Deprecation Recommendations\n")
                candidates = []
                for sname, sdata in reg_data["skills"].items():
                    reasons = []
                    usage = sdata.get("usage", {})
                    # Criteria 1: Zero usage for Watched skills
                    if sdata["state"] == "watched" and usage.get("invocation_count_30d", 0) == 0:
                        reasons.append("Zero usage in current event window (watched state)")
                    
                    # Criteria 2: Test fixtures (placeholder logic)
                    if "test" in sname.lower():
                        reasons.append("Identified as likely test fixture")

                    if reasons:
                        candidates.append({"skill": sname, "reasons": reasons, "state": sdata["state"]})

                if not candidates:
                    print("No deprecation candidates identified.")
                else:
                    for c in candidates:
                        print(f"## {c['skill']} [{c['state']}]")
                        for r in c["reasons"]: print(f"  - {r}")
                        print(f"  Recommendation: `skills deprecation plan {c['skill']}`\n")

            elif args.deprecation_command == "plan":
                sname = args.skill
                if sname not in reg_data["skills"]: print("Skill not found."); return
                aid = f"appr_dep_{sname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                plan = {
                    "schema_version": "0.1", "approval_id": aid, "created_at": datetime.now().isoformat() + "Z",
                    "status": "pending", "action": {"type": "deprecate_skill", "target": sname, "mutation_level": "high"},
                    "why": {"pattern": "Unused or redundant", "confidence": "medium"},
                    "proposed_changes": [f"Set {sname} state to deprecated", "Add deprecation warning to SKILL.md"],
                    "safety_checks_required": ["skills lifecycle verify"], "audit_log": []
                }
                os.makedirs(APPROVALS_DIR, exist_ok=True)
                with open(os.path.join(APPROVALS_DIR, f"{aid}.json"), "w") as f: json.dump(plan, f, indent=2)
                print(f"Deprecation plan created: {aid}")

        elif args.skill_command == "archive":
            if args.archive_command == "plan":
                sname = args.skill
                aid = f"appr_arc_{sname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                plan = {
                    "schema_version": "0.1", "approval_id": aid, "status": "pending",
                    "action": {"type": "archive_skill", "target": sname, "mutation_level": "critical"},
                    "proposed_changes": [f"Move {sname} to archive/", f"Remove {sname} from global store"],
                    "safety_checks_required": ["git status", "skills lifecycle verify"], "audit_log": []
                }
                with open(os.path.join(APPROVALS_DIR, f"{aid}.json"), "w") as f: json.dump(plan, f, indent=2)
                print(f"Archive plan created: {aid}")
        
        elif args.skill_command == "eval":

            evals_file = os.path.join(GLOBAL_SKILLS_PATH, "skills.evals.json")
            if not os.path.exists(evals_file): print("No evals file found."); return
            with open(evals_file, "r") as f: evals_data = json.load(f)
            
            skills_to_eval = []
            if args.core:
                skills_to_eval = ["ljg-skill-mentor", "repo-workflow-cartographer", "ljg-style-skill-sculptor", "skill-deployment-verifier", "version-sync-sculptor", "session-bridge-assembler", "repo-architecture-sensor", "agent-hygiene-auditor"]
            elif args.skill:
                skills_to_eval = [args.skill]
            
            if args.eval_command == "list":
                print(f"{'Skill':<30} {'Test Cases'}")
                print("-" * 50)
                for s, d in sorted(evals_data["skills"].items()):
                    print(f"{s:<30} {len(d['cases'])}")
            
            elif args.eval_command == "run":
                report = []
                # Header mapping for flexibility
                header_variants = {
                    "One Cut": ["One Cut", "一刀", "核心动作"],
                    "Redlines": ["Redlines", "红线", "红线管理"],
                    "Output Mold": ["Output Mold", "输出模具", "输出形态", "模具"]
                }
                
                for sname in skills_to_eval:
                    skill_path = os.path.join(GLOBAL_SKILLS_PATH, sname)
                    skill_md = os.path.join(skill_path, "SKILL.md")
                    cases = evals_data["skills"].get(sname, {}).get("cases", [])
                    
                    if not os.path.exists(skill_md):
                        print(f"[!] {sname:<30} SKILL.md missing. Skipping.")
                        continue
                    
                    with open(skill_md, "r") as f: content = f.read()
                    
                    skill_results = {"skill": sname, "cases": []}
                    for case in cases:
                        case_result = {"name": case["name"], "status": "PASS", "details": []}
                        checks = case.get("checks", {})
                        
                        # Section checks with variants
                        for section in checks.get("must_include_sections", []):
                            variants = header_variants.get(section, [section])
                            found_section = False
                            for v in variants:
                                if f"# {v}" in content or f"## {v}" in content:
                                    found_section = True; break
                            if not found_section:
                                case_result["status"] = "FAIL"
                                case_result["details"].append(f"Missing section: {section}")
                        
                        # String checks
                        for string in checks.get("must_include_strings", []):
                            if string not in content:
                                case_result["status"] = "FAIL"
                                case_result["details"].append(f"Missing string: {string}")
                        
                        # Redline compliance (heuristic)
                        redlines_variant = header_variants["Redlines"]
                        redlines_content = ""
                        for rv in redlines_variant:
                            if f"## {rv}" in content:
                                redlines_content = content.split(f"## {rv}")[1].split("##")[0]
                                break
                            elif f"# {rv}" in content:
                                redlines_content = content.split(f"# {rv}")[1].split("#")[0]
                                break
                        
                        for rule in checks.get("redline_compliance", []):
                            if rule not in redlines_content.lower() and rule not in content.lower():
                                case_result["status"] = "WARN"
                                case_result["details"].append(f"Redline might be missing: {rule}")

                        skill_results["cases"].append(case_result)
                    report.append(skill_results)
                
                # Output Report
                print("# Skill Quality Evaluation Report\n")
                for sres in report:
                    overall = "PASS" if all(c["status"] == "PASS" for c in sres["cases"]) else "FAIL"
                    if overall == "PASS" and any(c["status"] == "WARN" for c in sres["cases"]): overall = "WARN"
                    
                    print(f"## {sres['skill']} - [{overall}]")
                    for c in sres["cases"]:
                        print(f"  - Case: {c['name']} [{c['status']}]")
                        for d in c["details"]:
                            print(f"    - {d}")
                    print()
        else:
            skills_path = os.path.expanduser(args.path or GLOBAL_SKILLS_PATH); lock_file = os.path.join(skills_path, "skills.lock.json")
            if args.skill_command == "lock":
                skills = {}
                for d in os.listdir(skills_path):
                    p = os.path.join(skills_path, d)
                    if os.path.isdir(p) and not d.startswith("."):
                        h = get_skill_hash(p); 
                        if h: skills[d] = {"hash": h, "last_locked": datetime.now().isoformat()}
                with open(lock_file, "w") as f: json.dump({"schema_version": "0.1", "skills": skills}, f, indent=2)
                print("Locked.")
            elif args.skill_command == "verify":
                if not os.path.exists(lock_file): return
                with open(lock_file, "r") as f: lock_data = json.load(f); locked_skills = lock_data.get("skills", {})
                current_skills = [d for d in os.listdir(skills_path) if os.path.isdir(os.path.join(skills_path, d)) and not d.startswith(".")]
                errors = 0
                for s in current_skills:
                    p = os.path.join(skills_path, s); h = get_skill_hash(p)
                    if s not in locked_skills or locked_skills[s]["hash"] != h: print(f"[!] {s} DRIFTED"); errors += 1
                    else: print(f"[+] {s} VERIFIED")
                if errors > 0: sys.exit(1)

    elif args.command == "approvals":
        os.makedirs(STAGING_DIR, exist_ok=True); os.makedirs(APPROVALS_DIR, exist_ok=True)
        if args.approval_command == "create-test":
            aid = f"appr_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            data = {"schema_version": "0.1", "approval_id": aid, "created_at": datetime.now().isoformat() + "Z", "status": "pending", "action": {"type": args.action, "target": args.target, "mutation_level": "high"}, "why": {"pattern": "Test", "confidence": "high"}, "proposed_changes": [], "safety_checks_required": [], "audit_log": []}
            with open(os.path.join(APPROVALS_DIR, f"{aid}.json"), "w") as f: json.dump(data, f, indent=2)
            print(f"Created test approval: {aid}")
        elif args.approval_command == "list":
            for f in sorted(glob.glob(os.path.join(APPROVALS_DIR, "appr_*.json")), reverse=True):
                with open(f, "r") as fin: d = json.load(fin); print(f"{d['approval_id']:<25} {d['status']:<15} {d['action']['type']:<20} {d['created_at']}")
        elif args.approval_command == "show":
            f = os.path.join(APPROVALS_DIR, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                print(f"# Approval Packet: {data['action']['type']}\nID: {data['approval_id']}\nStatus: {data['status']}")
                print(f"Mutation Level: {data['action']['mutation_level']}")
                print(f"Why: {data['why'].get('pattern', 'N/A')} (confidence: {data['why'].get('confidence', 'N/A')})")
                print("\nProposed Changes:")
                for c in data.get('proposed_changes', []): print(f"- {c}")
                print("\nSafety Checks:")
                for s in data.get('safety_checks_required', []): print(f"- {s}")
                print("\nAudit Log:")
                for entry in data.get('audit_log', []): print(f"[{entry['timestamp']}] {entry['message']}")
            else: print("Approval not found.")
        elif args.approval_command in ["approve", "reject"]:
            f = os.path.join(APPROVALS_DIR, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                data["status"] = "approved" if args.approval_command == "approve" else "rejected"
                record_audit(data, f"Status: {data['status']}"); 
                with open(f, "w") as fout: json.dump(data, fout, indent=2)
                print(f"Approval {args.approval_id} {data['status']}.")
        elif args.approval_command == "apply":
            f = os.path.join(APPROVALS_DIR, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                if data["status"] != "approved": print(f"Not approved."); return
                data["status"] = "applying"; record_audit(data, "Applying"); atype = data["action"]["type"]
                try:
                    if atype == "forge_skill": success, msg = ApplyHandlers.forge_skill(data, STAGING_DIR)
                    elif atype == "deploy_skill": success, msg = ApplyHandlers.deploy_skill(data, STAGING_DIR, GLOBAL_SKILLS_PATH)
                    elif atype == "update_skills_lock": success, msg = ApplyHandlers.update_skills_lock(data, GLOBAL_SKILLS_PATH)
                    elif atype == "deprecate_skill": success, msg = ApplyHandlers.deprecate_skill(data)
                    else: success, msg = False, "Unknown"
                except Exception as e: success, msg = False, str(e)
                data["status"] = "verified" if success else "failed_verification"
                print(msg); record_audit(data, msg); 
                with open(f, "w") as fout: json.dump(data, fout, indent=2)

    elif args.command == "rollback":
        if args.rollback_command == "list":
            for f in sorted(glob.glob(os.path.join(APPROVALS_DIR, "appr_*.json")), reverse=True):
                with open(f, "r") as fin: d = json.load(fin)
                if d["status"] in ["failed_verification", "rollback_planned"]: print(f"{d['approval_id']:<25} {d['status']:<20} {d['action']['type']}")
        elif args.rollback_command == "plan":
            f = os.path.join(APPROVALS_DIR, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                data["status"] = "rollback_planned"; record_audit(data, "Rollback planned")
                with open(f, "w") as fout: json.dump(data, fout, indent=2)
                print(f"Rollback planned for {args.approval_id}")
        elif args.rollback_command == "apply":
            f = os.path.join(APPROVALS_DIR, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                if data["status"] != "rollback_planned": print("Plan first."); return
                data["status"] = "rollback_applying"; atype = data["action"]["type"]
                try:
                    if atype == "deploy_skill": success, msg = RollbackHandlers.rollback_skill_deploy(data, GLOBAL_SKILLS_PATH)
                    elif atype == "update_skills_lock": success, msg = RollbackHandlers.rollback_skills_lock(data, GLOBAL_SKILLS_PATH)
                    else: success, msg = False, "Err"
                    RollbackHandlers.store_amb_recovery_gotcha(data)
                except Exception as e: success, msg = False, str(e)
                data["status"] = "rolled_back" if success else "rollback_failed"
                print(msg); record_audit(data, msg); 
                with open(f, "w") as fout: json.dump(data, fout, indent=2)

if __name__ == "__main__":
    main()
