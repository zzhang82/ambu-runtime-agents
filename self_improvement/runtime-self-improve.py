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
                    
                    # Map project path to directory name
                    proj_dir_name = project_path.replace("/", "-")
                    
                    # Try to find the session file
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
                                except Exception:
                                    continue

                    ts = data.get('timestamp')
                    ts_iso = datetime.fromtimestamp(ts/1000).isoformat() + "Z" if ts else None
                    
                    event = {
                        "schema_version": "0.1",
                        "runtime": "claude",
                        "session_id": session_id,
                        "run_id": f"run_{ts}",
                        "timestamp_start": ts_iso,
                        "timestamp_end": ts_iso,
                        "workspace": project_path,
                        "user_goal": data.get("display"),
                        "outcome": "success", 
                        "tools_used": sorted(list(set(tools_used))),
                        "summary": "Imported from Claude history + session transcript"
                    }
                    events.append(event)
                except Exception:
                    continue
        return events

class GeminiAdapter:
    def __init__(self, base_path="~/.gemini/tmp"):
        self.base_path = os.path.expanduser(base_path)

    def normalize(self, limit=50):
        events = []
        if not os.path.exists(self.base_path):
            return events

        # Find all session JSON files
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
                    "schema_version": "0.1",
                    "runtime": "gemini",
                    "session_id": data.get("sessionId"),
                    "run_id": data.get("sessionId"),
                    "timestamp_start": data.get("startTime"),
                    "timestamp_end": data.get("lastUpdated"),
                    "workspace": data.get("projectHash"), # Usually a hash or directory
                    "tools_used": [],
                    "tool_sequence": [],
                    "commands_run": [],
                    "files_touched": [],
                    "memory_operations": [],
                    "outcome": "completed"
                }

                messages = data.get("messages", [])
                for msg in messages:
                    if msg.get("type") == "user":
                        # First user message is usually the goal
                        if not event_data.get("user_goal"):
                            event_data["user_goal"] = msg.get("content", "").strip()
                    
                    # Capture tool calls from gemini responses
                    tool_calls = msg.get("toolCalls", [])
                    for tc in tool_calls:
                        name = tc.get("name")
                        if name:
                            if name not in event_data["tools_used"]:
                                event_data["tools_used"].append(name)
                            event_data["tool_sequence"].append(name)
                            
                            args = tc.get("args", {})
                            if name in ["execute_command", "bash"]:
                                cmd = args.get("command") or args.get("cmd")
                                if cmd: event_data["commands_run"].append(cmd)
                            elif name in ["write_file", "edit_file", "apply_patch"]:
                                path = args.get("file_path") or args.get("path")
                                if path: event_data["files_touched"].append(path)
                            elif "memory" in name.lower() or "recall" in name.lower() or "store" in name.lower():
                                event_data["memory_operations"].append({
                                    "type": name,
                                    "timestamp": tc.get("timestamp")
                                })

                if event_data.get("session_id"):
                    event_data["summary"] = f"Imported from Gemini session {os.path.basename(file_path)}"
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

        # Find all rollout files, sort by mtime desc
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
                    "schema_version": "0.1",
                    "runtime": "codex",
                    "tools_used": [],
                    "tool_sequence": [],
                    "commands_run": [],
                    "files_touched": [],
                    "memory_operations": [],
                    "outcome": "completed"
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
                            # Try to find task in base_instructions if not found in user msg
                            instr = payload.get("base_instructions", {}).get("text", "")
                            if "Task:\n" in instr:
                                event_data["user_goal"] = instr.split("Task:\n")[-1].strip()

                        elif ev_type == "response_item":
                            payload_type = payload.get("type")
                            if payload_type == "message":
                                role = payload.get("role")
                                if role == "user":
                                    content = payload.get("content", [])
                                    for c in content:
                                        if isinstance(c, dict) and c.get("type") == "input_text":
                                            event_data["user_goal"] = c.get("text").strip()
                                        elif isinstance(c, str):
                                            event_data["user_goal"] = c.strip()
                            
                            elif payload_type == "function_call":
                                name = payload.get("name")
                                if name:
                                    if name not in event_data["tools_used"]:
                                        event_data["tools_used"].append(name)
                                    event_data["tool_sequence"].append(name)
                                    
                                    # Deep extraction for exec_command
                                    if name == "exec_command":
                                        args = payload.get("arguments", "{}")
                                        if isinstance(args, str):
                                            try: args = json.loads(args)
                                            except: pass
                                        cmd = args.get("cmd")
                                        if cmd: event_data["commands_run"].append(cmd)
                                    
                                    # Memory operations
                                    if "memory" in name.lower() or "recall" in name.lower() or "store" in name.lower():
                                        event_data["memory_operations"].append({
                                            "type": name,
                                            "timestamp": data.get("timestamp")
                                        })

                        elif ev_type == "task_complete":
                            event_data["timestamp_end"] = datetime.fromtimestamp(payload.get("completed_at", 0)).isoformat() + "Z"
                            event_data["outcome"] = "completed"
                    except:
                        continue

                if "session_id" in event_data:
                    event_data["summary"] = f"Imported from Codex rollout {os.path.basename(file_path)}"
                    events.append(event_data)
            except Exception as e:
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

        # Get all directories in runs_path sorted by name desc
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
                        with open(goal_path, 'r', encoding='utf-8') as f:
                            goal = f.read().strip()
                    
                    event = {
                        "schema_version": "0.1",
                        "runtime": "runtime-agents",
                        "session_id": meta.get("task_id"),
                        "run_id": meta.get("task_id"),
                        "timestamp_start": meta.get("started_at"),
                        "timestamp_end": meta.get("ended_at"),
                        "workspace": meta.get("cwd"),
                        "user_goal": goal,
                        "outcome": meta.get("status"),
                        "agent": meta.get("agent"),
                        "model": meta.get("model"),
                        "summary": f"Imported from runtime-agents run {meta.get('task_id')}"
                    }
                    
                    # Tool detail upgrade
                    res_path = os.path.join(run_dir, "result.json")
                    if os.path.exists(res_path):
                        with open(res_path, 'r', encoding='utf-8') as f:
                            res = json.load(f)
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
            
            # Fetch latest sessions
            query = """
                SELECT id, title, path, model, time_created, time_updated 
                FROM session 
                ORDER BY time_created DESC 
                LIMIT ?
            """
            cursor.execute(query, (limit,))
            sessions = cursor.fetchall()
            
            for sess in sessions:
                sid, title, workspace, model_json, start_ts, end_ts = sess
                
                # Fetch tools used for this session from part table
                cursor.execute("SELECT data FROM part WHERE session_id = ? ORDER BY time_created", (sid,))
                parts = cursor.fetchall()
                
                tools_used = []
                tool_sequence = []
                commands_run = []
                files_touched = []
                memory_ops = []
                
                for p in parts:
                    try:
                        pdata = json.loads(p[0])
                        if pdata.get("type") == "tool":
                            tool = pdata.get("tool")
                            if tool:
                                if tool not in tools_used:
                                    tools_used.append(tool)
                                tool_sequence.append(tool)
                                
                                # Extract commands and files
                                input_data = pdata.get("state", {}).get("input", {})
                                if tool == "bash":
                                    cmd = input_data.get("command")
                                    if cmd: commands_run.append(cmd)
                                elif tool in ["write", "edit"]:
                                    path = input_data.get("filePath") or input_data.get("file_path")
                                    if path: files_touched.append(path)
                                elif tool == "agentMemoryBridge":
                                    memory_ops.append({
                                        "type": "recall" if "recall" in pdata.get("title", "").lower() else "operation",
                                        "timestamp": datetime.fromtimestamp(pdata.get("time", {}).get("start", 0)/1000).isoformat() + "Z"
                                    })
                    except Exception:
                        continue

                # Determine outcome (heuristically)
                outcome = "completed" # Default for opencode sessions that finished
                
                event = {
                    "schema_version": "0.1",
                    "runtime": "opencode",
                    "session_id": sid,
                    "run_id": sid,
                    "timestamp_start": datetime.fromtimestamp(start_ts/1000).isoformat() + "Z",
                    "timestamp_end": datetime.fromtimestamp(end_ts/1000).isoformat() + "Z",
                    "workspace": workspace,
                    "user_goal": title,
                    "outcome": outcome,
                    "tools_used": sorted(list(set(tools_used))),
                    "tool_sequence": tool_sequence,
                    "commands_run": commands_run,
                    "files_touched": sorted(list(set(files_touched))),
                    "memory_operations": memory_ops,
                    "summary": f"Imported from opencode DB session {sid}"
                }
                events.append(event)
                
            conn.close()
        except Exception as e:
            print(f"Error querying opencode DB: {e}")
            
        return events

