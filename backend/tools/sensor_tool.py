"""
sensor_analysis tool — run sensor data analysis using the existing REAL service.
LOW risk. Returns risk level, anomalies, trends, and statistics.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class SensorAnalysisInput(BaseModel):
    analysis_id: str | None = None
    csv_data: str | None = None
    query: str = ""

    @field_validator("analysis_id")
    @classmethod
    def validate_id(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 100:
            raise ValueError("analysis_id too long")
        return v

    @field_validator("csv_data")
    @classmethod
    def validate_csv(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 500_000:
            raise ValueError("CSV data too large (max 500KB)")
        return v


class SensorAnalysisOutput(BaseModel):
    status: str
    result: dict | None = None
    analysis_id: str | None = None
    error: str | None = None


async def execute(inp: SensorAnalysisInput, context: dict) -> dict:
    from fastapi import HTTPException

    user = context.get("user")
    db = context.get("db")

    if db is None:
        return SensorAnalysisOutput(
            status="error", error="Database not available"
        ).model_dump()

    if inp.analysis_id:
        from sqlalchemy import select
        from models.sensor import SensorAnalysis

        result = await db.execute(
            select(SensorAnalysis).where(SensorAnalysis.id == inp.analysis_id)
        )
        analysis = result.scalar_one_or_none()
        if analysis is None or (user and analysis.owner_id != user.id):
            return SensorAnalysisOutput(
                status="not_found", error="Sensor analysis not found"
            ).model_dump()

        return SensorAnalysisOutput(
            status="completed",
            result=analysis.result_json if hasattr(analysis, "result_json") else None,
            analysis_id=analysis.id,
        ).model_dump()

    if inp.csv_data:
        from services.sensor_analysis_service import SensorAnalysisService
        svc = SensorAnalysisService(db)
        try:
            analysis = await svc.analyze_csv(
                csv_content=inp.csv_data,
                user_id=user.id if user else "anonymous",
            )
            return SensorAnalysisOutput(
                status="completed",
                result=analysis.get("result") if isinstance(analysis, dict) else None,
                analysis_id=analysis.get("id") if isinstance(analysis, dict) else None,
            ).model_dump()
        except Exception as exc:
            return SensorAnalysisOutput(
                status="error", error=str(exc)[:500]
            ).model_dump()

    return SensorAnalysisOutput(
        status="error",
        error="Provide analysis_id or csv_data"
    ).model_dump()
