"""
AgentRuntime — the single canonical autonomous agent loop.

Lifecycle:
  UNDERSTAND → PLAN → DECIDE → EXECUTE → OBSERVE → EVALUATE → VERIFY
       ↓                                              ↓
     DONE ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←← REPLAN
                                                        ↓
                                                     DECIDE
                                                        ↓
                                                     EXECUTE  ↺

The runtime owns the entire autonomous loop.
chat.py is a thin router that creates a runtime and streams its events.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.prompts import (
    COMPRESS_PROMPT,
    PLANNER_SYSTEM,
    PLANNER_USER,
    REASONER_SYSTEM,
    REASONER_USER,
    REPLANNER_SYSTEM,
    REPLANNER_USER,
    SIMPLE_REQUEST_SYSTEM,
    SIMPLE_REQUEST_USER,
    UNDERSTAND_SYSTEM,
    UNDERSTAND_USER,
    VERIFIER_SYSTEM,
    VERIFIER_USER,
)
from services.agent.schemas import (
    AgentDecision,
    Observation,
    Plan,
    PlanStep,
    RequestIntent,
    ToolAction,
    UnderstandingResult,
    VerificationCriteriaResult,
    VerificationResult,
    coerce_decision_data,
    extract_native_tool_call,
    parse_llm_json,
)
from services.agent_state import (
    AgentState,
    AgentStateMachine,
    MAX_ITERATIONS,
    MAX_TOOL_CALLS,
    MAX_REPLANS,
    MAX_RETRIES_PER_TOOL,
)
from services.llm_client import ChatMessage, ModelUnavailableError

logger = logging.getLogger(__name__)

# Max characters of tool output to include in LLM context
_MAX_OUTPUT_IN_CONTEXT = 2000

# Hard wall-clock timeout from environment
AGENT_MAX_RUNTIME_SECONDS = int(os.environ.get("AGENT_MAX_RUNTIME_SECONDS", "300"))

# Simple request patterns that don't need planning
_SIMPLE_REQUEST_PATTERNS = [
    r"^\s*(hi+|hello|hey|howdy|greetings)\s*(there)?\s*[!.]*\s*$",
    r"^\s*(good\s+(morning|afternoon|evening|day))\s*[!.]*\s*$",
    r"^\s*(thanks|thank\s*you|thx|ty)\s*[!.]*\s*$",
    r"^\s*(how\s+are\s+you|how\s+are\s+things|hru)\s*[?!]*\s*$",
    r"^\s*(what'?s\s+up|sup|yo)\s*[?!]*\s*$",
    r"^\s*(bye+|goodbye|see\s+ya|later|cya)\s*[!.]*\s*$",
    r"^\s*(ok|okay|k|sure|alright|cool|nice|great|awesome)\s*[!.]*\s*$",
    r"^\s*(help|what\s+can\s+you\s+do)\s*[?!]*\s*$",
    r"^\s*(who\s+are\s+you|what\s+are\s+you)\s*[?!]*\s*$",
]

# Timeout per LLM call type (seconds)
_TIMEOUT_PLANNER = 60.0
_TIMEOUT_REASONER = 60.0
_TIMEOUT_VERIFIER = 60.0
_TIMEOUT_REPLANNER = 60.0

# Loop detection: fingerprint threshold
_LOOP_DETECTION_THRESHOLD = 3

# Events that should be persisted to DB for durable execution timeline
_PERSIST_EVENT_TYPES = frozenset({
    "agent_started", "plan_created", "plan_updated",
    "tool_call", "tool_result", "tool_timeout", "tool_error",
    "observation", "verification", "verification_passed", "verification_failed",
    "final_response", "done", "error", "cancelled",
})


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(payload)}\n\n"


def _fingerprint(tool_name: str, tool_input: dict) -> str:
    """Compute a normalized action fingerprint for loop detection."""
    normalized = _json.dumps(tool_input, sort_keys=True, default=str)
    return f"{tool_name}::{normalized}"


# Tool-name aliases the LLM may emit instead of canonical registry names.
# Smaller/free models frequently output "websearch"/"search" for the canonical
# "web_search" tool or "webfetch" for "web_fetch". We canonicalize centrally,
# BEFORE any permission check, registry lookup, validation, or execution, so a
# misnamed tool never surfaces as "Tool 'x' not found". We do NOT register
# duplicate tools to compensate for model mistakes — aliases stay in one place.
_TOOL_ALIASES = {
    "websearch": "web_search",
    "web-search": "web_search",
    "search": "web_search",
    "websrch": "web_search",
    "web": "web_search",
    "google": "web_search",
    "google-search": "web_search",
    "google_search": "web_search",
    "bing": "web_search",
    "duckduckgo": "web_search",
    "search-the-web": "web_search",
    "webfetch": "web_fetch",
    "web-fetch": "web_fetch",
    "fetch": "web_fetch",
    "fetch-url": "web_fetch",
    "fetch_url": "web_fetch",
    "get-page": "web_fetch",
    "getpage": "web_fetch",
    "httpget": "web_fetch",
    "url": "web_fetch",
}


def canonicalize_tool_name(name: str | None) -> str | None:
    """Resolve a model-proposed tool name to its canonical registry name.

    Trims whitespace, normalizes case, then checks the alias map. Unknown names
    pass through (normalized so exact canonical lowercase names still match).
    """
    if not name:
        return name
    normalized = re.sub(r"\s+", " ", name.strip()).lower()
    return _TOOL_ALIASES.get(normalized, normalized)


def _verify_tool_result(tool_name: str, result: dict) -> tuple[bool, str]:
    """Objective verification of a tool result. Returns (passed, reason)."""
    if result.get("error"):
        return False, f"Tool error: {str(result['error'])[:200]}"

    if tool_name in ("run_command", "run_powershell"):
        exit_code = result.get("exit_code", -1)
        if exit_code != 0:
            stderr = result.get("stderr", "")[:200]
            return False, f"Command failed (exit {exit_code}): {stderr}"

    if tool_name == "file_write":
        if not result.get("path"):
            return False, "File write did not return a path"

    if tool_name == "python_exec":
        exit_code = result.get("exit_code", -1)
        if exit_code is not None and exit_code != 0:
            return False, f"Python execution failed (exit {exit_code})"

    return True, "OK"


def _classify_failure(tool_name: str, result: dict, error: str) -> str:
    """Classify a tool failure for the replanner.

    Returns: TRANSIENT | INVALID_TOOL_ARGUMENTS | NOT_FOUND | RATE_LIMIT |
             MODEL_ERROR | TOOL_ERROR | VERIFICATION_FAILED | UNAVAILABLE | FATAL
    """
    err = (error or str(result.get("error", ""))).lower()

    # INVALID_TOOL_ARGUMENTS: validation errors, missing fields, wrong types
    if "validation" in err or "missing" in err or "required" in err or "invalid" in err:
        return "INVALID_TOOL_ARGUMENTS"

    # NOT_FOUND
    if "not found" in err or "does not exist" in err:
        return "NOT_FOUND"

    # RATE_LIMIT
    if "rate limit" in err or "too many" in err or "429" in err:
        return "RATE_LIMIT"

    # MODEL_ERROR
    if "model" in err and ("error" in err or "unavailable" in err):
        return "MODEL_ERROR"

    # TIMEOUT
    if "timeout" in err or "timed out" in err:
        return "TRANSIENT"

    # PERMISSION
    if "permission" in err or "denied" in err or "forbidden" in err:
        return "FATAL"

    # UNAVAILABLE
    if "not available" in err or "unavailable" in err:
        return "UNAVAILABLE"

    # For command tools, non-zero exit
    if tool_name in ("run_command", "run_powershell", "python_exec"):
        exit_code = result.get("exit_code", -1)
        if exit_code is not None and exit_code != 0:
            return "TOOL_ERROR"

    return "TRANSIENT"


class AgentRuntime:
    """Single canonical autonomous agent loop.

    Usage:
        runtime = AgentRuntime()
        async for event_str in runtime.run(...):
            yield event_str  # SSE
    """

    def __init__(self) -> None:
        self._sequence: int = 0
        self._run_id: str | None = None
        self._db: AsyncSession | None = None
        self._user_kb_ids: list[str] | None = None

    async def _emit_event(self, event_type: str, payload: dict) -> str:
        """Emit an SSE event with monotonically increasing sequence number.

        If run_id and db are set, persists the event to the agent_events table.
        Returns the SSE string for yielding.
        """
        self._sequence += 1
        sse_str = _sse(event_type, payload)

        # Persist to DB if we have a run_id and db session
        if self._run_id and self._db:
            try:
                from models.agent import AgentEvent
                evt = AgentEvent(
                    run_id=self._run_id,
                    sequence=self._sequence,
                    event_type=event_type,
                    payload_json=_json.dumps(payload, default=str),
                )
                self._db.add(evt)
                await self._db.flush()
            except Exception:
                logger.warning("Failed to persist agent event %s", event_type, exc_info=True)

        return sse_str

    @staticmethod
    def _is_simple_request(goal: str) -> bool:
        """Check if the request is a simple conversational greeting."""
        stripped = goal.strip()
        if len(stripped) > 100:
            return False
        for pattern in _SIMPLE_REQUEST_PATTERNS:
            if re.match(pattern, stripped, re.IGNORECASE):
                return True
        return False

    def _build_conversation_context(self, max_messages: int = 20) -> str:
        """Build a conversation context string from recent history.

        Returns a formatted block showing recent turns so the agent can
        reference prior conversation (names, preferences, previous answers).
        Bounded to max_messages to avoid excessive token usage.
        """
        history = self._conversation_history
        if not history:
            return ""

        recent = history[-max_messages:] if len(history) > max_messages else history
        lines = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate very long messages
            if len(content) > 500:
                content = content[:500] + "...[truncated]"
            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
        return "\n".join(lines)

    async def _understand(
        self, *, llm: Any, model: str, goal: str, tool_descriptions: str,
    ) -> UnderstandingResult:
        """Classify user intent and determine execution path.

        Uses deterministic rules for obvious cases, LLM for ambiguous ones.
        Includes conversation history for context-aware classification.
        """
        stripped = goal.strip()

        # --- LLM-based understanding for everything ---
        system = UNDERSTAND_SYSTEM

        # Build user message with conversation context
        conv_ctx = self._build_conversation_context()
        if conv_ctx:
            user_content = (
                f"Recent conversation:\n{conv_ctx}\n\n"
                f"Current user message: {stripped}\n\n"
                f"Available tools:\n{tool_descriptions or 'No tools available'}\n\n"
                "Classify this request and determine the execution path."
            )
        else:
            user_content = UNDERSTAND_USER.format(goal=stripped, tools=tool_descriptions or "No tools available")

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=user_content),
                    ],
                    stream=False,
                    temperature=0.0,
                    max_tokens=512,
                ),
                timeout=30.0,  # Understanding must be fast
            )
            text = (resp.content or "") if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Understanding failed, defaulting to TASK: %s", exc)
            # Conservative fallback: treat as task (will create plan)
            return UnderstandingResult(
                intent=RequestIntent.TASK,
                goal=stripped,
                needs_plan=True,
                needs_tools=True,
                needs_verification=True,
                confidence=0.0,
                reasoning=f"Understanding LLM failed: {exc}",
            )

        data = parse_llm_json(text)
        if data.get("type") == "error":
            logger.warning("Understanding output unparseable: %s", text[:300])
            # Fallback: classify based on heuristics
            return self._heuristic_classify(stripped)

        try:
            result = UnderstandingResult.model_validate(data)
            # Override: CONVERSATION never needs plan/tools/verification
            if result.intent == RequestIntent.CONVERSATION:
                result.needs_plan = False
                result.needs_tools = False
                result.needs_verification = False
            # Knowledge requests are normally answered directly, but requests
            # referring to the user's KB/uploaded documents must enter the
            # tool path so search_kb can retrieve grounded evidence.
            elif result.intent == RequestIntent.KNOWLEDGE:
                kb_terms = (
                    "knowledge base", "knowledge bases", "kb", "uploaded",
                    "my documents", "my document", "my files", "my file",
                    "policy", "policies", "from my", "using my",
                )
                goal_lower = goal.lower()
                wants_user_knowledge = any(term in goal_lower for term in kb_terms)
                if wants_user_knowledge and self._user_kb_ids and "search_kb" in tool_names:
                    result.intent = RequestIntent.TASK
                    result.needs_plan = True
                    result.needs_tools = True
                    result.needs_verification = True
                else:
                    result.needs_plan = False
                    result.needs_verification = False
            # Override: ANALYSIS never needs plan
            elif result.intent == RequestIntent.ANALYSIS:
                result.needs_plan = False
            return result
        except Exception:
            logger.warning("Understanding schema invalid: %s", data)
            return self._heuristic_classify(stripped)

    @staticmethod
    def _heuristic_classify(goal: str) -> UnderstandingResult:
        """Fallback heuristic classification when LLM understanding fails."""
        lower = goal.lower().strip()

        # Knowledge questions
        knowledge_patterns = [
            r"^what\s+(is|are|was|were)\b",
            r"^how\s+(do|does|did|can|could|would|should)\b",
            r"^why\s+(do|does|did|is|are)\b",
            r"^explain\b",
            r"^define\b",
            r"^tell\s+me\s+about\b",
        ]
        for p in knowledge_patterns:
            if re.match(p, lower):
                return UnderstandingResult(
                    intent=RequestIntent.KNOWLEDGE,
                    goal=goal,
                    needs_plan=False,
                    needs_tools=False,
                    needs_verification=False,
                    confidence=0.7,
                    reasoning="Heuristic: knowledge question pattern",
                )

        # Tool tasks
        tool_patterns = [
            r"^read\b",
            r"^search\b",
            r"^find\b",
            r"^run\b",
            r"^execute\b",
            r"^open\b",
        ]
        for p in tool_patterns:
            if re.match(p, lower):
                return UnderstandingResult(
                    intent=RequestIntent.TOOL_TASK,
                    goal=goal,
                    needs_plan=False,
                    needs_tools=True,
                    needs_verification=True,
                    confidence=0.7,
                    reasoning="Heuristic: tool task pattern",
                )

        # Default: treat as task
        return UnderstandingResult(
            intent=RequestIntent.TASK,
            goal=goal,
            needs_plan=True,
            needs_tools=True,
            needs_verification=True,
            confidence=0.5,
            reasoning="Heuristic fallback: treating as task",
        )

    # ------------------------------------------------------------------
    # Intent-specific handlers
    # ------------------------------------------------------------------

    async def _generate_conversation_response(
        self, *, llm: Any, model: str, goal: str,
    ) -> str:
        """Generate a conversational response via the configured LLM.

        Never fabricates responses in Python — always delegates to the
        configured provider so the selected model is actually invoked.
        """
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=SIMPLE_REQUEST_SYSTEM),
            ChatMessage(role="user", content=SIMPLE_REQUEST_USER.format(goal=goal)),
        ]
        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=messages,
                    stream=False,
                    temperature=0.7,
                    max_tokens=256,
                ),
                timeout=30.0,
            )
            return (resp.content or "") if hasattr(resp, "content") else str(resp)
        except Exception as exc:
            logger.warning("Conversation response LLM failed: %s", exc)
            # Absolute fallback — still not hardcoded content
            return f"I'm here to help. You said: {goal[:200]}"

    async def _generate_knowledge_response(
        self, *, llm: Any, model: str, goal: str,
    ) -> str:
        """Generate a direct knowledge response without tools.

        Includes conversation history for context-aware answers (e.g., remembering
        user's name from earlier in the conversation).
        """
        system = "You are a helpful AI assistant inside Sovereign AI Workbench. Answer the user's question directly and concisely. Do NOT use any tools. Keep your response under 200 words. If the user mentioned something earlier in the conversation, use that context to provide a better answer."

        # Build message list with conversation history
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system),
        ]

        # Add conversation history for context
        conv_ctx = self._build_conversation_context(max_messages=10)
        if conv_ctx:
            messages.append(ChatMessage(
                role="user",
                content=f"Recent conversation for context:\n{conv_ctx}\n\nCurrent question: {goal}",
            ))
        else:
            messages.append(ChatMessage(role="user", content=f"Question: {goal}"))

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=messages,
                    stream=False,
                    temperature=0.3,
                    max_tokens=1024,
                ),
                timeout=60.0,
            )
            return (resp.content or "") if hasattr(resp, "content") else str(resp)
        except Exception as exc:
            logger.warning("Knowledge response failed: %s", exc)
            return f"I understand you're asking about: {goal}. I'm having trouble generating a response right now."

    async def _handle_analysis_with_tools(
        self, *, llm: Any, model: str, goal: str,
        tool_names: list[str], tool_descriptions: str,
        user_role: str, db: AsyncSession, user_id: str, reg: Any,
        agent: AgentStateMachine,
        observations: list[Observation], evidence: list[str],
        tool_results_context: list[str], failed_attempts: list[dict],
        start_time: float, _action_fingerprints: dict[str, int],
    ) -> str:
        """Handle analysis requests that may need tools but no multi-step plan."""
        # Single-step: let reasoner pick one tool, execute, respond
        decision = await self._decide(
            llm=llm, model=model, goal=goal, agent=agent,
            observations=observations, evidence=evidence,
            failed_attempts=failed_attempts,
            tool_results_context=tool_results_context,
            tool_descriptions=tool_descriptions,
        )

        if decision.decision in ("CONTINUE", "RETRY") and decision.next_action:
            action = decision.next_action
            action.tool = canonicalize_tool_name(action.tool) or action.tool
            if action.tool in tool_names:
                result = await self._execute_tool(
                    tool_name=action.tool, tool_input=action.input,
                    user_role=user_role, db=db, user_id=user_id, reg=reg, llm=llm,
                )
                passed, reason = _verify_tool_result(action.tool, result)
                tool_results_context.append(f"{action.tool} → {reason[:200]}")
                if passed:
                    evidence.append(reason)

        # Generate response with LLM
        return await self._generate_knowledge_response(llm=llm, model=model, goal=goal)

    async def _handle_tool_task(
        self, *, llm: Any, model: str, goal: str,
        tool_names: list[str], tool_descriptions: str,
        user_role: str, db: AsyncSession, user_id: str, reg: Any,
        agent: AgentStateMachine,
        observations: list[Observation], evidence: list[str],
        tool_results_context: list[str], failed_attempts: list[dict],
        start_time: float, _action_fingerprints: dict[str, int],
    ) -> str:
        """Handle explicit tool task requests (single tool execution)."""
        # Let reasoner pick the right tool
        decision = await self._decide(
            llm=llm, model=model, goal=goal, agent=agent,
            observations=observations, evidence=evidence,
            failed_attempts=failed_attempts,
            tool_results_context=tool_results_context,
            tool_descriptions=tool_descriptions,
        )

        if decision.decision in ("CONTINUE", "RETRY") and decision.next_action:
            action = decision.next_action
            action.tool = canonicalize_tool_name(action.tool) or action.tool
            if action.tool in tool_names:
                result = await self._execute_tool(
                    tool_name=action.tool, tool_input=action.input,
                    user_role=user_role, db=db, user_id=user_id, reg=reg, llm=llm,
                )
                passed, reason = _verify_tool_result(action.tool, result)
                tool_results_context.append(f"{action.tool} → {reason[:200]}")
                if passed:
                    evidence.append(reason)
                    return f"Tool execution completed successfully.\n\nResult:\n{reason[:500]}"
                else:
                    return f"Tool execution failed: {reason[:500]}"
            else:
                return f"Tool '{action.tool}' is not available."
        else:
            return f"I understand you want to use a tool for: {goal}. Let me try to help."

    async def _run_agent_loop(
        self, *, llm: Any, model: str, goal: str,
        agent: AgentStateMachine, plan: Plan | None, reg: Any,
        tool_names: list[str], tool_descriptions: str,
        user_role: str, db: AsyncSession, user_id: str,
        observations: list[Observation], evidence: list[str],
        failed_attempts: list[dict],
        tool_results_context: list[str],
        start_time: float, _action_fingerprints: dict[str, int],
        _result: list[str],
        run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run the main agent loop for TASK intent. Yields SSE events."""
        final_content = ""

        for iteration in range(MAX_ITERATIONS):
            # Check wall-clock timeout
            elapsed = time.monotonic() - start_time
            if elapsed > AGENT_MAX_RUNTIME_SECONDS:
                agent.fail(
                    f"Wall-clock timeout exceeded ({elapsed:.0f}s > {AGENT_MAX_RUNTIME_SECONDS}s)"
                )
                yield _sse("agent_state", agent.to_dict())
                error_msg = f"Wall-clock timeout: {AGENT_MAX_RUNTIME_SECONDS}s exceeded"
                yield _sse("error", {"message": error_msg})
                yield _sse("final_response", {
                    "content": error_msg,
                    "token_count": 0,
                    "state": "timed_out",
                    "elapsed_ms": agent.get_elapsed_ms(),
                })
                yield _sse("done", {
                    "content": error_msg,
                    "token_count": 0,
                    "activity": agent.activity,
                    "tool_calls": agent.tool_call_count,
                    "state": "timed_out",
                    "elapsed_ms": agent.get_elapsed_ms(),
                    "plan": [
                        {"id": s.id, "description": s.description, "status": s.status}
                        for s in agent.plan
                    ],
                    "observations": [],
                    "verification": None,
                })
                _result[0] = error_msg
                return

            # Check if already in terminal state
            if agent.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                break

            # Check safety limits
            limit_error = agent.check_limits()
            if limit_error:
                agent.fail(limit_error)
                yield _sse("agent_state", agent.to_dict())
                yield _sse("error", {"message": limit_error})
                yield _sse("final_response", {
                    "content": limit_error,
                    "token_count": 0,
                    "state": agent.state.value,
                    "elapsed_ms": agent.get_elapsed_ms(),
                })
                yield _sse("done", {
                    "content": limit_error,
                    "token_count": 0,
                    "activity": agent.activity,
                    "tool_calls": agent.tool_call_count,
                    "state": agent.state.value,
                    "elapsed_ms": agent.get_elapsed_ms(),
                    "plan": [
                        {"id": s.id, "description": s.description, "status": s.status}
                        for s in agent.plan
                    ],
                    "observations": [],
                    "verification": None,
                })
                _result[0] = limit_error
                return

            # --- REASON: Decide what to do next ---
            decision = await self._decide(
                llm=llm, model=model, goal=goal, agent=agent,
                observations=observations, evidence=evidence,
                failed_attempts=failed_attempts,
                tool_results_context=tool_results_context,
                tool_descriptions=tool_descriptions,
            )

            yield _sse("decision", {
                "decision": decision.decision,
                "reason": decision.reason,
                "iteration": iteration,
            })

            # If agent was cancelled during _decide, break
            if agent.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                break

            match decision.decision:
                case "COMPLETE":
                    # MUST go through verifier
                    yield _sse("verification_started", {"type": "output"})
                    verification = await self._verify(
                        llm=llm, model=model, goal=goal, agent=agent,
                        evidence=evidence, tool_results_context=tool_results_context,
                        observations=observations,
                    )
                    yield _sse("verification", verification.model_dump())

                    if verification.verified:
                        yield _sse("verification_passed", {
                            "type": "output",
                            "confidence": verification.confidence,
                        })
                        final_content = decision.reason or "Task completed successfully."
                        agent.complete()
                        yield _sse("agent_state", agent.to_dict())
                        break
                    else:
                        yield _sse("verification_failed", {
                            "type": "output",
                            "missing": verification.missing,
                        })
                        # Verifier rejected — replan
                        logger.info("Verifier rejected completion: %s", verification.missing)
                        failed_attempts.append({
                            "reason": "Completion rejected by verifier",
                            "missing": verification.missing,
                        })
                        new_plan = await self._replan(
                            llm=llm, model=model, goal=goal,
                            acceptance_criteria=plan.acceptance_criteria if plan else [],
                            failure_reason=f"Verification failed: {verification.missing}",
                            failed_steps=[], evidence=evidence,
                        )
                        if new_plan:
                            plan = new_plan
                            agent.create_plan([
                                {"description": s.description, "tool_name": s.tool}
                                for s in plan.steps
                            ])
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("plan_updated", {
                                "reason": "Completion verification failed",
                                "steps": [s.model_dump() for s in plan.steps],
                            })
                            agent.todo = type(agent.todo)()
                            for s in plan.steps:
                                agent.todo.add_task(s.description, tool_name=s.tool)
                            yield _sse("todo_updated", agent.todo.to_dict())

                case "VERIFY":
                    yield _sse("verification_started", {"type": "output"})
                    verification = await self._verify(
                        llm=llm, model=model, goal=goal, agent=agent,
                        evidence=evidence, tool_results_context=tool_results_context,
                        observations=observations,
                    )
                    yield _sse("verification", verification.model_dump())

                    if verification.verified:
                        yield _sse("verification_passed", {
                            "type": "output",
                            "confidence": verification.confidence,
                        })
                        final_content = "Task completed and verified."
                        agent.complete()
                        yield _sse("agent_state", agent.to_dict())
                        break
                    else:
                        yield _sse("verification_failed", {
                            "type": "output",
                            "missing": verification.missing,
                        })

                case "CONTINUE" | "RETRY":
                    if decision.next_action is None:
                        agent.fail("Reasoner returned CONTINUE/RETRY without next_action")
                        no_action_msg = "No action provided by reasoner"
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("error", {"message": no_action_msg})
                        yield _sse("final_response", {
                            "content": no_action_msg,
                            "token_count": 0,
                            "state": agent.state.value,
                            "elapsed_ms": agent.get_elapsed_ms(),
                        })
                        yield _sse("done", {
                            "content": no_action_msg,
                            "token_count": 0,
                            "activity": agent.activity,
                            "tool_calls": agent.tool_call_count,
                            "state": agent.state.value,
                            "elapsed_ms": agent.get_elapsed_ms(),
                            "plan": [
                                {"id": s.id, "description": s.description, "status": s.status}
                                for s in agent.plan
                            ],
                            "observations": [],
                            "verification": None,
                        })
                        _result[0] = final_content
                        return

                    action = decision.next_action

                    # Normalize the model-proposed tool name (websearch → web_search,
                    # search → web_search, webfetch → web_fetch, …) so allowed-list
                    # checks, loop fingerprints, todo bookkeeping, lifecycle events,
                    # and execution all use the canonical registry name.
                    action.tool = canonicalize_tool_name(action.tool) or action.tool

                    # Skip tool if not in allowed list (tool_mode=none)
                    if tool_names is not None and len(tool_names) == 0:
                        logger.info("Tool %s skipped (tool_mode=none)", action.tool)
                        continue

                    # Enforce per-tool retry limit
                    if not agent.can_retry(action.tool):
                        logger.info("Tool %s exceeded retry limit, skipping", action.tool)
                        failed_attempts.append({
                            "tool": action.tool,
                            "error": f"Exceeded max retries for {action.tool}",
                            "failure_type": "INVALID_TOOL_ARGUMENTS",
                        })
                        continue

                    # --- Loop detection via action fingerprinting ---
                    fp = _fingerprint(action.tool, action.input)
                    _action_fingerprints[fp] = _action_fingerprints.get(fp, 0) + 1
                    if _action_fingerprints[fp] >= _LOOP_DETECTION_THRESHOLD:
                        logger.warning(
                            "Loop detected: fingerprint %s seen %d times",
                            fp[:80], _action_fingerprints[fp],
                        )
                        failed_attempts.append({
                            "tool": action.tool,
                            "error": f"Loop detected: same action repeated {_action_fingerprints[fp]} times",
                            "failure_type": "TOOL_ERROR",
                        })
                        new_plan = await self._replan(
                            llm=llm, model=model, goal=goal,
                            acceptance_criteria=plan.acceptance_criteria if plan else [],
                            failure_reason=f"Loop detected: {action.tool} repeated {_action_fingerprints[fp]} times",
                            failed_steps=[action.tool], evidence=evidence,
                        )
                        if new_plan:
                            plan = new_plan
                            agent.create_plan([
                                {"description": s.description, "tool_name": s.tool}
                                for s in plan.steps
                            ])
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("plan_updated", {
                                "reason": "Loop detected — replanning",
                                "steps": [s.model_dump() for s in plan.steps],
                            })
                            agent.todo = type(agent.todo)()
                            for s in plan.steps:
                                agent.todo.add_task(s.description, tool_name=s.tool)
                            yield _sse("todo_updated", agent.todo.to_dict())
                        else:
                            agent.fail(
                                f"Loop detected: {action.tool} repeated "
                                f"{_action_fingerprints[fp]} times, no alternative plan"
                            )
                            loop_msg = "Loop detected, cannot recover"
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("error", {"message": loop_msg})
                            yield _sse("final_response", {
                                "content": loop_msg,
                                "token_count": 0,
                                "state": agent.state.value,
                                "elapsed_ms": agent.get_elapsed_ms(),
                            })
                            yield _sse("done", {
                                "content": loop_msg,
                                "token_count": 0,
                                "activity": agent.activity,
                                "tool_calls": agent.tool_call_count,
                                "state": agent.state.value,
                                "elapsed_ms": agent.get_elapsed_ms(),
                                "plan": [
                                    {"id": s.id, "description": s.description, "status": s.status}
                                    for s in agent.plan
                                ],
                                "observations": [],
                                "verification": None,
                            })
                            _result[0] = loop_msg
                            return
                        continue

                    call_id = f"call_{iteration}_{action.tool}"

                    # --- Start matching todo task ---
                    for t in agent.todo.tasks:
                        if (
                            t.status == "pending"
                            and t.description
                            and action.tool
                            and t.tool_name == action.tool
                        ):
                            agent.todo.start_task(t.id)
                            break
                    yield _sse("todo_updated", agent.todo.to_dict())

                    # Execute tool
                    agent.start_execution()
                    agent.record_tool_call(action.tool, call_id, action.reasoning[:200])
                    yield _sse("tool_call", {
                        "call_id": call_id,
                        "tool": action.tool,
                        "input_summary": str(action.input)[:200],
                        "reasoning": action.reasoning[:200],
                    })

                    # TASK 5: Guarantee exactly one terminal event per tool_call.
                    # Contract: every tool_call is followed by exactly one of
                    #   tool_result   (status = success | failed | error)
                    #   tool_timeout  (status = timeout)
                    # Wrap in try/except so even if _execute_tool or processing
                    # raises, we emit tool_result(status="error") instead of
                    # leaving the tool permanently RUNNING. There is NO separate
                    # "tool_failed" event type — frontend maps status "failed" and
                    # "error" to the error terminal state.
                    _tool_terminal_emitted = False
                    try:
                        result = await self._execute_tool(
                            tool_name=action.tool, tool_input=action.input,
                            user_role=user_role, db=db, user_id=user_id, reg=reg, llm=llm,
                        )

                        # Objective verification
                        passed, reason = _verify_tool_result(action.tool, result)
                        status = "success" if passed else "failed"
                        duration_ms = result.get("duration_ms", 0)

                        # Detect timeout vs other failure
                        is_timeout = (
                            not passed
                            and result.get("failure_type") == "TRANSIENT"
                            and "timed out" in (result.get("error") or "").lower()
                        )

                        agent.record_tool_result(
                            action.tool, call_id, status,
                            reason[:200], duration_ms,
                            error=reason if not passed else None,
                        )

                        if is_timeout:
                            yield _sse("tool_timeout", {
                                "call_id": call_id,
                                "tool": action.tool,
                                "error": result.get("error", "Tool timed out"),
                                "duration_ms": duration_ms,
                            })
                        else:
                            yield _sse("tool_result", {
                                "call_id": call_id,
                                "tool": action.tool,
                                "status": status,
                                "result_summary": reason[:500],
                                "duration_ms": duration_ms,
                                "error": reason if not passed else None,
                            })
                        _tool_terminal_emitted = True
                    except Exception as exc:
                        # Safety net: if anything between tool_call and terminal
                        # event raises, emit tool_result(status="error") so the
                        # tool is never left permanently RUNNING.
                        if not _tool_terminal_emitted:
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            agent.record_tool_result(
                                action.tool, call_id, "error",
                                str(exc)[:200], duration_ms, error=str(exc)[:200],
                            )
                            yield _sse("tool_result", {
                                "call_id": call_id,
                                "tool": action.tool,
                                "status": "error",
                                "result_summary": str(exc)[:500],
                                "duration_ms": duration_ms,
                                "error": str(exc)[:200],
                            })
                            _tool_terminal_emitted = True
                        raise  # Re-raise to outer exception handler

                    # --- Update matching todo task ---
                    for t in agent.todo.tasks:
                        if t.status == "active" and t.tool_name == action.tool:
                            if passed:
                                agent.todo.complete_task(t.id)
                            else:
                                agent.todo.fail_task(t.id, reason[:200])
                            break
                    yield _sse("todo_updated", agent.todo.to_dict())

                    # Record observation
                    obs = Observation(
                        tool=action.tool, success=passed,
                        exit_code=result.get("exit_code"),
                        observation=reason,
                        evidence=[reason] if passed else [],
                        artifacts=self._extract_artifacts(action.tool, result),
                        duration_ms=duration_ms,
                        output_summary=str(result)[:500],
                    )
                    observations.append(obs)
                    if passed:
                        evidence.extend(obs.evidence)

                    # Trim output for LLM context
                    trimmed = self._trim_output(result)
                    tool_results_context.append(
                        f"Step {iteration+1}: {action.tool} → {status}\n"
                        f"Output: {_json.dumps(trimmed)[:_MAX_OUTPUT_IN_CONTEXT]}"
                    )

                    # Observe
                    from services.agent_state import Observation as _AgentObs
                    agent_obs = _AgentObs(
                        tool=action.tool,
                        status="success" if passed else "error",
                        facts=[reason[:100]],
                        evidence_ids=[reason[:50]] if passed else [],
                        duration_ms=duration_ms,
                    )
                    agent.observe(agent_obs)
                    yield _sse("observation", {
                        "tool": action.tool,
                        "success": passed,
                        "observation": reason[:300],
                        "evidence": obs.evidence,
                    })

                    # Handle failure
                    if not passed:
                        failure_type = _classify_failure(action.tool, result, reason)
                        failed_attempts.append({
                            "tool": action.tool,
                            "error": reason[:300],
                            "failure_type": failure_type,
                        })

                        # TASK 2: When a tool fails because a required field is missing
                        # and we cannot provide it (e.g. search_kb without kb_id), mark
                        # the tool as permanently blocked for this run so the reasoner
                        # stops selecting it. This prevents infinite retry loops.
                        err_lower = (result.get("error") or "").lower()
                        if failure_type == "INVALID_TOOL_ARGUMENTS" and (
                            "required" in err_lower or "missing" in err_lower
                        ):
                            # Remove from tool_names so reasoner no longer sees it
                            if action.tool in tool_names:
                                tool_names = [t for t in tool_names if t != action.tool]
                                logger.info(
                                    "Tool %s permanently blocked: required field missing (%s)",
                                    action.tool, err_lower[:100],
                                )
                            failed_attempts[-1]["failure_type"] = "TOOL_UNAVAILABLE"

                        if failure_type == "FATAL":
                            agent.fail(f"Fatal error: {reason[:200]}")
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("error", {"message": f"Fatal: {reason[:200]}"})
                            _result[0] = final_content
                            return

                        if failure_type == "TRANSIENT" and agent.can_retry(action.tool):
                            agent.record_retry(action.tool)
                            yield _sse("retry", {
                                "tool": action.tool,
                                "attempt": agent.retries.get(action.tool, 0),
                                "reason": reason[:200],
                            })

                case "REPLAN":
                    new_plan = await self._replan(
                        llm=llm, model=model, goal=goal,
                        acceptance_criteria=plan.acceptance_criteria if plan else [],
                        failure_reason=decision.reason,
                        failed_steps=[a["tool"] for a in failed_attempts[-3:]],
                        evidence=evidence,
                    )
                    if new_plan:
                        plan = new_plan
                        agent.create_plan([
                            {"description": s.description, "tool_name": s.tool}
                            for s in plan.steps
                        ])
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("plan_updated", {
                            "reason": decision.reason,
                            "steps": [s.model_dump() for s in plan.steps],
                        })
                        agent.todo = type(agent.todo)()
                        for s in plan.steps:
                            agent.todo.add_task(s.description, tool_name=s.tool)
                        yield _sse("todo_updated", agent.todo.to_dict())

                case "ASK_USER":
                    final_content = decision.reason
                    # Persist the question for the frontend to render
                    question_text = decision.reason
                    options = []
                    # Extract options from the decision if present
                    if decision.next_action and decision.next_action.input:
                        options = decision.next_action.input.get("options", [])

                    # Set run status to awaiting_user and persist question
                    run_record = await self._get_run_record(db, run_id)
                    if run_record:
                        run_record.status = "awaiting_user"
                        run_record.pending_question = question_text
                        run_record.pending_options_json = _json.dumps(options) if options else None
                        await db.flush()

                    yield _sse("ask_user", {
                        "question": question_text,
                        "options": options,
                        "run_id": run_id,
                    })
                    yield _sse("agent_state", agent.to_dict())
                    agent.fail("Waiting for user input")
                    _result[0] = final_content
                    return

                case "ANSWER_DIRECTLY":
                    final_content = decision.answer or decision.reason
                    # ANSWER_DIRECTLY can follow a tool observation. COMPLETED is
                    # not reachable directly from OBSERVING (FSM: OBSERVING →
                    # REASONING → … → COMPLETED), so route through REASONING
                    # first — otherwise agent.complete() raises Invalid transition
                    # and the whole run is marked failed after a successful tool use.
                    if agent.state == AgentState.OBSERVING:
                        agent.reason()
                    agent.complete()
                    yield _sse("agent_state", agent.to_dict())
                    break

                case "FAIL":
                    agent.fail(decision.reason)
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": decision.reason})
                    yield _sse("final_response", {
                        "content": decision.reason,
                        "token_count": 0,
                        "state": agent.state.value,
                        "elapsed_ms": agent.get_elapsed_ms(),
                    })
                    yield _sse("done", {
                        "content": decision.reason,
                        "token_count": 0,
                        "activity": agent.activity,
                        "tool_calls": agent.tool_call_count,
                        "state": agent.state.value,
                        "elapsed_ms": agent.get_elapsed_ms(),
                        "plan": [
                            {"id": s.id, "description": s.description, "status": s.status}
                            for s in agent.plan
                        ],
                        "observations": [],
                        "verification": None,
                    })
                    _result[0] = decision.reason
                    return

        else:
            # Max iterations exhausted
            if not final_content:
                final_content = "I was unable to complete the analysis within the iteration limit."
            agent.fail("Max iterations reached")
            yield _sse("agent_state", agent.to_dict())
            yield _sse("error", {"message": "Max iterations reached"})
            yield _sse("final_response", {
                "content": final_content,
                "token_count": 0,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
            })
            yield _sse("done", {
                "content": final_content,
                "token_count": 0,
                "activity": agent.activity,
                "tool_calls": agent.tool_call_count,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan": [
                    {"id": s.id, "description": s.description, "status": s.status}
                    for s in agent.plan
                ],
                "observations": [],
                "verification": None,
            })

        _result[0] = final_content

    async def run(
        self,
        *,
        goal: str,
        user_id: str,
        user_role: str,
        model: str,
        llm: Any,
        db: AsyncSession,
        tool_names: list[str] | None = None,
        tool_descriptions: str = "",
        conversation_id: str | None = None,
        agent_state: AgentStateMachine | None = None,
        agent_mode: str = "agent",
        run_id: str | None = None,
        user_kb_ids: list[str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute the full autonomous agent loop.

        Yields SSE event strings. The caller wraps this in StreamingResponse.

        Flow:
          UNDERSTAND → ROUTE → (CONVERSATION | KNOWLEDGE | TASK) → PLAN → REASON → TOOL → OBSERVE → VERIFY

        conversation_history: list of {"role": "user"|"assistant", "content": "..."}
          Recent conversation messages for context. The agent uses this to understand
          prior turns (e.g., user said "My name is Rahul" → assistant said "Nice to meet you"
          → current goal "What is my name?" → agent knows the answer).
        """
        agent = agent_state or AgentStateMachine()
        start_time = time.monotonic()

        # Store run_id and db for event persistence
        self._run_id = run_id
        self._db = db
        self._sequence = 0
        self._user_kb_ids = user_kb_ids

        # --- Conversation context for memory ---
        # Recent messages provide conversational context so the agent can
        # reference prior turns (names, preferences, previous answers, etc.)
        self._conversation_history = conversation_history or []

        # --- Build execution context ---
        from tools.registry import get_registry
        reg = get_registry()

        if tool_names is None:
            available_tools = reg.list_enabled(user_role=user_role)
            tool_names = [t.name for t in available_tools]
        if not tool_descriptions:
            tool_descriptions = reg.get_tool_list_for_prompt(
                allowed_names=tool_names, user_role=user_role
            )

        # --- Initialize ---
        agent.start(goal)
        yield _sse("agent_state", agent.to_dict())

        # --- Create isolated workspace for file operations ---
        workspace_path = self._make_workspace(run_id or "unknown")
        self._workspace_path = workspace_path

        # --- Action fingerprint tracking for loop detection ---
        _action_fingerprints: dict[str, int] = {}

        # --- Emit agent_started event (via _emit_event for single source of truth) ---
        # TASK 4: Use _emit_event() instead of manual persistence to avoid
        # duplicate agent_started events. _emit_event handles both SSE emission
        # and DB persistence atomically.
        yield await self._emit_event("agent_started", {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "goal": goal[:200],
            "model": model,
            "agent_mode": agent_mode,
        })

        # --- Build initial context ---
        messages: list[ChatMessage] = []
        observations: list[Observation] = []
        evidence: list[str] = []
        failed_attempts: list[dict] = []
        final_content = ""
        token_count = 0

        # Tool results context for the LLM (last N results)
        tool_results_context: list[str] = []

        try:
            # ============================================================
            # STAGE 1: UNDERSTAND / ROUTE (mandatory first stage)
            # ============================================================
            yield _sse("understanding_started", {"goal": goal[:200]})

            understanding = await self._understand(
                llm=llm,
                model=model,
                goal=goal,
                tool_descriptions=tool_descriptions,
            )

            yield _sse("understanding_completed", {
                "intent": understanding.intent.value,
                "goal": understanding.goal[:200],
                "needs_plan": understanding.needs_plan,
                "needs_tools": understanding.needs_tools,
                "needs_verification": understanding.needs_verification,
                "confidence": understanding.confidence,
                "reasoning": understanding.reasoning[:200],
            })

            logger.info(
                "Understanding: intent=%s needs_plan=%s needs_tools=%s confidence=%.2f",
                understanding.intent.value,
                understanding.needs_plan,
                understanding.needs_tools,
                understanding.confidence,
            )

            # ============================================================
            # STAGE 2: ROUTE based on intent
            # ============================================================
            plan = None

            match understanding.intent:
                # --------------------------------------------------------
                # CONVERSATION: greetings, small talk, farewells
                # --------------------------------------------------------
                case RequestIntent.CONVERSATION:
                    # Route through LLM — never fabricate in Python
                    final_content = await self._generate_conversation_response(
                        llm=llm, model=model, goal=goal,
                    )
                    agent.complete()
                    yield _sse("agent_state", agent.to_dict())
                    # Fall through to finalize

                # --------------------------------------------------------
                # KNOWLEDGE: questions, explanations, definitions
                # --------------------------------------------------------
                case RequestIntent.KNOWLEDGE:
                    # Direct knowledge response — no plan, no tools
                    final_content = await self._generate_knowledge_response(
                        llm=llm, model=model, goal=goal,
                    )
                    agent.complete()
                    yield _sse("agent_state", agent.to_dict())
                    # Fall through to finalize

                # --------------------------------------------------------
                # ANALYSIS: compare, summarize, analyze
                # --------------------------------------------------------
                case RequestIntent.ANALYSIS:
                    # May need tools but no multi-step plan
                    if understanding.needs_tools and tool_names:
                        # Single-step: use tools then respond
                        final_content = await self._handle_analysis_with_tools(
                            llm=llm, model=model, goal=goal,
                            tool_names=tool_names, tool_descriptions=tool_descriptions,
                            user_role=user_role, db=db, user_id=user_id, reg=reg,
                            agent=agent, observations=observations, evidence=evidence,
                            tool_results_context=tool_results_context,
                            failed_attempts=failed_attempts,
                            start_time=start_time,
                            _action_fingerprints=_action_fingerprints,
                        )
                    else:
                        # Pure analysis — LLM reasoning only
                        final_content = await self._generate_knowledge_response(
                            llm=llm, model=model, goal=goal,
                        )
                    agent.complete()
                    yield _sse("agent_state", agent.to_dict())
                    # Fall through to finalize

                # --------------------------------------------------------
                # TOOL_TASK: explicit single tool request
                # --------------------------------------------------------
                case RequestIntent.TOOL_TASK:
                    # Single tool execution → observe → verify
                    if tool_names:
                        final_content = await self._handle_tool_task(
                            llm=llm, model=model, goal=goal,
                            tool_names=tool_names, tool_descriptions=tool_descriptions,
                            user_role=user_role, db=db, user_id=user_id, reg=reg,
                            agent=agent, observations=observations, evidence=evidence,
                            tool_results_context=tool_results_context,
                            failed_attempts=failed_attempts,
                            start_time=start_time,
                            _action_fingerprints=_action_fingerprints,
                        )
                    else:
                        final_content = "I understand you want to use a tool, but no tools are currently available."
                    agent.complete()
                    yield _sse("agent_state", agent.to_dict())
                    # Fall through to finalize

                # --------------------------------------------------------
                # TASK: complex multi-step work
                # --------------------------------------------------------
                case RequestIntent.TASK:
                    # Full planner → reasoner → tools → verify loop
                    if tool_names:
                        plan = await self._create_plan(
                            llm=llm,
                            model=model,
                            goal=understanding.goal,
                            tool_names=tool_names,
                            tool_descriptions=tool_descriptions,
                        )
                        if plan:
                            agent.create_plan([
                                {"description": s.description, "tool_name": s.tool}
                                for s in plan.steps
                            ])
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("plan_created", {
                                "goal": plan.goal,
                                "acceptance_criteria": plan.acceptance_criteria,
                                "steps": [s.model_dump() for s in plan.steps],
                            })

                            # Populate todo manager from plan
                            for s in plan.steps:
                                agent.todo.add_task(s.description, tool_name=s.tool)
                            yield _sse("todo_updated", agent.todo.to_dict())

                    # Plan mode: only generate plan, don't execute
                    if agent_mode == "plan":
                        if plan:
                            final_content = f"Plan created with {len(plan.steps)} steps:\n"
                            for s in plan.steps:
                                final_content += f"- {s.description}\n"
                        else:
                            final_content = "No plan could be generated for this request."
                        agent.complete()
                        yield _sse("agent_state", agent.to_dict())
                    else:
                        # === MAIN AGENT LOOP (for TASK intent only) ===
                        _result = [""]
                        async for event in self._run_agent_loop(
                            llm=llm, model=model, goal=understanding.goal,
                            agent=agent, plan=plan, reg=reg,
                            tool_names=tool_names, tool_descriptions=tool_descriptions,
                            user_role=user_role, db=db, user_id=user_id,
                            observations=observations, evidence=evidence,
                            failed_attempts=failed_attempts,
                            tool_results_context=tool_results_context,
                            start_time=start_time,
                            _action_fingerprints=_action_fingerprints,
                            _result=_result,
                            run_id=run_id,
                            conversation_id=conversation_id,
                        ):
                            yield event
                        final_content = _result[0]

        except asyncio.CancelledError:
            if agent.state != AgentState.CANCELLED:
                agent.cancel()
            yield _sse("agent_state", agent.to_dict())
            yield _sse("cancelled", {"message": "Cancelled"})
            cancel_msg = "Run was cancelled"
            yield _sse("final_response", {
                "content": cancel_msg,
                "token_count": 0,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
            })
            yield _sse("done", {
                "content": cancel_msg,
                "token_count": 0,
                "activity": agent.activity,
                "tool_calls": agent.tool_call_count,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan": [],
                "observations": [],
                "verification": None,
            })
            self._cleanup_workspace(getattr(self, "_workspace_path", ""))
            return
        except Exception as exc:
            logger.exception("Agent runtime error: %s", exc)
            if agent.state not in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                agent.fail(str(exc)[:200])
            error_msg = f"Agent error: {str(exc)[:200]}"
            yield _sse("agent_state", agent.to_dict())
            yield _sse("error", {"message": error_msg})
            yield _sse("final_response", {
                "content": error_msg,
                "token_count": 0,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
            })
            yield _sse("done", {
                "content": error_msg,
                "token_count": 0,
                "activity": agent.activity,
                "tool_calls": agent.tool_call_count,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan": [],
                "observations": [],
                "verification": None,
            })
            self._cleanup_workspace(getattr(self, "_workspace_path", ""))
            return

        # === FINALIZE ===
        # If the agent is in a terminal failure state (failed, cancelled, timed_out),
        # the appropriate done/error events were already emitted by the specific code path
        # (exception handler, FAIL case, timeout handler, etc.).
        # Only emit final_response + done for successful completions.
        if agent.state.value in ("failed", "cancelled"):
            # Cleanup workspace
            self._cleanup_workspace(getattr(self, "_workspace_path", ""))
            return

        # CRITICAL: Persist assistant message to DB BEFORE yielding final_response.
        # This ensures the response survives SSE connection drops.
        if final_content and self._db and conversation_id:
            try:
                from models.conversation import Message as _Msg
                assistant_msg = _Msg(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=final_content,
                    metadata_json=_json.dumps({
                        "agent": True,
                        "state": agent.state.value,
                        "tool_calls": agent.tool_call_count,
                        "run_id": run_id,
                    }),
                )
                self._db.add(assistant_msg)
                await self._db.flush()
            except Exception:
                logger.warning("Failed to persist assistant message in runtime", exc_info=True)

        # Stream final answer as tokens
        for i in range(0, len(final_content), 4):
            chunk = final_content[i:i + 4]
            token_count += 1
            yield _sse("token", {"delta": chunk})

        # Emit final_response BEFORE done — frontend uses this to commit the response
        # to detail.messages before streaming state is cleared.
        # CRITICAL INVARIANT: DONE => final response already exists in DB or run marked failed
        yield _sse("final_response", {
            "content": final_content,
            "token_count": token_count,
            "state": agent.state.value,
            "elapsed_ms": agent.get_elapsed_ms(),
        })

        yield _sse("done", {
            "content": final_content,
            "token_count": token_count,
            "activity": agent.activity,
            "tool_calls": agent.tool_call_count,
            "state": agent.state.value,
            "elapsed_ms": agent.get_elapsed_ms(),
            "plan": [
                {"id": s.id, "description": s.description, "status": s.status}
                for s in agent.plan
            ],
            "observations": [
                {"tool": o.tool, "status": o.status, "facts": o.facts}
                for o in agent.observations
            ],
            "verification": {
                "task_completed": agent.verification.task_completed,
                "evidence_grounded": agent.verification.evidence_grounded,
            } if agent.verification else None,
        })

        # --- Cleanup workspace ---
        self._cleanup_workspace(getattr(self, "_workspace_path", ""))

    # ------------------------------------------------------------------
    # Internal: Planning
    # ------------------------------------------------------------------

    async def _create_plan(
        self, *, llm: Any, model: str, goal: str,
        tool_names: list[str], tool_descriptions: str,
    ) -> Plan | None:
        """Ask the LLM to create a structured plan."""
        system = PLANNER_SYSTEM.format(max_steps=20)
        user = PLANNER_USER.format(goal=goal, tools=tool_descriptions)

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=user),
                    ],
                    stream=False,
                    temperature=0.0,
                    max_tokens=2048,
                ),
                timeout=_TIMEOUT_PLANNER,
            )
            text = (resp.content or "") if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Planning failed: %s", exc)
            return None

        data = parse_llm_json(text)
        if data.get("type") == "error":
            logger.warning("Planner raw output (unparseable): %s", text[:500])
            # Fallback plan for small models that can't produce JSON
            return Plan(
                goal=goal,
                acceptance_criteria=["Task completed successfully"],
                steps=[PlanStep(id=1, description="Complete the task", tool=None)],
            )

        try:
            return Plan.model_validate(data)
        except Exception:
            logger.warning("Failed to validate plan from LLM output: %s", data)
            return Plan(
                goal=goal,
                acceptance_criteria=["Task completed successfully"],
                steps=[PlanStep(id=1, description="Complete the task", tool=None)],
            )

    # ------------------------------------------------------------------
    # Internal: Reasoning / Decision
    # ------------------------------------------------------------------

    async def _decide(
        self, *, llm: Any, model: str, goal: str,
        agent: AgentStateMachine,
        observations: list[Observation],
        evidence: list[str],
        failed_attempts: list[dict],
        tool_results_context: list[dict[str, str]],
        tool_descriptions: str,
    ) -> AgentDecision:
        """Ask the LLM to decide the next action.

        Includes conversation history for context-aware decisions.
        """
        criteria_text = "\n".join(
            f"- {s.description} (tool: {s.tool_name or 'none'})"
            for s in agent.plan
        ) if agent.plan else "No plan created yet."

        current_step = "N/A"
        if agent.plan:
            pending = [s for s in agent.plan if s.status in ("pending", "active")]
            if pending:
                current_step = f"Step {pending[0].id}: {pending[0].description}"

        history = "\n".join(
            f"- {s}"
            for s in (tool_results_context[-10:] if tool_results_context else [])
        ) or "No steps taken yet."

        obs_text = "\n".join(
            f"- {o.tool}: {'OK' if o.success else 'FAILED'} — {o.observation[:100]}"
            for o in (observations[-5:] if observations else [])
        ) or "No observations yet."

        evidence_text = "\n".join(
            f"- {e[:100]}" for e in (evidence[-5:] if evidence else [])
        ) or "No evidence yet."

        failures_text = "\n".join(
            f"- {f.get('tool', 'unknown')}: {f.get('error', '')[:100]} ({f.get('failure_type', 'unknown')})"
            for f in (failed_attempts[-3:] if failed_attempts else [])
        ) or "None."

        # Include conversation history for context-aware reasoning
        conv_ctx = self._build_conversation_context(max_messages=10)
        conv_section = ""
        if conv_ctx:
            conv_section = f"\nRecent conversation:\n{conv_ctx}\n"

        system = REASONER_SYSTEM
        user = (
            f"Goal: {goal}\n"
            f"{conv_section}\n"
            f"Acceptance criteria:\n{criteria_text}\n\n"
            f"Current plan step: {current_step}\n\n"
            f"Previous steps summary:\n{history}\n\n"
            f"Recent observations:\n{obs_text}\n\n"
            f"Evidence collected:\n{evidence_text}\n\n"
            f"Failed attempts:\n{failures_text}\n\n"
            f"Decide the next action."
        )

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=user),
                    ],
                    stream=False,
                    temperature=0.0,
                    max_tokens=1024,
                ),
                timeout=_TIMEOUT_REASONER,
            )
            text = (resp.content or "") if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Reasoning failed: %s", exc)
            return AgentDecision(decision="FAIL", reason=f"LLM error: {exc}")

        decision = self._try_reasoner_decision(text)
        if decision is not None:
            return decision

        # parse_llm_json failed or schema validation failed — log + corrective retry
        logger.warning("Reasoner output (raw): %s", text[:500])
        retry_text = await self._retry_reasoner_with_correction(
            llm=llm, model=model, raw_output=text, goal=goal,
        )
        if retry_text:
            decision = self._try_reasoner_decision(retry_text)
            if decision is not None:
                return decision
            logger.warning("Reasoner retry still invalid: %s", retry_text[:300])

        # Fallback: never destroy a run that gathered real evidence. When the
        # reasoner cannot produce a decision but the agent has already executed
        # multiple tools, route to VERIFY — the verifier independently judges
        # the acceptance criteria, so a run with accumulated evidence can close
        # out honestly instead of hard-failing on a reasoner hiccup. FAIL only
        # when there is essentially no evidence to verify.
        pending_tools = (
            [s for s in agent.plan if s.status == "pending" and s.tool_name]
            if agent.plan else []
        )
        if (not pending_tools) or agent.tool_call_count == 0 or agent.tool_call_count >= 2:
            return AgentDecision(
                decision="VERIFY",
                reason="Could not parse reasoner output, attempting verification",
            )
        return AgentDecision(decision="FAIL", reason="Could not parse reasoner output")

    def _try_reasoner_decision(self, text: str) -> AgentDecision | None:
        """Try to parse reasoner text into an AgentDecision.

        Handles:
        1. Valid JSON with schema drift (reasoning→reason, list→first next_action)
        2. Native function-call tokens (no JSON at all):
           <|tool_call_start|>web_search(query='...')<|tool_call_end|>
           <tool_call>web_search<arg_key>query</arg_key>...</tool_call>
        Returns AgentDecision on success, None on failure.
        """
        # 1) Try JSON parse → coerce → validate
        data = parse_llm_json(text)
        if data.get("type") != "error":
            data = coerce_decision_data(data)
            try:
                return AgentDecision.model_validate(data)
            except Exception:
                pass  # fall through to native detection

        # 2) Detect native function-call token format (no JSON at all)
        tc = extract_native_tool_call(text)
        if tc and tc.get("tool"):
            return AgentDecision(
                decision="CONTINUE",
                reason="Model emitted a native tool call",
                next_action=ToolAction(tool=tc["tool"], input=tc.get("input") or {}),
                answer=None,
            )

        return None

    async def _retry_reasoner_with_correction(
        self, *, llm: Any, model: str, raw_output: str, goal: str,
    ) -> str | None:
        """Retry the reasoner with a corrective prompt when output was malformed."""
        corrective_system = (
            "You are the REASONER for an autonomous AI agent. "
            "Your previous response was NOT valid JSON. "
            "You MUST respond with ONLY a valid JSON object matching this exact schema:\n"
            '{"decision": "CONTINUE|RETRY|REPLAN|VERIFY|COMPLETE|ASK_USER|FAIL|ANSWER_DIRECTLY", '
            '"reason": "explanation", '
            '"next_action": {"tool": "name", "input": {...}, "reasoning": "why"} | null, '
            '"answer": "final answer when ANSWER_DIRECTLY, otherwise null"}\n'
            "For ANSWER_DIRECTLY set next_action to null and provide the final answer "
            "in the answer field. Do NOT include any text before or after the JSON. "
            "No markdown, no explanation."
        )
        corrective_user = (
            f"Goal: {goal}\n\n"
            f"Your previous malformed response was:\n{raw_output[:500]}\n\n"
            "Fix it. Return ONLY valid JSON."
        )
        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=corrective_system),
                        ChatMessage(role="user", content=corrective_user),
                    ],
                    stream=False,
                    temperature=0.0,
                    max_tokens=512,
                ),
                timeout=_TIMEOUT_REASONER,
            )
            return (resp.content or "") if hasattr(resp, "content") else str(resp)
        except Exception as exc:
            logger.warning("Reasoner corrective retry failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal: Verification
    # ------------------------------------------------------------------

    async def _verify(
        self, *, llm: Any, model: str, goal: str,
        agent: AgentStateMachine,
        evidence: list[str],
        tool_results_context: list[str],
        observations: list[Observation] | None = None,
    ) -> VerificationResult:
        """Verify that the goal has been actually achieved."""
        criteria_text = "\n".join(
            f"- {s.description}" for s in agent.plan
        ) if agent.plan else "No specific criteria."

        evidence_text = "\n".join(
            f"- {e[:200]}" for e in (evidence[-10:] if evidence else [])
        ) or "No evidence collected."

        tool_results_text = "\n".join(
            tool_results_context[-5:]
        ) or "No tool results."

        system = VERIFIER_SYSTEM
        user = VERIFIER_USER.format(
            goal=goal,
            criteria=criteria_text,
            evidence=evidence_text,
            tool_results=tool_results_text,
        )

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=user),
                    ],
                    stream=False,
                    temperature=0.0,
                    max_tokens=2048,
                ),
                timeout=_TIMEOUT_VERIFIER,
            )
            text = (resp.content or "") if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Verification failed: %s", exc)
            return VerificationResult(
                verified=False,
                confidence=0.0,
                missing=[f"Verification LLM error: {exc}"],
            )

        data = parse_llm_json(text)
        if data.get("type") == "error":
            logger.warning("Verifier raw output (unparseable): %s", text[:500])
            return VerificationResult(
                verified=False,
                confidence=0.0,
                missing=["Could not parse verification output"],
            )

        try:
            result = VerificationResult.model_validate(data)
        except Exception:
            logger.warning("Verifier invalid schema: %s", data)
            return VerificationResult(
                verified=False,
                confidence=0.0,
                missing=["Invalid verification output format"],
            )

        # Record verification in state machine
        agent.verify(type("VR", (), {
            "task_completed": result.verified,
            "evidence_grounded": result.confidence > 0.5,
            "tools_executed": [],
            "failed_tools": [],
            "unsupported_claims": result.unsupported_claims,
            "missing_evidence": result.missing,
            "details": f"Confidence: {result.confidence}",
        })())

        return result

    # ------------------------------------------------------------------
    # Internal: Replanning
    # ------------------------------------------------------------------

    async def _replan(
        self, *, llm: Any, model: str, goal: str,
        acceptance_criteria: list[str],
        failure_reason: str,
        failed_steps: list[str],
        evidence: list[str],
    ) -> Plan | None:
        """Create a new plan after failure."""
        system = REPLANNER_SYSTEM
        user = REPLANNER_USER.format(
            goal=goal,
            criteria="\n".join(f"- {c}" for c in acceptance_criteria) or "None defined.",
            failure_reason=failure_reason,
            failed_steps="\n".join(f"- {s}" for s in failed_steps) or "None.",
            evidence="\n".join(f"- {e[:100]}" for e in evidence[-5:]) or "None.",
        )

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=user),
                    ],
                    stream=False,
                    temperature=0.0,
                    max_tokens=2048,
                ),
                timeout=_TIMEOUT_REPLANNER,
            )
            text = (resp.content or "") if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Replanning failed: %s", exc)
            return None

        data = parse_llm_json(text)
        if data.get("type") == "error":
            return None

        try:
            return Plan.model_validate(data)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal: Tool Execution (via security chain)
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, *, tool_name: str, tool_input: dict,
        user_role: str, db: AsyncSession, user_id: str,
        reg: Any, llm: Any = None, skip_approval: bool = True,
    ) -> dict:
        """Execute a tool through the security chain.

        LLM → ToolRegistry → Permission → Validation → [Approval] → Execute → Result

        Per-tool timeout: 30s (independent of global agent timeout).
        Approval gate is skipped by default in autonomous agent mode
        (skip_approval=True) because there is no human to approve mid-run.
        """
        from services.audit_service import AuditService

        t0 = time.monotonic()
        _TOOL_TIMEOUT_SECONDS = 30.0

        # 0. Canonicalize the tool name before anything else so LLM aliases
        #    (websearch → web_search, webfetch → web_fetch, …) resolve to the
        #    registry name used for lookup, permission, validation, execution,
        #    lifecycle events, and the tool-call UI.
        canonical = canonicalize_tool_name(tool_name)
        if canonical != tool_name:
            logger.info("Canonicalized tool '%s' -> '%s'", tool_name, canonical)
            tool_name = canonical

        # 1. Lookup tool
        tool = reg.get(tool_name)
        if tool is None:
            return {
                "error": f"Tool '{tool_name}' not found or not enabled",
                "failure_type": "NOT_FOUND",
                "tool": tool_name,
                "provided_arguments": tool_input,
            }

        # 2. Permission check
        try:
            reg.check_permission(tool, user_role)
        except PermissionError as exc:
            return {
                "error": str(exc),
                "failure_type": "FATAL",
                "tool": tool_name,
                "provided_arguments": tool_input,
            }

        # 3. Input validation
        # TASK 1: Auto-inject kb_id for search_kb when user has KBs.
        # The LLM should never need to guess kb_id — we inject it from context.
        if tool_name == "search_kb" and self._user_kb_ids:
            if not tool_input.get("kb_id"):
                tool_input = {**tool_input, "kb_id": self._user_kb_ids[0]}
                logger.info("Auto-injected kb_id=%s for search_kb", self._user_kb_ids[0])
        try:
            validated_input = reg.validate_input(tool, tool_input)
        except Exception as exc:
            return {
                "error": f"Input validation failed: {exc}",
                "failure_type": "INVALID_TOOL_ARGUMENTS",
                "tool": tool_name,
                "provided_arguments": tool_input,
            }

        # 4. Approval gate (skipped for low/medium risk in autonomous agent mode)
        # High and critical risk tools ALWAYS require approval, even in autonomous mode.
        # This prevents dangerous tools (e.g., terminal commands) from executing
        # without human oversight.
        from tools.registry import RISK_HIGH, RISK_CRITICAL
        needs_approval = reg.requires_approval(tool)
        if needs_approval and not skip_approval:
            from services.approval_service import ApprovalService
            approval_svc = ApprovalService(db)
            req = await approval_svc.create_request(
                agent_run_id=None,
                requester_id=user_id,
                tool_name=tool_name,
                tool_input=validated_input.model_dump(),
                risk_level=tool.risk_level,
            )
            try:
                approved, note = await asyncio.wait_for(
                    approval_svc.wait_for_decision(req.id),
                    timeout=_TOOL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {
                    "error": f"Tool '{tool_name}' approval timed out ({_TOOL_TIMEOUT_SECONDS}s)",
                    "failure_type": "TRANSIENT",
                    "tool": tool_name,
                    "provided_arguments": tool_input,
                }
            if not approved:
                return {"error": f"Approval denied: {note}"}
        elif needs_approval and skip_approval and tool.risk_level in (RISK_HIGH, RISK_CRITICAL):
            return {
                "error": f"Tool '{tool_name}' requires human approval (risk={tool.risk_level})",
                "failure_type": "FATAL",
                "tool": tool_name,
                "provided_arguments": tool_input,
            }

        # 5. Build context with services tools need
        from types import SimpleNamespace
        context = {
            "user": SimpleNamespace(id=user_id, role=user_role),
            "workspace_path": getattr(self, "_workspace_path", ""),
        }

        # Lazily initialize RAG/KB services for tools that need them
        if tool_name in ("search_kb",):
            try:
                from services.knowledge_base_service import KnowledgeBaseService
                from services.qdrant_service import QdrantService
                from services.embedding_service import EmbeddingService
                from services.rag_service import RagService

                qdrant_svc = QdrantService()
                kb_svc = KnowledgeBaseService(db, qdrant_svc)
                context["kb_service"] = kb_svc

                if llm is not None:
                    embedding_svc = EmbeddingService(llm)
                    rag_svc = RagService(
                        llm=llm,
                        embedding_svc=embedding_svc,
                        qdrant_svc=qdrant_svc,
                    )
                    context["rag_service"] = rag_svc
            except Exception as exc:
                logger.debug("Failed to init RAG services for tool %s: %s", tool_name, exc)

        # 6. Execute with per-tool timeout
        try:
            output = await asyncio.wait_for(
                reg.execute(tool, validated_input, context),
                timeout=_TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - t0) * 1000)
            return {
                "error": f"Tool '{tool_name}' execution timed out ({_TOOL_TIMEOUT_SECONDS}s)",
                "failure_type": "TRANSIENT",
                "tool": tool_name,
                "provided_arguments": tool_input,
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            output = {"error": str(exc)[:1000]}

        duration_ms = int((time.monotonic() - t0) * 1000)
        output["duration_ms"] = duration_ms

        return output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_workspace(self, run_id: str) -> str:
        """Create an isolated workspace directory for file operations."""
        import uuid as _uuid
        from config import get_settings
        settings = get_settings()
        workspace = os.path.join(
            settings.sandbox_workspace,
            f"run_{run_id}_{_uuid.uuid4().hex[:8]}"
        )
        os.makedirs(workspace, exist_ok=True)
        logger.info("Created workspace: %s", workspace)
        return workspace

    @staticmethod
    def _cleanup_workspace(workspace: str) -> None:
        """Clean up workspace directory after run completes."""
        import shutil as _shutil
        try:
            if workspace and os.path.isdir(workspace):
                _shutil.rmtree(workspace, ignore_errors=True)
                logger.info("Cleaned workspace: %s", workspace)
        except Exception as exc:
            logger.warning("Could not clean workspace %s: %s", workspace, exc)

    @staticmethod
    def _trim_output(output: dict) -> dict:
        trimmed = {}
        for k, v in output.items():
            if isinstance(v, str) and len(v) > _MAX_OUTPUT_IN_CONTEXT:
                trimmed[k] = v[:_MAX_OUTPUT_IN_CONTEXT] + "...[truncated]"
            else:
                trimmed[k] = v
        return trimmed

    @staticmethod
    def _extract_artifacts(tool_name: str, result: dict) -> list[str]:
        """Extract artifact paths from tool results."""
        artifacts = []
        if tool_name == "file_write" and result.get("path"):
            artifacts.append(result["path"])
        if tool_name == "file_read" and result.get("path"):
            artifacts.append(result["path"])
        return artifacts

    async def _get_run_record(self, db: AsyncSession, run_id: str | None):
        """Get the AgentRun record from DB for status updates."""
        if not run_id:
            return None
        try:
            from models.agent import AgentRun
            result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            return result.scalar_one_or_none()
        except Exception:
            return None
