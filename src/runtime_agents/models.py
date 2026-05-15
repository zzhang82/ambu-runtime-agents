from dataclasses import dataclass, field
from typing import Any


TASK_STATUSES = {"queued", "running", "completed", "failed", "approval_required", "cancelled", "retrying"}
QUEUE_STATUSES = {"queued", "running", "completed", "failed", "approval_required", "cancelled", "retrying"}
PLAN_STATUSES = {"draft", "approved", "running", "blocked", "completed"}
SCHEDULE_STATUSES = {"enabled", "disabled", "removed", "failed"}


@dataclass
class TaskRef:
    task_id: str
    status: str


@dataclass
class QueueItem:
    queue_id: str
    status: str
    agent: str
    goal: str


@dataclass
class PlanSubtask:
    id: str
    agent: str
    goal: str
    type: str = "run"
    depends_on: list[str] = field(default_factory=list)


@dataclass
class PlanRef:
    plan_id: str
    status: str
    subtasks: list[PlanSubtask] = field(default_factory=list)


@dataclass
class PolicyDecision:
    mode: str
    capabilities: list[str]
    approved: list[str]
    blocked: list[str]


@dataclass
class ToolTrace:
    tool_id: str
    trust_level: str
    data_classes: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    egress: str = "none"
    source: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "tool_id": self.tool_id,
            "trust_level": self.trust_level,
            "data_classes": self.data_classes,
            "capabilities": self.capabilities,
            "egress": self.egress,
            "source": self.source,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class ContextState:
    profile: str | None
    workspace: str | None
    saw_untrusted_input: bool
    accessed_private_data: bool
    external_egress_used: bool
    data_classes: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    tool_trace: list[ToolTrace] = field(default_factory=list)
    tools_considered: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "workspace": self.workspace,
            "saw_untrusted_input": self.saw_untrusted_input,
            "accessed_private_data": self.accessed_private_data,
            "external_egress_used": self.external_egress_used,
            "data_classes": self.data_classes,
            "capabilities": self.capabilities,
            "tool_trace": [trace.to_payload() for trace in self.tool_trace],
            "tools_considered": self.tools_considered,
        }


@dataclass
class GuardrailDecision:
    decision: str
    rule_id: str
    reason: str
    action: str
    severity: str = "info"

    def to_payload(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "action": self.action,
            "severity": self.severity,
        }


@dataclass
class Action:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunEvent:
    schema_version: str = "0.1"
    runtime: str = "runtime-agents"
    session_id: str | None = None
    run_id: str | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    workspace: str | None = None
    user_goal: str | None = None
    outcome: str | None = None
    summary: str | None = None
    tools_used: list[str] = field(default_factory=list)
    tool_sequence: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    skills_invoked: list[str] = field(default_factory=list)
    memory_operations: list[dict[str, Any]] = field(default_factory=list)
    friction_points: list[str] = field(default_factory=list)
    artifacts_created: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime": self.runtime,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "workspace": self.workspace,
            "user_goal": self.user_goal,
            "outcome": self.outcome,
            "summary": self.summary,
            "tools_used": self.tools_used,
            "tool_sequence": self.tool_sequence,
            "files_touched": self.files_touched,
            "commands_run": self.commands_run,
            "skills_invoked": self.skills_invoked,
            "memory_operations": self.memory_operations,
            "friction_points": self.friction_points,
            "artifacts_created": self.artifacts_created,
        }


@dataclass
class ActionResult:
    status: str
    action_type: str
    risk: str
    executed: bool
    requires_confirmation: bool = False
    pending_action_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "action_type": self.action_type,
            "risk": self.risk,
            "executed": self.executed,
            "requires_confirmation": self.requires_confirmation,
            "pending_action_id": self.pending_action_id,
            "result": self.result,
            "error": self.error,
            "message": self.message,
        }
        return {key: value for key, value in payload.items() if value is not None}

    @classmethod
    def completed(cls, action_type: str, risk: str, result: dict[str, Any], message: str | None = None) -> "ActionResult":
        return cls(status="completed", action_type=action_type, risk=risk, executed=True, result=result, message=message)

    @classmethod
    def pending_confirmation(cls, action_type: str, risk: str, message: str | None = None) -> "ActionResult":
        return cls(status="pending_confirmation", action_type=action_type, risk=risk, executed=False, requires_confirmation=True, message=message)

    @classmethod
    def blocked(cls, action_type: str, risk: str, message: str | None = None) -> "ActionResult":
        return cls(status="blocked", action_type=action_type, risk=risk, executed=False, message=message)

    @classmethod
    def unsupported(cls, action_type: str, risk: str, message: str | None = None) -> "ActionResult":
        return cls(status="unsupported", action_type=action_type, risk=risk, executed=False, message=message)

    @classmethod
    def failed(cls, action_type: str, risk: str, error: str, message: str | None = None) -> "ActionResult":
        return cls(status="failed", action_type=action_type, risk=risk, executed=False, error=error, message=message)

    def with_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(payload)
        merged["action_result"] = self.to_payload()
        return merged

    def with_execution(self, payload: dict[str, Any], execution: list[dict[str, Any]]) -> dict[str, Any]:
        merged = self.with_payload(payload)
        merged["execution"] = execution
        return merged

    def as_route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(payload)
        merged["status"] = self.status
        if self.message is not None:
            merged["message"] = self.message
        return merged

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    @property
    def terminal(self) -> bool:
        return self.status in {"completed", "pending_confirmation", "blocked", "unsupported", "failed"}

    def summary(self) -> str:
        return self.message or self.error or self.status

    def __bool__(self) -> bool:
        return self.ok
