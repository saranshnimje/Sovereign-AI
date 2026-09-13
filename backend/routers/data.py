"""
Data/organizations management router.
"""
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.data import DataSource, Organization
from models.sensor import SensorAnalysis
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data"])


class OrganizationCreate(BaseModel):
    name: str
    description: str | None = None
    industry: str | None = None
    location: str | None = None
    website: str | None = None
    founded: str | None = None
    employee_count: str | None = None
    revenue: str | None = None
    ceo: str | None = None
    phone: str | None = None
    email: str | None = None
    details_json: str | None = None


class OrganizationResponse(BaseModel):
    id: str
    name: str
    description: str | None
    industry: str | None = None
    location: str | None = None
    website: str | None = None
    founded: str | None = None
    employee_count: str | None = None
    revenue: str | None = None
    ceo: str | None = None
    phone: str | None = None
    email: str | None = None
    details: dict | None = None
    owner_id: str
    kb_id: str | None
    created_at: str

    class Config:
        from_attributes = True


class DataSourceResponse(BaseModel):
    id: str
    org_id: str
    type: str
    name: str
    status: str
    last_error: str | None
    doc_count: int
    created_at: str

    class Config:
        from_attributes = True


class SensorAnalysisResponse(BaseModel):
    id: str
    original_name: str
    status: str
    error_message: str | None
    row_count: int
    column_count: int
    timestamp_column: str | None
    created_at: str

    class Config:
        from_attributes = True


# ------------------------------------------------------------------
# Organizations
# ------------------------------------------------------------------

@router.get("/organizations", response_model=list[OrganizationResponse])
async def list_organizations(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Organization).order_by(Organization.created_at.desc())
    if _user.role != "admin":
        query = query.where(Organization.owner_id == _user.id)
    result = await db.execute(query)
    orgs = list(result.scalars().all())
    return [
        OrganizationResponse(
            id=o.id,
            name=o.name,
            description=o.description,
            industry=o.industry,
            location=o.location,
            website=o.website,
            founded=o.founded,
            employee_count=o.employee_count,
            revenue=o.revenue,
            ceo=o.ceo,
            phone=o.phone,
            email=o.email,
            details=o.details if o.details else None,
            owner_id=o.owner_id,
            kb_id=o.kb_id,
            created_at=str(o.created_at) if o.created_at else None,
        )
        for o in orgs
    ]


@router.post("/organizations", response_model=OrganizationResponse)
async def create_organization(
    data: OrganizationCreate,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = Organization(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        industry=data.industry,
        location=data.location,
        website=data.website,
        founded=data.founded,
        employee_count=data.employee_count,
        revenue=data.revenue,
        ceo=data.ceo,
        phone=data.phone,
        email=data.email,
        details_json=data.details_json,
        owner_id=_user.id,
    )
    db.add(org)
    await db.flush()
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        description=org.description,
        industry=org.industry,
        location=org.location,
        website=org.website,
        founded=org.founded,
        employee_count=org.employee_count,
        revenue=org.revenue,
        ceo=org.ceo,
        phone=org.phone,
        email=org.email,
        details=org.details if org.details else None,
        owner_id=org.owner_id,
        kb_id=org.kb_id,
        created_at=str(org.created_at) if org.created_at else None,
    )


# ------------------------------------------------------------------
# Data sources
# ------------------------------------------------------------------

@router.get("/organizations/{org_id}/sources", response_model=list[DataSourceResponse])
async def list_data_sources(
    org_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify org exists and user has access
    org_result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if _user.role != "admin" and org.owner_id != _user.id:
        raise HTTPException(403, "Access denied")

    result = await db.execute(
        select(DataSource).where(DataSource.org_id == org_id).order_by(DataSource.created_at.desc())
    )
    sources = list(result.scalars().all())
    return [
        DataSourceResponse(
            id=s.id,
            org_id=s.org_id,
            type=s.type,
            name=s.name,
            status=s.status,
            last_error=s.last_error,
            doc_count=s.doc_count,
            created_at=str(s.created_at) if s.created_at else None,
        )
        for s in sources
    ]


# ------------------------------------------------------------------
# Sensor analyses
# ------------------------------------------------------------------

@router.get("/sensor-analyses", response_model=list[SensorAnalysisResponse])
async def list_sensor_analyses(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(SensorAnalysis).order_by(SensorAnalysis.created_at.desc())
    if _user.role != "admin":
        query = query.where(SensorAnalysis.owner_id == _user.id)
    result = await db.execute(query.offset(offset).limit(limit))
    analyses = list(result.scalars().all())
    return [
        SensorAnalysisResponse(
            id=a.id,
            original_name=a.original_name,
            status=a.status,
            error_message=a.error_message,
            row_count=a.row_count,
            column_count=a.column_count,
            timestamp_column=a.timestamp_column,
            created_at=str(a.created_at) if a.created_at else None,
        )
        for a in analyses
    ]


@router.post("/sensor-analyses", response_model=SensorAnalysisResponse)
async def upload_sensor_data(
    file: UploadFile,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")
    
    # Streaming size guard — read in chunks to avoid OOM on huge uploads
    from config import get_settings
    import os
    import re
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    chunks = []
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb} MB limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    
    if len(content) == 0:
        raise HTTPException(422, "File is empty")
    
    # Store the file and create analysis record
    upload_dir = os.path.join(settings.data_dir, "sensor_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    analysis_id = str(uuid.uuid4())
    safe_name = Path(file.filename).name
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
    safe_name = safe_name.strip("._") or "upload.csv"
    storage_path = os.path.join(upload_dir, f"{analysis_id}_{safe_name}")
    
    with open(storage_path, "wb") as f:
        f.write(content)
    
    sa = SensorAnalysis(
        id=analysis_id,
        owner_id=_user.id,
        original_name=safe_name,
        storage_path=storage_path,
        file_size=len(content),
        status="pending",
    )
    db.add(sa)
    await db.flush()
    
    # Run analysis in background? For now, do it synchronously
    try:
        from services.sensor_analysis_service import analyze_csv_bytes
        result = analyze_csv_bytes(content, safe_name)
        sa.status = "completed"
        sa.row_count = result.get("meta", {}).get("row_count", 0)
        sa.column_count = result.get("meta", {}).get("column_count", 0)
        sa.timestamp_column = result.get("meta", {}).get("timestamp_column")
        sa.result_json = json.dumps(result)
    except Exception as exc:
        sa.status = "failed"
        sa.error_message = str(exc)[:1000]
    
    await db.flush()
    return SensorAnalysisResponse(
        id=sa.id,
        original_name=sa.original_name,
        status=sa.status,
        error_message=sa.error_message,
        row_count=sa.row_count,
        column_count=sa.column_count,
        timestamp_column=sa.timestamp_column,
        created_at=str(sa.created_at) if sa.created_at else None,
    )


# ------------------------------------------------------------------
# Organization search
# ------------------------------------------------------------------

@router.get("/organizations/search")
async def search_organizations(
    q: str = Query(..., min_length=1, description="Search query"),
    category: str | None = Query(None, description="Filter: employees, departments, contacts, infrastructure, financials"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search organization data for use by the AI agent or UI."""
    from tools.org_search import execute as org_search_execute, OrgSearchInput
    validated = OrgSearchInput(query=q, category=category)
    result = await org_search_execute(validated, {"db": db})
    return result