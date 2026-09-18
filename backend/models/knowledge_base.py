"""KnowledgeBase and Document ORM models."""
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from models.user import User


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    qdrant_collection: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner: Mapped["User"] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase id={self.id} name={self.name}>"


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    kb_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploader_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | processing | indexed | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON: processing_steps list
    processing_steps_json: Mapped[str | None] = mapped_column(
        "processing_steps", Text, nullable=True
    )
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    # Object storage: "neon" for Neon Object Storage, None for legacy local files
    storage_provider: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document id={self.id} name={self.original_name} status={self.status}>"
