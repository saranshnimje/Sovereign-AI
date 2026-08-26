"""search_kb tool — semantic search over a knowledge base (LOW risk)."""
from __future__ import annotations
from pydantic import BaseModel, field_validator


class SearchKBInput(BaseModel):
    kb_id: str
    query: str
    top_k: int = 3

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty")
        if len(v) > 1000:
            raise ValueError("Query too long (max 1000 chars)")
        return v

    @field_validator("top_k")
    @classmethod
    def valid_top_k(cls, v: int) -> int:
        return max(1, min(v, 10))


class SearchKBOutput(BaseModel):
    results: list[dict]
    found: bool
    count: int


async def execute(inp: SearchKBInput, context: dict) -> dict:
    rag_service = context.get("rag_service")
    if rag_service is None:
        return SearchKBOutput(
            results=[], found=False, count=0
        ).model_dump()

    # Get KB info for embedding model
    kb_service = context.get("kb_service")
    embedding_model = "nomic-embed-text"
    if kb_service:
        try:
            kb = await kb_service.get(inp.kb_id)
            embedding_model = kb.embedding_model
        except Exception:
            pass

    result = await rag_service.query(
        kb_id=inp.kb_id,
        embedding_model=embedding_model,
        chat_model="",
        query=inp.query,
        top_k=inp.top_k,
        generate_answer=False,
    )

    items = [
        {
            "content": s.content,
            "filename": s.filename,
            "page_number": s.page_number,
            "score": round(s.score, 4),
            "doc_id": s.doc_id,
        }
        for s in result.sources
    ]
    return SearchKBOutput(
        results=items, found=bool(items), count=len(items)
    ).model_dump()
