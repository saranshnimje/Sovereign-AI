"""
Knowledge Base router — CRUD and RAG query.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role, resolve_llm_for_role_async, get_client_ip
from models.user import User
from schemas.document import (
    KBCreate, KBQueryRequest, KBQueryResponse, KBQuerySource, KBResponse,
)
from services.embedding_service import EmbeddingService
from services.knowledge_base_service import KnowledgeBaseService
from services.qdrant_service import QdrantService
from services.rag_service import RagService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge-bases"])


def _get_kb_service(
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseService:
    return KnowledgeBaseService(db=db, qdrant_svc=QdrantService())


async def _get_rag_service(
    db: AsyncSession = Depends(get_db),
) -> RagService:
    # Use the provider bound to the "chat" role for answer generation when set.
    llm = await resolve_llm_for_role_async(db, "chat")
    embedding_llm = await resolve_llm_for_role_async(db, "embedding")
    return RagService(
        llm=llm,
        embedding_svc=EmbeddingService(embedding_llm),
        qdrant_svc=QdrantService(),
    )


@router.post("/", response_model=KBResponse, status_code=201)
async def create_kb(
    data: KBCreate,
    request: Request,
    current_user: User = Depends(require_role("analyst", "admin")),
    svc: KnowledgeBaseService = Depends(_get_kb_service),
):
    kb = await svc.create(
        owner_id=current_user.id,
        name=data.name,
        description=data.description,
        embedding_model=data.embedding_model,
        client_ip=get_client_ip(request),
    )
    return KBResponse.model_validate(kb)


@router.get("/", response_model=list[KBResponse])
async def list_kbs(
    _user=Depends(get_current_user),
    svc: KnowledgeBaseService = Depends(_get_kb_service),
):
    kbs = await svc.list_all()
    return [KBResponse.model_validate(kb) for kb in kbs]


@router.get("/{kb_id}", response_model=KBResponse)
async def get_kb(
    kb_id: str,
    _user=Depends(get_current_user),
    svc: KnowledgeBaseService = Depends(_get_kb_service),
):
    kb = await svc.get(kb_id)
    return KBResponse.model_validate(kb)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: str,
    request: Request,
    current_user: User = Depends(require_role("admin")),
    svc: KnowledgeBaseService = Depends(_get_kb_service),
):
    await svc.delete(kb_id, user_id=current_user.id, client_ip=get_client_ip(request))
    return Response(status_code=204)


@router.post("/{kb_id}/query", response_model=KBQueryResponse)
async def query_kb(
    kb_id: str,
    data: KBQueryRequest,
    _user=Depends(get_current_user),
    kb_svc: KnowledgeBaseService = Depends(_get_kb_service),
    rag_svc: RagService = Depends(_get_rag_service),
):
    kb = await kb_svc.get(kb_id)  # validates existence

    # Determine chat model name (the client itself is provider-aware via DI)
    from services.model_service import _load_roles
    roles = _load_roles()
    chat_model = data.model_name or roles.get("chat") or "llama3.2:3b"

    result = await rag_svc.query(
        kb_id=kb_id,
        embedding_model=kb.embedding_model,
        chat_model=chat_model,
        query=data.query,
        top_k=data.top_k,
        score_threshold=data.score_threshold,
        generate_answer=data.generate_answer,
    )

    return KBQueryResponse(
        answer=result.answer,
        sources=[
            KBQuerySource(
                chunk_id=s.chunk_id,
                doc_id=s.doc_id,
                filename=s.filename,
                page_number=s.page_number,
                content=s.content,
                score=round(s.score, 4),
            )
            for s in result.sources
        ],
        query_embedding_ms=result.query_embedding_ms,
        retrieval_ms=result.retrieval_ms,
        generation_ms=result.generation_ms,
        low_confidence=result.low_confidence,
        error=result.error,
    )
