"""
Agent State Machine — deterministic, explicit, auditable.

Every state transition is explicit. Never fabricate a state.
Every transition is logged for audit.

States:
  IDLE → UNDERSTANDING → PLANNING → EXECUTING → OBSERVING → REASONING
  → VERIFYING → COMPLETED
  Any state → FAILED
  Any state → CANCELLED
  EXECUTING → WAITING_APPROVAL → EXECUTING
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Safety limits — increased for autonomous operation
MAX_ITERATIONS = 50
MAX_TOOL_CALLS = 30
MAX_EXECUTION_TIME_SECONDS = 600  # 10 minutes
MAX_PLAN_STEPS = 20
MAX_RETRIES = 3
MAX_RETRIES_PER_TOOL = 2
MAX_TODO_TASKS = 30
MAX_SUBAGENT_CONCURRENT = 5

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    IDLE = "idle"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    EXECUTING = "executing"
    OBSERVING = "observing"
    REASONING = "reasoning"
    VERIFYING = "verifying"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid transitions: from_state → set of allowed to_states
_VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {AgentState.UNDERSTANDING, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.UNDERSTANDING: {AgentState.PLANNING, AgentState.EXECUTING, AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.PLANNING: {AgentState.EXECUTING, AgentState.VERIFYING, AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.EXECUTING: {
        AgentState.OBSERVING, AgentState.WAITING_APPROVAL,
        AgentState.VERIFYING, AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED
    },
    AgentState.OBSERVING: {AgentState.REASONING, AgentState.EXECUTING, AgentState.VERIFYING, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.REASONING: {
        AgentState.EXECUTING, AgentState.VERIFYING,
        AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED
    },
    AgentState.VERIFYING: {AgentState.COMPLETED, AgentState.EXECUTING, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.WAITING_APPROVAL: {AgentState.EXECUTING, AgentState.REASONING, AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.COMPLETED: set(),
    AgentState.FAILED: set(),
    AgentState.CANCELLED: set(),
}


@dataclass
class AgentTransition:
    from_state: AgentState
    to_state: AgentState
    timestamp: float
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanStep:
    id: int
    description: str
    status: str = "pending"  # pending | active | completed | failed | skipped
    tool_name: str | None = None
    result_summary: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    observation: dict[str, Any] | None = None


@dataclass
class Observation:
    tool: str
    status: str  # success | error
    facts: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    raw_result: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class VerificationResult:
    task_completed: bool
    evidence_grounded: bool
    tools_executed: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    details: str = ""


@dataclass
class TodoTask:
    """A single task in the agent's dynamic todo list."""
    id: int
    description: str
    status: str = "pending"  # pending | active | completed | failed | retried
    tool_name: str | None = None
    subagent_type: str | None = None
    error: str | None = None
    retry_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None


