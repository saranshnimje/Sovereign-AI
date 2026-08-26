"""
Data management router — Organizations + Data Sources feeding existing RAG.

Security:
- Organization ownership enforced server-side (404 on foreign access).
- Each org maps to its own KnowledgeBase → Qdrant collection-per-org gives
  structural retrieval isolation.
- Source credentials are stored but MASKED on every read; never logged.
- Location sources require an explicit backend allowlist (DATA_LOCATIONS env,
  comma-separated absolute paths). Anything else stays status=pending.
- SQLite is the only DB engine implemented (stdlib, safe); PostgreSQL/MySQL
  configs are accepted but report honest "driver not available" failures.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import time

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.data import DataSource, Organization
from models.user import User
from services.audit_service import AuditService
from services.document_service import DocumentService
from services.embedding_service import EmbeddingService
from services.knowledge_base_service import KnowledgeBaseService
from services.qdrant_service import QdrantService

router = APIRouter(tags=["data"])

_SECRET_RE = re.compile(r"(key|token|secret|password)", re.I)
_TYPES = {"direct", "file", "location", "database", "web", "api"}


def _mask_cfg(cfg: dict | None) -> dict:
    out = {}
    for k, v in (cfg or {}).items():
        sv = str(v)
        out[k] = ("••••" + sv[-4:]) if (_SECRET_RE.search(k) and v) else v
    return out


def _svc_db(db: AsyncSession):
    return DocumentService(db=db, embedding_svc=None, qdrant_svc=None)  # not used directly


async def _get_org_owned(db: AsyncSession, org_id: str, user: User) -> Organization:
    res = await db.execute(select(Organization).where(Organization.id == org_id))
    org = res.scalar_one_or_none()
    # 404 (not 403) so foreign org existence is never disclosed — matches chat conv convention
    if org is None or (org.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Organization not found")
    return org


async def _ensure_kb(db: AsyncSession, org: Organization) -> str:
    if org.kb_id:
        return org.kb_id
    kbs = KnowledgeBaseService(db=db, qdrant_svc=QdrantService())
    kb = await kbs.create(owner_id=org.owner_id,
                          name=f"[org] {org.name}",
                          description=f"Knowledge base for organization {org.name}",
                          embedding_model="nomic-embed-text")
    org.kb_id = kb.id
    await db.flush()
    return kb.id


def _ingest_text(bg: BackgroundTasks, db_dep, kb_id: str, owner_id: str,
                 title: str, content: str, uploader: User):
    """Feed text through the EXISTING document pipeline (no duplication)."""
    up = UploadFile(filename=f"{title}.txt", file=io.BytesIO(content.encode()))
    emb = EmbeddingService(None)  # resolved inside process via settings client
    from dependencies import get_llm_client
    ds = DocumentService(db=db_dep, embedding_svc=EmbeddingService(get_llm_client()),
                         qdrant_svc=QdrantService())
    return ds, up


# ---------------------------------------------------------------- schemas
class OrgCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str | None = None


class SourceCreate(BaseModel):
    type: str
    name: str = Field(..., min_length=1, max_length=200)
    config: dict = {}


class DirectData(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    tags: list[str] | None = None


class WebData(BaseModel):
    url: str
    name: str | None = None


class DbSync(BaseModel):
    source_id: str
    tables: list[str]


# ---------------------------------------------------------------- orgs
@router.post("/orgs", status_code=201)
async def create_org(data: OrgCreate, bg: BackgroundTasks, request: Request,
                     user: User = Depends(require_role("analyst", "admin")),
                     db: AsyncSession = Depends(get_db)):
    org = Organization(name=data.name.strip(), description=data.description,
                       owner_id=user.id)
    db.add(org)
    await db.flush()
    await _ensure_kb(db, org)
    await AuditService(db).log("data", "org.created", "success", user_id=user.id,
                               resource_type="organization", resource_id=org.id,
                               metadata={"name": org.name}, request=request)
    return {"id": org.id, "name": org.name, "description": org.description,
            "kb_id": org.kb_id, "created_at": str(org.created_at)}


@router.get("/orgs")
async def list_orgs(user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    q = select(Organization)
    if user.role != "admin":
        q = q.where(Organization.owner_id == user.id)
    res = await db.execute(q.order_by(Organization.created_at))
    orgs = res.scalars().all()
    out = []
    for o in orgs:
        srcs = (await db.execute(select(DataSource).where(DataSource.org_id == o.id))).scalars().all()
        doc_n = chunk_n = 0
        if o.kb_id:
            from models.knowledge_base import KnowledgeBase
            kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == o.kb_id))).scalar_one_or_none()
            if kb:
                doc_n, chunk_n = kb.doc_count, kb.chunk_count
        statuses = [s.status for s in srcs]
        health = "failed" if "failed" in statuses else \
                 "syncing" if "syncing" in statuses else \
                 "ready" if o.kb_id else "pending"
        out.append({"id": o.id, "name": o.name, "description": o.description,
                    "created_at": str(o.created_at), "kb_id": o.kb_id,
                    "source_count": len(srcs), "doc_count": doc_n,
                    "chunk_count": chunk_n, "health": health})
    return out


@router.get("/orgs/{org_id}")
async def get_org(org_id: str, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    org = await _get_org_owned(db, org_id, user)
    srcs = (await db.execute(select(DataSource).where(DataSource.org_id == org.id)
                             .order_by(DataSource.created_at))).scalars().all()
    docs = []
    if org.kb_id:
        from models.knowledge_base import Document
        dres = await db.execute(select(Document).where(Document.kb_id == org.kb_id))
        docs = [{"id": d.id, "name": d.original_name, "status": d.status,
                 "chunks": d.chunk_count, "size": d.size_bytes}
                for d in dres.scalars().all()]
    return {
        "id": org.id, "name": org.name, "description": org.description,
        "created_at": str(org.created_at), "kb_id": org.kb_id,
        "sources": [{"id": s.id, "type": s.type, "name": s.name,
                     "status": s.status, "config": _mask_cfg(
                         json.loads(s.config_json) if s.config_json else {}),
                     "last_error": s.last_error} for s in srcs],
        "documents": docs,
    }


@router.delete("/orgs/{org_id}", status_code=204)
async def delete_org(org_id: str, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    org = await _get_org_owned(db, org_id, user)
    if org.kb_id:
        await KnowledgeBaseService(db=db, qdrant_svc=QdrantService()).delete(
            org.kb_id, user_id=user.id)
    await db.delete(org)
    await db.flush()
    await AuditService(db).log("data", "org.deleted", "success", user_id=user.id,
                               resource_type="organization", resource_id=org_id, request=request)


# ---------------------------------------------------------------- sources
@router.post("/orgs/{org_id}/sources", status_code=201)
async def add_source(org_id: str, data: SourceCreate, request: Request,
                     user: User = Depends(require_role("analyst", "admin")),
                     db: AsyncSession = Depends(get_db)):
    org = await _get_org_owned(db, org_id, user)
    if data.type not in _TYPES:
        raise HTTPException(422, f"type must be one of {sorted(_TYPES)}")
    cfg = dict(data.config or {})
    status = "connected"
    note = None
    if data.type == "location":
        allowed = [p for p in os.environ.get("DATA_LOCATIONS", "").split(";") if p]
        target = cfg.get("path", "")
        if not any(target.rstrip("\\/") == p.rstrip("\\/") or
                   target.rstrip("\\/").startswith(p.rstrip("\\/") + os.sep)
                   for p in allowed):
            status = "pending"
            note = ("Location is outside the configured allowlist "
                    "(DATA_LOCATIONS); configuration saved but scanning is blocked.")
    elif data.type == "database":
        if (cfg.get("type") or "").lower() not in ("sqlite", ""):
            status = "pending"
            note = "Only SQLite ingestion is implemented in this environment."
    src = DataSource(org_id=org.id, type=data.type, name=data.name.strip(),
                     config_json=json.dumps(cfg), status=status, last_error=note)
    db.add(src)
    await db.flush()
    await AuditService(db).log("data", "source.added", "success", user_id=user.id,
                               resource_type="data_source", resource_id=src.id,
                               metadata={"type": data.type}, request=request)  # no config → no secrets
    return {"id": src.id, "type": src.type, "name": src.name, "status": src.status,
            "config": _mask_cfg(cfg), "note": note}


@router.delete("/orgs/{org_id}/sources/{src_id}", status_code=204)
async def del_source(org_id: str, src_id: str,
                     user: User = Depends(require_role("analyst", "admin")),
                     db: AsyncSession = Depends(get_db)):
    await _get_org_owned(db, org_id, user)
    res = await db.execute(select(DataSource).where(
        DataSource.id == src_id, DataSource.org_id == org_id))
    src = res.scalar_one_or_none()
    if src is None:
        raise HTTPException(404, "Source not found")
    await db.delete(src)
    await db.flush()


# ---------------------------------------------------------------- ingestion
async def _upload_text(db: AsyncSession, org: Organization, user: User,
                       title: str, content: str, run_ocr=False):
    kb_id = await _ensure_kb(db, org)
    ds = DocumentService(db=db,
                         embedding_svc=EmbeddingService(
                             __import__("dependencies", fromlist=["get_llm_client"]).get_llm_client()),
                         qdrant_svc=QdrantService())
    safe = re.sub(r"[^\w\-. ]", "_", title)
    up = UploadFile(filename=safe + ".txt",
                    file=io.BytesIO(content.encode()))
    doc = await ds.upload_document(file=up, kb_id=kb_id, uploader_id=user.id,
                                   run_ocr=run_ocr)
    await ds.process_document(doc.id)
    fresh = await ds.get_document(doc.id)
    return {"document_id": fresh.id, "status": fresh.status,
            "chunks": fresh.chunk_count, "error": fresh.error_message}


@router.post("/orgs/{org_id}/direct")
async def add_direct(org_id: str, data: DirectData,
                     request: Request,
                     user: User = Depends(require_role("analyst", "admin")),
                     db: AsyncSession = Depends(get_db)):
    org = await _get_org_owned(db, org_id, user)
    body = data.content if not data.tags else \
        data.content + "\n\nTags: " + ", ".join(data.tags)
    result = await _upload_text(db, org, user, data.title, body)
    await AuditService(db).log("data", "direct.indexed", result["status"],
                               user_id=user.id, resource_type="organization",
                               resource_id=org.id,
                               metadata={"title": data.title, "chunks": result["chunks"]}, request=request)
    return result


@router.post("/orgs/{org_id}/web")
async def add_web(org_id: str, data: WebData,
                  user: User = Depends(require_role("analyst", "admin")),
                  db: AsyncSession = Depends(get_db)):
    org = await _get_org_owned(db, org_id, user)
    from tools.web import WebFetchInput, web_fetch_execute
    fetched = await web_fetch_execute(WebFetchInput(url=data.url, max_chars=20000), {})
    if fetched.get("error") or not fetched.get("content"):
        raise HTTPException(502, fetched.get("error") or "No content fetched")
    title = data.name or fetched["url"][:80]
    result = await _upload_text(db, org, user, title, fetched["content"])
    return {**result, "url": fetched["url"], "chars": len(fetched["content"])}


@router.post("/orgs/{org_id}/db/test")
async def test_db(org_id: str, data: SourceCreate,
                  user: User = Depends(require_role("analyst", "admin")),
                  db: AsyncSession = Depends(get_db)):
    await _get_org_owned(db, org_id, user)
    eng = (data.config.get("type") or "").lower()
    t0 = time.monotonic()
    if eng == "sqlite":
        path = data.config.get("path") or data.config.get("database") or ""
        ok = os.path.isfile(path)
        return {"success": ok, "latency_ms": int((time.monotonic()-t0)*1000),
                "error": None if ok else "SQLite file not found"}
    return {"success": False, "latency_ms": int((time.monotonic()-t0)*1000),
            "error": f"{eng or 'database'} driver not available in this environment"}


@router.get("/orgs/{org_id}/db/schema")
async def db_schema(org_id: str, source_id: str,
                    user: User = Depends(require_role("analyst", "admin")),
                    db: AsyncSession = Depends(get_db)):
    await _get_org_owned(db, org_id, user)
    src = (await db.execute(select(DataSource).where(
        DataSource.id == source_id, DataSource.org_id == org_id))).scalar_one_or_none()
    if src is None:
        raise HTTPException(404, "Source not found")
    cfg = json.loads(src.config_json or "{}")
    if (cfg.get("type") or "").lower() != "sqlite":
        raise HTTPException(400, "Schema discovery only implemented for SQLite")
    path = cfg.get("path") or cfg.get("database") or ""
    if not os.path.isfile(path):
        raise HTTPException(400, "SQLite file not found")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {}
        for (t,) in rows:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            tables[t] = n
        return {"tables": tables}
    finally:
        con.close()


@router.post("/orgs/{org_id}/db/sync")
async def db_sync(org_id: str, data: DbSync,
                  user: User = Depends(require_role("analyst", "admin")),
                  db: AsyncSession = Depends(get_db)):
    org = await _get_org_owned(db, org_id, user)
    src = (await db.execute(select(DataSource).where(
        DataSource.id == data.source_id, DataSource.org_id == org_id))).scalar_one_or_none()
    if src is None:
        raise HTTPException(404, "Source not found")
    cfg = json.loads(src.config_json or "{}")
    path = cfg.get("path") or cfg.get("database") or ""
    if (cfg.get("type") or "").lower() != "sqlite" or not os.path.isfile(path):
        raise HTTPException(400, "Source is not an available SQLite database")
    results = {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for table in data.tables[:20]:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                results[table] = "invalid table name"; continue
            try:
                rows = con.execute(f'SELECT * FROM "{table}" LIMIT 500').fetchall()
                cols = [d[0] for d in con.execute(f'SELECT * FROM "{table}" LIMIT 0').description]
                lines = [json.dumps(dict(zip(cols, r)), default=str) for r in rows]
                text = f"Table {table}\n" + "\n".join(lines)
                r = await _upload_text(db, org, user, f"db:{table}", text)
                results[table] = f'{r["status"]} ({r["chunks"]} chunks)'
            except Exception as exc:
                results[table] = f"error: {type(exc).__name__}"
    finally:
        con.close()
    src.status = "indexed"
    await db.flush()
    return {"synced": results}
