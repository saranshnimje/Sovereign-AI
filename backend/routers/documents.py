"""
Documents router — top-level document upload / list / get / retry / delete.

This is the canonical document API surface used by the integration suite:

    POST   /documents/upload        multipart(file, kb_id, run_ocr) → 202 pending
    GET    /documents?kb_id=        list accessible documents (owner+admin scoped)
    GET    /documents/{doc_id}      status + processing_steps (404 foreign)
    POST   /documents/{doc_id}/retry  re-run pipeline for a FAILED doc (200/409)
    DELETE /documents/{doc_id}      404 foreign / 204-able delete

Tenancy is enforced via services.kb_access — any missing OR unauthorised
resource returns a deliberate 404 (never 403), so existence is not leaked.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import AnalystRequired, get_current_user, get_llm_client
from models.user import User
from schemas.document import DocumentStatusResponse, DocumentResponse
from services.document_service import DocumentService
from services.embedding_service import EmbeddingService
from services.kb_access import get_document_checked
from services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


def _doc_service(db: AsyncSession) -> DocumentService:
    return DocumentService(db, EmbeddingService(get_llm_client()), QdrantService())


def _status_response(doc) -> DocumentStatusResponse:
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


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    file: UploadFile,
    kb_id: str = Form(...),
    run_ocr: bool = Form(False),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    _user: User = AnalystRequired,
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document into a knowledge base the user may access.

    Viewers get 403 (role gate); validation failures (bad extension / empty
    file / oversize) return 422; a missing or unauthorised KB returns 404.
    """
    # Tenancy first — deliberate 404 for foreign/unknown KB
    await get_kb_checked_for_upload(db, kb_id, _user)

    svc = _doc_service(db)
    try:
        doc = await svc.upload_document(file, kb_id, _user.id, run_ocr=run_ocr)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    background_tasks.add_task(svc.process_document, doc.id)
    return doc


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: Optional[str] = None,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _doc_service(db)
    return await svc.list_accessible_documents(_user, kb_id=kb_id)


@router.get("/{doc_id}", response_model=DocumentStatusResponse)
async def get_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc, _kb = await get_document_checked(db, doc_id, user)
    return _status_response(doc)


@router.post("/{doc_id}/retry")
async def retry_document(
    doc_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc, _kb = await get_document_checked(db, doc_id, user)
    if doc.status != "failed":
        raise HTTPException(409, f"Document is in '{doc.status}' state; only failed docs can be retried")
    svc = _doc_service(db)
    await svc.reset_for_retry(doc_id)
    background_tasks.add_task(svc.process_document, doc_id)
    return {"detail": "Retry scheduled", "doc_id": doc_id}


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # get_document_checked raises 404 for missing OR foreign docs
    await get_document_checked(db, doc_id, user)
    svc = _doc_service(db)
    await svc.delete_document_checked(None, doc_id, user)
    return {"detail": "Document deleted"}


async def get_kb_checked_for_upload(db: AsyncSession, kb_id: str, user: User):
    """Fetch the target KB with tenancy enforcement (404 on foreign/missing)."""
    from services.kb_access import ensure_kb_access
    from models.knowledge_base import KnowledgeBase
    from sqlalchemy import select

    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    ensure_kb_access(kb, user, write=True)
    return kb