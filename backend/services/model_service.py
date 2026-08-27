"""
Model management service — proxies Ollama model list and manages role assignments.
Role assignments are persisted to a JSON file whose path is derived from
config.Settings.model_roles_file (configurable via DATA_DIR env var).
"""
import json
import logging
import os
from typing import AsyncGenerator

import httpx

from config import get_settings
from schemas.model import ModelInfo
from services.llm_client import OllamaClient

logger = logging.getLogger(__name__)

_DEFAULT_ROLES = {
    "chat": "llava:7b",
    "embedding": "nomic-embed-text:latest",
    "vision": None,
}


def _roles_file() -> str:
    """Always derive path from config so DATA_DIR is respected."""
    return get_settings().model_roles_file


def _load_roles() -> dict:
    path = _roles_file()
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return dict(_DEFAULT_ROLES)


def _save_roles(roles: dict) -> None:
    path = _roles_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(roles, f, indent=2)


class ModelService:
    def __init__(self, llm: OllamaClient) -> None:
        self.llm = llm
        self.settings = get_settings()

    async def list_models(self) -> list[ModelInfo]:
        """Return all Ollama models with role annotations."""
        raw = await self.llm.list_models()
        roles = _load_roles()
        active_models = {v: k for k, v in roles.items() if v}

        result = []
        for m in raw:
            name = m.get("name", "")
            details = m.get("details", {})
            assigned_roles = [r for r, model in roles.items() if model == name]
            result.append(
                ModelInfo(
                    name=name,
                    display_name=name,
                    family=details.get("family"),
                    parameter_size=details.get("parameter_size"),
                    quantization=details.get("quantization_level"),
                    size_bytes=m.get("size"),
                    modified_at=m.get("modified_at"),
                    roles=assigned_roles,
                    status="available",
                )
            )
        return result

    def get_roles(self) -> dict:
        return _load_roles()

    def set_role(self, role: str, model_name: str, provider_id: str | None = None) -> dict:
        if role not in ("chat", "embedding", "vision"):
            from fastapi import HTTPException
            raise HTTPException(400, f"Unknown role: {role}")
        roles = _load_roles()
        roles[role] = model_name
        # Provider binding for this role (None = default local Ollama instance)
        roles[f"{role}_provider_id"] = provider_id
        _save_roles(roles)
        return roles

    async def health_check(self, model_name: str) -> dict:
        is_up, latency = await self.llm.health_check(model_name)
        return {
            "model": model_name,
            "status": "available" if is_up else "unavailable",
            "latency_ms": latency,
        }

    async def stream_pull(self, model_name: str) -> AsyncGenerator[str, None]:
        """Stream pull progress from Ollama as SSE."""
        settings = get_settings()
        url = settings.ollama_url.rstrip("/") + "/api/pull"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=600, write=30, pool=5)) as client:
                async with client.stream("POST", url, json={"name": model_name}) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.strip():
                            yield f"data: {line}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
