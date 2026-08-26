"""
Document management router.
Upload, status polling, list, delete.
"""
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role, resolve_llm_for_role_async
from models.user import User
from schemas.document import DocumentResponse, DocumentStatusResponse, ProcessingStep
from services.document_service import DocumentService
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


async def _get_doc_service(
    db: AsyncSession = Depends(get_db),
) -> DocumentService:
    # Embeddings are generated through the provider bound to the "embedding"
    # role when one is set; otherwise the default local Ollama instance.
    embedding_llm = await resolve_llm_for_role_async(db, "embedding")
    return DocumentService(
        db=db,
        embedding_svc=EmbeddingService(embedding_llm),
        qdrant_svc=QdrantService(),
    )


def _map_doc(doc, include_steps: bool = False):
    steps: list[ProcessingStep] = []
    if include_steps and doc.processing_steps_json:
        try:
            raw = json.loads(doc.processing_steps_json)
            steps = [ProcessingStep(**s) for s in raw]
        except Exception:
            pass

    base = DocumentResponse(
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
    )
    if include_steps:
        return DocumentStatusResponse(**base.model_dump(), processing_steps=steps)
    return base


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    kb_id: str = Form(...),
    run_ocr: bool = Form(True),
    current_user: User = Depends(require_role("analyst", "admin")),
    svc: DocumentService = Depends(_get_doc_service),
):
    try:
        doc = await svc.upload_document(
            file=file,
            kb_id=kb_id,
            uploader_id=current_user.id,
            run_ocr=run_ocr,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    # Queue background processing
    background_tasks.add_task(svc.process_document, doc.id)

    return _map_doc(doc)


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
    svc: DocumentService = Depends(_get_doc_service),
):
    docs = await svc.list_documents(kb_id=kb_id, limit=limit, offset=offset)
    return [_map_doc(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentStatusResponse)
async def get_document(
    doc_id: str,
    _user=Depends(get_current_user),
    svc: DocumentService = Depends(_get_doc_service),
):
    doc = await svc.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return _map_doc(doc, include_steps=True)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    _user=Depends(require_role("analyst", "admin")),
    svc: DocumentService = Depends(_get_doc_service),
):
    await svc.delete_document(doc_id)
    return Response(status_code=204)
