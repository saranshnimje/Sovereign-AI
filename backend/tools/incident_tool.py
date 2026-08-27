"""
incident_get + incident_investigate tools — access authorized incident data
and run evidence-grounded investigation using the existing REAL services.
LOW risk (read) / MEDIUM risk (investigate). Ownership enforced.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class IncidentGetInput(BaseModel):
    incident_id: str

    @field_validator("incident_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("incident_id too long")
        return v


class IncidentGetOutput(BaseModel):
    status: str
    incident: dict | None = None
    error: str | None = None


async def execute_get(inp: IncidentGetInput, context: dict) -> dict:
    user = context.get("user")
    db = context.get("db")

    if db is None:
        return IncidentGetOutput(
            status="error", error="Database not available"
        ).model_dump()

    from sqlalchemy import select
    from models.incident import Incident

    result = await db.execute(
        select(Incident).where(Incident.id == inp.incident_id)
    )
    inc = result.scalar_one_or_none()
    if inc is None or (user and inc.owner_id != user.id):
        return IncidentGetOutput(
            status="not_found", error="Incident not found"
        ).model_dump()

    return IncidentGetOutput(
        status="ok",
        incident={
            "id": inc.id,
            "title": inc.title,
            "machine": inc.machine,
            "asset_tag": inc.asset_tag,
            "description": inc.description,
            "risk_level": inc.risk_level,
            "status": inc.status,
            "created_at": str(inc.created_at) if inc.created_at else None,
        },
    ).model_dump()


class IncidentInvestigateInput(BaseModel):
    incident_id: str

    @field_validator("incident_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("incident_id too long")
        return v


class IncidentInvestigateOutput(BaseModel):
    status: str
    result: dict | None = None
    error: str | None = None


async def execute_investigate(inp: IncidentInvestigateInput, context: dict) -> dict:
    user = context.get("user")
    db = context.get("db")

    if db is None:
        return IncidentInvestigateOutput(
            status="error", error="Database not available"
        ).model_dump()

    from sqlalchemy import select
    from models.incident import Incident

    result = await db.execute(
        select(Incident).where(Incident.id == inp.incident_id)
    )
    inc = result.scalar_one_or_none()
    if inc is None or (user and inc.owner_id != user.id):
        return IncidentInvestigateOutput(
            status="not_found", error="Incident not found"
        ).model_dump()

    try:
        from services.incident_service import IncidentService
        svc = IncidentService(db)
        investigation = await svc.investigate(inc.id)
        return IncidentInvestigateOutput(
            status="completed",
            result=investigation if isinstance(investigation, dict) else {"result": str(investigation)},
        ).model_dump()
    except ImportError:
        return IncidentInvestigateOutput(
            status="error",
            error="IncidentService not available — investigation requires the full service layer",
        ).model_dump()
    except Exception as exc:
        return IncidentInvestigateOutput(
            status="error", error=str(exc)[:500]
        ).model_dump()
