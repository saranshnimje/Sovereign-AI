"""Chat router — conversations and streaming messages."""
import asyncio
import json as _json
import logging
import time as _time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from dependencies import get_current_user, resolve_llm_for_role_async
from models.user import User
from schemas.chat import ConversationCreate, ConversationDetail, ConversationResponse, MessageCreate
from services.chat_service import ChatService
from services.settings_service import load_settings
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
    _rl: None = Depends(ai_rate_limit),
):
    """
    Agent-mode chat with PLAN → ACT → OBSERVE → REASON → VERIFY flow.

    SSE events:
      agent_state     — state machine transition
      plan            — model + task info + available tools
      plan_step       — individual plan step update
      tool_call       — LLM selected a tool
      tool_started    — execution began
      tool_result     — execution completed
      tool_error      — execution failed
      observation     — structured observation after tool execution
      verification    — verification before final answer
      token           — incremental text token
      done            — stream complete
      error           — error occurred
      cancelled       — user cancelled
    """
    import asyncio
    import json as _json
    import time as _time
    import uuid as _uuid

    from services.llm_client import ChatMessage as _ChatMessage, ModelUnavailableError
    from services.agent_state import (
        AgentStateMachine, AgentState, Observation, VerificationResult,
        MAX_ITERATIONS, MAX_TOOL_CALLS, MAX_EXECUTION_TIME_SECONDS
    )
    from tools.registry import get_registry, RISK_HIGH, RISK_CRITICAL
    from models.conversation import Conversation, Message as _Msg
    from sqlalchemy import select as _select

    body = data.model_dump()
    tool_mode = (body.get("tool_mode") or "auto")
    manual_tools = body.get("tools") or []
    agent_mode = body.get("agent_mode") or "agent"  # "plan" | "agent"

    # --- create self-managed session (outlives FastAPI dependency lifecycle) ---
    from database import AsyncSessionLocal
    session = AsyncSessionLocal()

    try:
        # --- resolve model client ---
        if data.provider_id:
            from models.provider import LLMProvider as _P
            from services.llm_client import build_provider as _build
            res = await session.execute(_select(_P).where(_P.id == data.provider_id))
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

        # --- verify conversation ownership ---
        from sqlalchemy.orm import selectinload
        res = await session.execute(_select(Conversation).options(
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

    # --- build execution context ---
    reg = get_registry()
    available_tools = reg.list_enabled(user_role=current_user.role)
    tool_names = [t.name for t in available_tools]
    if tool_mode == "none":
        tool_names = []
    elif tool_mode == "manual":
        tool_names = [t for t in manual_tools if isinstance(t, str) and t in tool_names]

    tool_descriptions = reg.get_tool_list_for_prompt(
        allowed_names=tool_names, user_role=current_user.role
    )

    from services.rag_service import RagService as _Rag
    from services.embedding_service import EmbeddingService as _Emb
    from services.knowledge_base_service import KnowledgeBaseService as _KbSvc
    from services.qdrant_service import QdrantService as _Qd
    from services.settings_service import load_settings as _ls

    emb_llm = await resolve_llm_for_role_async(session, "embedding")
    qdrant = _Qd()
    sys_settings = _ls()
    exec_ctx = {
        "user_role": current_user.role,
        "user": current_user,
        "db": session,
        "rag_service": _Rag(llm=llm, embedding_svc=_Emb(emb_llm), qdrant_svc=qdrant),
        "kb_service": _KbSvc(db=session, qdrant_svc=qdrant),
    }

    # Initialize state machine
    agent = AgentStateMachine()

    async def _gen():
        nonlocal tool_names

        logger.info("Agent generator started: conv=%s model=%s provider_id=%s tool_mode=%s",
                     conv_id, data.model_name, data.provider_id, tool_mode)

        agent.start(data.content)

        # Emit initial state
        yield _sse("agent_state", agent.to_dict())

        # Persist user message immediately so it survives LLM failures
        user_msg = _Msg(conversation_id=conv_id, role="user",
                        content=data.content,
                        metadata_json=_json.dumps({"local": True, "agent": True}))
        session.add(user_msg)
        await session.flush()
        try:
            await session.commit()
        except Exception:
            logger.warning("Failed to commit user message (non-fatal)", exc_info=True)

        # --- Build system prompt ---
        if tool_mode == "none" or not tool_names:
            system_prompt = (
                "You are Sovereign AI Workbench's AI assistant. "
                "Answer the user's question directly using your knowledge.\n"
            )
        else:
            system_prompt = (
                "You are Sovereign AI Workbench's autonomous AI agent.\n\n"
                "AVAILABLE ACTIONS (respond with ONLY one JSON object):\n\n"
                "1. Call a tool:\n"
                '{{"tool_call": {{"tool": "TOOL_NAME", "input": {{...}}, "reasoning": "why"}}}}\n\n'
                "2. Mark task complete:\n"
                '{{"complete": {{"result": "final answer or summary"}}}}\n\n'
                "3. Replan (when current approach isn't working):\n"
                '{{"replan": {{"reason": "why", "new_steps": ["step1", "step2"]}}}}\n\n'
                "4. Update your todo list:\n"
                '{{"update_todo": {{"action": "add|complete|fail|retry", "task_id": N, "description": "..."}}}}\n\n'
                "5. Spawn a sub-agent for independent work:\n"
                '{{"spawn_subagent": {{"task": "description", "agent_type": "researcher|coder|tester|reviewer"}}}}\n\n'
                "Available tools:\n"
                + tool_descriptions + "\n\n"
                "TODO LIST:\n"
                "{todo_summary}\n\n"
                "HOW TO WORK AUTONOMOUSLY:\n"
                "1. Understand the goal completely\n"
                "2. Create a todo list (use update_todo to add tasks)\n"
                "3. Work through tasks one by one\n"
                "4. After EACH tool call, verify the result succeeded\n"
                "5. If a tool fails, do NOT repeat it — try a different approach\n"
                "6. For independent tasks, use spawn_subagent\n"
                "7. When all tasks are done, verify the overall result\n"
                "8. Only say 'complete' when you've verified success\n\n"
                "VERIFICATION RULES:\n"
                "- If run_command exit_code != 0 → it FAILED, fix the command\n"
                "- If run_powershell exit_code != 0 → it FAILED, fix the script\n"
                "- If file_write returns no path → it FAILED\n"
                "- Never assume a tool succeeded — check the result\n\n"
                "Maximum iterations remaining: {remaining}\n"
                "Previous steps: {summary}\n"
            )

        messages: list[_ChatMessage] = []
        messages.append(_ChatMessage(role="system", content=system_prompt.format(
            todo_summary="No tasks yet — create your todo list with update_todo.",
            remaining=MAX_ITERATIONS,
            summary="None",
        )))
        messages.append(_ChatMessage(role="user", content=data.content))

        final_content = ""
        token_count = 0

        # Check sovereignty
        yield _sse("agent_state", {
            **agent.to_dict(),
            "sovereignty": "local",
            "provider": model_label,
        })

        try:
            # Emit initial plan event with available tools
            yield _sse("plan", {
                "model": model_label,
                "task_type": "agent",
                "tools": tool_names,
            })

            # === PHASE: PLANNING ===
            if tool_mode != "none" and tool_names:
                try:
                    planning_prompt = (
                        f"Task: {data.content}\n\n"
                        f"Available tools: {', '.join(tool_names)}\n\n"
                        "Think step by step:\n"
                        "1. What does the user want?\n"
                        "2. Do I need any tool to answer this accurately?\n"
                        "3. If yes, which tool(s) and what input?\n\n"
                        "Respond with a JSON plan:\n"
                        '{"plan": {"goal": "...", "steps": [{"description": "...", "tool_name": "TOOL_NAME or null"}, ...]}}\n\n'
                        "Keep it simple (max 3 steps). If you can answer from knowledge, use one step with tool_name null.\n"
                    )
                    messages.append(_ChatMessage(role="user", content=planning_prompt))

                    _model = data.model_name or conv.model_name
                    logger.info("Agent planning LLM call: model=%s provider=%s messages=%d", _model, model_label, len(messages))
                    try:
                        resp = None
                        async for _marker, _val in _run_with_heartbeat(
                            llm.chat(
                                model=_model,
                                messages=messages,
                                stream=False,
                                temperature=0.0,
                                max_tokens=1024,
                            ),
                            timeout=120.0,
                        ):
                            if _marker == "tick":
                                yield _sse("agent_state", {
                                    **agent.to_dict(),
                                    "thinking": True,
                                })
                            else:
                                resp = _val
                        logger.info("Agent planning LLM response: content_len=%d", len(resp.content) if hasattr(resp, "content") else 0)
                    except asyncio.TimeoutError:
                        agent.fail("LLM timed out (120s) during planning")
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("error", {"message": f"Model {_model} timed out. Try a smaller model (e.g. llama3.2:3b)."})
                        return
                    except ModelUnavailableError as exc:
                        agent.fail(f"Model unavailable: {exc}")
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("error", {"message": f"Model unavailable: {exc}"})
                        return
                    except Exception as exc:
                        agent.fail(f"LLM error: {str(exc)[:200]}")
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("error", {"message": f"LLM error: {str(exc)[:200]}"})
                        return
                    plan_text = resp.content if hasattr(resp, "content") else str(resp)

                    # Parse plan
                    plan_data = _parse_plan(plan_text)
                    if plan_data:
                        goal = plan_data.get("goal", data.content)
                        steps = plan_data.get("steps", [])

                        # Normalize steps: ensure description and optional tool_name
                        normalized_steps = []
                        for s in steps:
                            if isinstance(s, dict):
                                normalized_steps.append({
                                    "description": s.get("description", ""),
                                    "tool_name": s.get("tool_name") or s.get("tool"),
                                })
                            elif isinstance(s, str):
                                normalized_steps.append({"description": s, "tool_name": None})

                        if normalized_steps:
                            agent.create_plan(normalized_steps)
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("plan", {
                                "model": model_label,
                                "task_type": "agent",
                                "goal": goal,
                                "tools": tool_names,
                                "steps": [
                                    {"id": s.id, "description": s.description, "status": s.status}
                                    for s in agent.plan
                                ],
                            })

                            # Remove the planning prompt from messages
                            messages.pop()
                            messages.pop()
                            messages.append(_ChatMessage(role="user", content=data.content))
                except Exception as exc:
                    logger.warning("Planning failed: %s", exc)
                    # Remove planning messages if added
                    while len(messages) > 2:
                        messages.pop()
                    messages.append(_ChatMessage(role="user", content=data.content))

            # === MAIN AGENT LOOP ===
            for _iteration in range(MAX_ITERATIONS):
                # Check safety limits
                limit_error = agent.check_limits()
                if limit_error:
                    agent.fail(limit_error)
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": limit_error})
                    return

                # Ask LLM
                try:
                    _model = data.model_name or conv.model_name
                    logger.info("Agent main loop LLM call: model=%s provider=%s iteration=%d messages=%d", _model, model_label, _iteration, len(messages))
                    llm_text = None
                    async for _marker, _val in _run_with_heartbeat(
                        llm.chat(
                            model=_model,
                            messages=messages,
                            stream=False,
                            temperature=0.0,
                            max_tokens=2048,
                        ),
                        timeout=120.0,
                    ):
                        if _marker == "tick":
                            yield _sse("agent_state", {
                                **agent.to_dict(),
                                "thinking": True,
                            })
                        else:
                            llm_text = _val.content if hasattr(_val, "content") else str(_val)
                    logger.info("Agent main loop LLM response: len=%d", len(llm_text))
                except asyncio.TimeoutError:
                    agent.fail("LLM timed out (120s)")
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": f"Model {_model} timed out after 120s. Try a smaller model (e.g. llama3.2:3b)."})
                    return
                except ModelUnavailableError as exc:
                    agent.fail(f"Model unavailable: {exc}")
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": f"Model unavailable: {exc}"})
                    return
                except Exception as exc:
                    agent.fail(f"LLM error: {str(exc)[:200]}")
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": f"LLM error: {str(exc)[:200]}"})
                    return

                # Parse all possible LLM actions
                tool_call = _parse_tool_call(llm_text)
                plan_data = _parse_plan(llm_text)
                verification_data = _parse_verification(llm_text)
                complete_data = _parse_complete(llm_text)
                replan_data = _parse_replan(llm_text)
                update_todo_data = _parse_update_todo(llm_text)
                spawn_subagent_data = _parse_spawn_subagent(llm_text)

                # Handle update_todo action
                if update_todo_data and tool_call is None:
                    action = update_todo_data.get("action", "add")
                    task_id = update_todo_data.get("task_id")
                    desc = update_todo_data.get("description", "")
                    if action == "add" and desc:
                        task = agent.todo.add_task(desc)
                        yield _sse("todo_updated", agent.todo.to_dict())
                        yield _sse("todo_task_added", {
                            "task_id": task.id, "description": desc, "status": "pending"
                        })
                    elif action == "complete" and task_id:
                        agent.todo.complete_task(task_id)
                        yield _sse("todo_updated", agent.todo.to_dict())
                    elif action == "fail" and task_id:
                        agent.todo.fail_task(task_id, update_todo_data.get("error", ""))
                        yield _sse("todo_updated", agent.todo.to_dict())
                    elif action == "retry" and task_id:
                        agent.todo.retry_task(task_id)
                        yield _sse("todo_updated", agent.todo.to_dict())

                    # Feed confirmation back to LLM
                    messages.append(_ChatMessage(role="user", content=(
                        f"Todo updated: {action}. Current todo:\n"
                        + _json.dumps(agent.todo.to_dict(), indent=1)
                        + "\nContinue working on your tasks."
                    )))
                    continue

                # Handle replan action
                if replan_data and tool_call is None:
                    reason = replan_data.get("reason", "")
                    new_steps = replan_data.get("new_steps", [])
                    yield _sse("recovery_started", {
                        "reason": reason,
                        "strategy": "replan",
                    })
                    # Reset failed tasks, add new steps
                    for t in agent.todo.tasks:
                        if t.status == "failed":
                            t.status = "pending"
                            t.error = None
                    for step_desc in new_steps:
                        agent.todo.add_task(step_desc)
                    yield _sse("todo_updated", agent.todo.to_dict())
                    yield _sse("recovery_completed", {"strategy": "replan", "success": True})
                    messages.append(_ChatMessage(role="user", content=(
                        f"Replanned: {reason}. Updated todo:\n"
                        + _json.dumps(agent.todo.to_dict(), indent=1)
                        + "\nContinue with the next task."
                    )))
                    continue

                # Handle complete action
                if complete_data and tool_call is None:
                    result_text = complete_data.get("result", "")
                    # Run final verification before accepting completion
                    tools_used = [a["tool"] for a in agent.activity]
                    failed_tools = [a["tool"] for a in agent.activity if a["status"] == "error"]
                    pending_tasks = agent.todo.get_pending_count()

                    # If there are still pending tasks, don't allow completion
                    if pending_tasks > 0:
                        messages.append(_ChatMessage(role="user", content=(
                            f"You have {pending_tasks} unfinished tasks in your todo list. "
                            f"Complete all tasks before finishing. Continue working."
                        )))
                        continue

                    # If tools failed, ask for recovery
                    if failed_tools:
                        messages.append(_ChatMessage(role="user", content=(
                            f"Some tools failed: {', '.join(failed_tools)}. "
                            f"Try to recover or provide a partial result with caveats."
                        )))
                        continue

                    final_content = result_text
                    break

                # Handle spawn_subagent action
                if spawn_subagent_data and tool_call is None:
                    sub_task = spawn_subagent_data.get("task", "")
                    agent_type = spawn_subagent_data.get("agent_type", "researcher")
                    yield _sse("subagent_spawned", {
                        "session_id": f"sub-{_uuid.uuid4().hex[:8]}",
                        "agent_type": agent_type,
                        "task": sub_task[:200],
                    })
                    # For now, feed the sub-agent result as a simulated completion
                    # (Full sub-agent system in Phase 3)
                    messages.append(_ChatMessage(role="user", content=(
                        f"Sub-agent '{agent_type}' received task: {sub_task}\n"
                        f"(Sub-agent execution simulated — full multi-agent coming soon)\n"
                        f"Continue with your main tasks."
                    )))
                    continue

                # No tool call and no special action → final answer
                if tool_call is None:
                    # Check for verification response
                    if verification_data:
                        vr = VerificationResult(
                            task_completed=verification_data.get("task_completed", True),
                            evidence_grounded=len(verification_data.get("evidence", [])) > 0,
                            tools_executed=[a["tool"] for a in agent.activity],
                            failed_tools=[a["tool"] for a in agent.activity if a["status"] == "error"],
                            unsupported_claims=verification_data.get("issues", []),
                            details=str(verification_data.get("evidence", ""))[:500],
                        )
                        agent.verify(vr)
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("verification", {
                            "task_completed": vr.task_completed,
                            "evidence_grounded": vr.evidence_grounded,
                            "tools_executed": vr.tools_executed,
                            "failed_tools": vr.failed_tools,
                            "unsupported_claims": vr.unsupported_claims,
                        })

                        if vr.task_completed:
                            final_content = llm_text
                            break
                        else:
                            messages.append(_ChatMessage(role="user", content=(
                                "Verification failed. Issues:\n"
                                + "\n".join(vr.unsupported_claims + vr.missing_evidence)
                                + "\nFix these issues and try again."
                            )))
                            continue

                    # Normal final answer — but verify if tools were used
                    if agent.activity:
                        yield _sse("verification_started", {"type": "final"})
                        all_ok = all(a["status"] != "error" for a in agent.activity)
                        yield _sse("verification_passed" if all_ok else "verification_failed", {
                            "type": "final",
                            "tools_ok": all_ok,
                        })
                    final_content = llm_text
                    break

                # If tool_mode=none, skip all tool execution
                if tool_mode == "none":
                    final_content = llm_text
                    break

                # === PLAN MODE: skip tool execution, only plan ===
                if agent_mode == "plan":
                    # In plan mode, just return the plan without executing
                    final_content = (
                        f"## Plan\n\n"
                        f"**Goal:** {data.content}\n\n"
                        f"**Tasks:**\n"
                        + "\n".join(
                            f"- [ ] {t.description}"
                            for t in agent.todo.tasks
                        )
                        + f"\n\n*Switch to Agent mode to execute this plan.*"
                    )
                    break

                # === EXECUTE TOOL CALL ===
                tool_name = tool_call.get("tool", "")
                tool_input = tool_call.get("input", {})
                reasoning = tool_call.get("reasoning", "")
                call_id = _uuid.uuid4().hex[:12]

                agent.start_execution()
                yield _sse("agent_state", agent.to_dict())

                # Emit tool_call event
                yield _sse("tool_call", {
                    "call_id": call_id,
                    "tool": tool_name,
                    "input_summary": _input_summary(tool_name, tool_input),
                    "reasoning": reasoning[:200],
                })

                agent.record_tool_call(tool_name, call_id, _input_summary(tool_name, tool_input))

                # Update plan step if matching
                for step in agent.plan:
                    if step.status == "pending" and step.tool_name == tool_name:
                        step.status = "active"
                        step.started_at = _time.monotonic()
                        yield _sse("plan_step", {
                            "id": step.id,
                            "status": "active",
                            "tool_name": tool_name,
                        })
                        break

                # Validate tool exists
                tool_def = reg.get(tool_name)
                if tool_def is None:
                    yield _sse("tool_error", {
                        "call_id": call_id,
                        "tool": tool_name,
                        "error": f"Tool '{tool_name}' not found or not enabled",
                    })
                    agent.record_tool_result(tool_name, call_id, "error", "Not found", 0, f"Tool not found")
                    messages.append(_ChatMessage(role="user", content=(
                        f"Tool '{tool_name}' is not available. Choose a different tool or answer directly."
                    )))
                    continue

                # Permission check
                try:
                    reg.check_permission(tool_def, current_user.role)
                except PermissionError as exc:
                    yield _sse("tool_error", {
                        "call_id": call_id,
                        "tool": tool_name,
                        "error": f"Permission denied: {exc}",
                    })
                    agent.record_tool_result(tool_name, call_id, "error", "Permission denied", 0, str(exc))
                    messages.append(_ChatMessage(role="user", content=(
                        f"Permission denied for tool '{tool_name}'. Choose a different tool or answer directly."
                    )))
                    continue

                # Input validation
                try:
                    validated_input = reg.validate_input(tool_def, tool_input)
                except Exception as exc:
                    yield _sse("tool_error", {
                        "call_id": call_id,
                        "tool": tool_name,
                        "error": f"Invalid input: {str(exc)[:200]}",
                    })
                    agent.record_tool_result(tool_name, call_id, "error", "Invalid input", 0, str(exc)[:200])
                    messages.append(_ChatMessage(role="user", content=(
                        f"Invalid input for tool '{tool_name}': {str(exc)[:200]}. "
                        f"Fix the input or answer directly."
                    )))
                    continue

                # Approval gate for high-risk tools
                if reg.requires_approval(tool_def):
                    agent.request_approval(tool_name)
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("approval_required", {
                        "call_id": call_id,
                        "tool": tool_name,
                        "input_summary": _input_summary(tool_name, tool_input),
                        "risk_level": tool_def.risk_level,
                    })
                    agent.record_tool_result(tool_name, call_id, "error", "Approval required", 0, "High-risk tool requires approval")
                    messages.append(_ChatMessage(role="user", content=(
                        f"Tool '{tool_name}' requires human approval. "
                        f"Proceed without this tool or answer directly."
                    )))
                    continue

                # Execute
                yield _sse("tool_started", {
                    "call_id": call_id,
                    "tool": tool_name,
                })

                t0 = _time.monotonic()
                try:
                    result = await reg.execute(tool_def, validated_input, exec_ctx)
                    duration_ms = int((_time.monotonic() - t0) * 1000)
                    has_error = bool(result.get("error"))
                    status = "error" if has_error else "success"
                    result_summary = _result_summary(tool_name, result)

                    yield _sse("tool_result", {
                        "call_id": call_id,
                        "tool": tool_name,
                        "status": status,
                        "result_summary": result_summary,
                        "duration_ms": duration_ms,
                        "error": result.get("error"),
                    })

                    agent.record_tool_result(tool_name, call_id, status, result_summary, duration_ms, result.get("error"))

                    # Update plan step
                    for step in agent.plan:
                        if step.status == "active" and step.tool_name == tool_name:
                            step.status = "completed" if status == "success" else "failed"
                            step.result_summary = result_summary
                            step.completed_at = _time.monotonic()
                            yield _sse("plan_step", {
                                "id": step.id,
                                "status": step.status,
                                "result_summary": result_summary,
                            })
                            break

                    # Create observation
                    obs = _create_observation(tool_name, result, status, duration_ms)
                    agent.observe(obs)

                    yield _sse("observation", {
                        "tool": tool_name,
                        "status": status,
                        "facts": obs.facts,
                        "evidence_ids": obs.evidence_ids,
                        "duration_ms": duration_ms,
                    })

                    # === AUTONOMOUS VERIFICATION ===
                    passed, reason = _verify_tool_result(tool_name, result)
                    yield _sse("verification_started", {"type": "tool_result", "tool": tool_name})

                    if not passed:
                        # Verification failed — self-correction loop
                        yield _sse("verification_failed", {
                            "type": "tool_result",
                            "tool": tool_name,
                            "reason": reason,
                        })
                        agent.todo.fail_task(
                            agent.todo.get_current().id if agent.todo.get_current() else 0,
                            reason,
                        )
                        yield _sse("todo_updated", agent.todo.to_dict())

                        # Feed failure back to LLM for recovery
                        recovery_msg = (
                            f"VERIFICATION FAILED for '{tool_name}': {reason}\n\n"
                            f"You MUST try a different approach. Do NOT repeat the same action.\n"
                            f"Current goal: {data.content}\n"
                            f"Iteration: {agent.iteration}/{MAX_ITERATIONS}"
                        )
                        messages.append(_ChatMessage(role="user", content=recovery_msg))
                        continue

                    yield _sse("verification_passed", {
                        "type": "tool_result",
                        "tool": tool_name,
                    })

                    # Mark current todo task as completed
                    current_task = agent.todo.get_current()
                    if current_task and current_task.tool_name == tool_name:
                        agent.todo.complete_task(current_task.id)
                        yield _sse("todo_updated", agent.todo.to_dict())

                    # Feed result back to LLM with observation context
                    result_text = _json.dumps(result, default=str)[:2000]
                    agent.tool_results_context.append(f"[{tool_name}]: {result_text}")

                    todo_summary = _json.dumps(agent.todo.to_dict())
                    observation_context = (
                        f"Tool '{tool_name}' completed successfully.\n"
                        f"Result:\n{result_text}\n\n"
                        f"Facts: {', '.join(obs.facts)}\n\n"
                        f"TODO LIST: {todo_summary}\n\n"
                        f"Continue working on your tasks. "
                        f"If all tasks are complete, verify and call 'complete'. "
                        f"Otherwise, call the next tool."
                    )
                    messages.append(_ChatMessage(role="user", content=observation_context))

                except Exception as exc:
                    duration_ms = int((_time.monotonic() - t0) * 1000)
                    yield _sse("tool_result", {
                        "call_id": call_id,
                        "tool": tool_name,
                        "status": "error",
                        "result_summary": None,
                        "duration_ms": duration_ms,
                        "error": str(exc)[:500],
                    })
                    agent.record_tool_result(tool_name, call_id, "error", str(exc)[:200], duration_ms, str(exc)[:500])

                    # Update plan step
                    for step in agent.plan:
                        if step.status == "active" and step.tool_name == tool_name:
                            step.status = "failed"
                            step.error = str(exc)[:200]
                            step.completed_at = _time.monotonic()
                            yield _sse("plan_step", {
                                "id": step.id,
                                "status": "failed",
                                "error": str(exc)[:200],
                            })
                            break

                    messages.append(_ChatMessage(role="user", content=(
                        f"Tool '{tool_name}' failed: {str(exc)[:300]}. "
                        f"Try a different approach or answer directly."
                    )))

            # If we exhausted iterations without a final answer
            if not final_content:
                final_content = llm_text if 'llm_text' in dir() else "I was unable to complete the analysis."

        except asyncio.CancelledError:
            agent.cancel()
            yield _sse("agent_state", agent.to_dict())
            yield _sse("cancelled", {"message": "Cancelled"})
            return
        except Exception as exc:
            logger.exception("Agent loop error: %s", exc)
            agent.fail(str(exc)[:200])
            yield _sse("agent_state", agent.to_dict())
            yield _sse("error", {"message": f"Agent error: {str(exc)[:200]}"})
            return

        # === FINALIZE ===
        if agent.state not in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
            agent.complete()
            yield _sse("agent_state", agent.to_dict())

        # Stream final answer as tokens
        chunk_size = 4
        for i in range(0, len(final_content), chunk_size):
            chunk = final_content[i:i + chunk_size]
            token_count += 1
            yield _sse("token", {"delta": chunk})

        # Persist assistant message
        asst = _Msg(conversation_id=conv_id, role="assistant", content=final_content,
                    token_count=token_count, finish_reason="stop",
                    metadata_json=_json.dumps({
                        "local": True, "model": data.model_name or conv.model_name,
                        "agent": {
                            "activity": agent.activity,
                            "plan": [
                                {"id": s.id, "description": s.description, "status": s.status}
                                for s in agent.plan
                            ],
                            "observations": [
                                {"tool": o.tool, "status": o.status, "facts": o.facts}
                                for o in agent.observations
                            ],
                            "verification": {
                                "task_completed": agent.verification.task_completed,
                                "evidence_grounded": agent.verification.evidence_grounded,
                            } if agent.verification else None,
                            "state": agent.state.value,
                            "elapsed_ms": agent.get_elapsed_ms(),
                        }}))
        session.add(asst)

        if not conv.title and len(conv.messages) <= 2:
            raw = data.content.strip().replace("\n", " ")
            conv.title = raw[:80] + ("..." if len(raw) > 80 else "")
        from datetime import datetime as _dt, timezone as _tz
        conv.updated_at = _dt.now(_tz.utc)
        await session.flush()

        # Audit
        from services.audit_service import AuditService
        audit = AuditService(session)
        await audit.log(
            "agent", "agent.chat.completed", "success",
            user_id=current_user.id,
            resource_type="conversation", resource_id=conv_id,
            metadata={
                "tool_calls": agent.tool_call_count,
                "tools_used": list({a["tool"] for a in agent.activity}),
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan_steps": len(agent.plan),
                "observations": len(agent.observations),
            },
        )

        try:
            await session.commit()
        except Exception:
            logger.warning("Agent commit failed (non-fatal)", exc_info=True)

        yield _sse("done", {
            "token_count": token_count,
            "activity": agent.activity,
            "tool_calls": agent.tool_call_count,
            "state": agent.state.value,
            "elapsed_ms": agent.get_elapsed_ms(),
            "plan": [
                {"id": s.id, "description": s.description, "status": s.status}
                for s in agent.plan
            ],
            "observations": [
                {"tool": o.tool, "status": o.status, "facts": o.facts}
                for o in agent.observations
            ],
            "verification": {
                "task_completed": agent.verification.task_completed,
                "evidence_grounded": agent.verification.evidence_grounded,
            } if agent.verification else None,
        })

        await session.close()

    async def _tracked_agent_gen():
        _track_stream(conv_id, current_user.id, "agent")
        try:
            async for chunk in _gen():
                yield chunk
        finally:
            _untrack_stream(conv_id)
            try:
                if session.is_active:
                    await session.close()
            except Exception:
                pass

    return StreamingResponse(_tracked_agent_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(event: str, payload: dict) -> str:
    import json as _j
    return f"event: {event}\ndata: {_j.dumps(payload)}\n\n"


async def _run_with_heartbeat(coro, timeout: float, heartbeat_interval: float = 25.0):
    """Run a coroutine within `timeout` while yielding periodic heartbeat ticks
    so the SSE connection and upstream proxies stay alive during long blocking
    LLM calls.

    Yields ("tick", None) every `heartbeat_interval` seconds while `coro` is
    running, and finally ("result", value) once it completes. Raises
    asyncio.TimeoutError if `timeout` elapses first.
    """
    import asyncio as _aio

    task = _aio.create_task(coro)
    elapsed = 0.0
    try:
        while True:
            try:
                value = await _aio.wait_for(
                    _aio.shield(task), timeout=heartbeat_interval)
            except _aio.TimeoutError:
                elapsed += heartbeat_interval
                if elapsed >= timeout:
                    raise
                yield ("tick", None)
                continue
            yield ("result", value)
            return
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (_aio.CancelledError, Exception):
                pass


def _verify_tool_result(tool_name: str, result: dict) -> tuple[bool, str]:
    """Objective verification of a tool result. Returns (passed, reason)."""
    if result.get("error"):
        return False, f"Tool error: {str(result['error'])[:200]}"

    if tool_name in ("run_command", "run_powershell"):
        exit_code = result.get("exit_code", -1)
        if exit_code != 0:
            stderr = result.get("stderr", "")[:200]
            return False, f"Command failed (exit {exit_code}): {stderr}"

    if tool_name == "file_write":
        if not result.get("path"):
            return False, "File write did not return a path"

    if tool_name == "python_exec":
        exit_code = result.get("exit_code", -1)
        if exit_code is not None and exit_code != 0:
            return False, f"Python execution failed (exit {exit_code})"

    return True, "OK"


def _build_verification_prompt(tool_name: str, result: dict, goal: str) -> str:
    """Build context for LLM to understand a verification failure."""
    result_summary = str(result)[:500]
    return (
        f"Verification FAILED for tool '{tool_name}'.\n"
        f"Result: {result_summary}\n\n"
        f"Original goal: {goal}\n\n"
        f"Analyze what went wrong and try a different approach. "
        f"Do NOT repeat the same failed action."
    )


async def _tool_args_for(name: str, content: str, user_id: str, db, kb_pref=None, user=None):
    """Build safe canned arguments per tool from the user message."""
    import re as _re2
    from sqlalchemy import select as _sel2
    from models.knowledge_base import KnowledgeBase

    if name == "calculator":
        exprs = _re2.findall(r"[\d\.\+\-\*/\(\)%\s]{3,}", content)
        exprs = [e.strip() for e in exprs if any(c.isdigit() for c in e)]
        if not exprs:
            m = _re2.search(r"(?:what is|calculate|compute)\s+(.+)\?", content, _re2.I)
            if m and any(c.isdigit() for c in m.group(1)):
                exprs = [m.group(1)]
            else:
                return None
        from tools.calculator import CalculatorInput
        return CalculatorInput(expression=exprs[0][:100])
    if name == "web_search":
        from tools.web import WebSearchInput
        q = _re2.sub(r"\b(search|the internet|for|latest|and|summarize|please)\b",
                     " ", content, flags=_re2.I)
        return WebSearchInput(query=(q.strip() or content)[:200])
    if name == "web_fetch":
        m = _re2.search(r"https?://\S+", content)
        if not m:
            return None  # only fetch URLs explicitly present in chat
        from tools.web import WebFetchInput
        return WebFetchInput(url=m.group(0).rstrip(".!?)"))
    if name == "time_now":
        from tools.meta_tools import TimeNowInput
        return TimeNowInput()
    if name == "search_kb":
        if kb_pref:
            from tools.search_kb import SearchKBInput
            return SearchKBInput(kb_id=kb_pref, query=content[:300])
        # Tenancy-scoped fallback: only consider KBs this user may access.
        from services.kb_access import kb_access_filter
        kb = (await db.execute(
            _sel2(KnowledgeBase).where(kb_access_filter(user))
            .order_by(KnowledgeBase.created_at.desc()).limit(1)
        )).scalar_one_or_none() if user is not None else None
        if kb is None:
            return None
        from tools.search_kb import SearchKBInput
        return SearchKBInput(kb_id=kb.id, query=content[:300])
    return None


def _safe_summary(name: str, result: dict) -> str:
    if name == "web_search":
        n = len(result.get("results") or [])
        return f"Retrieved {n} results"
    if name == "web_fetch":
        c = result.get("content") or ""
        return f"Fetched {len(c)} chars"
    if name == "calculator":
        return f"= {result.get('result')}"
    if name == "search_kb":
        n = result.get("count")
        if n is None:
            n = len(result.get("results") or [])
        return f"Retrieved {n} chunks"
    return "completed"


def _parse_tool_call(text: str) -> dict | None:
    """Extract tool_call JSON from LLM response. Returns None if no tool call."""
    import re as _re3
    import json as _j3
    text = _re3.sub(r"```(?:json)?\n?", "", text)
    text = _re3.sub(r"```\n?", "", text)
    m = _re3.search(r"\{.*\}", text, _re3.DOTALL)
    if m:
        try:
            data = _j3.loads(m.group())
            if "tool_call" in data:
                tc = data["tool_call"]
                if isinstance(tc, dict) and "tool" in tc:
                    # Normalize input: some LLMs send "input" as a string instead of dict
                    raw_input = tc.get("input", {})
                    if isinstance(raw_input, str):
                        try:
                            parsed = _j3.loads(raw_input)
                            if isinstance(parsed, dict):
                                tc["input"] = parsed
                        except (_j3.JSONDecodeError, TypeError):
                            pass
                    return tc
        except _j3.JSONDecodeError:
            pass
    return None


def _input_summary(tool_name: str, tool_input: dict) -> str:
    """Generate a safe human-readable summary of tool input (no secrets)."""
    if tool_name == "calculator":
        return tool_input.get("expression", "")[:80]
    if tool_name == "search_kb":
        q = tool_input.get("query", "")[:60]
        return f"Query: {q}"
    if tool_name == "web_search":
        return f"Search: {tool_input.get('query', '')[:60]}"
    if tool_name == "web_fetch":
        url = tool_input.get("url", "")
        return url[:80]
    if tool_name == "system_status":
        return "Checking services"
    if tool_name == "sensor_analysis":
        aid = tool_input.get("analysis_id")
        return f"Analysis #{aid[:12]}" if aid else "New analysis"
    if tool_name == "vision_inspection":
        iid = tool_input.get("image_id") or tool_input.get("incident_id", "")
        return f"Image #{iid[:12]}" if iid else "Vision query"
    if tool_name == "incident_get":
        return f"Incident #{tool_input.get('incident_id', '')[:12]}"
    if tool_name == "incident_investigate":
        return f"Investigate #{tool_input.get('incident_id', '')[:12]}"
    if tool_name == "file_read":
        return f"Read: {tool_input.get('path', '')}"
    if tool_name == "file_write":
        return f"Write: {tool_input.get('path', '')}"
    if tool_name == "file_list":
        return "List files"
    if tool_name == "run_command":
        return f"Shell: {tool_input.get('command', '')[:60]}"
    if tool_name == "run_powershell":
        script = tool_input.get("script", "")[:60]
        return f"PS: {script}"
    if tool_name == "spawn_subagent":
        return f"Subagent: {tool_input.get('task', '')[:50]}"
    if tool_name == "get_subagent_result":
        return f"Get result: {tool_input.get('session_id', '')[:12]}"
    if tool_name == "list_subagents":
        return "List subagents"
    if tool_name == "cancel_subagent":
        return f"Cancel: {tool_input.get('session_id', '')[:12]}"
    return str(tool_input)[:80]


def _result_summary(tool_name: str, result: dict) -> str:
    """Generate a safe human-readable summary of tool result."""
    if result.get("error"):
        return f"Error: {str(result['error'])[:100]}"
    if tool_name == "calculator":
        return f"= {result.get('result')}"
    if tool_name == "search_kb":
        n = result.get("count", len(result.get("results", [])))
        return f"Found {n} chunks"
    if tool_name == "web_search":
        n = len(result.get("results", []))
        return f"Found {n} results"
    if tool_name == "web_fetch":
        c = len(result.get("content", ""))
        return f"Fetched {c} chars"
    if tool_name == "system_status":
        status = result.get("ollama_status", "unknown")
        n = len(result.get("models", []))
        return f"Ollama: {status}, {n} models"
    if tool_name == "sensor_analysis":
        r = result.get("result")
        if r and isinstance(r, dict):
            risk = r.get("risk", {}).get("level", "unknown")
            return f"Risk: {risk}"
        return result.get("status", "completed")
    if tool_name == "vision_inspection":
        return result.get("status", "completed")
    if tool_name == "incident_get":
        inc = result.get("incident")
        if inc:
            return f"{inc.get('title', '')} (risk: {inc.get('risk_level', '?')})"
        return result.get("status", "not_found")
    if tool_name == "incident_investigate":
        return result.get("status", "completed")
    if tool_name in ("file_read", "file_write", "file_list", "file_delete"):
        return str(result.get("content", result.get("path", "done")))[:100]
    if tool_name in ("run_command", "run_powershell"):
        ec = result.get("exit_code", -1)
        stdout = result.get("stdout", "")[:80]
        status = "ok" if ec == 0 else f"exit {ec}"
        return f"{status}: {stdout}"
    if tool_name == "spawn_subagent":
        return f"Spawned: {result.get('session_id', '')[:12]}"
    if tool_name == "get_subagent_result":
        return f"Status: {result.get('status', 'unknown')}"
    return result.get("status", "completed")


def _parse_plan(text: str) -> dict | None:
    """Extract plan JSON from LLM response."""
    import re as _re
    cleaned = _re.sub(r"```(?:json)?\n?", "", text)
    cleaned = _re.sub(r"```\n?", "", cleaned)
    m = _re.search(r'\{[^{}]*"plan"\s*:\s*\{.*\}\s*\}', cleaned, _re.DOTALL)
    if m:
        try:
            obj = _json.loads(m.group())
            if isinstance(obj, dict) and "plan" in obj:
                return obj["plan"]
        except Exception:
            pass
    # Fallback: try to find any object with "goal" and "steps"
    m2 = _re.search(r'\{[^{}]*"goal"\s*:.*"steps"\s*:\s*\[.*?\]\s*\}', cleaned, _re.DOTALL)
    if m2:
        try:
            obj = _json.loads(m2.group())
            if isinstance(obj, dict) and "goal" in obj:
                return obj
        except Exception:
            pass
    return None


def _parse_verification(text: str) -> dict | None:
    """Extract verification JSON from LLM response."""
    import re as _re
    cleaned = _re.sub(r"```(?:json)?\n?", "", text)
    cleaned = _re.sub(r"```\n?", "", cleaned)
    m = _re.search(r'\{[^{}]*"verification"\s*:\s*\{.*\}\s*\}', cleaned, _re.DOTALL)
    if m:
        try:
            obj = _json.loads(m.group())
            if isinstance(obj, dict) and "verification" in obj:
                return obj["verification"]
        except Exception:
            pass
    # Fallback: look for task_completed
    m2 = _re.search(r'\{[^{}]*"task_completed"\s*:\s*(true|false).*\}', cleaned, _re.DOTALL)
    if m2:
        try:
            return _json.loads(m2.group())
        except Exception:
            pass
    return None


def _parse_complete(text: str) -> dict | None:
    """Extract complete action JSON from LLM response."""
    import re as _re
    cleaned = _re.sub(r"```(?:json)?\n?", "", text)
    cleaned = _re.sub(r"```\n?", "", cleaned)
    m = _re.search(r'\{[^{}]*"complete"\s*:\s*\{.*\}\s*\}', cleaned, _re.DOTALL)
    if m:
        try:
            obj = _json.loads(m.group())
            if isinstance(obj, dict) and "complete" in obj:
                return obj["complete"]
        except Exception:
            pass
    return None


def _parse_replan(text: str) -> dict | None:
    """Extract replan action JSON from LLM response."""
    import re as _re
    cleaned = _re.sub(r"```(?:json)?\n?", "", text)
    cleaned = _re.sub(r"```\n?", "", cleaned)
    m = _re.search(r'\{[^{}]*"replan"\s*:\s*\{.*\}\s*\}', cleaned, _re.DOTALL)
    if m:
        try:
            obj = _json.loads(m.group())
            if isinstance(obj, dict) and "replan" in obj:
                return obj["replan"]
        except Exception:
            pass
    return None


def _parse_update_todo(text: str) -> dict | None:
    """Extract update_todo action JSON from LLM response."""
    import re as _re
    cleaned = _re.sub(r"```(?:json)?\n?", "", text)
    cleaned = _re.sub(r"```\n?", "", cleaned)
    m = _re.search(r'\{[^{}]*"update_todo"\s*:\s*\{.*\}\s*\}', cleaned, _re.DOTALL)
    if m:
        try:
            obj = _json.loads(m.group())
            if isinstance(obj, dict) and "update_todo" in obj:
                return obj["update_todo"]
        except Exception:
            pass
    return None


def _parse_spawn_subagent(text: str) -> dict | None:
    """Extract spawn_subagent action JSON from LLM response."""
    import re as _re
    cleaned = _re.sub(r"```(?:json)?\n?", "", text)
    cleaned = _re.sub(r"```\n?", "", cleaned)
    m = _re.search(r'\{[^{}]*"spawn_subagent"\s*:\s*\{.*\}\s*\}', cleaned, _re.DOTALL)
    if m:
        try:
            obj = _json.loads(m.group())
            if isinstance(obj, dict) and "spawn_subagent" in obj:
                return obj["spawn_subagent"]
        except Exception:
            pass
    return None


def _create_observation(tool_name: str, result: dict, status: str, duration_ms: int):
    """Create a structured Observation from tool execution result."""
    from services.agent_state import Observation
    facts: list[str] = []
    evidence_ids: list[str] = []

    if status == "error":
        facts.append(f"{tool_name} failed: {str(result.get('error', 'unknown'))[:100]}")
    else:
        facts.append(f"{tool_name} completed successfully")
        # Extract tool-specific facts
        if tool_name == "sensor_analysis":
            r = result.get("result", {})
            if isinstance(r, dict):
                risk = r.get("risk", {})
                if risk:
                    facts.append(f"Risk level: {risk.get('level', 'unknown')}")
                anomalies = r.get("anomalies", [])
                if anomalies:
                    facts.append(f"{len(anomalies)} anomalies detected")
        elif tool_name == "vision_inspection":
            findings = result.get("findings", [])
            if findings:
                facts.append(f"{len(findings)} findings")
                for f in findings[:3]:
                    if isinstance(f, dict):
                        facts.append(f"  - {f.get('category', 'unknown')}: {f.get('finding', '')[:60]}")
        elif tool_name == "web_search":
            results = result.get("results", [])
            if results:
                facts.append(f"{len(results)} search results")
                for r in results[:3]:
                    if isinstance(r, dict):
                        facts.append(f"  - {r.get('title', '')[:60]}")
        elif tool_name == "web_fetch":
            content = result.get("content", "")
            if content:
                facts.append(f"Fetched {len(content)} chars")
        elif tool_name == "system_status":
            status_val = result.get("ollama_status", "unknown")
            models = result.get("models", [])
            facts.append(f"Ollama: {status_val}, {len(models)} models")
        elif tool_name == "incident_get":
            inc = result.get("incident")
            if inc:
                facts.append(f"Incident: {inc.get('title', '')} (risk: {inc.get('risk_level', '?')})")
        elif tool_name in ("file_read", "file_write", "file_list", "file_delete"):
            path = result.get("path", "")
            if path:
                facts.append(f"File: {path}")
        elif tool_name == "rag_query":
            results = result.get("results", [])
            if results:
                facts.append(f"{len(results)} RAG results")

    return Observation(
        tool=tool_name,
        status=status,
        facts=facts,
        evidence_ids=evidence_ids,
        timestamp_ms=duration_ms,
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

