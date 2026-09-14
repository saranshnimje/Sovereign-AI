"""
Chat service — conversations, messages, and SSE streaming.

Streaming SSE protocol:
  event: token    data: {"delta": "..."}          — incremental text token
  event: evidence data: {"sources": [...], ...}   — RAG evidence (once, before done)
  event: done     data: {"finish_reason": "...", "token_count": N}
  event: error    data: {"code": "...", "message": "..."}

Cancellation: if the client disconnects mid-stream, the generator receives
asyncio.CancelledError which we catch to abort cleanly.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from models.conversation import Conversation, Message
from schemas.chat import ConversationCreate, ConversationDetail, ConversationResponse, MessageCreate, MessageResponse
from services.llm_client import ChatMessage, ModelUnavailableError, OllamaClient
from services.provider_health import provider_health

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, db: AsyncSession, llm: OllamaClient) -> None:
        self.db = db
        self.llm = llm
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    async def list_conversations(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[ConversationResponse]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        convs = list(result.scalars().all())

        responses = []
        for c in convs:
            # Count messages
            count_result = await self.db.execute(
                select(func.count()).where(Message.conversation_id == c.id)
            )
            msg_count = count_result.scalar_one()
            resp = ConversationResponse.model_validate(c)
            resp.message_count = msg_count
            responses.append(resp)
        return responses

    async def create_conversation(
        self, user_id: str, data: ConversationCreate
    ) -> ConversationResponse:
        conv = Conversation(
            user_id=user_id,
            model_name=data.model_name,
            title=data.title,
            system_prompt=data.system_prompt,
        )
        self.db.add(conv)
        await self.db.flush()
        resp = ConversationResponse.model_validate(conv)
        resp.message_count = 0
        return resp

    async def get_conversation(
        self, conv_id: str, user_id: str
    ) -> ConversationDetail:
        result = await self.db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conv_id, Conversation.user_id == user_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            from fastapi import HTTPException
            raise HTTPException(404, "Conversation not found")

        base = ConversationResponse.model_validate(conv)
        detail = ConversationDetail(
            **base.model_dump(),
            messages=[self._map_message(m) for m in conv.messages],
        )
        detail.message_count = len(detail.messages)
        return detail

    async def delete_conversation(self, conv_id: str, user_id: str) -> None:
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == user_id
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            from fastapi import HTTPException
            raise HTTPException(404, "Conversation not found")
        await self.db.delete(conv)
        await self.db.flush()

    # ------------------------------------------------------------------
    # Streaming send-message
    # ------------------------------------------------------------------
    async def stream_message(
        self, conv_id: str, user_id: str, data: MessageCreate,
        rag_sources: list[dict] | None = None,
        rag_context: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Yields SSE-formatted strings.
        Saves user message first, then streams and saves assistant message.

        When rag_sources is provided (from chat router RAG retrieval), an
        evidence event is emitted before the first token so the frontend can
        render citation chips and an evidence panel.

        Cancellation: if the client disconnects, asyncio.CancelledError is
        raised inside this generator. We catch it to abort cleanly without
        saving a partial assistant message.
        """
        sources = rag_sources or []
        full_content = ""
        token_count = 0

        try:
            # Fetch conversation
            result = await self.db.execute(
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .where(Conversation.id == conv_id, Conversation.user_id == user_id)
            )
            conv = result.scalar_one_or_none()
            if not conv:
                yield _sse_error("conversation_not_found", "Conversation not found")
                return

            # Save user message
            user_msg = Message(
                conversation_id=conv_id,
                role="user",
                content=data.content,
                metadata_json=json.dumps({"local": True}),
            )
            self.db.add(user_msg)
            await self.db.flush()

            # Emit evidence event (once, before tokens) if sources present
            if sources:
                evidence_payload = _build_evidence_payload(sources)
                yield _sse_evidence(evidence_payload)

            # Build message history for LLM
            model = data.model_name or conv.model_name
            history: list[ChatMessage] = []
            if conv.system_prompt:
                history.append(ChatMessage(role="system", content=conv.system_prompt))

            # Truncate history to last ~40 messages to stay within context
            recent = conv.messages[-40:] if len(conv.messages) > 40 else conv.messages
            for m in recent:
                if m.id != user_msg.id:
                    history.append(ChatMessage(role=m.role, content=m.content))

            # Inject RAG context into user message if available
            user_content = data.content
            if rag_context:
                user_content = (
                    f"Context from knowledge base:\n{rag_context}\n\n"
                    f"Question: {data.content}\n\n"
                    "Cite sources using [Source N] notation matching the evidence provided."
                )
            history.append(ChatMessage(role="user", content=user_content))

            # Stream from LLM
            finish_reason = "stop"
            try:
                stream = await self.llm.chat(model=model, messages=history, stream=True)
            except ModelUnavailableError as primary_exc:
                # Provider failover: try alternative providers
                logger.warning("Primary LLM failed, attempting failover: %s", primary_exc)
                from services.provider_health import provider_health
                provider_health.record_failure(str(self.llm.__class__.__name__), model, str(primary_exc))

                # Try failover providers
                fallback_llm = await self._get_failover_llm(model)
                if fallback_llm:
                    logger.info("Attempting failover to %s", fallback_llm.__class__.__name__)
                    stream = await fallback_llm.chat(model=model, messages=history, stream=True)
                else:
                    raise

            async for token in stream:  # type: ignore[union-attr]
                full_content += token
                token_count += 1
                yield _sse_token(token)

        except asyncio.CancelledError:
            # Client disconnected — save partial content so the user sees progress
            logger.info("Chat stream cancelled by client disconnect (conv=%s)", conv_id)
            if full_content:
                metadata: dict[str, Any] = {
                    "local": True, "model": model, "partial": True,
                }
                if sources:
                    metadata["evidence"] = _build_evidence_payload(sources)
                assistant_msg = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=full_content,
                    token_count=token_count,
                    finish_reason="cancelled",
                    metadata_json=json.dumps(metadata, default=str),
                )
                self.db.add(assistant_msg)
                from datetime import datetime as _dt, timezone as _tz
                conv.updated_at = _dt.now(_tz.utc)
                try:
                    await self.db.flush()
                    await self.db.commit()
                except Exception:
                    logger.warning("Partial message commit failed", exc_info=True)
            yield _sse_error("cancelled", "Generation cancelled")
            return
        except ModelUnavailableError as exc:
            logger.error("LLM unavailable for model=%s: %s", model, exc)
            yield _sse_error("llm_unavailable", f"The AI model is currently unavailable: {exc}")
            return
        except Exception as exc:
            logger.exception("Unexpected error during chat stream for model=%s: %s", model, exc)
            yield _sse_error("stream_error", f"An unexpected error occurred during streaming: {exc}")
            return

        # Save assistant message (only if we got tokens)
        if full_content:
            metadata: dict[str, Any] = {"local": True, "model": model}
            if sources:
                metadata["evidence"] = _build_evidence_payload(sources)

            assistant_msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content=full_content,
                token_count=token_count,
                finish_reason=finish_reason,
                metadata_json=json.dumps(metadata, default=str),
            )
            self.db.add(assistant_msg)

            # Auto-generate title from first user message (truncate to 80 chars).
            if not conv.title and len(conv.messages) <= 2:
                raw = data.content.strip().replace("\n", " ")
                conv.title = raw[:80] + ("…" if len(raw) > 80 else "")

            from datetime import datetime as _dt, timezone as _tz
            conv.updated_at = _dt.now(_tz.utc)
            await self.db.flush()

            try:
                await self.db.commit()
            except Exception:
                logger.warning("Chat stream commit failed (non-fatal)", exc_info=True)

        yield _sse_done(finish_reason, token_count)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    async def export_conversation(
        self, conv_id: str, user_id: str, fmt: str = "markdown"
    ) -> str:
        detail = await self.get_conversation(conv_id, user_id)

        if fmt == "json":
            return json.dumps(
                {
                    "id": detail.id,
                    "title": detail.title,
                    "model": detail.model_name,
                    "created_at": detail.created_at.isoformat(),
                    "messages": [
                        {"role": m.role, "content": m.content, "ts": m.created_at.isoformat()}
                        for m in detail.messages
                    ],
                },
                indent=2,
            )

        # Markdown
        lines = [
            f"# {detail.title or 'Conversation'}",
            f"**Model:** {detail.model_name}  |  **Date:** {detail.created_at.date()}",
            "",
        ]
        for m in detail.messages:
            role_label = "**You**" if m.role == "user" else f"**{m.role.title()}**"
            lines.append(f"{role_label}: {m.content}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _get_failover_llm(self, model: str):
        """Try alternative providers when the primary one fails."""
        try:
            from sqlalchemy import select as _select
            from models.provider import LLMProvider as _P
            from services.llm_client import build_provider as _build
            from services.provider_health import provider_health

            # Get all enabled providers
            result = await self.db.execute(
                _select(_P).where(_P.enabled == True)
            )
            providers = list(result.scalars().all())

            # Skip the current provider
            current_provider_name = self.llm.__class__.__name__
            for p in providers:
                if p.provider_type in ("ollama",):
                    continue  # Skip local Ollama for failover
                try:
                    provider_key = f"{p.provider_type}:{p.name}"
                    health = provider_health.get(provider_key)
                    if not health.is_available():
                        continue  # Skip unhealthy providers

                    failover_llm = _build(
                        provider_type=p.provider_type,
                        base_url=p.base_url,
                        api_key=p.api_key,
                        custom_headers=p.custom_headers if hasattr(p, 'custom_headers') and p.custom_headers else None,
                    )
                    # Quick health check
                    healthy, _ = await failover_llm.health_check(model)
                    if healthy:
                        return failover_llm
                except Exception as exc:
                    logger.debug("Failover provider %s failed health check: %s", p.name, exc)
                    continue
        except Exception as exc:
            logger.warning("Failover resolution failed: %s", exc)
        return None
    def _map_message(self, m: Message) -> MessageResponse:
        meta: dict | None = None
        if m.metadata_json:
            try:
                meta = json.loads(m.metadata_json)
            except Exception:
                pass
        return MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            token_count=m.token_count,
            finish_reason=m.finish_reason,
            created_at=m.created_at,
            metadata=meta,
        )


