"""
Settings router — admin-only system configuration.
GET  /settings        → current settings
PUT  /settings        → update settings (validated on backend)
GET  /settings/summary → dashboard aggregate counts
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.agent import AgentRun, ApprovalRequest
from models.audit import AuditLog
from models.knowledge_base import Document, KnowledgeBase
from models.user import User
from schemas.settings import DashboardSummary, SystemSettings
from services.audit_service import AuditService
from services.settings_service import load_settings, save_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])


# ---- Settings CRUD ----

@router.get("/", response_model=SystemSettings)
async def get_settings(_admin=Depends(require_role("admin"))):
    return load_settings()


@router.put("/", response_model=SystemSettings)
async def update_settings(
    data: SystemSettings,
    request: Request,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    save_settings(data)
    audit = AuditService(db)
    await audit.log(
        "config", "config.updated", "success",
        user_id=admin.id,
        metadata={"fields_updated": list(data.model_dump().keys())},
        request=request,
    )
    return data


# ---- Dashboard summary counts ----

@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate counts for the dashboard. Auth required (any role)."""
    try:
        kb_count = (await db.execute(select(func.count()).select_from(KnowledgeBase))).scalar_one()
    except Exception:
        kb_count = 0
    try:
        doc_count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    except Exception:
        doc_count = 0
    try:
        run_count = (await db.execute(select(func.count()).select_from(AgentRun))).scalar_one()
    except Exception:
        run_count = 0
    try:
        pending_count = (
            await db.execute(
                select(func.count()).select_from(ApprovalRequest).where(
                    ApprovalRequest.status == "pending"
                )
            )
        ).scalar_one()
    except Exception:
        pending_count = 0
    try:
        audit_count = (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    except Exception:
        audit_count = 0

    return DashboardSummary(
        knowledge_base_count=kb_count,
        document_count=doc_count,
        agent_run_count=run_count,
        pending_approval_count=pending_count,
        total_audit_events=audit_count,
    )


# ---- User management (admin) ----

@router.get("/users", response_model=list[dict])
async def list_users_settings(
    _admin=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users with their roles. Admin only."""
    result = await db.execute(
        select(User).order_by(User.created_at)
    )
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "role": u.role,
            "is_active": u.is_active,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]