class TodoManager:
    """
    Dynamic task list that the agent can modify during execution.
    Supports add, complete, fail, retry, insert, reorder, split.
    """

    def __init__(self) -> None:
        self.tasks: list[TodoTask] = []
        self._next_id: int = 1

    def add_task(self, description: str, tool_name: str | None = None,
                 subagent_type: str | None = None, after_id: int | None = None) -> TodoTask:
        """Add a new task. If after_id is given, insert after that task."""
        if len(self.tasks) >= MAX_TODO_TASKS:
            raise RuntimeError(f"Todo limit reached ({MAX_TODO_TASKS})")
        task = TodoTask(
            id=self._next_id,
            description=description,
            tool_name=tool_name,
            subagent_type=subagent_type,
        )
        self._next_id += 1
        if after_id is not None:
            idx = next((i for i, t in enumerate(self.tasks) if t.id == after_id), None)
            if idx is not None:
                self.tasks.insert(idx + 1, task)
                return task
        self.tasks.append(task)
        return task

    def complete_task(self, task_id: int) -> TodoTask | None:
        """Mark a task as completed."""
        task = self._find(task_id)
        if task:
            task.status = "completed"
            task.completed_at = time.monotonic()
        return task

    def fail_task(self, task_id: int, error: str = "") -> TodoTask | None:
        """Mark a task as failed."""
        task = self._find(task_id)
        if task:
            task.status = "failed"
            task.error = error[:500]
        return task

    def retry_task(self, task_id: int) -> TodoTask | None:
        """Mark a task for retry (resets to pending, increments count)."""
        task = self._find(task_id)
        if task and task.retry_count < MAX_RETRIES_PER_TOOL:
            task.status = "retried"
            task.retry_count += 1
            task.error = None
            task.completed_at = None
            return task
        return None

    def start_task(self, task_id: int) -> TodoTask | None:
        """Mark a task as actively being worked on."""
        task = self._find(task_id)
        if task and task.status in ("pending", "retried"):
            task.status = "active"
        return task

    def get_current(self) -> TodoTask | None:
        """Get the current active task, or the next pending one."""
        active = next((t for t in self.tasks if t.status == "active"), None)
        if active:
            return active
        return next((t for t in self.tasks if t.status in ("pending", "retried")), None)

    def get_pending_count(self) -> int:
        return sum(1 for t in self.tasks if t.status in ("pending", "retried", "active"))

    def split_task(self, task_id: int, new_descriptions: list[str]) -> list[TodoTask]:
        """Split a task into multiple sub-tasks."""
        task = self._find(task_id)
        if not task:
            return []
        idx = next((i for i, t in enumerate(self.tasks) if t.id == task_id), None)
        if idx is None:
            return []
        # Remove original and insert replacements
        self.tasks.pop(idx)
        new_tasks = []
        for desc in reversed(new_descriptions):
            new_task = TodoTask(
                id=self._next_id,
                description=desc,
                tool_name=task.tool_name,
                subagent_type=task.subagent_type,
            )
            self._next_id += 1
            self.tasks.insert(idx, new_task)
            new_tasks.append(new_task)
        return list(reversed(new_tasks))

    def reorder(self, new_order: list[int]) -> None:
        """Reorder tasks by list of task IDs."""
        task_map = {t.id: t for t in self.tasks}
        reordered = [task_map[tid] for tid in new_order if tid in task_map]
        # Append any tasks not in new_order
        seen = set(new_order)
        reordered.extend(t for t in self.tasks if t.id not in seen)
        self.tasks = reordered

    def to_dict(self) -> dict[str, Any]:
        """Serialize for SSE and DB storage."""
        current = self.get_current()
        return {
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description,
                    "status": t.status,
                    "tool_name": t.tool_name,
                    "subagent_type": t.subagent_type,
                    "error": t.error,
                    "retry_count": t.retry_count,
                }
                for t in self.tasks
            ],
            "current_task_id": current.id if current else None,
            "pending_count": self.get_pending_count(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TodoManager":
        """Restore from serialized data."""
        mgr = cls()
        for t in data.get("tasks", []):
            task = TodoTask(
                id=t["id"],
                description=t["description"],
                status=t.get("status", "pending"),
                tool_name=t.get("tool_name"),
                subagent_type=t.get("subagent_type"),
                error=t.get("error"),
                retry_count=t.get("retry_count", 0),
            )
            mgr.tasks.append(task)
            mgr._next_id = max(mgr._next_id, task.id + 1)
        return mgr

    def _find(self, task_id: int) -> TodoTask | None:
        return next((t for t in self.tasks if t.id == task_id), None)


class AgentStateMachine:
    """
    Deterministic agent state machine.
    Every transition is explicit and logged.
    """

    def __init__(self) -> None:
        self.state: AgentState = AgentState.IDLE
        self.transitions: list[AgentTransition] = []
        self.plan: list[PlanStep] = []
        self.observations: list[Observation] = []
        self.verification: VerificationResult | None = None
        self.goal: str = ""
        self.iteration: int = 0
        self.tool_call_count: int = 0
        self.start_time: float = 0.0
        self.retries: dict[str, int] = {}  # tool_name → retry count
        self.error_message: str = ""
        self.activity: list[dict[str, Any]] = []
        self.tool_results_context: list[str] = []
        self.todo: TodoManager = TodoManager()

    def transition(
        self, to_state: AgentState, reason: str = "", metadata: dict[str, Any] | None = None
    ) -> AgentTransition:
        """Make an explicit state transition. Raises if invalid."""
        allowed = _VALID_TRANSITIONS.get(self.state, set())
        if to_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self.state.value} → {to_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        t = AgentTransition(
            from_state=self.state,
            to_state=to_state,
            timestamp=time.monotonic(),
            reason=reason,
            metadata=metadata or {},
        )
        self.transitions.append(t)
        old_state = self.state
        self.state = to_state
        logger.info(
            "Agent state: %s → %s (%s)", old_state.value, to_state.value, reason
        )
        return t

    def start(self, goal: str) -> None:
        """Initialize the agent for a new task."""
        self.goal = goal
        self.start_time = time.monotonic()
        self.iteration = 0
        self.tool_call_count = 0
        self.retries.clear()
        self.observations.clear()
        self.plan.clear()
        self.verification = None
        self.error_message = ""
        self.activity.clear()
        self.tool_results_context.clear()
        self.todo = TodoManager()
        self.transition(AgentState.UNDERSTANDING, reason=f"Goal: {goal[:100]}")

    def create_plan(self, steps: list[dict[str, str]]) -> None:
        """Create a structured plan from LLM output."""
        self.plan = []
        for i, step in enumerate(steps):
            self.plan.append(PlanStep(
                id=i + 1,
                description=step.get("description", ""),
                tool_name=step.get("tool_name"),
            ))
        self.transition(AgentState.PLANNING, reason=f"Plan with {len(self.plan)} steps")

    def start_execution(self) -> None:
        """Transition to execution. Handles state from various predecessors."""
        self.iteration += 1
        # If already executing, skip transition
        if self.state == AgentState.EXECUTING:
            return
        # If in OBSERVING or REASONING, go through REASONING first
        if self.state in (AgentState.OBSERVING, AgentState.REASONING):
            if self.state == AgentState.OBSERVING:
                self.transition(AgentState.REASONING, reason="Analysis complete")
        self.transition(AgentState.EXECUTING, reason=f"Iteration {self.iteration}")

    def record_tool_call(self, tool_name: str, call_id: str, input_summary: str) -> None:
        """Record a tool call in activity."""
        self.tool_call_count += 1
        self.activity.append({
            "tool": tool_name,
            "call_id": call_id,
            "input_summary": input_summary,
            "status": "running",
            "started_at": time.monotonic(),
        })

    def record_tool_result(
        self, tool_name: str, call_id: str, status: str,
        result_summary: str, duration_ms: int, error: str | None = None
    ) -> None:
        """Record tool result in activity."""
        for a in self.activity:
            if a.get("call_id") == call_id:
                a["status"] = status
                a["result_summary"] = result_summary
                a["duration_ms"] = duration_ms
                a["error"] = error
                a["completed_at"] = time.monotonic()
                break

    def observe(self, observation: Observation) -> None:
        """Record an observation after tool execution."""
        self.observations.append(observation)
        self.transition(AgentState.OBSERVING, reason=f"Observed: {observation.tool}")

    def reason(self) -> None:
        """Transition to reasoning state."""
        self.transition(AgentState.REASONING, reason=f"Based on {len(self.observations)} observations")

    def request_approval(self, tool_name: str) -> None:
        """Transition to waiting for approval."""
        self.transition(
            AgentState.WAITING_APPROVAL,
            reason=f"Approval needed for: {tool_name}"
        )

    def verify(self, verification: VerificationResult) -> None:
        """Record verification result."""
        self.verification = verification
        self.transition(AgentState.VERIFYING, reason=f"Task completed: {verification.task_completed}")

    def complete(self) -> None:
        """Mark as completed."""
        self.transition(AgentState.COMPLETED, reason="Task completed")

    def fail(self, error: str) -> None:
        """Mark as failed."""
        self.error_message = error
        self.transition(AgentState.FAILED, reason=error)

    def cancel(self) -> None:
        """Mark as cancelled."""
        self.transition(AgentState.CANCELLED, reason="User cancelled")

    def can_retry(self, tool_name: str) -> bool:
        """Check if we can retry a failed tool."""
        count = self.retries.get(tool_name, 0)
        return count < MAX_RETRIES_PER_TOOL

    def record_retry(self, tool_name: str) -> None:
        """Record a retry attempt."""
        self.retries[tool_name] = self.retries.get(tool_name, 0) + 1

    def check_limits(self) -> str | None:
        """Check if any safety limit is exceeded. Returns error message or None."""
        elapsed = time.monotonic() - self.start_time
        if elapsed > MAX_EXECUTION_TIME_SECONDS:
            return f"Execution time exceeded ({elapsed:.0f}s > {MAX_EXECUTION_TIME_SECONDS}s)"
        if self.iteration > MAX_ITERATIONS:
            return f"Iterations exceeded ({self.iteration} > {MAX_ITERATIONS})"
        if self.tool_call_count >= MAX_TOOL_CALLS:
            return f"Tool calls exceeded ({self.tool_call_count} >= {MAX_TOOL_CALLS})"
        if len(self.plan) > MAX_PLAN_STEPS:
            return f"Plan steps exceeded ({len(self.plan)} > {MAX_PLAN_STEPS})"
        return None

    def get_elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        return int((time.monotonic() - self.start_time) * 1000)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for SSE events."""
        return {
            "state": self.state.value,
            "goal": self.goal,
            "iteration": self.iteration,
            "tool_call_count": self.tool_call_count,
            "elapsed_ms": self.get_elapsed_ms(),
            "plan": [
                {
                    "id": s.id,
                    "description": s.description,
                    "status": s.status,
                    "tool_name": s.tool_name,
                    "result_summary": s.result_summary,
                    "error": s.error,
                }
                for s in self.plan
            ],
            "observations": [
                {
                    "tool": o.tool,
                    "status": o.status,
                    "facts": o.facts,
                    "evidence_ids": o.evidence_ids,
                    "duration_ms": o.duration_ms,
                }
                for o in self.observations
            ],
            "verification": {
                "task_completed": self.verification.task_completed,
                "evidence_grounded": self.verification.evidence_grounded,
                "tools_executed": self.verification.tools_executed,
                "failed_tools": self.verification.failed_tools,
                "details": self.verification.details,
            } if self.verification else None,
            "todo": self.todo.to_dict(),
            "error": self.error_message or None,
        }