# ------------------------------------------------------------------
# SSE helpers
# ------------------------------------------------------------------
def _sse_token(delta: str) -> str:
    data = json.dumps({"delta": delta})
    return f"event: token\ndata: {data}\n\n"


def _sse_evidence(evidence: dict) -> str:
    data = json.dumps(evidence, default=str)
    return f"event: evidence\ndata: {data}\n\n"


def _sse_done(finish_reason: str, token_count: int) -> str:
    data = json.dumps({"finish_reason": finish_reason, "token_count": token_count})
    return f"event: done\ndata: {data}\n\n"


def _sse_error(code: str, message: str) -> str:
    data = json.dumps({"code": code, "message": message})
    return f"event: error\ndata: {data}\n\n"


def _build_evidence_payload(sources: list[dict]) -> dict:
    """
    Build structured evidence payload for the frontend citation system.
    Each source has: index, source_type, label, doc_id, filename,
    page_number, score, content_preview, analysis_id, sensor, severity.
    """
    formatted: list[dict] = []
    for i, src in enumerate(sources, 1):
        entry: dict[str, Any] = {
            "index": i,
            "source_type": src.get("source_type", "document"),
            "label": src.get("citation_label", f"[Source {i}]"),
        }
        # Document-specific fields
        if src.get("doc_id"):
            entry["doc_id"] = src["doc_id"]
        if src.get("filename"):
            entry["filename"] = src["filename"]
        if src.get("page_number") is not None:
            entry["page_number"] = src["page_number"]
        if src.get("score") is not None:
            entry["score"] = round(float(src["score"]), 4)
        if src.get("content"):
            entry["content_preview"] = src["content"][:300]
        # Sensor-specific fields
        if src.get("analysis_id"):
            entry["analysis_id"] = src["analysis_id"]
        if src.get("sensor"):
            entry["sensor"] = src["sensor"]
        if src.get("severity"):
            entry["severity"] = src["severity"]
        formatted.append(entry)

    return {
        "sources": formatted,
        "source_count": len(formatted),
    }
