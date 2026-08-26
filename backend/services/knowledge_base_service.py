"""
Knowledge Base service — CRUD for knowledge bases.
"""
from __future__ import annotations
import logging
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.knowledge_base import KnowledgeBase
from services.audit_service import AuditService
from services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession, qdrant_svc: QdrantService) -> None:
        self.db = db
        self.qdrant = qdrant_svc
        self.settings = get_settings()

    async def create(
        self,
        owner_id: str,
        name: str,
        description: str | None,
        embedding_model: str | None,
        client_ip: str | None = None,
    ) -> KnowledgeBase:
        if not name or not name.strip():
            raise HTTPException(400, "Knowledge base name is required")
        if len(name) > 100:
            raise HTTPException(400, "Name too long (max 100 chars)")

        model = embedding_model or self.settings.default_embedding_model
        kb_id = str(uuid.uuid4())

        kb = KnowledgeBase(
            id=kb_id,
            owner_id=owner_id,
            name=name.strip(),
            description=description,
            embedding_model=model,
            qdrant_collection=f"kb_{kb_id.replace('-', '_')}",
        )
        self.db.add(kb)
        await self.db.flush()

        # Create Qdrant collection (dimension comes from model)
        from services.embedding_service import get_expected_dimension
        dim = get_expected_dimension(model)
        try:
            self.qdrant.create_collection(kb_id, dim)
        except Exception as exc:
            logger.warning("Could not pre-create Qdrant collection for KB %s: %s", kb_id, exc)

        audit = AuditService(self.db)
        await audit.log(
            "rag", "knowledge_base.created", "success",
            user_id=owner_id,
            resource_type="knowledge_base", resource_id=kb_id,
            ip_address=client_ip,
        )
        return kb

    async def list_all(self) -> list[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, kb_id: str) -> KnowledgeBase:
        result = await self.db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise HTTPException(404, f"Knowledge base '{kb_id}' not found")
        return kb

    async def delete(self, kb_id: str, user_id: str, client_ip: str | None = None) -> None:
        kb = await self.get(kb_id)

        # Delete all documents on disk and from Qdrant is handled by cascade + doc_service
        # Here we just drop the Qdrant collection and the KB record
        try:
            self.qdrant.delete_collection(kb_id)
        except Exception as exc:
            logger.warning("Qdrant collection delete failed for KB %s: %s", kb_id, exc)

        await self.db.delete(kb)
        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "rag", "knowledge_base.deleted", "success",
            user_id=user_id,
            resource_type="knowledge_base", resource_id=kb_id,
        )
