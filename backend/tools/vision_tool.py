"""
vision_inspection tool — analyze an image using the existing REAL vision service.
LOW risk. Only operates on authorized images.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class VisionInspectionInput(BaseModel):
    image_id: str | None = None
    incident_id: str | None = None
    query: str = ""

    @field_validator("image_id")
    @classmethod
    def validate_image_id(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 100:
            raise ValueError("image_id too long")
        return v

    @field_validator("incident_id")
    @classmethod
    def validate_incident_id(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 100:
            raise ValueError("incident_id too long")
        return v


class VisionInspectionOutput(BaseModel):
    status: str
    result: dict | None = None
    image_id: str | None = None
    error: str | None = None


async def execute(inp: VisionInspectionInput, context: dict) -> dict:
    user = context.get("user")
    db = context.get("db")

    if db is None:
        return VisionInspectionOutput(
            status="error", error="Database not available"
        ).model_dump()

    if inp.image_id:
        from sqlalchemy import select
        from models.vision import InspectionImage
        from models.incident import Incident

        result = await db.execute(
            select(InspectionImage).where(InspectionImage.id == inp.image_id)
        )
        img = result.scalar_one_or_none()
        if img is None:
            return VisionInspectionOutput(
                status="not_found", error="Image not found"
            ).model_dump()

        inc_result = await db.execute(
            select(Incident).where(Incident.id == img.incident_id)
        )
        inc = inc_result.scalar_one_or_none()
        if inc is None or (user and inc.owner_id != user.id):
            return VisionInspectionOutput(
                status="not_found", error="Image not found"
            ).model_dump()

        import json
        result_data = json.loads(img.result_json) if img.result_json else None
        return VisionInspectionOutput(
            status=img.status,
            result=result_data,
            image_id=img.id,
        ).model_dump()

    if inp.incident_id:
        from sqlalchemy import select
        from models.vision import InspectionImage
        from models.incident import Incident

        inc_result = await db.execute(
            select(Incident).where(Incident.id == inp.incident_id)
        )
        inc = inc_result.scalar_one_or_none()
        if inc is None or (user and inc.owner_id != user.id):
            return VisionInspectionOutput(
                status="not_found", error="Incident not found"
            ).model_dump()

        imgs_result = await db.execute(
            select(InspectionImage).where(InspectionImage.incident_id == inp.incident_id)
        )
        images = list(imgs_result.scalars().all())
        if not images:
            return VisionInspectionOutput(
                status="not_found", error="No images for this incident"
            ).model_dump()

        import json
        latest = images[-1]
        result_data = json.loads(latest.result_json) if latest.result_json else None
        return VisionInspectionOutput(
            status=latest.status,
            result=result_data,
            image_id=latest.id,
        ).model_dump()

    return VisionInspectionOutput(
        status="error",
        error="Provide image_id or incident_id"
    ).model_dump()
