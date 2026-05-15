import json
import os
import sys
import glob
import argparse
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
                    # /home/zzs333 -> -home-zzs333
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

class OpencodeAdapter:
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
                        "runtime": "opencode",
                        "session_id": meta.get("task_id"),
                        "run_id": meta.get("task_id"),
                        "timestamp_start": meta.get("started_at"),
                        "timestamp_end": meta.get("ended_at"),
                        "workspace": meta.get("cwd"),
                        "user_goal": goal,
                        "outcome": meta.get("status"),
                        "agent": meta.get("agent"),
                        "model": meta.get("model"),
                        "summary": f"Imported from opencode run {meta.get('task_id')}"
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

def main():
    parser = argparse.ArgumentParser(description="Runtime Self-Improvement CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--runtime", choices=["claude", "opencode"], required=True)
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

    args = parser.parse_args()

    if args.command == "ingest":
        events = []
        if args.runtime == "claude":
            adapter = ClaudeCCRAdapter("~/.claude/history.jsonl")
            events = adapter.normalize(args.recent)
        elif args.runtime == "opencode":
            adapter = OpencodeAdapter("~/.local/share/runtime-agents")
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

        # Load installed skills
        skills = []
        if os.path.exists(skills_path):
            skills = [d for d in os.listdir(skills_path) if os.path.isdir(os.path.join(skills_path, d))]

        print(f"Scanning {len(events)} events against {len(skills)} installed skills...\n")

        # Cluster goals and tools
        goal_counts = Counter()
        tool_counts = Counter()
        goal_to_traces = {}
        
        noise_count = 0
        orchestration_count = 0
        
        def normalize_goal(g):
            g = g.lower().strip()
            # Rule-based intent normalization - HIGH SPECIFICITY FIRST
            if any(x in g for x in ["architecture", "archeatecture", "repo state", "codebase map", "understand structure", "inspect the workspace", "how does this project work", "current state"]):
                return "architecture sensing"
            if any(x in g for x in ["resume", "last session", "yesterday", "prelude", "stopped after", "picking up"]):
                return "session recovery"
            if any(x in g for x in ["version", "changelog", "release", "tag", "sync"]):
                return "release sync"
            if any(x in g for x in ["test status", "verify tests", "analyze tests", "check test status"]):
                return "status check"
            if "relevant project memory" in g and "task:" in g:
                # Extract task part
                parts = g.split("task:")
                if len(parts) > 1:
                    return f"handoff: {normalize_goal(parts[1])}"
            if g.startswith("/effort"):
                return "effort estimation"
            if "continue" in g:
                return "session recovery"
            return g

        categorized_counts = Counter()

        for ev in events:
            raw_goal = ev.get("user_goal", "")
            goal = normalize_goal(raw_goal)
            
            # Pattern classification
            tools = ev.get("tools_used", [])
            tool_tuple = tuple(tools)
            
            is_noise = not goal or goal in ["hi", "hello", "/model", "test", "status", "hi cole", "do nothing"]
            is_orchestration = len(tools) > 8 and "TaskCreate" in tools and "TaskUpdate" in tools
            
            if is_noise:
                noise_count += 1
                continue
            
            if is_orchestration:
                orchestration_count += 1
                # Still track it for analysis but label as orchestration
                categorized_counts["generic orchestration"] += 1
            
            goal_counts[goal] += 1
            if tools:
                tool_counts[tool_tuple] += 1
                if goal not in goal_to_traces:
                    goal_to_traces[goal] = []
                goal_to_traces[goal].append({
                    "session_id": ev.get("session_id"),
                    "tools": tools,
                    "runtime": ev.get("runtime"),
                    "raw_goal": raw_goal
                })

        print("--- Pattern Funnel ---")
        print(f"{len(events)} events")
        print(f"├── {noise_count} noise: do nothing/hi/model")
        print(f"├── {orchestration_count} orchestration baseline")
        
        candidates = []
        covered_count = 0
        p1_watchlist = []
        already_forged = []
        
        # Sort by count
        sorted_goals = goal_counts.most_common()
        
        for goal, count in sorted_goals:
            if goal == "generic orchestration": continue
            
            covered_by = None
            goal_normalized = goal.replace("-", " ").replace("_", " ")
            
            # Rule-based categorization for known skills
            if goal == "session recovery": covered_by = "session-bridge-assembler"
            elif goal == "release sync": covered_by = "version-sync-sculptor"
            elif "deploy" in goal or "install" in goal: covered_by = "skill-deployment-verifier"
            else:
                for skill in skills:
                    skill_normalized = skill.replace("-", " ").replace("_", " ")
                    if skill_normalized in goal_normalized or goal_normalized in skill_normalized:
                        covered_by = skill
                        break
            
            if covered_by:
                covered_count += 1
                already_forged.append((goal, covered_by, count))
            elif count >= args.min_count:
                candidates.append({
                    "goal": goal,
                    "count": count,
                    "traces": goal_to_traces.get(goal, [])[:5]
                })
            else:
                p1_watchlist.append((goal, count))

        print(f"├── {covered_count} already forged")
        print(f"├── {len(p1_watchlist)} P1 watchlist")
        print(f"└── {len(candidates)} new P0 candidates")

        print("\n--- Skill Coverage Matrix ---")
        print(f"{'Pattern':<30} {'Status':<25} {'Covered By':<25}")
        print("-" * 80)
        for goal, skill, count in already_forged:
            print(f"{goal:<30} {'already_forged':<25} {skill:<25}")
        for goal, count in p1_watchlist:
            print(f"{goal:<30} {'p1_watchlist':<25} {'none':<25}")
        for cand in candidates:
            print(f"{cand['goal']:<30} {'new_p0_candidate':<25} {'none':<25}")
        print(f"{'generic orchestration':<30} {'reject_noise':<25} {'n/a':<25}")

        # Save report
        report = {
            "timestamp": datetime.now().isoformat(),
            "event_count": len(events),
            "noise_count": noise_count,
            "orchestration_count": orchestration_count,
            "skill_count": len(skills),
            "covered_count": covered_count,
            "already_forged": already_forged,
            "p1_watchlist": p1_watchlist,
            "candidates": candidates,
            "frequent_tool_sequences": [ {"seq": list(seq), "count": count} for seq, count in tool_counts.most_common(10) if count >= args.min_count ]
        }
        
        report_path = os.path.expanduser("~/.runtime-agents/reports/latest-scan.json")
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to {report_path}")

    elif args.command == "suggest":
        scan_report_path = os.path.expanduser("~/.runtime-agents/reports/latest-scan.json")
        if not os.path.exists(scan_report_path):
            print(f"No scan report found at {scan_report_path}. Run scan first.")
            return

        with open(scan_report_path, 'r', encoding='utf-8') as f:
            scan_data = json.load(f)

        candidates = scan_data.get("candidates", [])
        watchlist = scan_data.get("p1_watchlist", [])
        
        all_targets = []
        for cand in candidates:
            cand["status"] = "new_p0_candidate"
            all_targets.append(cand)
        for goal, count in watchlist:
            all_targets.append({"goal": goal, "count": count, "status": "p1_watchlist", "traces": []})

        if args.pattern:
            all_targets = [t for t in all_targets if args.pattern in t["goal"]]

        if not all_targets:
            print("No candidates found.")
            return

        if args.handoff_to_sculptor:
            print(f"--- Sculptor Handoff Brief: {all_targets[0]['goal']} ---")
            print(f"Draft spec for LJG-style forge. DO NOT AUTO-DEPLOY.\n")
            # Minimal handoff content
            print(f"Goal: {all_targets[0]['goal']}")
            print(f"Status: {all_targets[0]['status']}")
            print(f"Count: {all_targets[0]['count']}")
            print("\nSpec Template:")
            print("One Cut: ...\nTrigger: ...\nRedlines: ...")
            return

        print(f"Generating suggestions for {len(all_targets)} targets...\n")
        
        suggestions = []
        for target in all_targets:
            goal = target["goal"]
            count = target["count"]
            status = target["status"]
            
            # Classification logic (same as before but using status from scan)
            recommendation = "Forge" if status == "new_p0_candidate" else "Watch"
            if "reject" in status: recommendation = "Reject"

            suggestion = {
                "candidate": goal,
                "status": status,
                "count": count,
                "evidence": {
                    "occurrences": count,
                    "matching_runs": [],
                    "common_goal_shape": goal,
                    "common_tool_sequence": [],
                    "failure_points": "N/A",
                    "already_covered": "no"
                },
                "spec": {
                    "one_cut": "TODO",
                    "trigger": f"User asks to: {goal}",
                    "recommendation": recommendation
                }
            }
            suggestions.append(suggestion)

        # Output logic... (similar to before)
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        md_path = os.path.expanduser(f"~/.runtime-agents/reports/suggestions-{ts}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# Skill Suggestions Report ({ts})\n\n")
            for s in suggestions:
                f.write(f"## Skill Suggestion: {s['candidate']}\n\n")
                f.write(f"### Status\n{s['status']}\n\n")
                f.write(f"### Recommendation\n{s['spec']['recommendation']}\n\n")
        print(f"Suggestions saved to {md_path}")

    elif args.command == "cluster":
        if args.semantic:
            print("--- Semantic Clustering Request ---")
            print("Analyze events in ~/.runtime-agents/events/agent-runs.jsonl")
            print("Group by: similar goal + tool sequence + input/output shape.")
            print("Specifically look for variations of 'architecture sensing'.")
            # In a real tool, this would invoke an LLM. 
            # Here I will perform a simulated semantic search in the next step using Task.



if __name__ == "__main__":
    main()
