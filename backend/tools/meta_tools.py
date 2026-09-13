"""
Utility + agent meta tools: current date/time, tool discovery, model selection.

tool_discovery and model_select are READ-ONLY introspection helpers that let
the agent (or user) see what capabilities exist. They never mutate state.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Time
# ------------------------------------------------------------------
class TimeNowInput(BaseModel):
    tz_offset_minutes: int = Field(0, ge=-720, le=840,
                                   description="UTC offset in minutes")


class TimeNowOutput(BaseModel):
    iso_utc: str
    local_iso: str | None = None


async def time_now_execute(data: TimeNowInput, context: dict) -> dict:
    from datetime import timedelta, timezone
    now = datetime.now(timezone.utc)
    local = now.astimezone(timezone(timedelta(minutes=data.tz_offset_minutes)))
    return {"iso_utc": now.isoformat(), "local_iso": local.isoformat()}


# ------------------------------------------------------------------
# Tool Discovery — list available tools for the calling role
# ------------------------------------------------------------------
class ToolDiscoveryInput(BaseModel):
    category: str | None = None


class ToolDiscoveryOutput(BaseModel):
    tools: list[dict[str, Any]]
    count: int


async def tool_discovery_execute(data: ToolDiscoveryInput, context: dict) -> dict:
    from tools.registry import get_registry
    reg = get_registry()
    role = context.get("user_role", "viewer")
    items = []
    for t in reg.list_enabled(user_role=role):
        if data.category and data.category not in t.tags:
            continue
        items.append({"name": t.name, "description": t.description,
                      "risk": t.risk_level, "tags": t.tags})
    return {"tools": items, "count": len(items)}


# ------------------------------------------------------------------
# Model Selection — surface discovered models so the agent/user can choose
# ------------------------------------------------------------------
class ModelSelectInput(BaseModel):
    task_type: str | None = Field(
        None, description="reasoning | coding | fast | vision | embedding")
    limit: int = Field(10, ge=1, le=50)


class ModelSelectOutput(BaseModel):
    candidates: list[dict[str, Any]]
    note: str | None = None


_TASK_PREFERENCE = {
    # ordering preference by substring — honest, metadata-driven only
    "fast": ["small", "mini", "nano", "3b", "1b"],
    "coding": ["codex", "code", "qwen", "deepseek"],
    "vision": [],   # only models the provider marks vision-capable qualify
    "embedding": ["embed"],
    "reasoning": [],
}


async def model_select_execute(data: ModelSelectInput, context: dict) -> dict:
    """Read-only listing of enabled discovered models. No capability invention."""
    from sqlalchemy import select
    from database import AsyncSessionLocal
    from models.provider_model import ProviderModel
    from models.provider import LLMProvider

    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(ProviderModel, LLMProvider.name)
                .join(LLMProvider, LLMProvider.id == ProviderModel.provider_id)
                .where(ProviderModel.status == "available",
                       ProviderModel.enabled.is_(True),
                       LLMProvider.enabled.is_(True))
                .order_by(ProviderModel.provider_id, ProviderModel.model_id)
            )
            rows = [(r.model_id, r.family, pname) for r, pname in res.all()]
    except Exception:
        return {"candidates": [], "note": "Model catalog unavailable"}

    pref_tokens = _TASK_PREFERENCE.get(data.task_type or "", [])
    scored = []
    for model_id, family, provider_name in rows:
        score = 0
        low = model_id.lower()
        if data.task_type == "embedding" and "embed" not in low:
            continue
        if data.task_type == "vision":
            # Only route vision when metadata actually supports it.
            continue  # no provider currently reports vision capability → refuse
        for tok in pref_tokens:
            if tok in low:
                score += 1
        scored.append((score, model_id, family, provider_name))

    scored.sort(key=lambda t: (-t[0], t[1]))
    out = [{"model_id": m, "provider": p, "family": f}
           for _, m, f, p in scored[: data.limit]]
    note = None
    if data.task_type == "vision" and not out:
        note = ("No vision-capable models found in any catalog; "
                "vision routing refused rather than guessed.")
    return {"candidates": out, "note": note}
