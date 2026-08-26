"""
Document service — orchestrates the full processing pipeline:
  validate → save → extract → OCR → clean → chunk → embed → index → done
"""
from __future__ import annotations
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.knowledge_base import KnowledgeBase, Document  # type: ignore[attr-defined]
from services.audit_service import AuditService
from services.embedding_service import EmbeddingService, get_expected_dimension
from services.ocr_service import needs_ocr, run_ocr
from services.qdrant_service import QdrantService
from services.text_extractor import extract_text, ExtractionError
from utils.chunker import chunk_text
from utils.file_validator import validate_upload
from utils.text_cleaner import clean_text, is_mostly_empty

logger = logging.getLogger(__name__)

# Processing step names (ordered)
STEPS = ["validation", "extraction", "ocr", "cleaning", "chunking", "embedding", "indexing"]


def _make_steps(status_map: dict[str, str] | None = None) -> list[dict]:
    sm = status_map or {}
    return [{"step": s, "status": sm.get(s, "pending"), "duration_ms": None} for s in STEPS]


def _set_step(steps: list[dict], name: str, status: str, duration_ms: int | None = None):
    for s in steps:
        if s["step"] == name:
            s["status"] = status
            if duration_ms is not None:
                s["duration_ms"] = duration_ms
            break


class DocumentService:
    def __init__(
        self,
        db: AsyncSession,
        embedding_svc: EmbeddingService,
        qdrant_svc: QdrantService,
    ) -> None:
        self.db = db
        self.embedding_svc = embedding_svc
        self.qdrant_svc = qdrant_svc
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Upload entry point (called from router — fast path)
    # ------------------------------------------------------------------
    async def upload_document(
        self,
        file: UploadFile,
        kb_id: str,
        uploader_id: str,
        run_ocr: bool = True,
    ) -> Document:
        """
        Validate, save, and create a Document record (status=pending).
        Actual processing is enqueued as a FastAPI background task.
        """
        # Read file content
        content = await file.read()

        # Validate
        try:
            safe_name, detected_mime = validate_upload(
                file.filename or "upload",
                content,
                max_size_mb=self.settings.max_upload_size_mb,
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        # Ensure KB exists
        kb = await self._get_kb(kb_id)
        if kb is None:
            raise ValueError(f"Knowledge base '{kb_id}' not found")

        # Build storage path
        kb_dir = Path(self.settings.upload_dir) / kb_id
        kb_dir.mkdir(parents=True, exist_ok=True)
        doc_id = str(uuid.uuid4())
        stored_name = f"{doc_id}_{safe_name}"
        storage_path = str(kb_dir / stored_name)

        # Save file
        with open(storage_path, "wb") as f:
            f.write(content)

        steps = _make_steps({"validation": "done"})

        doc = Document(
            id=doc_id,
            kb_id=kb_id,
            uploader_id=uploader_id,
            filename=stored_name,
            original_name=safe_name,
            mime_type=detected_mime,
            size_bytes=len(content),
            storage_path=storage_path,
            status="pending",
            processing_steps_json=json.dumps(steps),
            metadata_json=json.dumps({"run_ocr": run_ocr}),
        )
        self.db.add(doc)
        await self.db.flush()
        return doc

    # ------------------------------------------------------------------
    # Background processing (called as BackgroundTask)
    # ------------------------------------------------------------------
    async def process_document(self, doc_id: str) -> None:
        """
        Full async processing pipeline. Updates document status in DB.
        Errors are caught and stored as status=failed.
        """
        import time

        # Re-fetch document in a fresh context  
        doc = await self._get_doc(doc_id)
        if doc is None:
            logger.error("process_document: doc %s not found", doc_id)
            return

        steps = json.loads(doc.processing_steps_json or "[]") or _make_steps()
        meta = json.loads(doc.metadata_json or "{}")
        run_ocr_flag: bool = meta.get("run_ocr", True)

        await self._set_status(doc_id, "processing")

        try:
            # ---- 1. Extract ----
            t0 = time.monotonic()
            _set_step(steps, "extraction", "running")
            await self._save_steps(doc_id, steps)

            text, page_count = await extract_text(doc.storage_path, doc.mime_type)
            extract_ms = int((time.monotonic() - t0) * 1000)
            _set_step(steps, "extraction", "done", extract_ms)

            # ---- 2. OCR ----
            if run_ocr_flag and needs_ocr(text, doc.mime_type):
                _set_step(steps, "ocr", "running")
                await self._save_steps(doc_id, steps)
                t1 = time.monotonic()
                ocr_text = await run_ocr(doc.storage_path, doc.mime_type)
                ocr_ms = int((time.monotonic() - t1) * 1000)
                text = (text + "\n" + ocr_text).strip() if text else ocr_text
                _set_step(steps, "ocr", "done", ocr_ms)
            else:
                _set_step(steps, "ocr", "skipped")

            # ---- 3. Clean ----
            _set_step(steps, "cleaning", "running")
            await self._save_steps(doc_id, steps)
            text = clean_text(text)
            _set_step(steps, "cleaning", "done")

            if is_mostly_empty(text):
                raise ExtractionError("Document produced no usable text after extraction")

            # ---- 4. Chunk ----
            _set_step(steps, "chunking", "running")
            await self._save_steps(doc_id, steps)
            kb = await self._get_kb(doc.kb_id)
            chunks = chunk_text(
                text,
                chunk_size=self.settings.default_chunk_size,
                overlap=self.settings.default_chunk_overlap,
                doc_id=doc_id,
                kb_id=doc.kb_id,
                filename=doc.original_name,
            )
            _set_step(steps, "chunking", "done")
            if not chunks:
                raise ExtractionError("Chunking produced no chunks")

            # ---- 5. Embed ----
            _set_step(steps, "embedding", "running")
            await self._save_steps(doc_id, steps)
            t2 = time.monotonic()
            embed_model = kb.embedding_model
            vectors = await self.embedding_svc.embed_texts(
                [c.content for c in chunks], model=embed_model
            )
            embed_ms = int((time.monotonic() - t2) * 1000)
            _set_step(steps, "embedding", "done", embed_ms)

            # ---- 6. Index ----
            _set_step(steps, "indexing", "running")
            await self._save_steps(doc_id, steps)
            payloads = [
                {
                    "doc_id":    doc_id,
                    "kb_id":     doc.kb_id,
                    "chunk_index": c.chunk_index,
                    "content":   c.content,
                    "token_count": c.token_count,
                    "page_number": c.page_number,
                    "filename":  doc.original_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                for c in chunks
            ]
            # Ensure Qdrant collection exists
            vec_dim = len(vectors[0]) if vectors else get_expected_dimension(embed_model)
            self.qdrant_svc.create_collection(doc.kb_id, vec_dim)
            self.qdrant_svc.upsert_vectors(
                kb_id=doc.kb_id,
                vectors=vectors,
                payloads=payloads,
                ids=[c.chunk_id for c in chunks],
            )
            _set_step(steps, "indexing", "done")

            # ---- Finalise ----
            await self._finalize(
                doc_id, steps, page_count=page_count, chunk_count=len(chunks)
            )
            # Update KB counts
            await self._increment_kb_counts(doc.kb_id, doc_delta=1, chunk_delta=len(chunks))

            # Audit
            audit = AuditService(self.db)
            await audit.log(
                "document", "document.indexed", "success",
                resource_type="document", resource_id=doc_id,
                metadata={"chunks": len(chunks), "pages": page_count},
            )
            logger.info("Document %s indexed: %d chunks", doc_id, len(chunks))

        except Exception as exc:
            logger.exception("Document processing failed for %s: %s", doc_id, exc)
            _set_step(steps, next(
                (s["step"] for s in steps if s["status"] in ("running", "pending")),
                "indexing"
            ), "failed")
            await self._fail(doc_id, steps, str(exc))
            audit = AuditService(self.db)
            await audit.log(
                "document", "document.processing.failed", "failure",
                resource_type="document", resource_id=doc_id,
                metadata={"error": str(exc)[:500]},
            )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    async def get_document(self, doc_id: str, user_id: str | None = None) -> Document | None:
        result = await self.db.execute(
            select(Document).where(Document.id == doc_id)
        )
        doc = result.scalar_one_or_none()
        return doc

    async def list_documents(
        self, kb_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Document]:
        q = select(Document).order_by(Document.created_at.desc())
        if kb_id:
            q = q.where(Document.kb_id == kb_id)
        result = await self.db.execute(q.offset(offset).limit(limit))
        return list(result.scalars().all())

    async def delete_document(self, doc_id: str) -> None:
        doc = await self._get_doc(doc_id)
        if not doc:
            from fastapi import HTTPException
            raise HTTPException(404, "Document not found")

        # Remove from Qdrant
        try:
            self.qdrant_svc.delete_document_vectors(doc.kb_id, doc_id)
        except Exception as exc:
            logger.warning("Failed to delete vectors for doc %s: %s", doc_id, exc)

        # Remove file
        try:
            if os.path.exists(doc.storage_path):
                os.remove(doc.storage_path)
        except Exception as exc:
            logger.warning("Failed to delete file %s: %s", doc.storage_path, exc)

        # Update KB counts
        await self._increment_kb_counts(doc.kb_id, doc_delta=-1, chunk_delta=-doc.chunk_count)

        await self.db.delete(doc)
        await self.db.flush()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    async def _get_doc(self, doc_id: str) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == doc_id))
        return result.scalar_one_or_none()

    async def _get_kb(self, kb_id: str) -> KnowledgeBase | None:
        result = await self.db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
        return result.scalar_one_or_none()

    async def _set_status(self, doc_id: str, status: str) -> None:
        doc = await self._get_doc(doc_id)
        if doc:
            doc.status = status
            await self.db.flush()

    async def _save_steps(self, doc_id: str, steps: list[dict]) -> None:
        doc = await self._get_doc(doc_id)
        if doc:
            doc.processing_steps_json = json.dumps(steps)
            await self.db.flush()

    async def _finalize(
        self, doc_id: str, steps: list[dict], page_count: int, chunk_count: int
    ) -> None:
        doc = await self._get_doc(doc_id)
        if doc:
            doc.status = "indexed"
            doc.page_count = page_count
            doc.chunk_count = chunk_count
            doc.processing_steps_json = json.dumps(steps)
            doc.error_message = None
            await self.db.flush()

    async def _fail(self, doc_id: str, steps: list[dict], error: str) -> None:
        doc = await self._get_doc(doc_id)
        if doc:
            doc.status = "failed"
            doc.error_message = error[:1000]
            doc.processing_steps_json = json.dumps(steps)
            await self.db.flush()

    async def _increment_kb_counts(
        self, kb_id: str, doc_delta: int, chunk_delta: int
    ) -> None:
        kb = await self._get_kb(kb_id)
        if kb:
            kb.doc_count = max(0, kb.doc_count + doc_delta)
            kb.chunk_count = max(0, kb.chunk_count + chunk_delta)
            await self.db.flush()
