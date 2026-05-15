import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict

from runtime_agents.models import AgentRunEvent
from runtime_agents.paths import EVENTS_JSONL
from runtime_agents.state import append_jsonl


class EventCapture:
    def __init__(self, runtime: str = "runtime-agents", session_id: str | None = None, workspace: str | None = None):
        self.event = AgentRunEvent(
            runtime=runtime,
            session_id=session_id,
            workspace=workspace,
            timestamp_start=self._now_iso(),
        )
        self.active = True

    def _now_iso(self) -> str:
        return datetime.now().isoformat() + "Z"

    def set_goal(self, goal: str):
        self.event.user_goal = goal

    def set_run_id(self, run_id: str):
        self.event.run_id = run_id

    def record_tool(self, tool_name: str):
        if tool_name not in self.event.tools_used:
            self.event.tools_used.append(tool_name)
        self.event.tool_sequence.append(tool_name)

    def record_command(self, command: str):
        self.event.commands_run.append(command)

    def record_file(self, file_path: str):
        if file_path not in self.event.files_touched:
            self.event.files_touched.append(file_path)

    def record_skill(self, skill_name: str):
        if skill_name not in self.event.skills_invoked:
            self.event.skills_invoked.append(skill_name)

    def record_memory_op(self, op_type: str, namespace: str, query: str | None = None, result_count: int = 0):
        self.event.memory_operations.append({
            "type": op_type,
            "namespace": namespace,
            "query": query,
            "result_count": result_count,
            "timestamp": self._now_iso()
        })

    def record_friction(self, friction: str):
        self.event.friction_points.append(friction)

    def record_artifact(self, artifact_path: str):
        self.event.artifacts_created.append(artifact_path)

    def finish(self, outcome: str, summary: str | None = None):
        if not self.active:
            return
        self.event.outcome = outcome
        self.event.summary = summary
        self.event.timestamp_end = self._now_iso()
        
        # Ensure events directory exists
        EVENTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
        
        append_jsonl(EVENTS_JSONL, self.event.to_payload())
        self.active = False
