"""
system_status tool — returns actual local service and model status.
LOW risk, read-only. No secrets exposed.
"""
from __future__ import annotations

from pydantic import BaseModel


class SystemStatusInput(BaseModel):
    pass


class SystemStatusOutput(BaseModel):
    ollama_status: str
    models: list[dict]
    sandbox_available: bool


async def execute(inp: SystemStatusInput, context: dict) -> dict:
    from config import get_settings
    settings = get_settings()

    ollama_status = "unavailable"
    models = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            if resp.status_code == 200:
                ollama_status = "available"
                data = resp.json()
                for m in data.get("models", []):
                    models.append({
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                    })
    except Exception:
        pass

    sandbox_available = False
    try:
        from services.sandbox_service import SandboxService
        sandbox = SandboxService()
        sandbox_available = sandbox.available
    except Exception:
        pass

    return {
        "ollama_status": ollama_status,
        "models": models[:10],
        "sandbox_available": sandbox_available,
    }
