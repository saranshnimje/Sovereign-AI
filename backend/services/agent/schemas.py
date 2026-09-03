"""Structured Pydantic schemas for the agent runtime.

Every LLM interaction produces typed output — never rely on free-form prose
to control the agent loop.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


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
    decision: Literal["CONTINUE", "RETRY", "REPLAN", "VERIFY", "COMPLETE", "ASK_USER", "FAIL"]
    reason: str
    next_action: ToolAction | None = None


# ---------------------------------------------------------------------------
# Observation (after tool execution)
# ---------------------------------------------------------------------------

class Observation(BaseModel):
    tool: str
    success: bool
    exit_code: int | None = None
    observation: str
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
    failure_type: Literal["TRANSIENT", "BAD_INPUT", "UNAVAILABLE", "FATAL"] = "TRANSIENT"
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

def parse_llm_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response. Handles markdown fences, prose wrapping."""
    text = re.sub(r"```(?:json)?\n?", "", text)
    text = re.sub(r"```\n?", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
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
