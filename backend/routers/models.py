"""Model management router."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, get_llm_client, require_role
from models.user import User
from models.user_prefs import UserModelPref
from schemas.model import (
    ModelInfo, ModelPullRequest, ModelRoleRequest,
    UserModelPrefResponse, UserModelPrefUpdate,
)
from services.model_service import ModelService
from services.llm_client import OllamaClient

router = APIRouter(tags=["models"])


def _svc(llm: OllamaClient = Depends(get_llm_client)) -> ModelService:
    return ModelService(llm)


# ------------------------------------------------------------------
# Per-user preferred chat model (declared before /{param} routes)
# ------------------------------------------------------------------

@router.get("/preferences", response_model=UserModelPrefResponse)
async def get_my_model_preference(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's preferred chat model (per-user isolation)."""
    result = await db.execute(
        select(UserModelPref).where(UserModelPref.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        return UserModelPrefResponse(provider_id=None, model_name=None)
    return UserModelPrefResponse(
        provider_id=pref.provider_id, model_name=pref.model_name,
        updated_at=pref.updated_at,
    )


@router.put("/preferences", response_model=UserModelPrefResponse)
async def set_my_model_preference(
    data: UserModelPrefUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Set the current user's preferred chat model.
    Each user can only ever modify their own row — enforced by user_id PK.
    """
    if not data.model_name or not data.model_name.strip():
        raise HTTPException(422, "model_name is required")

    result = await db.execute(
        select(UserModelPref).where(UserModelPref.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = UserModelPref(user_id=current_user.id)
        db.add(pref)
    pref.provider_id = data.provider_id
    pref.model_name = data.model_name.strip()
    await db.flush()
    await db.refresh(pref)
    return UserModelPrefResponse(
        provider_id=pref.provider_id, model_name=pref.model_name,
        updated_at=pref.updated_at,
    )


@router.get("/", response_model=list[ModelInfo])
async def list_models(
    _user=Depends(get_current_user),
    svc: ModelService = Depends(_svc),
):
    return await svc.list_models()


@router.get("/roles")
async def get_roles(
    _user=Depends(get_current_user),
    svc: ModelService = Depends(_svc),
):
    return svc.get_roles()


@router.put("/roles")
async def set_role(
    data: ModelRoleRequest,
    _admin=Depends(require_role("admin")),
    svc: ModelService = Depends(_svc),
):
    return svc.set_role(data.role, data.model_name, provider_id=data.provider_id)


@router.post("/pull")
async def pull_model(
    data: ModelPullRequest,
    _admin=Depends(require_role("admin")),
    svc: ModelService = Depends(_svc),
):
    """Stream model pull progress as SSE."""
    return StreamingResponse(
        svc.stream_pull(data.model_name),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/health/{model_name:path}")
async def model_health(
    model_name: str,
    _user=Depends(get_current_user),
    svc: ModelService = Depends(_svc),
):
    return await svc.health_check(model_name)
