"""
Sub-agent tools — spawn, query, list, and cancel child agents.

Child agents inherit the authenticated user's identity and role. They must
never execute with an anonymous or synthetic tenant context.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SpawnSubagentInput(BaseModel):
    task: str = Field(..., description="Detailed description of what the sub-agent should accomplish", max_length=2000)
    agent_type: str = Field(..., description="Type of sub-agent: researcher, coder, tester, reviewer, security, data_analyst")
    model: str | None = Field(None, description="Specific model to use", max_length=100)
    tools: list[str] | None = Field(None, description="Optional narrower subset of tools permitted to the requesting user")
    context: str | None = Field(None, description="Additional task context", max_length=5000)


class SpawnSubagentOutput(BaseModel):
    session_id: str
    agent_type: str
    status: str
    message: str


class GetSubagentResultInput(BaseModel):
    session_id: str = Field(..., max_length=50)
    timeout: int = Field(60, ge=1, le=300)


class GetSubagentResultOutput(BaseModel):
    session_id: str
    status: str
    agent_type: str
    summary: str
    findings: list[dict] = []
    artifacts: list[str] = []
    files_changed: list[str] = []
    recommendations: list[str] = []
    elapsed_ms: int = 0
    error: str | None = None


class ListSubagentsInput(BaseModel):
    pass


class ListSubagentsOutput(BaseModel):
    active: list[dict] = []
    completed: list[dict] = []
    total_active: int = 0
    total_completed: int = 0


class CancelSubagentInput(BaseModel):
    session_id: str = Field(..., max_length=50)


class CancelSubagentOutput(BaseModel):
    session_id: str
    status: str
    message: str


_VALID_AGENT_TYPES = {"researcher", "coder", "tester", "reviewer", "security", "data_analyst"}


async def execute_spawn(validated_input: SpawnSubagentInput, context: dict) -> dict:
    from services.subagent_manager import get_subagent_manager

    if validated_input.agent_type not in _VALID_AGENT_TYPES:
        return {"error": f"Invalid agent type '{validated_input.agent_type}'. Must be one of: {', '.join(sorted(_VALID_AGENT_TYPES))}"}

    user = context.get("user")
    user_id = getattr(user, "id", None) if user else None
    user_role = getattr(user, "role", "") if user else ""
    if not user_id:
        return {"error": "Authenticated user context is required to spawn a sub-agent"}

    manager = get_subagent_manager()
    depth = int(context.get("depth", 0)) + 1
    parent_id = context.get("run_id")

    try:
        session = await manager.spawn(
            parent_id=parent_id,
            task=validated_input.task,
            agent_type=validated_input.agent_type,
            model=validated_input.model,
            tools=validated_input.tools,
            context=validated_input.context,
            depth=depth,
            user_role=user_role,
            user_id=str(user_id),
        )
        return {
            "session_id": session.id,
            "agent_type": session.agent_type,
            "status": "running",
            "message": f"Sub-agent '{session.agent_type}' spawned for task: {validated_input.task[:100]}",
        }
    except RuntimeError as exc:
        return {"error": str(exc)}


async def execute_get_result(validated_input: GetSubagentResultInput, context: dict) -> dict:
    from services.subagent_manager import get_subagent_manager
    manager = get_subagent_manager()
    result = await manager.get_result(validated_input.session_id, timeout=validated_input.timeout)
    if result is None:
        session = manager.get_session(validated_input.session_id)
        if session:
            return {"session_id": validated_input.session_id, "status": session.status, "agent_type": session.agent_type, "summary": "Still running or no result yet.", "error": session.error}
        return {"error": f"Sub-agent '{validated_input.session_id}' not found"}
    return {
        "session_id": result.agent_id,
        "status": result.status,
        "agent_type": result.agent_type,
        "summary": result.summary,
        "findings": result.findings,
        "artifacts": result.artifacts,
        "files_changed": result.files_changed,
        "recommendations": result.recommendations,
        "elapsed_ms": result.elapsed_ms,
        "error": None if result.status == "completed" else result.summary,
    }


async def execute_list(validated_input: ListSubagentsInput, context: dict) -> dict:
    from services.subagent_manager import get_subagent_manager
    manager = get_subagent_manager()
    return {"active": [s.to_dict() for s in manager.list_active()], "completed": [s.to_dict() for s in manager.list_completed()], "total_active": len(manager.active), "total_completed": len(manager.completed)}


async def execute_cancel(validated_input: CancelSubagentInput, context: dict) -> dict:
    from services.subagent_manager import get_subagent_manager
    manager = get_subagent_manager()
    cancelled = await manager.cancel(validated_input.session_id)
    return {
        "session_id": validated_input.session_id,
        "status": "cancelled" if cancelled else "not_found",
        "message": f"Sub-agent '{validated_input.session_id}' {'cancelled' if cancelled else 'not found or not running'}",
    }
