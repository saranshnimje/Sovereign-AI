"""
Agent router — create runs, list, detail, cancel.
SSE streaming for live execution trace.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role, resolve_llm_for_role_async, get_client_ip
from models.user import User
from schemas.agent import AgentRunCreate, AgentRunDetail, AgentRunResponse, ToolCallResponse
from services.agent_service import AgentService
from services.embedding_service import EmbeddingService
from services.knowledge_base_service import KnowledgeBaseService
from services.qdrant_service import QdrantService
from services.rag_service import RagService
from services.sandbox_service import SandboxService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agents"])

# Module-level sandbox (one Docker client per process)
_sandbox = SandboxService()


async def _get_agent_service(
    db: AsyncSession = Depends(get_db),
) -> AgentService:
    # Route agent reasoning through the provider bound to the "chat" role.
    llm = await resolve_llm_for_role_async(db, "chat")
    qdrant = QdrantService()
    embedding = EmbeddingService(llm)
    rag = RagService(llm=llm, embedding_svc=embedding, qdrant_svc=qdrant)
    kb = KnowledgeBaseService(db=db, qdrant_svc=qdrant)
    return AgentService(
        db=db,
        llm=llm,
        sandbox=_sandbox,
        rag_service=rag,
        kb_service=kb,
    )


def _map_run(run) -> AgentRunResponse:
    return AgentRunResponse(
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
    )


def _map_tool_call(tc) -> ToolCallResponse:
    import json as _json
    try:
        input_data = _json.loads(tc.input_json) if tc.input_json else {}
    except Exception:
        input_data = {}
    try:
        output_data = _json.loads(tc.output_json) if tc.output_json else None
    except Exception:
        output_data = None
    return ToolCallResponse(
        id=tc.id,
        step_number=tc.step_number,
        tool_name=tc.tool_name,
        input_data=input_data,
        output_data=output_data,
        status=tc.status,
        exit_code=tc.exit_code,
        duration_ms=tc.duration_ms,
        sandbox_used=tc.sandbox_used,
        container_id=tc.container_id,
        created_at=tc.created_at,
    )


@router.get("/capabilities")
async def agent_capabilities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    What can the agent do RIGHT NOW for this user?
    Groups enabled models by provider, lists available tools, plugins.
    """
    from services.tool_catalog import ToolCatalogService
    from dependencies import resolve_llm_for_role_async  # noqa: F401
    from sqlalchemy import select
    from models.provider_model import ProviderModel
    from models.provider import LLMProvider

    catalog = ToolCatalogService(db)
    await catalog.sync()
    tools = [t for t in await catalog.list_tools() if t["available"]]

    res = await db.execute(
        select(ProviderModel.model_id, ProviderModel.family, LLMProvider.name)
        .join(LLMProvider, LLMProvider.id == ProviderModel.provider_id)
        .where(ProviderModel.status == "available",
               ProviderModel.enabled.is_(True),
               LLMProvider.enabled.is_(True))
    )
    models = [{"model_id": m, "family": f, "provider": p}
              for m, f, p in res.all()]

    return {
        "models": models,
        "tools": [{"name": t["name"], "category": t["category"],
                   "description": t["description"]} for t in tools],
        "plugins": [p for p in await catalog.list_plugins() if p["enabled"]],
    }


@router.post("/plan")
async def plan_task(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Classify a goal and recommend model + tools + plugins.
    Heuristic, deterministic, availability-filtered. Read-only.
    """
    goal = (data or {}).get("goal", "")
    if not goal.strip():
        raise HTTPException(422, "goal is required")
    from services.tool_catalog import ToolCatalogService
    catalog = ToolCatalogService(db)
    return await catalog.plan_task(goal, user_role=current_user.role)


@router.post("/runs", response_model=AgentRunResponse, status_code=202)
async def create_run(
    data: AgentRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(require_role("analyst", "admin")),
    svc: AgentService = Depends(_get_agent_service),
):
    run = await svc.create_run(
        user_id=current_user.id,
        client_ip=get_client_ip(request),
        goal=data.goal,
        model_name=data.model_name,
        allowed_tools=data.allowed_tools,
        kb_ids=data.kb_ids,
        max_iterations=data.max_iterations,
    )
    # Execute in background — non-blocking
    background_tasks.add_task(
        svc.execute_run, run.id, current_user.role
    )
    return _map_run(run)


@router.get("/runs", response_model=list[AgentRunResponse])
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    svc: AgentService = Depends(_get_agent_service),
):
    # Viewers see nothing; analysts see their own; admins see all
    uid = None if current_user.role == "admin" else current_user.id
    runs = await svc.list_runs(user_id=uid, limit=limit, offset=offset)
    return [_map_run(r) for r in runs]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    svc: AgentService = Depends(_get_agent_service),
):
    run = await svc.get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if current_user.role != "admin" and run.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    tcs = await svc.get_tool_calls(run_id)
    detail = AgentRunDetail(
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
        tool_calls=[_map_tool_call(tc) for tc in tcs],
    )
    return detail


@router.post("/runs/{run_id}/cancel", response_model=AgentRunResponse)
async def cancel_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    svc: AgentService = Depends(_get_agent_service),
):
    run = await svc.get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if current_user.role != "admin" and run.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    updated = await svc.cancel_run(run_id, current_user.id)
    return _map_run(updated)

@router.get("/tools")
async def list_tools(current_user: User = Depends(get_current_user)):
    """Return the list of registered tools visible to the current user's role."""
    from tools.registry import get_registry
    reg = get_registry()
    tools = reg.list_enabled(user_role=current_user.role)
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": t.risk_level,
            "requires_sandbox": t.requires_sandbox,
            "required_role": t.required_role,
            "tags": t.tags,
        }
        for t in tools
    ]


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    svc: AgentService = Depends(_get_agent_service),
):
    """
    SSE stream of agent run events.
    Creates a fresh DB session per poll to avoid holding a single session
    open across long asyncio.sleep() intervals (SQLAlchemy async sessions
    should not be held across multiple await points at the app level).

    Events emitted:
      status   — run status/iteration update
      step     — new tool call recorded
      complete — run finished (result included)
      error    — run failed
    """
    # Auth check using the injected session (fast, single query)
    run = await svc.get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if current_user.role != "admin" and run.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    # Store auth info for use inside the generator
    allowed_user_id = current_user.id
    is_admin = current_user.role == "admin"

    async def _event_generator():
        from database import AsyncSessionLocal
        from dependencies import resolve_llm_for_role_async as _resolve_llm

        last_step_count = 0
        max_polls = 400  # 400 × 1.5s = 600s max

        for _ in range(max_polls):
            try:
                # Fresh session per poll — avoids holding session across sleeps
                async with AsyncSessionLocal() as poll_db:
                    llm = await _resolve_llm(poll_db, "chat")
                    poll_svc = AgentService(
                        db=poll_db,
                        llm=llm,
                        sandbox=_sandbox,
                    )
                    current_run = await poll_svc.get_run(run_id)
                    if current_run is None:
                        yield f"event: error\ndata: {json.dumps({'message': 'Run not found'})}\n\n"
                        return
                    # Auth re-check
                    if not is_admin and current_run.user_id != allowed_user_id:
                        yield f"event: error\ndata: {json.dumps({'message': 'Access denied'})}\n\n"
                        return

                    tcs = await poll_svc.get_tool_calls(run_id)

                # Emit new tool calls
                new_tcs = tcs[last_step_count:]
                for tc in new_tcs:
                    try:
                        inp = json.loads(tc.input_json) if tc.input_json else {}
                    except Exception:
                        inp = {}
                    try:
                        out = json.loads(tc.output_json) if tc.output_json else None
                    except Exception:
                        out = None
                    step_data = json.dumps({
                        "step_number": tc.step_number,
                        "tool_name": tc.tool_name,
                        "status": tc.status,
                        "input_data": inp,
                        "output_data": out,
                        "duration_ms": tc.duration_ms,
                        "sandbox_used": tc.sandbox_used,
                    })
                    yield f"event: step\ndata: {step_data}\n\n"
                last_step_count = len(tcs)

                # Emit status
                status_data = json.dumps({
                    "status": current_run.status,
                    "iteration_count": current_run.iteration_count,
                    "step_count": current_run.step_count,
                })
                yield f"event: status\ndata: {status_data}\n\n"

                if current_run.status == "completed":
                    yield f"event: complete\ndata: {json.dumps({'result': current_run.result})}\n\n"
                    return
                if current_run.status in ("failed", "cancelled"):
                    yield f"event: error\ndata: {json.dumps({'message': current_run.error_message or current_run.status})}\n\n"
                    return

                await asyncio.sleep(1.5)

            except asyncio.CancelledError:
                return  # Client disconnected — clean exit
            except Exception as exc:
                logger.warning("SSE stream error for run %s: %s", run_id, exc)
                yield f"event: error\ndata: {json.dumps({'message': 'Internal stream error'})}\n\n"
                return

        yield f"event: error\ndata: {json.dumps({'message': 'Stream timeout after 10 minutes'})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