def get_skill_hash(skill_path):
    skill_md = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md):
        return None
    with open(skill_md, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

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

def main():
    parser = argparse.ArgumentParser(description="Runtime Self-Improvement CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--runtime", choices=["claude", "opencode", "runtime-agents", "codex", "gemini"], required=True)
    ingest_parser.add_argument("--recent", type=int, default=50)

    # Scan command
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--events", default="~/.runtime-agents/events/agent-runs.jsonl")
    scan_parser.add_argument("--skills", default="~/.config/opencode/skills/")
    scan_parser.add_argument("--min-count", type=int, default=3)

    # Suggest command
    suggest_parser = subparsers.add_parser("suggest")
    suggest_parser.add_argument("--from-scan", default="latest")
    suggest_parser.add_argument("--min-count", type=int, default=3)
    suggest_parser.add_argument("--pattern", help="Specific pattern to export")
    suggest_parser.add_argument("--handoff-to-sculptor", action="store_true", help="Export as sculptor brief")

    # Cluster command
    cluster_parser = subparsers.add_parser("cluster")
    cluster_parser.add_argument("--events", default="~/.runtime-agents/events/agent-runs.jsonl")
    cluster_parser.add_argument("--semantic", action="store_true", help="Trigger semantic clustering request")

    # Skills commands
    skills_parser = subparsers.add_parser("skills")
    skills_subparsers = skills_parser.add_subparsers(dest="skill_command")
    
    skills_status_parser = skills_subparsers.add_parser("status")
    skills_status_parser.add_argument("--path", default="~/.config/opencode/skills/")

    skills_verify_parser = skills_subparsers.add_parser("verify")
    skills_verify_parser.add_argument("--all", action="store_true")
    skills_verify_parser.add_argument("--path", default="~/.config/opencode/skills/")

    skills_lock_parser = skills_subparsers.add_parser("lock")
    skills_lock_parser.add_argument("--path", default="~/.config/opencode/skills/")

    # Hooks commands (Milestone 2A)
    hooks_parser = subparsers.add_parser("hooks")
    hooks_subparsers = hooks_parser.add_subparsers(dest="hook_command")

    hooks_post_run = hooks_subparsers.add_parser("post-run")
    hooks_post_run.add_argument("--goal", required=True)
    hooks_post_run.add_argument("--runtime", default="opencode")
    hooks_post_run.add_argument("--session-id")
    hooks_post_run.add_argument("--outcome", default="success")

    hooks_session_start = hooks_subparsers.add_parser("session-start")
    hooks_session_start.add_argument("--workspace", default=os.getcwd())

    hooks_after_deploy = hooks_subparsers.add_parser("after-deploy")
    hooks_after_deploy.add_argument("--skill", required=True)

    hooks_after_release_change = hooks_subparsers.add_parser("after-release-change")

    hooks_every_n_runs = hooks_subparsers.add_parser("every-n-runs")
    hooks_every_n_runs.add_argument("--n", type=int, default=10)

    # Recommend command (Milestone 2B)
    recommend_parser = subparsers.add_parser("recommend")
    recommend_parser.add_argument("--workspace", default=os.getcwd())
    recommend_parser.add_argument("--runtime", default="opencode")
    recommend_parser.add_argument("--goal", help="Current user goal")
    recommend_parser.add_argument("--from-event", choices=["latest"], help="Recommend based on an event")
    recommend_parser.add_argument("--recent", type=int, help="Number of recent events to consider")

    # Events commands (Milestone 2C)
    events_parser = subparsers.add_parser("events")
    events_subparsers = events_parser.add_subparsers(dest="event_command")

    events_validate = events_subparsers.add_parser("validate")
    events_validate.add_argument("--recent", type=int, default=20)
    events_validate.add_argument("--runtime", choices=["claude", "opencode", "runtime-agents", "codex", "gemini"])
    events_validate.add_argument("--events", default="~/.runtime-agents/events/agent-runs.jsonl")

    # Schedule commands (Milestone 2G)
    schedule_parser = subparsers.add_parser("schedule")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command")
    
    schedule_check = schedule_subparsers.add_parser("check")
    schedule_check.add_argument("--workspace", default=os.getcwd())
    schedule_check.add_argument("--policy", default="/home/zzs333/code/runtime-agents/self_improvement/policy/scheduling_policy.yaml")
    
    schedule_run = schedule_subparsers.add_parser("run")
    schedule_run.add_argument("--workspace", default=os.getcwd())
    schedule_run.add_argument("--policy", default="/home/zzs333/code/runtime-agents/self_improvement/policy/scheduling_policy.yaml")
    schedule_run.add_argument("--dry-run", action="store_true")
    schedule_run.add_argument("--apply-observe-only", action="store_true")

    args = parser.parse_args()

    if args.command == "ingest":
        events = []
        if args.runtime == "claude":
            adapter = ClaudeCCRAdapter("~/.claude/history.jsonl")
            events = adapter.normalize(args.recent)
        elif args.runtime == "opencode":
            adapter = OpencodeAdapter()
            events = adapter.normalize(args.recent)
        elif args.runtime == "runtime-agents":
            adapter = RuntimeAgentsAdapter("~/.local/share/runtime-agents")
            events = adapter.normalize(args.recent)
        elif args.runtime == "codex":
            adapter = CodexAdapter()
            events = adapter.normalize(args.recent)
        elif args.runtime == "gemini":
            adapter = GeminiAdapter()
            events = adapter.normalize(args.recent)
            
        if events:
            store_path = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
            os.makedirs(os.path.dirname(store_path), exist_ok=True)
            with open(store_path, 'a', encoding='utf-8') as f:
                for ev in events:
                    f.write(json.dumps(ev) + "\n")
            print(f"Successfully ingested {len(events)} runs from {args.runtime}")
        else:
            print(f"No events found for {args.runtime}")

    elif args.command == "scan":
        # ... (keep existing scan implementation)
        events_path = os.path.expanduser(args.events)
        skills_path = os.path.expanduser(args.skills)
        
        if not os.path.exists(events_path):
            print(f"No events found at {events_path}. Run ingest first.")
            return

        events = []
        with open(events_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                try:
                    events.append(json.loads(line))
                except Exception as e:
                    continue

        skills = []
        if os.path.exists(skills_path):
            skills = [d for d in os.listdir(skills_path) if os.path.isdir(os.path.join(skills_path, d))]

        print(f"Scanning {len(events)} events against {len(skills)} installed skills...\n")

        goal_counts = Counter()
        tool_counts = Counter()
        goal_to_traces = {}
        noise_count = 0
        orchestration_count = 0
        
        def normalize_goal(g):
            g = g.lower().strip()
            if any(x in g for x in ["architecture", "repo state", "codebase map", "understand structure"]): return "architecture sensing"
            if any(x in g for x in ["resume", "last session", "yesterday", "prelude"]): return "session recovery"
            if any(x in g for x in ["version", "changelog", "release", "tag", "sync"]): return "release sync"
            return g

        for ev in events:
            raw_goal = ev.get("user_goal", "")
            goal = normalize_goal(raw_goal)
            tools = ev.get("tools_used", [])
            tool_tuple = tuple(tools)
            
            is_noise = not goal or goal in ["hi", "hello", "test", "status"]
            if is_noise:
                noise_count += 1
                continue
            
            goal_counts[goal] += 1
            if tools:
                tool_counts[tool_tuple] += 1
                if goal not in goal_to_traces: goal_to_traces[goal] = []
                goal_to_traces[goal].append({"session_id": ev.get("session_id"), "tools": tools})

        candidates = []
        covered_count = 0
        already_forged = []
        p1_watchlist = []
        
        for goal, count in goal_counts.most_common():
            covered_by = None
            if goal == "session recovery": covered_by = "session-bridge-assembler"
            elif goal == "release sync": covered_by = "version-sync-sculptor"
            else:
                for s in skills:
                    if s.replace("-", " ") in goal or goal in s.replace("-", " "):
                        covered_by = s
                        break
            
            if covered_by:
                covered_count += 1
                already_forged.append((goal, covered_by, count))
            elif count >= args.min_count:
                candidates.append({"goal": goal, "count": count})
            else:
                p1_watchlist.append((goal, count))

        print(f"--- Pattern Funnel ---")
        print(f"{len(events)} events, {covered_count} forged, {len(candidates)} P0, {len(p1_watchlist)} P1")
        
        report = {"timestamp": datetime.now().isoformat(), "candidates": candidates, "p1_watchlist": p1_watchlist}
        report_path = os.path.expanduser("~/.runtime-agents/reports/latest-scan.json")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)

    elif args.command == "suggest":
        # ... (keep existing suggest implementation)
        scan_report_path = os.path.expanduser("~/.runtime-agents/reports/latest-scan.json")
        if not os.path.exists(scan_report_path):
            print("No scan report. Run scan first.")
            return
        with open(scan_report_path, 'r', encoding='utf-8') as f:
            scan_data = json.load(f)
        print(f"Suggestions based on {len(scan_data.get('candidates', []))} P0 candidates.")

    elif args.command == "skills":
        skills_path = os.path.expanduser(args.path)
        lock_file = os.path.join(skills_path, "skills.lock.json")
        
        if args.skill_command == "status":
            print(f"Skill Store: {skills_path}")
            skills = [d for d in os.listdir(skills_path) if os.path.isdir(os.path.join(skills_path, d)) and not d.startswith(".")]
            print(f"Skills: {len(skills)}")

        elif args.skill_command == "lock":
            skills = {}
            for d in os.listdir(skills_path):
                p = os.path.join(skills_path, d)
                if os.path.isdir(p) and not d.startswith("."):
                    h = get_skill_hash(p)
                    if h: skills[d] = {"hash": h, "last_locked": datetime.now().isoformat()}
            with open(lock_file, "w") as f:
                json.dump({"schema_version": "0.1", "skills": skills}, f, indent=2)
            print(f"Locked {len(skills)} skills.")

        elif args.skill_command == "verify":
            if not os.path.exists(lock_file): return
            with open(lock_file, "r") as f: lock_data = json.load(f)
            locked_skills = lock_data.get("skills", {})
            current_skills = [d for d in os.listdir(skills_path) if os.path.isdir(os.path.join(skills_path, d)) and not d.startswith(".")]
            errors = 0
            for s in current_skills:
                p = os.path.join(skills_path, s)
                h = get_skill_hash(p)
                if s not in locked_skills or locked_skills[s]["hash"] != h:
                    print(f"[!] {s} DRIFTED")
                    errors += 1
                else: print(f"[+] {s} VERIFIED")
            if errors > 0: sys.exit(1)

    elif args.command == "hooks":
        if args.hook_command == "post-run":
            event = {
                "schema_version": "0.1",
                "runtime": args.runtime,
                "session_id": args.session_id or f"sess_{int(datetime.now().timestamp())}",
                "timestamp_start": datetime.now().isoformat() + "Z",
                "user_goal": args.goal,
                "outcome": args.outcome,
                "summary": f"Recorded via post-run hook"
            }
            store_path = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
            os.makedirs(os.path.dirname(store_path), exist_ok=True)
            with open(store_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event) + "\n")
            print(f"[hook:post-run] Event recorded: {args.goal}")

        elif args.hook_command == "session-start":
            print(f"[hook:session-start] Inspecting workspace: {args.workspace}")
            # Logic to recommend bridge
            if os.path.exists(os.path.join(args.workspace, ".opencode")):
                print("RECOMMENDATION: Run '/session-bridge-assembler' to recover context.")
            else:
                print("Status: Fresh workspace.")

        elif args.hook_command == "after-deploy":
            print(f"[hook:after-deploy] Verifying skill: {args.skill}")
            subprocess.run(["python3", sys.argv[0], "skills", "verify", "--all"])
            print("RECOMMENDATION: Run '/skill-deployment-verifier' for cross-platform check.")
            print("NOTE: Do not update skills.lock.json automatically.")

        elif args.hook_command == "after-release-change":
            print(f"[hook:after-release-change] Release files modified.")
            print("RECOMMENDATION: Run '/version-sync-sculptor' in verify-only mode.")

        elif args.hook_command == "every-n-runs":
            store_path = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
            if os.path.exists(store_path):
                with open(store_path, 'r') as f:
                    count = sum(1 for _ in f)
                if count % args.n == 0:
                    print(f"[hook:every-n-runs] Hit interval {args.n}.")
                    print("RECOMMENDATION: Run 'runtime-self-improve scan && runtime-self-improve suggest'.")

    elif args.command == "recommend":
        goal = (args.goal or "").lower()
        workspace = os.path.expanduser(args.workspace)
        runtime = args.runtime.lower()
        recent_count = args.recent or 0
        
        # Determine fidelity-based confidence
        fidelity = "low"
        if runtime in ["claude", "codex", "gemini"]: fidelity = "high"
        elif runtime in ["opencode", "runtime-agents"]: fidelity = "medium"
        
        recommendation = {
            "action": "do nothing",
            "skill": "none",
            "confidence": "Low",
            "mode": "observe",
            "why": [],
            "alternatives": [],
            "safety": {"mutation_required": "no", "approval_required": "no", "verifier_needed": "no"},
            "next_command": ""
        }

        signals = []
        
        # Priority rules
        # Rule 7: Forge/Sculpt request
        if "new skill" in goal or "create skill" in goal:
            signals.append("skill-forge-intent")
            recommendation["action"] = "sculpt new skill"
            recommendation["skill"] = "ljg-style-skill-sculptor"
            recommendation["confidence"] = "High"
            recommendation["why"].append("Direct request for skill creation.")
            recommendation["safety"]["approval_required"] = "yes"
            recommendation["next_command"] = "/ljg-style-skill-sculptor"

        # Rule 1: Resume language + AMB/Workspace check
        elif any(x in goal for x in ["continue", "resume", "last session", "yesterday", "prelude"]):
            signals.append("session-recovery-intent")
            if os.path.exists(os.path.join(workspace, ".opencode")):
                recommendation["action"] = "recover session context"
                recommendation["skill"] = "session-bridge-assembler"
                recommendation["confidence"] = "High" if fidelity == "high" else "Medium"
                recommendation["why"].append("Resume language detected and .opencode context exists.")
                recommendation["next_command"] = "/session-bridge-assembler"

        # Rule 2: Architecture / What does this repo do?
        elif any(x in goal for x in ["architecture", "what does this repo", "repo state", "understand structure", "how it works"]):
            signals.append("architecture-discovery-intent")
            recommendation["action"] = "map repository architecture"
            recommendation["skill"] = "repo-architecture-sensor"
            recommendation["confidence"] = "High"
            recommendation["why"].append("User asked for structural or architectural overview.")
            recommendation["next_command"] = "/repo-architecture-sensor"

        # Rule 3: Version/Changelog drift
        elif any(x in goal for x in ["pyproject.toml", "changelog.md", "package.json"]) and ("change" in goal or "drift" in goal):
            signals.append("version-drift-intent")
            recommendation["action"] = "verify release documentation sync"
            recommendation["skill"] = "version-sync-sculptor"
            recommendation["confidence"] = "Medium"
            recommendation["why"].append("Release manifests or changelog files mentioned in context of change.")
            recommendation["next_command"] = "/version-sync-sculptor"

        # Rule 4: Release/Burn-in cleanliness
        elif any(x in goal for x in ["clean and ready", "is v1.5.1 clean", "handoff ready", "hygiene"]):
            signals.append("release-hygiene-intent")
            recommendation["action"] = "audit repository hygiene"
            recommendation["skill"] = "agent-hygiene-auditor"
            recommendation["confidence"] = "High"
            recommendation["why"].append("User asked for release readiness or hygiene check.")
            recommendation["next_command"] = "/agent-hygiene-auditor"

        # Rule 5: Skill store changes
        elif "skill" in goal and any(x in goal for x in ["change", "add", "modify", "deploy"]):
            signals.append("skill-management-intent")
            recommendation["action"] = "verify skill deployment"
            recommendation["skill"] = "skill-deployment-verifier"
            recommendation["confidence"] = "Medium"
            recommendation["why"].append("Skill modification detected in goal or context.")
            recommendation["next_command"] = "runtime-self-improve skills verify && /skill-deployment-verifier"

        # Rule 6: Repeated friction / every N runs
        elif recent_count > 15:
            signals.append("high-run-volume")
            recommendation["action"] = "scan for repeated workflows"
            recommendation["skill"] = "repo-workflow-cartographer"
            recommendation["confidence"] = "Medium"
            recommendation["why"].append(f"Significant run volume ({recent_count}) accumulated.")
            recommendation["next_command"] = "runtime-self-improve scan && runtime-self-improve suggest"

        # Check for High Fidelity Event in latest
        events_path = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
        if os.path.exists(events_path):
            with open(events_path, "r") as f:
                lines = f.readlines()
                if lines:
                    latest = json.loads(lines[-1])
                    if latest.get("tool_sequence") and latest.get("outcome"):
                        fidelity = "high"
                        recommendation["confidence"] = "High"
                        recommendation["why"].append("High-fidelity event detected in latest run.")

        # Final Mold Output
        print("# Context-Aware Recommendation\n")
        print(f"## Recommended Action\n- action: {recommendation['action']}\n- skill: {recommendation['skill']}\n- confidence: {recommendation['confidence']}\n- mode: {recommendation['mode']}")
        print(f"\n## Why\n- signals: {', '.join(signals) if signals else 'none'}\n- recent events: Considered {recent_count} runs\n- runtime fidelity: {fidelity}")
        for w in recommendation['why']:
            print(f"- {w}")
        print("\n## Safety")
        for k, v in recommendation['safety'].items():
            print(f"- {k.replace('_', ' ')}: {v}")
        print(f"\n## Next Command\n`{recommendation['next_command']}`")

    elif args.command == "events":
        events_path = os.path.expanduser(args.events)
        if args.event_command == "validate":
            if not os.path.exists(events_path):
                print(f"No events found at {events_path}")
                return
            
            events = []
            with open(events_path, "r") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                        if args.runtime and ev.get("runtime") != args.runtime:
                            continue
                        events.append(ev)
                    except Exception:
                        continue
            
            recent = events[-args.recent:]
            print(f"Validating {len(recent)} recent events{' for ' + args.runtime if args.runtime else ''}...\n")
            
            for i, ev in enumerate(recent):
                runtime = ev.get("runtime", "unknown")
                has_tools = "yes" if ev.get("tool_sequence") else "no"
                has_outcome = "yes" if ev.get("outcome") else "no"
                has_files = "yes" if ev.get("files_touched") else "no"
                has_cmds = "yes" if ev.get("commands_run") else "no"
                
                fidelity = "Low"
                # Fidelity scoring logic (Milestone 2D)
                if ev.get("tool_sequence") and ev.get("outcome") and (ev.get("files_touched") or ev.get("commands_run")):
                    fidelity = "High"
                elif ev.get("user_goal") and ev.get("timestamp_start") and ev.get("outcome"):
                    fidelity = "Medium"
                    
                print(f"[{i+1}] {ev.get('timestamp_start', 'N/A'):<25} | {runtime:<15} | Fidelity: {fidelity:<6} | Tools: {has_tools:<3} | Outcome: {has_outcome:<3} | Files/Cmds: {has_files}/{has_cmds}")

    elif args.command == "schedule":
        policy_path = os.path.expanduser(args.policy)
        state_path = os.path.expanduser("~/.runtime-agents/scheduler/state.json")
        events_path = os.path.expanduser("~/.runtime-agents/events/agent-runs.jsonl")
        skills_path = os.path.expanduser("~/.config/opencode/skills/")
        
        if not os.path.exists(policy_path):
            print(f"Policy not found at {policy_path}")
            return
        
        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f) if yaml else {}
            
        state = {
            "schema_version": "0.1",
            "last_scan_event_id": None, "last_suggest_event_id": None,
            "last_scan_at": None, "last_suggest_at": None,
            "last_skill_verify_hash": None, "last_release_verify_hash": None,
            "suppressed_recommendations": []
        }
        if os.path.exists(state_path):
            with open(state_path, "r") as f:
                state.update(json.load(f))
        
        # Gather signals
        new_events = []
        scan_events = []
        suggest_events = []
        last_ts = None
        
        if os.path.exists(events_path):
            with open(events_path, "r") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                        ts = ev.get("timestamp_start")
                        if not ts: continue
                        last_ts = ts
                        
                        is_hf = ev.get("tool_sequence") and ev.get("outcome")
                        
                        if not state.get("last_scan_at") or ts > state["last_scan_at"]:
                            new_events.append(ev)
                            if is_hf: scan_events.append(ev)
                        
                        if not state.get("last_suggest_at") or ts > state["last_suggest_at"]:
                            if is_hf: suggest_events.append(ev)
                    except: continue
        
        current_skills_hash = get_dir_hash(skills_path)
        release_files = policy.get("triggers", {}).get("release_files_changed", {}).get("files", [])
        current_release_hash = get_files_hash(release_files, args.workspace)
        
        # Check for dirty worktree (Hygiene)
        is_dirty = False
        try:
            res = subprocess.run(["git", "status", "--porcelain"], cwd=args.workspace, capture_output=True, text=True)
            if res.stdout.strip(): is_dirty = True
        except: pass

        actions_due = []
        actions_skipped = []
        
        # Trigger 1: Scan
        scan_n = policy.get("triggers", {}).get("scan_every_n_events", {}).get("n", 20)
        if len(scan_events) >= scan_n:
            actions_due.append({"action": "runtime-self-improve scan", "reason": f"{len(scan_events)} new high-fidelity events", "mode": "recommend"})
        else:
            actions_skipped.append({"action": "runtime-self-improve scan", "reason": f"only {len(scan_events)}/{scan_n} hf events since last scan"})

        # Trigger 2: Suggest
        suggest_n = policy.get("triggers", {}).get("suggest_every_n_events", {}).get("n", 100)
        if len(suggest_events) >= suggest_n:
            actions_due.append({"action": "runtime-self-improve suggest", "reason": f"{len(suggest_events)} new high-fidelity events", "mode": "recommend"})
        else:
            actions_skipped.append({"action": "runtime-self-improve suggest", "reason": f"only {len(suggest_events)}/{suggest_n} hf events since last suggest"})

        # Trigger 3: Skill store changed
        if current_skills_hash != state["last_skill_verify_hash"]:
            actions_due.append({"action": "runtime-self-improve skills verify", "reason": "skill store hash changed", "mode": "observe"})
            actions_due.append({"action": "recommend skill-deployment-verifier", "reason": "skill store hash changed", "mode": "recommend"})
        
        # Trigger 4: Release files changed
        if current_release_hash != state["last_release_verify_hash"]:
            actions_due.append({"action": "recommend version-sync-sculptor verify-only", "reason": "release files modified", "mode": "recommend"})

        # Trigger 5: Similar failures
        failure_threshold = policy.get("triggers", {}).get("similar_failures", {}).get("threshold", 3)
        failures = [ev for ev in new_events if ev.get("outcome") == "failed"]
        if len(failures) >= failure_threshold:
             actions_due.append({"action": "repo-workflow-cartographer focused scan", "reason": f"{len(failures)} recent failures detected", "mode": "recommend"})

        # Trigger 6: Hygiene (Dirty Worktree)
        if is_dirty:
            actions_due.append({"action": "recommend agent-hygiene-auditor", "reason": "dirty worktree detected", "mode": "recommend"})

        # Report Output
        print("# Scheduler Decision Report\n")
        print(f"## Mode\n{policy.get('mode', 'unknown')}")
        print(f"\n## Event Window\n- new events (all): {len(new_events)}\n- hf events (for scan): {len(scan_events)}\n- hf events (for suggest): {len(suggest_events)}")
        
        print("\n## Actions Due")
        for i, a in enumerate(actions_due, 1):
            print(f"{i}. {a['action']}\n   reason: {a['reason']}\n   mode: {a['mode']}\n   mutation: no")
            
        print("\n## Actions Skipped")
        for i, a in enumerate(actions_skipped, 1):
            print(f"{i}. {a['action']}\n   reason: {a['reason']}")

        print("\n## Recommendations")
        recs = [a['action'] for a in actions_due if a['mode'] == 'recommend']
        if recs:
            for r in recs: print(f"- Run: `{r}`")
        else:
            print("- None")
        
        print("\n## Safety\nNo mutating action was executed.")

        if args.schedule_command == "run" and not args.dry_run:
            # Update state hashes if observe-only or if manually accepted
            if current_skills_hash: state["last_skill_verify_hash"] = current_skills_hash
            if current_release_hash: state["last_release_verify_hash"] = current_release_hash
            
            # If scan/suggest due, update timestamp
            if any(a["action"] == "runtime-self-improve scan" for a in actions_due):
                state["last_scan_at"] = last_ts
            
            if any(a["action"] == "runtime-self-improve suggest" for a in actions_due):
                state["last_suggest_at"] = last_ts
            
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)
            print(f"\nState updated in {state_path}")


if __name__ == "__main__":
    main()

