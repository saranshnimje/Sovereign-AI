"""Pydantic schemas for document and knowledge-base endpoints."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


class ProcessingStep(BaseModel):
    step: str
    status: str          # pending | running | done | failed | skipped
    duration_ms: int | None = None
    detail: str | None = None


class DocumentResponse(BaseModel):
    id: str
    kb_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    status: str          # pending | processing | indexed | failed
    page_count: int | None
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentStatusResponse(DocumentResponse):
    processing_steps: list[ProcessingStep] = []


# ---- Knowledge Base schemas ----

class KBCreate(BaseModel):
    name: str
    description: str | None = None
    embedding_model: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        if len(v) > 100:
            raise ValueError("Name too long (max 100 chars)")
        return v


class KBResponse(BaseModel):
    id: str
    name: str
    description: str | None
    embedding_model: str
    qdrant_collection: str
    owner_id: str
    doc_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KBQueryRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    query: str
    top_k: int = 5
    score_threshold: float = 0.3
    generate_answer: bool = True
    model_name: str | None = None  # override chat model for this query

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty")
        if len(v) > 2000:
            raise ValueError("Query too long (max 2000 chars)")
        return v

    @field_validator("top_k")
    @classmethod
    def valid_top_k(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("top_k must be between 1 and 20")
        return v


class KBQuerySource(BaseModel):
    chunk_id: str
    doc_id: str
    filename: str
    page_number: int | None
    content: str
    score: float


class KBQueryResponse(BaseModel):
    answer: str | None
    sources: list[KBQuerySource]
    query_embedding_ms: int
    retrieval_ms: int
    generation_ms: int | None
    low_confidence: bool = False
    error: str | None = None
