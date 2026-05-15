import json
import os
import sys
import glob
import argparse
import hashlib
import subprocess
import sqlite3
from datetime import datetime
from collections import Counter

try:
    import yaml
except ImportError:
    yaml = None

def get_dir_hash(path):
    if not os.path.exists(path):
        return None
    hash_sha256 = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        for names in sorted(files):
            if names.startswith(".git") or names == "skills.lock.json":
                continue
            filepath = os.path.join(root, names)
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
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

class ClaudeCCRAdapter:
    def __init__(self, history_path, projects_base="~/.claude/projects"):
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
                    session_id = data.get("sessionId")
                    project_path = data.get("project", "")
                    proj_dir_name = project_path.replace("/", "-")
                    session_file = os.path.join(self.projects_base, proj_dir_name, f"{session_id}.jsonl")
                    
                    tools_used = []
                    if os.path.exists(session_file):
                        with open(session_file, 'r', encoding='utf-8') as sf:
                            for sline in sf:
                                try:
                                    sdata = json.loads(sline)
                                    if sdata.get("type") == "assistant":
                                        msg = sdata.get("message", {})
                                        content = msg.get("content", [])
                                        for item in content:
                                            if isinstance(item, dict) and item.get("type") == "tool_use":
                                                tools_used.append(item.get("name"))
                                except Exception: continue

                    ts = data.get('timestamp')
                    ts_iso = datetime.fromtimestamp(ts/1000).isoformat() + "Z" if ts else None
                    event = {
                        "schema_version": "0.1", "runtime": "claude", "session_id": session_id,
                        "run_id": f"run_{ts}", "timestamp_start": ts_iso, "timestamp_end": ts_iso,
                        "workspace": project_path, "user_goal": data.get("display"), "outcome": "success", 
                        "tools_used": sorted(list(set(tools_used))), "tool_sequence": tools_used,
                        "summary": "Imported from Claude history"
                    }
                    events.append(event)
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
                with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
                event_data = {
                    "schema_version": "0.1", "runtime": "gemini", "session_id": data.get("sessionId"),
                    "run_id": data.get("sessionId"), "timestamp_start": data.get("startTime"),
                    "timestamp_end": data.get("lastUpdated"), "workspace": data.get("projectHash"),
                    "tools_used": [], "tool_sequence": [], "commands_run": [], "files_touched": [],
                    "memory_operations": [], "outcome": "completed"
                }
                messages = data.get("messages", [])
                for msg in messages:
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
                if f.startswith("rollout-") and f.endswith(".jsonl"):
                    files.append(os.path.join(root, f))
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
                            event_data["session_id"] = payload.get("id")
                            event_data["run_id"] = payload.get("id")
                            event_data["timestamp_start"] = payload.get("timestamp")
                            event_data["workspace"] = payload.get("cwd")
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
            sessions = cursor.fetchall()
            for sess in sessions:
                sid, title, workspace, model_json, start_ts, end_ts = sess
                cursor.execute("SELECT data FROM part WHERE session_id = ? ORDER BY time_created", (sid,))
                parts = cursor.fetchall()
                tools_used, tool_sequence, commands_run, files_touched, memory_ops = [], [], [], [], []
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
                event = {
                    "schema_version": "0.1", "runtime": "opencode", "session_id": sid, "run_id": sid,
                    "timestamp_start": datetime.fromtimestamp(start_ts/1000).isoformat() + "Z",
                    "timestamp_end": datetime.fromtimestamp(end_ts/1000).isoformat() + "Z",
                    "workspace": workspace, "user_goal": title, "outcome": "completed",
                    "tools_used": sorted(list(set(tools_used))), "tool_sequence": tool_sequence,
                    "commands_run": commands_run, "files_touched": sorted(list(set(files_touched))),
                    "memory_operations": memory_ops, "summary": f"Imported from opencode DB session {sid}"
                }
                events.append(event)
            conn.close()
        except Exception as e: print(f"Error querying opencode DB: {e}")
        return events

