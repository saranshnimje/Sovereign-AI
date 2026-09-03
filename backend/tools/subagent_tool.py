"""
Sub-agent tools — spawn, query, list, and cancel child agents.

These tools allow the main agent to delegate work to specialized sub-agents
that run in parallel with their own context, tools, and model.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SpawnSubagentInput(BaseModel):
    """Input schema for spawn_subagent tool."""
    task: str = Field(
        ...,
        description="Detailed description of what the sub-agent should accomplish",
        max_length=2000,
    )
    agent_type: str = Field(
        ...,
        description="Type of sub-agent: researcher, coder, tester, reviewer, security, data_analyst",
    )
    model: str | None = Field(
        None,
        description="Specific model to use (e.g. 'llama3.2:3b'). Uses default if omitted.",
        max_length=100,
    )
    tools: list[str] | None = Field(
        None,
        description="Override the default tool list for this agent type. Optional.",
    )
    context: str | None = Field(
        None,
        description="Additional context to provide the sub-agent (e.g. file contents, error messages)",
        max_length=5000,
    )


class SpawnSubagentOutput(BaseModel):
    """Output schema for spawn_subagent tool."""
    session_id: str
    agent_type: str
    status: str
    message: str


class GetSubagentResultInput(BaseModel):
    """Input schema for get_subagent_result tool."""
    session_id: str = Field(
        ...,
        description="The session ID of the sub-agent to query",
        max_length=50,
    )
    timeout: int = Field(
        60,
        description="Maximum seconds to wait for the result (default 60)",
        ge=1,
        le=300,
    )


class GetSubagentResultOutput(BaseModel):
    """Output schema for get_subagent_result tool."""
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
    """Input schema for list_subagents tool."""
    pass


class ListSubagentsOutput(BaseModel):
    """Output schema for list_subagents tool."""
    active: list[dict] = []
    completed: list[dict] = []
    total_active: int = 0
    total_completed: int = 0


class CancelSubagentInput(BaseModel):
    """Input schema for cancel_subagent tool."""
    session_id: str = Field(
        ...,
        description="The session ID of the sub-agent to cancel",
        max_length=50,
    )


class CancelSubagentOutput(BaseModel):
    """Output schema for cancel_subagent tool."""
    session_id: str
    status: str
    message: str


async def execute_spawn(validated_input: SpawnSubagentInput, context: dict) -> dict:
    """Spawn a new sub-agent to work on a task."""
    from services.subagent_manager import get_subagent_manager

    # Validate agent type
    valid_types = {"researcher", "coder", "tester", "reviewer", "security", "data_analyst"}
    if validated_input.agent_type not in valid_types:
        return {"error": f"Invalid agent type '{validated_input.agent_type}'. Must be one of: {', '.join(valid_types)}"}

    manager = get_subagent_manager()

    # Get depth from parent context
    depth = context.get("depth", 0) + 1
    parent_id = context.get("run_id")

    # Get user role from context
    user = context.get("user")
    user_role = getattr(user, "role", "analyst") if user else "analyst"

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
    """Wait for and retrieve a sub-agent's result."""
    from services.subagent_manager import get_subagent_manager

    manager = get_subagent_manager()
    result = await manager.get_result(
        validated_input.session_id,
        timeout=validated_input.timeout,
    )

    if result is None:
        session = manager.get_session(validated_input.session_id)
        if session:
            return {
                "session_id": validated_input.session_id,
                "status": session.status,
                "agent_type": session.agent_type,
                "summary": "Still running or no result yet.",
                "error": session.error,
            }
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
    """List all active and completed sub-agents."""
    from services.subagent_manager import get_subagent_manager

    manager = get_subagent_manager()
    return {
        "active": [s.to_dict() for s in manager.list_active()],
        "completed": [s.to_dict() for s in manager.list_completed()],
        "total_active": len(manager.active),
        "total_completed": len(manager.completed),
    }


async def execute_cancel(validated_input: CancelSubagentInput, context: dict) -> dict:
    """Cancel a running sub-agent."""
    from services.subagent_manager import get_subagent_manager

    manager = get_subagent_manager()
    cancelled = await manager.cancel(validated_input.session_id)

    if cancelled:
        return {
            "session_id": validated_input.session_id,
            "status": "cancelled",
            "message": f"Sub-agent '{validated_input.session_id}' cancelled",
        }
    return {
        "session_id": validated_input.session_id,
        "status": "not_found",
        "message": f"Sub-agent '{validated_input.session_id}' not found or not running",
    }
