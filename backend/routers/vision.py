"""
Vision inspection router — upload, analyze, and manage inspection images.
"""
import json
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from dependencies import get_current_user, require_role
from models.incident import Incident
from models.user import User
from models.vision import InspectionImage
from services.audit_service import AuditService
from services.vision_service import (
    VisionError,
    analyze_image,
    parse_vision_response,
    resolve_vision_model,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vision"])

UPLOAD_DIR = Path(get_settings().data_dir) / "uploads" / "vision"

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _safe_name(name: str) -> str:
    """Strip path components and dangerous characters."""
    name = os.path.basename(name)
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name[:120] or "image.png"


def _detect_mime(content: bytes) -> str:
    """Detect image MIME type from magic bytes instead of trusting client headers."""
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:2] == b"\xff\xd8":
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:4] == b"GIF8":
        return "image/gif"
    return "application/octet-stream"


def _serialize(img: InspectionImage) -> dict:
    return {
        "id": img.id,
        "incident_id": img.incident_id,
        "owner_id": img.owner_id,
        "original_name": img.original_name,
        "status": img.status,
        "size_bytes": img.size_bytes,
        "mime_type": img.mime_type,
        "ai_model": img.ai_model,
        "result": json.loads(img.result_json) if img.result_json else None,
        "error_message": img.error_message,
        "created_at": img.created_at.isoformat() if img.created_at else None,
        "updated_at": img.updated_at.isoformat() if img.updated_at else None,
    }


# ------------------------------------------------------------------
# Upload image to incident
# ------------------------------------------------------------------

