"""
Vision inspection service — LOCAL multimodal analysis of inspection images.

SOVEREIGNTY RULE: images are analysed ONLY through the local Ollama
provider. Cloud adapters are refused explicitly — an image must never
leave the machine.

HONESTY RULE: callers receive one of exactly three outcomes:
  completed  → validated structured findings actually returned by the model
  unavailable→ no local vision model configured / provider unreachable
  failed     → provider or validation error (real message preserved)
No code path fabricates a "defect detected" result.
"""
from __future__ import annotations

import base64
import json
import logging

from services.llm_client import ModelUnavailableError, OllamaProvider

logger = logging.getLogger(__name__)

ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_MAX_STR = 2000


class VisionError(Exception):
    """Raised when the model response cannot be validated."""


def resolve_vision_model() -> str | None:
    """
    Configured vision model name, if any:
      model-roles binding ("vision") wins, else DEFAULT_VISION_MODEL env.
    Empty/None ⇒ vision is NOT configured.
    """
    try:
        from services.model_service import _load_roles

        bound = (_load_roles() or {}).get("vision")
        if bound and str(bound).strip():
            return str(bound).strip()
    except Exception:  # roles file unreadable — fall through to settings
        pass
    from config import get_settings

    name = (get_settings().default_vision_model or "").strip()
    return name or None


def build_vision_prompt(machine: str, asset_tag: str | None) -> tuple[str, str]:
    """(system, user) prompt demanding STRICT JSON per the inspection schema."""
    system = (
        "You are an industrial visual-inspection assistant. Analyse ONLY what is "
        "visible in the supplied image. Respond with a SINGLE valid JSON object and "
        "nothing else, using EXACTLY this schema:\n"
        '{"finding": string, '
        '"defects": [{"type": string, "severity": "LOW|MEDIUM|HIGH|CRITICAL", '
        '"confidence": number between 0 and 1, "description": string}], '
        '"recommendation": string, "limitations": [string]}\n'
        "Rules: describe only observable evidence; use LOW/MEDIUM/HIGH/CRITICAL "
        "verbatim; confidence reflects how certain the visual evidence is; if the "
        "image is unclear or shows no defect, say so inside 'finding' and return an "
        "empty defects list; never invent measurements or part numbers."
    )
    ctx = f"Machine: {machine or 'unspecified'}"
    if asset_tag:
        ctx += f" · Asset: {asset_tag}"
    user = (
        f"{ctx}\nInspect this image for visible mechanical/thermal/surface "
        "abnormalities relevant to the reported incident. Return only the JSON object."
    )
    return system, user


def _clean_str(v, limit: int = _MAX_STR) -> str:
    return "" if v is None else str(v)[:limit]


def parse_vision_response(text: str) -> dict:
    """
    Validate + normalise a model response into the structured schema.
    Raises VisionError on anything that is not a conforming JSON object.
    Never partially trusts the model: every field is type-checked here.
    """
    raw = (text or "").strip()
    # strip optional markdown fences
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise VisionError("Malformed model response: no JSON object found")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise VisionError(f"Malformed model response: invalid JSON ({exc})") from exc

    if not isinstance(data, dict):
        raise VisionError("Malformed model response: top-level must be an object")

    finding = _clean_str(data.get("finding"))
    recommendation = data.get("recommendation")
    limitations_raw = data.get("limitations") or []
    defects_raw = data.get("defects")

    if not isinstance(defects_raw, list):
        raise VisionError("Malformed model response: 'defects' must be a list")

    defects: list[dict] = []
    for d in defects_raw[:20]:
        if not isinstance(d, dict):
            raise VisionError("Malformed model response: defect entries must be objects")
        severity = _clean_str(d.get("severity"), 20).upper()
        if severity not in ALLOWED_SEVERITIES:
            raise VisionError(
                f"Malformed model response: invalid severity {severity!r}")
        try:
            confidence = float(d.get("confidence"))
        except (TypeError, ValueError):
            raise VisionError(
                "Malformed model response: defect confidence must be numeric")
        confidence = min(1.0, max(0.0, confidence))
        defects.append({
            "type": _clean_str(d.get("type"), 120),
            "severity": severity,
            "confidence": round(confidence, 4),
            "description": _clean_str(d.get("description"), 1000),
        })

    limitations = [_clean_str(x, 300) for x in limitations_raw if isinstance(x, str)][:10]

    return {
        "finding": finding,
        "defects": defects,
        "recommendation": _clean_str(recommendation) if recommendation is not None else None,
        "limitations": limitations,
    }


async def analyze_image(
    llm,
    model: str,
    image_bytes: bytes,
    machine: str,
    asset_tag: str | None,
) -> dict:
    """
    Run local vision analysis.
    Returns {"status": "completed", "result": {...}, "model": model}
    Raises ModelUnavailableError when provider unreachable/not configured;
    VisionError on malformed output; other exceptions propagate as failures.

    Only the LOCAL Ollama provider is permitted (sovereignty rule).
    """
    if not isinstance(llm, OllamaProvider):
        raise ModelUnavailableError(
            "Vision requires the local Ollama provider; cloud providers are blocked")

    b64 = base64.b64encode(image_bytes).decode()
    system, user = build_vision_prompt(machine, asset_tag)
    from services.llm_client import ChatMessage

    resp = await llm.chat(
        model=model,
        messages=[ChatMessage(role="user", content=user, images=[b64])],
        system_prompt=system,
        temperature=0.1,
        max_tokens=900,
        stream=False,
    )
    text = getattr(resp, "content", "") or ""
    result = parse_vision_response(text)
    return {"status": "completed", "result": result, "model": model}
