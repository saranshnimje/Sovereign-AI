"""
Agent run management router.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.agent import AgentRun, ToolCall
from models.user import User
from schemas.agent import AgentRunCreate, AgentRunDetail, AgentRunResponse, ToolCallResponse
from services.tool_catalog import ToolCatalogService
from utils.rate_limit import ai_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])


class PlanRequest(BaseModel):
    goal: str = Field(..., min_length=1)

    @field_validator("goal")
    @classmethod
    def goal_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Goal must not be empty or whitespace-only")
        return v


@router.get("/runs")
async def list_agent_runs(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AgentRun).order_by(AgentRun.created_at.desc())
    if status:
        query = query.where(AgentRun.status == status)
    # Non-admin users see only their own runs
    if _user.role != "admin":
        query = query.where(AgentRun.user_id == _user.id)
    # Count total
    count_q = select(func.count()).select_from(AgentRun)
    if status:
        count_q = count_q.where(AgentRun.status == status)
    if _user.role != "admin":
        count_q = count_q.where(AgentRun.user_id == _user.id)
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(query.offset(offset).limit(limit))
    items = list(result.scalars().all())
    return {"items": items, "total": total}


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
async def get_agent_run(
    run_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Agent run not found")
    if _user.role != "admin" and run.user_id != _user.id:
        raise HTTPException(403, "Access denied")
    # Fetch tool calls
    tc_result = await db.execute(
        select(ToolCall).where(ToolCall.agent_run_id == run_id).order_by(ToolCall.step_number)
    )
    tool_calls = list(tc_result.scalars().all())
    return AgentRunDetail(
        id=run.id,
        goal=run.goal,
        status=run.status,
        step_count=run.step_count,
        iteration_count=run.iteration_count,
        result=run.result,
        error_message=run.error_message,
        model_name=run.model_name,
        max_iterations=run.max_iterations,
        created_at=run.created_at,
        updated_at=run.updated_at,
        tool_calls=tool_calls,
    )


@router.get("/runs/{run_id}/tool-calls", response_model=list[ToolCallResponse])
async def get_tool_calls(
    run_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify run exists and user has access
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Agent run not found")
    if _user.role != "admin" and run.user_id != _user.id:
        raise HTTPException(403, "Access denied")
    tc_result = await db.execute(
        select(ToolCall).where(ToolCall.agent_run_id == run_id).order_by(ToolCall.step_number)
    )
    return list(tc_result.scalars().all())


@router.post("/runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.status not in ("pending", "running", "awaiting_approval"):
        raise HTTPException(400, f"Cannot cancel run in status '{run.status}'")
    run.status = "cancelled"
    await db.flush()
    return {"detail": "Agent run cancelled", "run_id": run_id}


# ------------------------------------------------------------------
# Create agent run (analyst+ only)
# ------------------------------------------------------------------

@router.post("/runs", status_code=201)
async def create_agent_run(
    data: AgentRunCreate,
    _user: User = Depends(require_role("analyst")),
    db: AsyncSession = Depends(get_db),
):
    # Validate KB ownership if kb_ids provided
    if data.kb_ids:
        from models.knowledge_base import KnowledgeBase

        for kb_id in data.kb_ids:
            kb = await db.get(KnowledgeBase, kb_id)
            if kb is None or (kb.owner_id != _user.id and _user.role != "admin"):
                raise HTTPException(404, "Knowledge base not found")

    run = AgentRun(
        goal=data.goal,
        user_id=_user.id,
        model_name=data.model_name,
        allowed_tools=json.dumps(data.allowed_tools) if data.allowed_tools else None,
        kb_ids=json.dumps(data.kb_ids) if data.kb_ids else None,
        max_iterations=data.max_iterations,
        status="pending",
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return {
        "id": run.id,
        "goal": run.goal,
        "status": run.status,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


# ------------------------------------------------------------------
# Task planner (requires auth)
# ------------------------------------------------------------------

@router.post("/plan")
async def plan_task(
    data: PlanRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ToolCatalogService(db)
    result = await svc.plan_task(data.goal.strip(), _user.role)
    return result


# ------------------------------------------------------------------
# Capabilities (requires auth)
# ------------------------------------------------------------------

@router.get("/capabilities")
async def get_capabilities(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ToolCatalogService(db)
    all_tools = await svc.list_tools()
    tools = [t for t in all_tools if t.get("enabled")]
    all_plugins = await svc.list_plugins()
    plugins = [p for p in all_plugins if p.get("enabled")]
    return {
        "models": [],
        "tools": tools,
        "plugins": plugins,
    }


# ------------------------------------------------------------------
# ASK_USER: Answer a pending question to resume an agent run
# ------------------------------------------------------------------

class UserAnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=5000)


@router.post("/runs/{run_id}/answer")
async def answer_user_question(
    run_id: str,
    data: UserAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(ai_rate_limit),
):
    """Answer a pending ASK_USER question to resume an agent run.

    Returns an SSE stream of the resumed agent execution, matching the
    same event format as the initial agent run. This ensures the frontend
    receives real-time updates without getting stuck on streaming=true.
    """
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Access denied")
    if run.status != "awaiting_user":
        raise HTTPException(400, f"Run is not awaiting user input (status: {run.status})")

    # Persist the answer
    run.user_answer = data.answer
    run.status = "running"
    run.pending_question = None
    run.pending_options_json = None
    await db.flush()

    from services.agent.runtime import AgentRuntime, _sse
    from dependencies import resolve_llm_for_role_async
    from database import AsyncSessionLocal
    from services.agent_state import AgentStateMachine
    from models.conversation import Conversation, Message as Msg
    from sqlalchemy.orm import selectinload
    from tools.registry import get_registry

    async def _resume_stream():
        """Stream SSE events from the resumed agent run."""
        full_content = ""
        try:
            async with AsyncSessionLocal() as resume_db:
                # Resolve LLM
                llm = await resolve_llm_for_role_async(resume_db, "chat")

                # Reload the run
                res = await resume_db.execute(select(AgentRun).where(AgentRun.id == run_id))
                fresh_run = res.scalar_one_or_none()
                if not fresh_run or fresh_run.status != "running":
                    yield _sse("error", {"message": "Run is no longer active"})
                    yield _sse("done", {"content": "", "state": "failed"})
                    return

                # Get conversation history
                conv_res = await resume_db.execute(
                    select(Conversation)
                    .options(selectinload(Conversation.messages))
                    .where(Conversation.id == run.conversation_id)
                )
                conv = conv_res.scalar_one_or_none()
                conversation_history = []
                if conv:
                    for msg in conv.messages[-20:]:
                        if msg.role in ("user", "assistant"):
                            conversation_history.append({"role": msg.role, "content": msg.content})

                # Add the user's answer to conversation history
                conversation_history.append({"role": "user", "content": data.answer})

                # Build the resumed goal with the answer
                resumed_goal = (
                    f"User answered your question: '{run.goal}'\n"
                    f"User's answer: {data.answer}\n\n"
                    f"Continue with the task using this information."
                )

                # Get tool names from plan
                plan_meta = json.loads(run.plan_json or "{}")
                allowed_tools = plan_meta.get("allowed_tools")

                reg = get_registry()
                available_tools = reg.list_enabled(user_role=current_user.role)
                tool_names = [t.name for t in available_tools]
                if allowed_tools:
                    tool_names = [t for t in tool_names if t in allowed_tools]

                tool_descriptions = reg.get_tool_list_for_prompt(
                    allowed_names=tool_names, user_role=current_user.role
                )

                # Get user KB IDs
                user_kb_ids = []
                if "search_kb" in tool_names:
                    from models.knowledge_base import KnowledgeBase
                    kb_res = await resume_db.execute(
                        select(KnowledgeBase.id).where(KnowledgeBase.owner_id == current_user.id)
                    )
                    user_kb_ids = [row[0] for row in kb_res.all()]

                runtime = AgentRuntime()
                agent = AgentStateMachine()

                async for event_str in runtime.run(
                    goal=resumed_goal,
                    user_id=current_user.id,
                    user_role=current_user.role,
                    model=fresh_run.model_name or "default",
                    llm=llm,
                    db=resume_db,
                    tool_names=tool_names,
                    tool_descriptions=tool_descriptions,
                    conversation_id=run.conversation_id,
                    agent_state=agent,
                    agent_mode="agent",
                    run_id=run_id,
                    user_kb_ids=user_kb_ids,
                    conversation_history=conversation_history,
                ):
                    # Extract final content from final_response event
                    if event_str.startswith("event: final_response\n"):
                        try:
                            payload = json.loads(event_str.split("data: ", 1)[1].split("\n\n", 1)[0])
                            full_content = payload.get("content", "")
                        except Exception:
                            pass

                    yield event_str

                # Update run status
                fresh_run.status = agent.state.value if agent.state.value in (
                    "completed", "failed", "cancelled"
                ) else "completed"
                fresh_run.result = full_content[:10000] if full_content else None
                await resume_db.commit()

        except Exception as exc:
            logger.exception("Failed to resume agent run %s: %s", run_id, exc)
            yield _sse("error", {"message": f"Resume failed: {str(exc)[:200]}"})
            yield _sse("done", {
                "content": full_content,
                "state": "failed",
                "token_count": 0,
                "activity": "",
                "tool_calls": 0,
                "elapsed_ms": 0,
                "plan": [],
                "observations": [],
                "verification": None,
            })
            try:
                async with AsyncSessionLocal() as err_db:
                    res = await err_db.execute(select(AgentRun).where(AgentRun.id == run_id))
                    err_run = res.scalar_one_or_none()
                    if err_run:
                        err_run.status = "failed"
                        err_run.error_message = str(exc)[:1000]
                        await err_db.commit()
            except Exception:
                pass

    return StreamingResponse(
        _resume_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )