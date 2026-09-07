"""Chat router — conversations and streaming messages."""
import asyncio
import json
import logging
import time as _time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from dependencies import get_current_user, resolve_llm_for_role_async
from models.user import User
from models.conversation import Conversation, Message as Msg
from schemas.chat import ConversationCreate, ConversationDetail, ConversationResponse, MessageCreate
from services.chat_service import ChatService
from services.settings_service import load_settings
from services.agent_state import AgentStateMachine
from tools.registry import get_registry
from utils.rate_limit import ai_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

# --- In-memory stream tracker ---
# Maps conv_id -> {user_id, started_at, type}
_active_streams: dict[str, dict] = {}


def _track_stream(conv_id: str, user_id: str, stream_type: str = "direct"):
    _active_streams[conv_id] = {
        "user_id": user_id,
        "started_at": _time.time(),
        "type": stream_type,
    }


def _untrack_stream(conv_id: str):
    _active_streams.pop(conv_id, None)


def get_active_streams_for_user(user_id: str) -> list[str]:
    return [cid for cid, info in _active_streams.items() if info["user_id"] == user_id]


async def _get_chat_service(
    db: AsyncSession = Depends(get_db),
) -> ChatService:
    # Route chat through the provider bound to the "chat" role when one is set;
    # otherwise the default local Ollama instance is used.
    llm = await resolve_llm_for_role_async(db, "chat")
    return ChatService(db, llm)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    svc: ChatService = Depends(_get_chat_service),
):
    return await svc.list_conversations(current_user.id, limit=limit, offset=offset)


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    svc: ChatService = Depends(_get_chat_service),
):
    return await svc.create_conversation(current_user.id, data)


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    svc: ChatService = Depends(_get_chat_service),
):
    return await svc.get_conversation(conv_id, current_user.id)


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    svc: ChatService = Depends(_get_chat_service),
):
    await svc.delete_conversation(conv_id, current_user.id)
    return Response(status_code=204)


@router.get("/conversations/{conv_id}/status")
async def get_conversation_status(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if a conversation has an active stream running."""
    # Verify ownership
    from models.conversation import Conversation
    res = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = res.scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "Conversation not found")

    active = _active_streams.get(conv_id)
    return {
        "active": active is not None,
        "type": active["type"] if active else None,
        "started_at": active["started_at"] if active else None,
    }


@router.get("/conversations/{conv_id}/agent-events")
async def get_agent_events(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get persisted agent execution events for a conversation.

    Returns events ordered by sequence number for rendering the agent timeline.
    """
    from models.agent import AgentRun, AgentEvent
    from models.conversation import Conversation

    # Verify conversation ownership
    res = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = res.scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "Conversation not found")

    # Find agent runs for this conversation (via assistant messages with run_id metadata)
    # We join through messages to find run_ids associated with this conversation
    from sqlalchemy.orm import selectinload
    msg_res = await db.execute(
        select(Msg).where(
            Msg.conversation_id == conv_id,
            Msg.role == "assistant",
        )
    )
    messages = list(msg_res.scalars().all())

    run_ids = set()
    for msg in messages:
        try:
            meta = json.loads(msg.metadata_json) if msg.metadata_json else {}
            if meta.get("run_id"):
                run_ids.add(meta["run_id"])
        except Exception:
            pass

    # Also check agent_runs directly
    run_res = await db.execute(
        select(AgentRun).where(AgentRun.user_id == current_user.id)
    )
    for run in run_res.scalars().all():
        run_ids.add(run.id)

    if not run_ids:
        return {"events": [], "runs": []}

    # Fetch events for all runs
    events = []
    for rid in run_ids:
        evt_res = await db.execute(
            select(AgentEvent).where(
                AgentEvent.run_id == rid
            ).order_by(AgentEvent.sequence)
        )
        for evt in evt_res.scalars().all():
            events.append({
                "id": evt.id,
                "run_id": evt.run_id,
                "sequence": evt.sequence,
                "event_type": evt.event_type,
                "payload": json.loads(evt.payload_json) if evt.payload_json else {},
                "created_at": evt.created_at.isoformat() if evt.created_at else None,
            })

    # Sort by sequence across all runs
    events.sort(key=lambda e: e["sequence"])

    # Fetch run metadata
    runs = []
    run_res2 = await db.execute(
        select(AgentRun).where(AgentRun.id.in_(run_ids))
    )
    for run in run_res2.scalars().all():
        runs.append({
            "id": run.id,
            "goal": run.goal,
            "status": run.status,
            "result": run.result,
            "step_count": run.step_count,
            "model_name": run.model_name,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        })

    return {"events": events, "runs": runs}


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: str,
    request: Request,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    svc: ChatService = Depends(_get_chat_service),
    _rl: None = Depends(ai_rate_limit),
):
    """
    Send a message and receive a streaming SSE response.
    Content-Type: text/event-stream

    SSE event types:
      token    — incremental text token
      evidence — RAG sources (once, before first token, if rag_kb_ids provided)
      done     — stream complete
      error    — error occurred

    Routing precedence for the LLM connection:
      1. data.provider_id  (explicit per-message selection from the Chat UI)
      2. provider bound to the "chat" role in model settings
      3. default local Ollama instance
    """
    # Read rag_kb_ids from raw body (schema skips unknown fields with extra="allow")
    rag_kb_ids: list[str] | None = None
    try:
        raw_body = await request.body()
        if raw_body:
            body_json = _json.loads(raw_body)
            rag_kb_ids = body_json.get("rag_kb_ids")
    except Exception:
        pass

    # Resolve LLM provider
    if data.provider_id:
        from sqlalchemy import select as _select
        from models.provider import LLMProvider as _LLMProvider
        from services.llm_client import build_provider as _build

        result = await db.execute(
            _select(_LLMProvider).where(_LLMProvider.id == data.provider_id)
        )
        provider = result.scalar_one_or_none()
        if provider is None:
            raise HTTPException(404, "Provider not found")
        if not provider.enabled:
            raise HTTPException(400, "Provider is disabled")
        logger.info("Chat using provider=%s type=%s url=%s model=%s",
                     provider.name, provider.provider_type, provider.base_url, data.model_name)
        llm = _build(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            api_key=provider.api_key,
            custom_headers=provider.custom_headers if hasattr(provider, 'custom_headers') and provider.custom_headers else None,
        )
        svc = ChatService(db, llm)
    else:
        logger.info("Chat using default provider (model=%s)", data.model_name)

    # --- RAG retrieval (when rag_kb_ids provided) ---
    rag_sources: list[dict] | None = None
    rag_context: str | None = None

    if rag_kb_ids:
        try:
            from services.rag_service import RagService
            from services.embedding_service import EmbeddingService
            from services.qdrant_service import QdrantService
            from services.knowledge_base_service import KnowledgeBaseService
            from models.knowledge_base import KnowledgeBase

            sys_settings = load_settings()
            emb_llm = await resolve_llm_for_role_async(db, "embedding")
            embedding_svc = EmbeddingService(emb_llm)
            qdrant_svc = QdrantService()

            # Verify user has access to all requested KBs (authorization gate)
            kb_result = await db.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(rag_kb_ids),
                    KnowledgeBase.user_id == current_user.id,
                )
            )
            authorized_kbs = list(kb_result.scalars().all())
            authorized_ids = {kb.id for kb in authorized_kbs}

            # Only search KBs the user is authorized for
            all_sources: list[dict] = []
            context_parts: list[str] = []
            for kb_id in rag_kb_ids:
                if kb_id not in authorized_ids:
                    # Honest not-found: do not reveal KB existence
                    continue
                kb = next(kb for kb in authorized_kbs if kb.id == kb_id)
                rag_svc = RagService(
                    llm=svc.llm,
                    embedding_svc=embedding_svc,
                    qdrant_svc=qdrant_svc,
                )
                try:
                    result = await rag_svc.query(
                        kb_id=kb_id,
                        embedding_model=kb.embedding_model or sys_settings.default_embedding_model,
                        chat_model=data.model_name or "llama3.2:3b",
                        query=data.content,
                        top_k=sys_settings.default_top_k,
                        score_threshold=sys_settings.default_score_threshold,
                        generate_answer=False,
                    )
                    for src in result.sources:
                        all_sources.append({
                            "source_type": "document",
                            "doc_id": src.doc_id,
                            "chunk_id": src.chunk_id,
                            "filename": src.filename,
                            "page_number": src.page_number,
                            "score": src.score,
                            "content": src.content,
                            "citation_label": (
                                f"[Doc {len(all_sources)+1}: {src.filename}"
                                f"{', p.' + str(src.page_number) if src.page_number else ''}]"
                            ),
                        })
                        context_parts.append(
                            f"<document source=\"[Source {len(all_sources)}] "
                            f"{src.filename}{', p.' + str(src.page_number) if src.page_number else ''}\">\n"
                            f"{src.content[:800]}\n</document>"
                        )
                except Exception as exc:
                    logger.warning("RAG retrieval failed for KB %s: %s", kb_id, exc)

            if all_sources:
                rag_sources = all_sources
                rag_context = "\n\n".join(context_parts)

        except Exception as exc:
            logger.warning("RAG setup failed: %s", exc)
            # Continue without RAG — honest degradation

    async def _tracked_stream():
        _track_stream(conv_id, current_user.id, "direct")
        try:
            async for chunk in svc.stream_message(
                conv_id, current_user.id, data,
                rag_sources=rag_sources,
                rag_context=rag_context,
            ):
                yield chunk
        finally:
            _untrack_stream(conv_id)

    return StreamingResponse(
        _tracked_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{conv_id}/agent")
async def send_agent_message(
    conv_id: str,
    data: MessageCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(ai_rate_limit),
    _session_factory=None,
):
    """
    Agent-mode chat — thin router that delegates to AgentRuntime.

    SSE events:
      agent_state, plan_created, plan_updated, decision, tool_call,
      tool_result, observation, verification, token, done, error, cancelled
    """
    body = data.model_dump()
    tool_mode = (body.get("tool_mode") or "auto")
    agent_mode = (body.get("agent_mode") or "agent")
    manual_tools = body.get("tools") or []

    # Use injected db for initial lookups (conversation, provider)
    # Create a self-managed session for the streaming generator
    # _session_factory allows test injection to use in-memory DB
    from database import AsyncSessionLocal
    session = (_session_factory or AsyncSessionLocal)()

    try:
        if data.provider_id:
            from models.provider import LLMProvider as _P
            from services.llm_client import build_provider as _build
            res = await db.execute(select(_P).where(_P.id == data.provider_id))
            prov = res.scalar_one_or_none()
            if prov is None:
                raise HTTPException(404, "Provider not found")
            if not prov.enabled:
                raise HTTPException(400, "Provider is disabled")
            llm = _build(prov.provider_type, prov.base_url, prov.api_key,
                         custom_headers=prov.custom_headers if hasattr(prov, 'custom_headers') and prov.custom_headers else None)
            model_label = f"{prov.name} / {data.model_name or prov.model_name}"
        else:
            llm = await resolve_llm_for_role_async(session, "chat")
            model_label = f"Auto / {data.model_name or 'default'}"

        from sqlalchemy.orm import selectinload
        res = await db.execute(select(Conversation).options(
            selectinload(Conversation.messages)
        ).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id))
        conv = res.scalar_one_or_none()
        if conv is None:
            raise HTTPException(404, "Conversation not found")
    except HTTPException:
        await session.close()
        raise
    except Exception:
        await session.close()
        raise

    # Build tool list
    reg = get_registry()
    available_tools = reg.list_enabled(user_role=current_user.role)
    tool_names = [t.name for t in available_tools]
    if tool_mode == "none":
        tool_names = []
    elif tool_mode == "manual":
        tool_names = [t for t in manual_tools if isinstance(t, str) and t in tool_names]

    # TASK 1: Filter out search_kb when no knowledge bases exist for this user.
    # Without this, the agent attempts search_kb with a missing kb_id → validation
    # error → retry loop → never recovers.
    # When KBs DO exist, collect their IDs so runtime can auto-inject kb_id.
    user_kb_ids: list[str] = []
    if "search_kb" in tool_names:
        try:
            from models.knowledge_base import KnowledgeBase
            kb_res = await db.execute(
                select(KnowledgeBase.id).where(KnowledgeBase.owner_id == current_user.id)
            )
            user_kb_ids = [row[0] for row in kb_res.all()]
            if not user_kb_ids:
                tool_names = [t for t in tool_names if t != "search_kb"]
                logger.info("Filtered search_kb: user %s has no knowledge bases", current_user.id)
            else:
                logger.info("User %s has %d KBs, search_kb will auto-inject kb_id", current_user.id, len(user_kb_ids))
        except Exception:
            # If KB query fails, keep search_kb (honest degradation)
            pass

    tool_descriptions = reg.get_tool_list_for_prompt(
        allowed_names=tool_names, user_role=current_user.role
    )

    # Persist user message
    user_msg = Msg(conversation_id=conv_id, role="user",
                   content=data.content,
                   metadata_json=json.dumps({"local": True, "agent": True}))
    session.add(user_msg)
    await session.flush()
    try:
        await session.commit()
    except Exception:
        logger.warning("Failed to commit user message (non-fatal)", exc_info=True)

    # Initialize agent state
    agent = AgentStateMachine()

    # Create AgentRun record for durable execution tracking
    from models.agent import AgentRun
    agent_run = AgentRun(
        user_id=current_user.id,
        goal=data.content,
        status="running",
        model_name=data.model_name,
    )
    session.add(agent_run)
    await session.flush()
    run_id = agent_run.id

    # Delegate to runtime
    from services.agent.runtime import AgentRuntime, _PERSIST_EVENT_TYPES

    runtime = AgentRuntime()

    async def _gen():
        nonlocal tool_names

        logger.info("Agent generator started: conv=%s run_id=%s model=%s provider_id=%s tool_mode=%s agent_mode=%s",
                     conv_id, run_id, data.model_name, data.provider_id, tool_mode, agent_mode)

        full_content = ""
        try:
            async for event_str in runtime.run(
                goal=data.content,
                user_id=current_user.id,
                user_role=current_user.role,
                model=data.model_name or data.model_name,
                llm=llm,
                db=session,
                tool_names=tool_names,
                tool_descriptions=tool_descriptions,
                conversation_id=conv_id,
                agent_state=agent,
                agent_mode=agent_mode,
                run_id=run_id,
                user_kb_ids=user_kb_ids,
            ):
                # On final_response: persist assistant message BEFORE yielding
                # This ensures DONE => final response already exists in DB
                if event_str.startswith("event: final_response\n"):
                    try:
                        payload = json.loads(event_str.split("data: ", 1)[1].split("\n\n", 1)[0])
                        full_content = payload.get("content", "")
                    except Exception:
                        pass

                    if full_content:
                        try:
                            assistant_msg = Msg(
                                conversation_id=conv_id,
                                role="assistant",
                                content=full_content,
                                metadata_json=json.dumps({
                                    "local": True, "agent": True,
                                    "state": agent.state.value,
                                    "tool_calls": agent.tool_call_count,
                                    "run_id": run_id,
                                })
                            )
                            session.add(assistant_msg)
                            await session.flush()
                            await session.commit()
                        except Exception:
                            logger.warning("Failed to persist assistant message", exc_info=True)

                # Yield event to frontend
                yield event_str

                # TASK 6: Persist key lifecycle events to DB for durable timeline.
                # This ensures agent_events table has a complete record even if
                # the frontend misses events during streaming.
                # Skip agent_started — runtime already persists it manually.
                if event_str.startswith("event: ") and not event_str.startswith("event: agent_started"):
                    try:
                        ev_type = event_str.split("event: ", 1)[1].split("\n", 1)[0].strip()
                        if ev_type in _PERSIST_EVENT_TYPES:
                            ev_payload = json.loads(event_str.split("data: ", 1)[1].split("\n\n", 1)[0])
                            from models.agent import AgentEvent
                            # Continue sequence from runtime's counter to avoid
                            # duplicate seq numbers (runtime already used seq 1 for agent_started)
                            if not hasattr(_gen, '_evt_seq'):
                                from sqlalchemy import func, select
                                max_seq_q = await session.execute(
                                    select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                                        AgentEvent.run_id == run_id
                                    )
                                )
                                _gen._evt_seq = max_seq_q.scalar()
                            _evt_seq = _gen._evt_seq + 1
                            _gen._evt_seq = _evt_seq
                            evt = AgentEvent(
                                run_id=run_id,
                                sequence=_evt_seq,
                                event_type=ev_type,
                                payload_json=json.dumps(ev_payload, default=str),
                            )
                            session.add(evt)
                            await session.flush()
                    except Exception:
                        pass  # Non-fatal: persistence failure must not break the stream

                # Collect final content from done event (fallback)
                if event_str.startswith("event: done\n"):
                    try:
                        payload = json.loads(event_str.split("data: ", 1)[1].split("\n\n", 1)[0])
                        if not full_content:
                            full_content = payload.get("content", "")
                    except Exception:
                        pass
        except Exception as exc:
            # TASK 5: If the runtime generator throws mid-stream, emit a done
            # event with error state so the frontend sees a completed lifecycle
            # instead of a raw network error / connection reset.
            logger.exception("Agent generator error: %s", exc)
            if agent.state.value not in ("completed", "failed", "cancelled"):
                agent.fail(str(exc)[:200])
            error_done = _sse("done", {
                "content": full_content,
                "token_count": 0,
                "activity": agent.activity,
                "tool_calls": agent.tool_call_count,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan": [],
                "observations": [],
                "verification": None,
            })
            yield error_done

        # Update AgentRun status after stream completes
        try:
            agent_run.status = agent.state.value if agent.state.value in (
                "completed", "failed", "cancelled", "timed_out"
            ) else "completed"
            agent_run.result = full_content[:10000] if full_content else None
            agent_run.step_count = agent.tool_call_count
            agent_run.plan_json = json.dumps([
                {"id": s.id, "description": s.description, "status": s.status}
                for s in agent.plan
            ]) if agent.plan else None
            await session.commit()
        except Exception:
            logger.warning("Failed to update AgentRun status", exc_info=True)

        # Audit log
        try:
            from services.audit_service import AuditService as _AuditSvc
            svc = _AuditSvc(session)
            await svc.log(
                event_type="agent",
                action="agent_complete",
                outcome=agent.state.value,
                user_id=current_user.id,
                resource_type="conversation",
                resource_id=conv_id,
                metadata={
                    "conversation_id": conv_id,
                    "state": agent.state.value,
                    "tool_calls": agent.tool_call_count,
                },
            )
            await session.commit()
        except Exception:
            logger.warning("Failed to log audit event", exc_info=True)

    async def _tracked_agent_gen():
        """Wrap _gen() with heartbeat keepalive to prevent SSE idle timeout.

        Yields SSE `: heartbeat\n\n` comments every 15 seconds during long
        LLM calls.  The Nginx proxy_read_timeout is 600s, so 15s keepalives
        provide a large safety margin.  On failure, closes the DB session.
        """
        import asyncio as _aio

        heartbeat_event = _aio.Event()

        async def _heartbeat_ticker():
            """Set the heartbeat event every 15 seconds."""
            try:
                while True:
                    await _aio.sleep(15)
                    heartbeat_event.set()
            except _aio.CancelledError:
                return

        ticker_task = _aio.ensure_future(_heartbeat_ticker())
        try:
            async for chunk in _gen():
                # After yielding each chunk, check if heartbeat is due
                if heartbeat_event.is_set():
                    heartbeat_event.clear()
                    yield ": heartbeat\n\n"
                yield chunk
            # Final heartbeat check after stream ends
            if heartbeat_event.is_set():
                yield ": heartbeat\n\n"
        except _aio.CancelledError:
            pass
        finally:
            ticker_task.cancel()
            try:
                await ticker_task
            except _aio.CancelledError:
                pass

            if session.is_active:
                try:
                    await session.close()
                except Exception:
                    pass

    async def _tracked_stream_with_untrack():
        _track_stream(conv_id, current_user.id, "agent")
        try:
            async for chunk in _tracked_agent_gen():
                yield chunk
        finally:
            _untrack_stream(conv_id)

    return StreamingResponse(
        _tracked_stream_with_untrack(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/conversations/{conv_id}/export")
async def export_conversation(
    conv_id: str,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    current_user: User = Depends(get_current_user),
    svc: ChatService = Depends(_get_chat_service),
):
    content = await svc.export_conversation(conv_id, current_user.id, fmt=format)
    media_type = "application/json" if format == "json" else "text/markdown"
    filename = f"conversation_{conv_id[:8]}.{('json' if format == 'json' else 'md')}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/conversations/{conv_id}")
async def rename_conversation(
    conv_id: str,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a conversation. Owner-only; foreign IDs return 404."""
    from models.conversation import Conversation
    title = (data or {}).get("title", "").strip()
    if not title:
        raise HTTPException(422, "title is required")
    res = await db.execute(select(Conversation).where(
        Conversation.id == conv_id, Conversation.user_id == current_user.id))
    conv = res.scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    conv.title = title[:200]
    await db.flush()
    return {"id": conv.id, "title": conv.title}

