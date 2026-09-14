"""
Artifact router — API endpoints for agent-generated file management.
"""
import logging
import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from models.user import User
from services.artifact_service import ArtifactService
from utils.rate_limit import ai_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])


@router.get("")
async def list_artifacts(
    conversation_id: str | None = None,
    run_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List artifacts for the current user."""
    svc = ArtifactService(db)
    artifacts = await svc.list_artifacts(
        user_id=current_user.id,
        conversation_id=conversation_id,
        run_id=run_id,
    )
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "relative_path": a.relative_path,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "checksum": a.checksum,
            "conversation_id": a.conversation_id,
            "run_id": a.run_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in artifacts
    ]


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get artifact metadata."""
    svc = ArtifactService(db)
    artifact = await svc.get_artifact(artifact_id, current_user.id)
    return {
        "id": artifact.id,
        "filename": artifact.filename,
        "relative_path": artifact.relative_path,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "checksum": artifact.checksum,
        "conversation_id": artifact.conversation_id,
        "run_id": artifact.run_id,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(ai_rate_limit),
):
    """Download an artifact file."""
    svc = ArtifactService(db)
    artifact = await svc.get_artifact(artifact_id, current_user.id)

    path = svc.get_artifact_path(artifact)
    if not path:
        raise HTTPException(404, "Artifact file not found on disk")

    mime_type = artifact.mime_type or "application/octet-stream"
    return FileResponse(
        path=path,
        media_type=mime_type,
        filename=artifact.filename,
    )


@router.get("/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(ai_rate_limit),
):
    """Preview an artifact file (for text-based files)."""
    svc = ArtifactService(db)
    artifact = await svc.get_artifact(artifact_id, current_user.id)

    path = svc.get_artifact_path(artifact)
    if not path:
        raise HTTPException(404, "Artifact file not found on disk")

    # Only preview text-based files
    previewable = [
        "text/", "application/json", "application/javascript",
        "application/xml", "application/x-yaml",
    ]
    mime = artifact.mime_type or ""
    if not any(mime.startswith(p) for p in previewable):
        raise HTTPException(400, "File type not previewable")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(100000)  # Max 100KB preview
        return {"content": content, "filename": artifact.filename, "mime_type": mime}
    except Exception as exc:
        raise HTTPException(500, f"Could not read file: {exc}")


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an artifact."""
    svc = ArtifactService(db)
    await svc.delete_artifact(artifact_id, current_user.id)
