"""
Knowledge bases router — CRUD for knowledge bases and documents.
"""
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from dependencies import AnalystRequired, get_current_user, get_llm_client, require_role
from models.knowledge_base import Document, KnowledgeBase
from models.user import User
from schemas.document import (
    DocumentResponse,
    DocumentStatusResponse,
    KBCreate,
    KBQueryRequest,
    KBResponse,
)
from services.audit_service import AuditService
from services.document_service import DocumentService
from services.embedding_service import EmbeddingService
from services.kb_access import ensure_kb_access, get_kb_checked
from services.knowledge_base_service import KnowledgeBaseService
from services.llm_client import OllamaClient
from services.qdrant_service import QdrantService
from config import get_settings
from services.rag_service import RagService
from services.settings_service import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge-bases"])


def _kb_service(db: AsyncSession) -> KnowledgeBaseService:
    return KnowledgeBaseService(db, QdrantService())


def _doc_service(db: AsyncSession, llm_client=None) -> DocumentService:
    if llm_client is None:
        llm_client = get_llm_client()
    embedding_svc = EmbeddingService(llm_client)
    return DocumentService(db, embedding_svc, QdrantService())


async def _process_document_background(doc_id: str) -> None:
    """Process a document with a fresh DB session after upload has committed."""
    async with AsyncSessionLocal() as task_db:
        svc = _doc_service(task_db)
        try:
            await svc.process_document(doc_id)
            await task_db.commit()
        except Exception:
            await task_db.rollback()
            logger.exception("Background document processing failed for %s", doc_id)


# ------------------------------------------------------------------
# Knowledge Base CRUD
# ------------------------------------------------------------------

@router.get("/", response_model=list[KBResponse])
async def list_knowledge_bases(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _kb_service(db)
    kbs = await svc.list_accessible(_user)
    return kbs


@router.post("/", response_model=KBResponse, status_code=201)
async def create_knowledge_base(
    data: KBCreate,
    request: Request,
    analyst: User = AnalystRequired,
    db: AsyncSession = Depends(get_db),
):
    svc = _kb_service(db)
    client_ip = request.client.host if request.client else None
    kb = await svc.create(
        owner_id=analyst.id,
        name=data.name,
        description=data.description,
        embedding_model=data.embedding_model,
        client_ip=client_ip,
    )
    return kb


@router.get("/{kb_id}", response_model=KBResponse)
async def get_knowledge_base(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _kb_service(db)
    return await get_kb_checked(db, kb_id, user)


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    request: Request,
    user: User = AnalystRequired,
    db: AsyncSession = Depends(get_db),
):
    svc = _kb_service(db)
    kb = await get_kb_checked(db, kb_id, user, write=True)
    client_ip = request.client.host if request.client else None
    await svc.delete(kb_id, user_id=user.id, client_ip=client_ip)
    return {"detail": "Knowledge base deleted"}


@router.post("/{kb_id}/query")
async def query_knowledge_base(
    kb_id: str,
    data: KBQueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await get_kb_checked(db, kb_id, user)

    llm = OllamaClient(get_settings().ollama_url)
    embed_svc = EmbeddingService(llm)
    qdrant_svc = QdrantService()
    rag_svc = RagService(llm, embed_svc, qdrant_svc)

    settings = load_settings()
    result = await rag_svc.query(
        kb_id=kb_id,
        embedding_model=kb.embedding_model,
        chat_model=data.model_name or getattr(settings, "default_chat_model", None) or "llama3",
        query=data.query,
        top_k=data.top_k,
        score_threshold=data.score_threshold,
        generate_answer=data.generate_answer,
    )
    return {
        "answer": result.answer,
        "sources": [
            {
                "chunk_id": s.chunk_id,
                "doc_id": s.doc_id,
                "filename": s.filename,
                "page_number": s.page_number,
                "content": s.content,
                "score": s.score,
            }
            for s in result.sources
        ],
        "low_confidence": result.low_confidence,
        "query_embedding_ms": result.query_embedding_ms,
        "retrieval_ms": result.retrieval_ms,
        "generation_ms": result.generation_ms,
    }


# ------------------------------------------------------------------
# Documents
# ------------------------------------------------------------------

@router.get("/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _doc_service(db)
    docs = await svc.list_accessible_documents(_user, kb_id=kb_id)
    return docs


@router.post("/{kb_id}/documents", response_model=DocumentResponse)
async def upload_document(
    kb_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _doc_service(db)
    try:
        doc = await svc.upload_document(file, kb_id, _user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # Commit before scheduling the worker so its fresh DB session can see the row.
    await db.commit()
    await db.refresh(doc)
    background_tasks.add_task(_process_document_background, doc.id)
    return doc


@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    kb_id: str,
    doc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _doc_service(db)
    doc = await svc.get_document(doc_id, _user.id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "Document not found")
    steps = json.loads(doc.processing_steps_json or "[]")
    return DocumentStatusResponse(
        id=doc.id,
        kb_id=doc.kb_id,
        original_name=doc.original_name,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        status=doc.status,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        processing_steps=steps,
    )


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str,
    doc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _doc_service(db)
    doc = await svc.get_document(doc_id, _user.id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "Document not found")
    await svc.delete_document_checked(None, doc_id, _user)
    return {"detail": "Document deleted"}