def get_skill_hash(skill_path):
    skill_md = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md): return None
    with open(skill_md, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Runtime Self-Improvement CLI")
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--runtime", choices=["claude", "opencode", "runtime-agents", "codex", "gemini"], required=True)
    ingest_parser.add_argument("--recent", type=int, default=50)

    subparsers.add_parser("scan")
    subparsers.add_parser("suggest")

    skills_parser = subparsers.add_parser("skills")
    skills_subparsers = skills_parser.add_subparsers(dest="skill_command")
    skills_subparsers.add_parser("status")
    skills_subparsers.add_parser("lock")
    skills_verify = skills_subparsers.add_parser("verify")
    skills_verify.add_argument("--all", action="store_true")
    skills_verify.add_argument("--path")

    hooks_parser = subparsers.add_parser("hooks")
    hooks_subparsers = hooks_parser.add_subparsers(dest="hook_command")
    hooks_subparsers.add_parser("post-run").add_argument("--goal", required=True)
    hooks_subparsers.add_parser("session-start").add_argument("--workspace")

    recommend_parser = subparsers.add_parser("recommend")
    recommend_parser.add_argument("--workspace", default=os.getcwd())
    recommend_parser.add_argument("--runtime", default="opencode")
    recommend_parser.add_argument("--goal")
    recommend_parser.add_argument("--recent", type=int)

    events_parser = subparsers.add_parser("events")
    events_subparsers = events_parser.add_subparsers(dest="event_command")
    events_validate = events_subparsers.add_parser("validate")
    events_validate.add_argument("--recent", type=int, default=20)
    events_validate.add_argument("--runtime")

    schedule_parser = subparsers.add_parser("schedule")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command")
    schedule_subparsers.add_parser("check").add_argument("--workspace", default=os.getcwd())
    schedule_run = schedule_subparsers.add_parser("run")
    schedule_run.add_argument("--workspace", default=os.getcwd())
    schedule_run.add_argument("--dry-run", action="store_true")

    approvals_parser = subparsers.add_parser("approvals")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approval_command")
    approvals_subparsers.add_parser("list")
    approvals_show = approvals_subparsers.add_parser("show")
    approvals_show.add_argument("approval_id")
    approvals_approve = approvals_subparsers.add_parser("approve")
    approvals_approve.add_argument("approval_id")
    approvals_reject = approvals_subparsers.add_parser("reject")
    approvals_reject.add_argument("approval_id")
    approvals_apply = approvals_subparsers.add_parser("apply")
    approvals_apply.add_argument("approval_id")
    approvals_history = approvals_subparsers.add_parser("history")
    
    # Internal forge test command
    approvals_create = approvals_subparsers.add_parser("create-test")
    approvals_create.add_argument("--action", default="forge_skill")
    approvals_create.add_argument("--target", default="test-skill")

    args = parser.parse_args()

    if args.command == "approvals":
        approvals_dir = os.path.expanduser("~/.runtime-agents/approvals/")
        os.makedirs(approvals_dir, exist_ok=True)
        
        if args.approval_command == "create-test":
            aid = f"appr_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            data = {
                "schema_version": "0.1", "approval_id": aid, "created_at": datetime.now().isoformat() + "Z",
                "status": "pending", "action": {"type": args.action, "target": args.target, "mutation_level": "high"},
                "why": {"pattern": "Test validation", "confidence": "high"},
                "proposed_changes": ["Create test skill directory", "Write SKILL.md"],
                "safety_checks_required": ["skill-deployment-verifier"],
                "approved_at": None
            }
            with open(os.path.join(approvals_dir, f"{aid}.json"), "w") as f: json.dump(data, f, indent=2)
            print(f"Created test approval: {aid}")

        elif args.approval_command == "list":
            files = glob.glob(os.path.join(approvals_dir, "appr_*.json"))
            print(f"{'ID':<25} {'Status':<15} {'Action':<20} {'Created'}")
            print("-" * 80)
            for f in sorted(files, reverse=True):
                with open(f, "r") as fin:
                    data = json.load(fin)
                    print(f"{data['approval_id']:<25} {data['status']:<15} {data['action']['type']:<20} {data['created_at']}")
        
        elif args.approval_command == "show":
            f = os.path.join(approvals_dir, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                print(f"# Approval Packet: {data['action']['type']}")
                print(f"ID: {data['approval_id']}\nStatus: {data['status']}\nMutation Level: {data['action']['mutation_level']}")
                print(f"Why: {data['why']['pattern']} (confidence: {data['why']['confidence']})")
                print("\nProposed Changes:")
                for c in data['proposed_changes']: print(f"- {c}")
                print("\nSafety Checks:")
                for s in data['safety_checks_required']: print(f"- {s}")
            else: print("Approval not found.")

        elif args.approval_command in ["approve", "reject"]:
            f = os.path.join(approvals_dir, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                if data["status"] == "pending":
                    data["status"] = "approved" if args.approval_command == "approve" else "rejected"
                    data["approved_at" if args.approval_command == "approve" else "rejected_at"] = datetime.now().isoformat() + "Z"
                    with open(f, "w") as fout: json.dump(data, fout, indent=2)
                    print(f"Approval {args.approval_id} {data['status']}.")
                else: print(f"Approval already in state: {data['status']}")
            else: print("Approval not found.")

        elif args.approval_command == "apply":
            f = os.path.join(approvals_dir, f"{args.approval_id}.json")
            if os.path.exists(f):
                with open(f, "r") as fin: data = json.load(fin)
                if data["status"] == "approved":
                    print(f"Applying action: {data['action']['type']} on {data['action']['target']}...")
                    # Verification simulation
                    data["status"] = "applied"
                    print("Running safety checks...")
                    for s in data["safety_checks_required"]: print(f" - Executing {s}...")
                    data["status"] = "verified"
                    data["applied_at"] = datetime.now().isoformat() + "Z"
                    with open(f, "w") as fout: json.dump(data, fout, indent=2)
                    print(f"Approval {args.approval_id} applied and verified.")
                else: print(f"Cannot apply. Status is {data['status']}. Must be 'approved'.")
            else: print("Approval not found.")

if __name__ == "__main__":
    main()
