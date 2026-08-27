"""
Central Knowledge-Base / Document access policy.

Single canonical authorization mechanism for every KB-scoped resource
(documents, chunks, RAG retrieval, agent search_kb tool).

Policy (tenancy isolation):
  - ADMIN: full access everywhere.
  - Owner: full read/write on their own KBs and everything inside them.
  - Everyone else: DENIED with 404 — deliberately identical to the
    "does not exist" response so resource existence is never leaked.

This module MUST be used instead of ad-hoc role checks for any
operation scoped to a knowledge base or document.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_base import Document, KnowledgeBase
from models.user import User

logger = logging.getLogger(__name__)

_404_KB = "Knowledge base not found"
_404_DOC = "Document not found"


def ensure_kb_access(
    kb: KnowledgeBase | None,
    user: User,
    write: bool = False,
) -> KnowledgeBase:
    """
    Enforce access to a knowledge base.

    Raises HTTPException(404) when the KB is missing OR the user is not
    permitted to see it. Returns the KB when authorized (convenience).
    """
    if kb is not None and (user.role == "admin" or kb.owner_id == user.id):
        return kb
    # Missing OR unauthorized → indistinguishable 404 (no existence leakage)
    raise HTTPException(404, _404_KB)


def kb_access_filter(user: User):
    """
    SQLAlchemy criterion limiting KnowledgeBase queries to those the user may see.
    Compose as: select(KnowledgeBase).where(kb_access_filter(user)).
    """
    from sqlalchemy import or_

    if user.role == "admin":
        return or_(True)  # no restriction — keep type consistent
    return KnowledgeBase.owner_id == user.id


async def get_kb_checked(
    db: AsyncSession, kb_id: str, user: User, write: bool = False
) -> KnowledgeBase:
    """Fetch a KB by id and enforce access. 404 on missing/unauthorized."""
    result = await db.execute(
        select_knowledge_base().where(KnowledgeBase.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    return ensure_kb_access(kb, user, write=write)


def select_knowledge_base():
    from sqlalchemy import select

    return select(KnowledgeBase)


async def get_document_checked(
    db: AsyncSession, doc_id: str, user: User, write: bool = False
) -> tuple[Document, KnowledgeBase]:
    """
    Fetch a document by id and enforce access THROUGH ITS KNOWLEDGE BASE
    (documents inherit the KB owner's tenancy).
    Returns (document, kb). 404 on missing/unauthorized.
    """
    from sqlalchemy import select

    result = await db.execute(
        select(Document).where(Document.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, _404_DOC)

    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id)
    )
    kb = kb_result.scalar_one_or_none()
    ensure_kb_access(kb, user, write=write)
    return doc, kb
