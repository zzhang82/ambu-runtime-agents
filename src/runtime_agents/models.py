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
