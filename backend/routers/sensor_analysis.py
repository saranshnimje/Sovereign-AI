"""
Sensor analysis router — upload CSV, run deterministic analysis, retrieve results.
"""
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from dependencies import get_current_user
from models.sensor import SensorAnalysis
from models.user import User
from services.audit_service import AuditService
from services.sensor_analysis_service import (
    SensorAnalysisError,
    analyze_csv_bytes,
    build_explanation_prompt,
)

router = APIRouter(tags=["sensor-analyses"])


# ------------------------------------------------------------------
# AI explanation hook (called with exactly three arguments)
# ------------------------------------------------------------------
async def _try_ai_explanation(db: AsyncSession, record: SensorAnalysis, payload: dict):
    """
    Attempt AI explanation. Failure must NEVER affect the analysis or its numbers.
    """
    try:
        from dependencies import get_llm_client
        from services.llm_client import ChatMessage
        from config import get_settings as _gs

        settings = _gs()
        llm = get_llm_client()
        system_prompt, user_prompt = build_explanation_prompt(payload)

        response = await llm.chat(
            model=settings.default_chat_model,
            messages=[ChatMessage(role="user", content=user_prompt)],
            system_prompt=system_prompt,
        )

        record.ai_model = settings.default_chat_model
        record.ai_explanation = response.content
        await db.flush()
    except Exception as exc:
        msg = str(exc)
        if "unavailable" not in msg.lower():
            msg = f"LLM service unavailable: {msg}"
        record.ai_explanation_error = msg[:500]
        await db.flush()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _serialize(sa: SensorAnalysis, include_result: bool = False) -> dict:
    result_data = None
    if include_result and sa.result_json:
        try:
            result_data = json.loads(sa.result_json)
        except (json.JSONDecodeError, TypeError):
            result_data = None

    return {
        "id": sa.id,
        "owner_id": sa.owner_id,
        "original_name": sa.original_name,
        "file_size": sa.file_size,
        "status": sa.status,
        "error_message": sa.error_message,
        "encoding": sa.encoding,
        "row_count": sa.row_count,
        "column_count": sa.column_count,
        "timestamp_column": sa.timestamp_column,
        "result": result_data,
        "ai_model": sa.ai_model,
        "ai_explanation": sa.ai_explanation,
        "ai_explanation_error": sa.ai_explanation_error,
        "created_at": sa.created_at.isoformat() if sa.created_at else None,
        "updated_at": sa.updated_at.isoformat() if sa.updated_at else None,
    }


def _check_ownership(sa: SensorAnalysis, user: User):
    """Raise 404 if user cannot access this resource."""
    if user.role != "admin" and sa.owner_id != user.id:
        raise HTTPException(404, "Sensor analysis not found")


