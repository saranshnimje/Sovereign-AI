"""Structured Pydantic schemas for the agent runtime.

Every LLM interaction produces typed output — never rely on free-form prose
to control the agent loop.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Request Intent (Understanding Stage)
# ---------------------------------------------------------------------------

class RequestIntent(str, Enum):
    """Classification of user request intent."""
    CONVERSATION = "conversation"   # Greetings, thanks, small talk
    KNOWLEDGE = "knowledge"         # Questions, explanations, definitions
    ANALYSIS = "analysis"           # Compare, summarize, analyze content
    TOOL_TASK = "tool_task"         # Explicit tool request (read file, search KB)
    TASK = "task"                   # Complex multi-step task


class UnderstandingResult(BaseModel):
    """Output of the UNDERSTAND/ROUTE stage."""
    intent: RequestIntent
    goal: str
    needs_plan: bool = False
    needs_tools: bool = False
    needs_verification: bool = False
    confidence: float = 1.0
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Goal + Acceptance Criteria
# ---------------------------------------------------------------------------

class AcceptanceCriteria(BaseModel):
    goal: str
    criteria: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    id: int
    description: str
    tool: str | None = None
    success_criteria: str = ""
    status: Literal["pending", "running", "completed", "failed", "blocked", "skipped"] = "pending"
    attempts: int = 0
    error: str | None = None


class Plan(BaseModel):
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool Action
# ---------------------------------------------------------------------------

class ToolAction(BaseModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Agent Decision (from the Reasoner)
# ---------------------------------------------------------------------------

class AgentDecision(BaseModel):
    decision: Literal["CONTINUE", "RETRY", "REPLAN", "VERIFY", "COMPLETE", "ASK_USER", "FAIL", "ANSWER_DIRECTLY"]
    reason: str
    next_action: ToolAction | None = None
    answer: str | None = None


# ---------------------------------------------------------------------------
# Observation (after tool execution)
# ---------------------------------------------------------------------------

class Observation(BaseModel):
    tool: str
    success: bool
    exit_code: int | None = None
    observation: str
    failure_type: str | None = None
    evidence: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    output_summary: str = ""


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class VerificationCriteriaResult(BaseModel):
    criterion: str
    satisfied: bool
    evidence: str = ""


class VerificationResult(BaseModel):
    verified: bool
    confidence: float = 0.0
    criteria: list[VerificationCriteriaResult] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Replan Request
# ---------------------------------------------------------------------------

class ReplanRequest(BaseModel):
    reason: str
    failure_type: Literal["TRANSIENT", "INVALID_TOOL_ARGUMENTS", "NOT_FOUND", "RATE_LIMIT", "MODEL_ERROR", "TOOL_ERROR", "VERIFICATION_FAILED", "UNAVAILABLE", "FATAL"] = "TRANSIENT"
    new_steps: list[PlanStep] | None = None


# ---------------------------------------------------------------------------
# Agent Event (persisted + streamed)
# ---------------------------------------------------------------------------

class AgentEvent(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence: int = 0
    run_id: str = ""
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# LLM Output Parsing
# ---------------------------------------------------------------------------

def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the best balanced top-level JSON object embedded in `text`.

    Walks each ``{`` tracking brace depth inside string literals (incl. escaped
    quotes) so trailing prose, multiple objects, or braces inside string values
    never break extraction. If several objects parse, the one with the most
    top-level keys wins — model responses often embed a small incidental object
    (``{"a": 1}``) beside the real schema payload, which has more fields. Returns
    None if no balanced object yields a valid dict.
    """
    start = 0
    best: dict[str, Any] | None = None
    while start < len(text):
        start = text.find("{", start)
        if start == -1:
            break
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        obj = json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # not valid JSON — try the next '{'
                    if isinstance(obj, dict) and (
                        best is None or len(obj) > len(best)
                    ):
                        best = obj
                    break
        start += 1
    return best


def parse_llm_json(text: str | None) -> dict[str, Any]:
    """Extract JSON from an LLM response. Robust to real-world model output:
      - None/empty content
      - markdown code fences (```json … ```)
      - JSON embedded in surrounding prose / reasoning text
      - multiple JSON objects, whitespace noise
    Returns a dict on success, or ``{"type": "error", ...}`` when nothing usable.
    """
    if text is None or not text.strip():
        return {"type": "error", "message": "Empty or None response from LLM"}
    text = text.strip()

    # Fast path: the whole response is the JSON object.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strip markdown fences, then retry.
    fenced = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    try:
        parsed = json.loads(fenced)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Balanced-brace extraction (handles prose-wrapped + trailing text).
    obj = _extract_json_object(text)
    if obj is not None:
        return obj
    obj = _extract_json_object(fenced)
    if obj is not None:
        return obj

    return {"type": "error", "message": f"Could not parse LLM output: {text[:300]}"}


def safe_parse(text: str, model: type[T], fallback: T | None = None) -> T | None:
    """Parse LLM JSON into a Pydantic model. Returns None on failure."""
    data = parse_llm_json(text)
    if data.get("type") == "error":
        return fallback
    try:
        return model.model_validate(data)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Native function-call token recovery