@router.post("/incidents/{incident_id}/vision", status_code=201)
async def upload_vision_image(
    incident_id: str,
    file: UploadFile = File(...),
    analyze_now: str = Form("true"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if _user.role == "viewer":
        raise HTTPException(403, "Viewers cannot upload images")

    # Verify incident exists and user has access
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = result.scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "Incident not found")
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(404, "Incident not found")

    # Streaming size guard — read in chunks to avoid OOM on huge uploads
    max_mb = get_settings().max_upload_size_mb
    max_bytes = max_mb * 1024 * 1024
    chunks = []
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(422, f"File exceeds {max_mb} MB limit")
        chunks.append(chunk)
    content = b"".join(chunks)

    if len(content) == 0:
        raise HTTPException(422, "File is empty")

    # Detect MIME from magic bytes instead of trusting client header
    mime = _detect_mime(content)
    if mime not in ALLOWED_MIME:
        raise HTTPException(422, f"Unsupported image format: {mime}")

    # Store file
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{_safe_name(file.filename or 'image.png')}"
    storage_path = UPLOAD_DIR / stored_name
    storage_path.write_bytes(content)

    # Create DB record
    img = InspectionImage(
        incident_id=incident_id,
        owner_id=_user.id,
        original_name=_safe_name(file.filename or "image.png"),
        storage_path=str(storage_path),
        mime_type=mime,
        size_bytes=len(content),
        status="pending",
    )
    db.add(img)
    await db.flush()
    await db.refresh(img)

    # Audit
    audit_svc = AuditService(db)
    await audit_svc.log(
        event_type="vision",
        action="vision.image_uploaded",
        outcome="success",
        user_id=_user.id,
        resource_type="inspection_image",
        resource_id=img.id,
        metadata={"incident_id": incident_id, "filename": img.original_name},
    )

    # Optionally run analysis
    if analyze_now.lower() == "true":
        await _run_analysis(db, img, inc)

    await db.refresh(img)
    return _serialize(img)


async def _run_analysis(db: AsyncSession, img: InspectionImage, inc: Incident):
    """Attempt vision analysis; update status honestly."""
    audit_svc = AuditService(db)
    model = resolve_vision_model()
    if not model:
        img.status = "unavailable"
        img.error_message = "Vision model unavailable: no local vision model configured"
        await audit_svc.log(
            event_type="vision",
            action="vision.analysis_skipped",
            outcome="skipped",
            resource_type="inspection_image",
            resource_id=img.id,
            metadata={"reason": "no_model"},
        )
        await db.flush()
        return

    img.status = "analyzing"
    img.ai_model = model
    await db.flush()

    await audit_svc.log(
        event_type="vision",
        action="vision.analysis_started",
        outcome="success",
        resource_type="inspection_image",
        resource_id=img.id,
        metadata={"model": model},
    )

    try:
        from dependencies import resolve_llm_for_role_async
        from services.llm_client import OllamaProvider

        llm = await resolve_llm_for_role_async(db, "analyst")
        if not isinstance(llm, OllamaProvider):
            img.status = "unavailable"
            img.error_message = "Vision requires local Ollama provider"
            await db.flush()
            return

        image_bytes = Path(img.storage_path).read_bytes()
        res = await analyze_image(
            llm, model, image_bytes, inc.machine, inc.asset_tag
        )
        img.status = "completed"
        img.result_json = json.dumps(res["result"])
        img.ai_model = res.get("model", model)
        await audit_svc.log(
            event_type="vision",
            action="vision.analysis_completed",
            outcome="success",
            resource_type="inspection_image",
            resource_id=img.id,
            metadata={"model": model},
        )
    except VisionError as ve:
        img.status = "failed"
        img.error_message = f"malformed: {ve}"
    except Exception as exc:
        img.status = "failed"
        img.error_message = str(exc)[:500]
    await db.flush()
    await db.refresh(img)


# ------------------------------------------------------------------
# List images for an incident
# ------------------------------------------------------------------

@router.get("/incidents/{incident_id}/vision")
async def list_incident_images(
    incident_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify incident exists and user has access
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = result.scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "Incident not found")
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(404, "Incident not found")

    imgs = (await db.execute(
        select(InspectionImage)
        .where(InspectionImage.incident_id == incident_id)
        .order_by(InspectionImage.created_at)
    )).scalars().all()
    return [_serialize(i) for i in imgs]


# ------------------------------------------------------------------
# Get image metadata
# ------------------------------------------------------------------

@router.get("/images/{image_id}")
async def get_image(
    image_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InspectionImage).where(InspectionImage.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(404, "Image not found")
    if _user.role != "admin" and img.owner_id != _user.id:
        raise HTTPException(404, "Image not found")
    return _serialize(img)


# ------------------------------------------------------------------
# Serve image file
# ------------------------------------------------------------------

@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InspectionImage).where(InspectionImage.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(404, "Image not found")
    if _user.role != "admin" and img.owner_id != _user.id:
        raise HTTPException(404, "Image not found")

    path = Path(img.storage_path)
    if not path.exists():
        raise HTTPException(404, "Image file not found on disk")

    audit_svc = AuditService(db)
    await audit_svc.log(
        event_type="vision",
        action="vision.viewed",
        outcome="success",
        user_id=_user.id,
        resource_type="inspection_image",
        resource_id=img.id,
    )

    return FileResponse(
        path, media_type=img.mime_type,
        headers={"Content-Disposition": f'inline; filename="{img.original_name}"'},
    )


# ------------------------------------------------------------------
# Trigger analysis
# ------------------------------------------------------------------

@router.post("/images/{image_id}/analyze")
async def analyze_image_endpoint(
    image_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InspectionImage).where(InspectionImage.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(404, "Image not found")
    if _user.role != "admin" and img.owner_id != _user.id:
        raise HTTPException(404, "Image not found")

    # Get parent incident for context
    inc_result = await db.execute(select(Incident).where(Incident.id == img.incident_id))
    inc = inc_result.scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "Parent incident not found")

    await _run_analysis(db, img, inc)
    await db.refresh(img)
    return _serialize(img)


# ------------------------------------------------------------------
# Delete image
# ------------------------------------------------------------------

@router.delete("/images/{image_id}", status_code=204)
async def delete_image(
    image_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InspectionImage).where(InspectionImage.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(404, "Image not found")
    if _user.role != "admin" and img.owner_id != _user.id:
        raise HTTPException(404, "Image not found")

    # Remove file from disk
    path = Path(img.storage_path)
    if path.exists():
        path.unlink()

    await db.delete(img)
    await db.flush()