# ------------------------------------------------------------------
# POST /api/v1/sensor-analyses
# ------------------------------------------------------------------
@router.post("", status_code=201)
async def create_sensor_analysis(
    file: UploadFile = File(...),
    generate_explanation: str = Form("true"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Role gate
    if _user.role == "viewer":
        raise HTTPException(403, "Viewers cannot upload sensor data")

    # Extension check
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(422, "Only CSV files are accepted")

    # Streaming size guard — read in chunks to avoid OOM on huge uploads
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

    # Persist uploaded file
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    analysis_id = str(uuid.uuid4())
    safe_name = Path(file.filename).name
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
    safe_name = safe_name.strip("._") or "upload.csv"
    storage_path = str(upload_dir / f"{analysis_id}_{safe_name}")

    with open(storage_path, "wb") as f:
        f.write(content)

    # Create DB record
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

    audit = AuditService(db)
    await audit.log(
        "sensor", "sensor.uploaded", "success",
        user_id=_user.id,
        resource_type="sensor_analysis",
        resource_id=sa.id,
    )

    # Run deterministic analysis
    try:
        result = analyze_csv_bytes(content, safe_name)
        sa.status = "completed"
        sa.encoding = result["file"]["encoding"]
        sa.row_count = result["file"]["rows"]
        sa.column_count = result["file"]["columns"]
        sa.timestamp_column = result["schema"]["timestamp_column"]
        sa.result_json = json.dumps(result)
        await db.flush()

        await audit.log(
            "sensor", "sensor.analysis.completed", "success",
            user_id=_user.id,
            resource_type="sensor_analysis",
            resource_id=sa.id,
        )
    except (SensorAnalysisError, Exception) as exc:
        sa.status = "failed"
        sa.error_message = str(exc)[:1000]
        await db.flush()

        await audit.log(
            "sensor", "sensor.analysis.failed", "failure",
            user_id=_user.id,
            resource_type="sensor_analysis",
            resource_id=sa.id,
            metadata={"error": str(exc)[:500]},
        )

    # Optional AI explanation (must never alter numerical results)
    do_explain = generate_explanation.strip().lower() in ("true", "1", "yes")
    if do_explain and sa.status == "completed":
        payload = json.loads(sa.result_json)
        await _try_ai_explanation(db, sa, payload)

    # Refresh to ensure all attributes are loaded before serialization
    await db.refresh(sa)
    return _serialize(sa, include_result=True)


# ------------------------------------------------------------------
# GET /api/v1/sensor-analyses
# ------------------------------------------------------------------
@router.get("")
async def list_sensor_analyses(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(SensorAnalysis).order_by(SensorAnalysis.created_at.desc())
    if _user.role != "admin":
        query = query.where(SensorAnalysis.owner_id == _user.id)
    result = await db.execute(query.offset(offset).limit(limit))
    analyses = list(result.scalars().all())
    return [_serialize(a) for a in analyses]


# ------------------------------------------------------------------
# GET /api/v1/sensor-analyses/{analysis_id}
# ------------------------------------------------------------------
@router.get("/{analysis_id}")
async def get_sensor_analysis(
    analysis_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SensorAnalysis).where(SensorAnalysis.id == analysis_id)
    )
    sa = result.scalar_one_or_none()
    if not sa:
        raise HTTPException(404, "Sensor analysis not found")
    _check_ownership(sa, _user)

    audit = AuditService(db)
    await audit.log(
        "sensor", "sensor.analysis.viewed", "success",
        user_id=_user.id,
        resource_type="sensor_analysis",
        resource_id=sa.id,
    )

    return _serialize(sa, include_result=True)


# ------------------------------------------------------------------
# GET /api/v1/sensor-analyses/{analysis_id}/anomalies
# ------------------------------------------------------------------
@router.get("/{analysis_id}/anomalies")
async def get_anomalies(
    analysis_id: str,
    severity: str | None = Query(None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SensorAnalysis).where(SensorAnalysis.id == analysis_id)
    )
    sa = result.scalar_one_or_none()
    if not sa:
        raise HTTPException(404, "Sensor analysis not found")
    _check_ownership(sa, _user)

    anomalies = []
    if sa.result_json:
        try:
            payload = json.loads(sa.result_json)
            anomalies = payload.get("anomalies", [])
        except (json.JSONDecodeError, TypeError):
            anomalies = []

    if severity:
        anomalies = [a for a in anomalies if a.get("severity") == severity]

    return {"items": anomalies, "total": len(anomalies)}


# ------------------------------------------------------------------
# DELETE /api/v1/sensor-analyses/{analysis_id}
# ------------------------------------------------------------------
@router.delete("/{analysis_id}", status_code=204)
async def delete_sensor_analysis(
    analysis_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SensorAnalysis).where(SensorAnalysis.id == analysis_id)
    )
    sa = result.scalar_one_or_none()
    if not sa:
        raise HTTPException(404, "Sensor analysis not found")
    _check_ownership(sa, _user)

    # Remove stored file
    if sa.storage_path and os.path.exists(sa.storage_path):
        try:
            os.remove(sa.storage_path)
        except OSError:
            pass

    audit = AuditService(db)
    await audit.log(
        "sensor", "sensor.analysis.deleted", "success",
        user_id=_user.id,
        resource_type="sensor_analysis",
        resource_id=sa.id,
    )

    await db.delete(sa)
    await db.flush()