# ---------------------------------------------------------------------------

# GLM / Qwen-JetBrains dialect: <|tool_call_start|>…<|tool_call_end|>
# Body is either a single call "tool_name(args)" or a bracketed list of calls
# "[tool_a(args), tool_b(args)]" (models often emit several parallel calls).
_NATIVE_TOOLCALL_GEMMA = re.compile(
    r"<\|tool_call_start\|>(.*?)<\|tool_call_end\|>",
    re.DOTALL,
)
# One call inside the body: tool_name(arg1='v1', arg2=v2, ...)
_NATIVE_TOOLCALL_CALL = re.compile(
    r"([A-Za-z0-9_]+)\s*\((.*?)\)",
    re.DOTALL,
)
# A bracketed list of calls, ordered by their position in the body
_NATIVE_TOOLCALL_LIST = re.compile(
    r"\[\s*(.*?)\]",
    re.DOTALL,
)

# Qwen dialect: <tool_call>tool_name<arg_key>...</arg_key><arg_value>...</arg_value></tool_call>
_NATIVE_TOOLCALL_XML = re.compile(
    r"<tool_call>\s*([A-Za-z0-9_]+)(.*?)</tool_call>",
    re.DOTALL,
)
_NATIVE_TOOLCALL_KEYS = re.compile(
    r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>",
    re.DOTALL,
)

_KWARG_RE = re.compile(
    r"""([A-Za-z0-9_]+)\s*=\s*(?P<q>['"])(?P<v>.*?)(?P=q)|([A-Za-z0-9_]+)\s*=\s*([^\s,()]+)""",
)


def _parse_call_body(argstr: str) -> dict[str, Any]:
    """Parse ``key='value', other=1`` into ``{"key": "value", "other": "1"}``."""
    input_: dict[str, Any] = {}
    for km in _KWARG_RE.finditer(argstr):
        if km.group("q"):
            key, val = km.group(1), km.group("v")
        else:
            key, val = km.group(4), km.group(5)
        input_[key] = val.strip()
    return input_


def extract_native_tool_call(text: str | None) -> dict[str, Any] | None:
    """Recover a tool call emitted in native function-call token syntax.

    Dialects handled:

    * ``<|tool_call_start|>tool_name(key='val', ...)<|tool_call_end|>``
      (GLM-4, Qwen-JetBrains, DeepSeek-Coder-V2)
    * ``<|tool_call_start|>[tool_a(...), tool_b(...)]<|tool_call_end|>``
      (a bracketed list of parallel calls — the first is returned)
    * ``<tool_call>tool_name<arg_key>k</arg_key><arg_value>v</arg_value></tool_call>``
      (Qwen default)

    Returns ``{"tool": name, "input": {k: v, ...}}`` or ``None``.
    """
    if not text:
        return None

    # --- Gemma / GLM / JetBrains format ---
    m = _NATIVE_TOOLCALL_GEMMA.search(text)
    if m:
        body = m.group(1)
        # A bracketed list of parallel calls: take the FIRST call in the list.
        listed = _NATIVE_TOOLCALL_LIST.search(body)
        calls_text = listed.group(1) if listed else body
        call = _NATIVE_TOOLCALL_CALL.search(calls_text)
        if call:
            return {
                "tool": call.group(1),
                "input": _parse_call_body(call.group(2)),
            }
        # Fall through to Qwen XML handling (body may hold a <tool_call> instead)
        m2 = _NATIVE_TOOLCALL_XML.search(body)
        if m2:
            name = m2.group(1)
            kwargs: dict[str, Any] = {}
            for km in _NATIVE_TOOLCALL_KEYS.finditer(m2.group(2)):
                kwargs[km.group(1).strip()] = km.group(2).strip()
            if kwargs:
                return {"tool": name, "input": kwargs}
        return None

    # --- Qwen XML format ---
    m = _NATIVE_TOOLCALL_XML.search(text)
    if m:
        name = m.group(1)
        body = m.group(2)
        kwargs: dict[str, Any] = {}
        for km in _NATIVE_TOOLCALL_KEYS.finditer(body):
            kwargs[km.group(1).strip()] = km.group(2).strip()
        if kwargs:
            return {"tool": name, "input": kwargs}
        return None

    return None


def coerce_decision_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize common model drift so ``AgentDecision`` validates.

    * ``reasoning`` → ``reason``  (models mislabel the field)
    * ``next_action`` as a list of parallel tools → take the first element
    * ``parameters`` alias → ``input``
    """
    out = dict(data)
    if "reason" not in out and "reasoning" in out:
        out["reason"] = out["reasoning"]
    na = out.get("next_action")
    if isinstance(na, list):
        out["next_action"] = na[0] if na else None
    na = out.get("next_action")
    if isinstance(na, dict):
        na2 = dict(na)
        if "parameters" in na2 and "input" not in na2:
            na2["input"] = na2.pop("parameters")
        if isinstance(na2.get("input"), str):
            na2["input"] = {"value": na2["input"]}
        out["next_action"] = na2
    return out
