"""Gemini model-discovery helper.

Google Gemini does not expose an OpenAI-compatible /v1/models response.
Use GET /v1beta/models?key=... and read the top-level `models` array.
"""
from __future__ import annotations

import httpx


async def list_gemini_models(api_key: str, base_url: str = "https://generativelanguage.googleapis.com") -> list[dict]:
    """Return Gemini models that support generateContent.

    Kept as a small helper so the provider can use the native Gemini API
    instead of the OpenAI-compatible model-list format.
    """
    url = f"{base_url.rstrip('/')}/v1beta/models"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params={"key": api_key})
        response.raise_for_status()
        data = response.json()

    models: list[dict] = []
    for model in data.get("models", []):
        methods = model.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        name = model.get("name", "")
        if name.startswith("models/"):
            name = name[len("models/"):]
        models.append({
            "id": name,
            "name": name,
            "display_name": model.get("displayName") or name,
            "provider": "gemini",
            "raw": model,
        })
    return models
