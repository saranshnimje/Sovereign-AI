"""
Agent run management router.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.agent import AgentRun, ToolCall
from models.user import User
from schemas.agent import AgentRunDetail, AgentRunResponse, ToolCallResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])


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