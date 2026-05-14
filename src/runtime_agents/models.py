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
class Action:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


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
