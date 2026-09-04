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
    UnderstandingResult,
    VerificationCriteriaResult,
    VerificationResult,
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


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(payload)}\n\n"


def _fingerprint(tool_name: str, tool_input: dict) -> str:
    """Compute a normalized action fingerprint for loop detection."""
    normalized = _json.dumps(tool_input, sort_keys=True, default=str)
    return f"{tool_name}::{normalized}"


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

    async def _understand(
        self, *, llm: Any, model: str, goal: str, tool_descriptions: str,
    ) -> UnderstandingResult:
        """Classify user intent and determine execution path.

        Uses deterministic rules for obvious cases, LLM for ambiguous ones.
        """
        stripped = goal.strip()

        # --- Deterministic fast path for obvious greetings ---
        if self._is_simple_request(stripped):
            return UnderstandingResult(
                intent=RequestIntent.CONVERSATION,
                goal=f"Respond naturally to: {stripped}",
                needs_plan=False,
                needs_tools=False,
                needs_verification=False,
                confidence=1.0,
                reasoning="Simple greeting/small talk detected by pattern match",
            )

        # --- LLM-based understanding for everything else ---
        system = UNDERSTAND_SYSTEM
        user = UNDERSTAND_USER.format(goal=stripped, tools=tool_descriptions or "No tools available")

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
                    max_tokens=512,
                ),
                timeout=30.0,  # Understanding must be fast
            )
            text = resp.content if hasattr(resp, "content") else str(resp)
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
            # Override: KNOWLEDGE never needs plan
            elif result.intent == RequestIntent.KNOWLEDGE:
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

    def _generate_conversation_response(self, goal: str) -> str:
        """Generate a direct response for conversational requests."""
        stripped = goal.strip().lower()
        # Deterministic responses for common greetings
        if any(w in stripped for w in ["hi", "hello", "hey", "howdy", "greetings"]):
            return "Hello! How can I help you today?"
        if any(w in stripped for w in ["thanks", "thank you", "thx", "ty"]):
            return "You're welcome! Let me know if you need anything else."
        if any(w in stripped for w in ["bye", "goodbye", "see you", "later"]):
            return "Goodbye! Feel free to come back anytime."
        if any(w in stripped for w in ["how are you", "how are things"]):
            return "I'm doing well, thanks for asking! How can I assist you?"
        if any(w in stripped for w in ["good morning", "good afternoon", "good evening"]):
            return f"{goal.strip().split()[0].title()}! How can I help you?"
        # Generic conversational response
        return "I understand. How can I help you?"

    async def _generate_knowledge_response(
        self, *, llm: Any, model: str, goal: str,
    ) -> str:
        """Generate a direct knowledge response without tools."""
        system = "You are a helpful AI assistant. Answer the user's question directly and concisely. Do NOT use any tools. Keep your response under 200 words."
        user = f"Question: {goal}"

        try:
            resp = await asyncio.wait_for(
                llm.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=system),
                        ChatMessage(role="user", content=user),
                    ],
                    stream=False,
                    temperature=0.3,
                    max_tokens=1024,
                ),
                timeout=60.0,
            )
            return resp.content if hasattr(resp, "content") else str(resp)
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
            if action.tool in tool_names:
                result = await self._execute_tool(
                    tool_name=action.tool, tool_input=action.input,
                    user_role=user_role, db=db, user_id=user_id, reg=reg,
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
            if action.tool in tool_names:
                result = await self._execute_tool(
                    tool_name=action.tool, tool_input=action.input,
                    user_role=user_role, db=db, user_id=user_id, reg=reg,
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
                yield _sse("error", {
                    "message": f"Wall-clock timeout: {AGENT_MAX_RUNTIME_SECONDS}s exceeded"
                })
                yield _sse("done", {
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

            # Check if already in terminal state
            if agent.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                break

            # Check safety limits
            limit_error = agent.check_limits()
            if limit_error:
                agent.fail(limit_error)
                yield _sse("agent_state", agent.to_dict())
                yield _sse("error", {"message": limit_error})
                yield _sse("done", {
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
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("error", {"message": "No action provided"})
                        _result[0] = final_content
                        return

                    action = decision.next_action

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
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("error", {"message": "Loop detected, cannot recover"})
                            yield _sse("done", {
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

                    result = await self._execute_tool(
                        tool_name=action.tool, tool_input=action.input,
                        user_role=user_role, db=db, user_id=user_id, reg=reg,
                    )

                    # Objective verification
                    passed, reason = _verify_tool_result(action.tool, result)
                    status = "success" if passed else "failed"
                    duration_ms = result.get("duration_ms", 0)

                    agent.record_tool_result(
                        action.tool, call_id, status,
                        reason[:200], duration_ms,
                        error=reason if not passed else None,
                    )
                    yield _sse("tool_result", {
                        "call_id": call_id,
                        "tool": action.tool,
                        "status": status,
                        "result_summary": reason[:500],
                        "duration_ms": duration_ms,
                        "error": reason if not passed else None,
                    })

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
                    agent.fail("Waiting for user input")
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("token", {"delta": decision.reason})
                    break

                case "ANSWER_DIRECTLY":
                    final_content = decision.answer or decision.reason
                    agent.complete()
                    yield _sse("agent_state", agent.to_dict())
                    break

                case "FAIL":
                    agent.fail(decision.reason)
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": decision.reason})
                    yield _sse("done", {
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

        else:
            # Max iterations exhausted
            if not final_content:
                final_content = "I was unable to complete the analysis within the iteration limit."
            agent.fail("Max iterations reached")
            yield _sse("agent_state", agent.to_dict())
            yield _sse("error", {"message": "Max iterations reached"})

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
    ) -> AsyncGenerator[str, None]:
        """Execute the full autonomous agent loop.

        Yields SSE event strings. The caller wraps this in StreamingResponse.

        Flow:
          UNDERSTAND → ROUTE → (CONVERSATION | KNOWLEDGE | TASK) → PLAN → REASON → TOOL → OBSERVE → VERIFY
        """
        agent = agent_state or AgentStateMachine()
        start_time = time.monotonic()

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

        # --- Action fingerprint tracking for loop detection ---
        _action_fingerprints: dict[str, int] = {}

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
                    # Direct response — no tools, no plan, no verification
                    final_content = self._generate_conversation_response(goal)
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
                        ):
                            yield event
                        final_content = _result[0]

        except asyncio.CancelledError:
            if agent.state != AgentState.CANCELLED:
                agent.cancel()
            yield _sse("agent_state", agent.to_dict())
            yield _sse("cancelled", {"message": "Cancelled"})
            yield _sse("done", {
                "token_count": 0,
                "activity": agent.activity,
                "tool_calls": agent.tool_call_count,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan": [],
                "observations": [],
                "verification": None,
            })
            return
        except Exception as exc:
            logger.exception("Agent runtime error: %s", exc)
            if agent.state not in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                agent.fail(str(exc)[:200])
            yield _sse("agent_state", agent.to_dict())
            yield _sse("error", {"message": f"Agent error: {str(exc)[:200]}"})
            yield _sse("done", {
                "token_count": 0,
                "activity": agent.activity,
                "tool_calls": agent.tool_call_count,
                "state": agent.state.value,
                "elapsed_ms": agent.get_elapsed_ms(),
                "plan": [],
                "observations": [],
                "verification": None,
            })
            return

        # === FINALIZE ===
        # Stream final answer as tokens
        for i in range(0, len(final_content), 4):
            chunk = final_content[i:i + 4]
            token_count += 1
            yield _sse("token", {"delta": chunk})

        yield _sse("done", {
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
            text = resp.content if hasattr(resp, "content") else str(resp)
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
        tool_results_context: list[str],
        tool_descriptions: str,
    ) -> AgentDecision:
        """Ask the LLM to decide the next action."""
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

        system = REASONER_SYSTEM
        user = REASONER_USER.format(
            goal=goal,
            criteria=criteria_text,
            current_step=current_step,
            history=history,
            observations=obs_text,
            evidence=evidence_text,
            failures=failures_text,
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
            text = resp.content if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Reasoning failed: %s", exc)
            return AgentDecision(decision="FAIL", reason=f"LLM error: {exc}")

        data = parse_llm_json(text)
        if data.get("type") == "error":
            logger.warning("Reasoner raw output (unparseable): %s", text[:500])
            # Fallback: if no tools executed yet, try verification
            if agent.tool_call_count == 0:
                return AgentDecision(
                    decision="VERIFY",
                    reason="Could not parse reasoner output, attempting verification",
                )
            return AgentDecision(decision="FAIL", reason="Could not parse reasoner output")

        try:
            decision = AgentDecision.model_validate(data)
        except Exception:
            logger.warning("Reasoner invalid schema: %s | raw: %s", data, text[:300])
            # Fallback: if plan is done or no tools needed, verify
            pending_tools = [s for s in agent.plan if s.status == "pending" and s.tool_name] if agent.plan else []
            # If no tools executed yet (first iteration), or no pending tools, try verification
            if not pending_tools or agent.tool_call_count == 0:
                return AgentDecision(
                    decision="VERIFY",
                    reason="Reasoner output invalid, attempting verification",
                )
            return AgentDecision(decision="FAIL", reason="Invalid reasoner output format")

        return decision

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
            text = resp.content if hasattr(resp, "content") else str(resp)
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
            # If no tools were used and no observations, assume simple task is done
            obs_list = observations or []
            if not obs_list and not tool_results_context:
                return VerificationResult(
                    verified=True,
                    confidence=0.7,
                    criteria=[],
                    missing=[],
                )
            return VerificationResult(
                verified=False,
                confidence=0.0,
                missing=["Could not parse verification output"],
            )

        try:
            result = VerificationResult.model_validate(data)
        except Exception:
            logger.warning("Verifier invalid schema: %s", data)
            obs_list = observations or []
            if not obs_list and not tool_results_context:
                return VerificationResult(
                    verified=True,
                    confidence=0.7,
                    criteria=[],
                    missing=[],
                )
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
            text = resp.content if hasattr(resp, "content") else str(resp)
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
        reg: Any,
    ) -> dict:
        """Execute a tool through the security chain.

        LLM → ToolRegistry → Permission → Validation → Risk → Approval → Sandbox → Audit → Result
        """
        from services.approval_service import ApprovalService
        from services.audit_service import AuditService
        from models.agent import ToolCall
        from models.base import generate_uuid

        t0 = time.monotonic()

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
        try:
            validated_input = reg.validate_input(tool, tool_input)
        except Exception as exc:
            return {
                "error": f"Input validation failed: {exc}",
                "failure_type": "INVALID_TOOL_ARGUMENTS",
                "tool": tool_name,
                "provided_arguments": tool_input,
            }

        # 4. Approval gate
        if reg.requires_approval(tool):
            approval_svc = ApprovalService(db)
            req = await approval_svc.create_request(
                agent_run_id=None,
                requester_id=user_id,
                tool_name=tool_name,
                tool_input=validated_input.model_dump(),
                risk_level=tool.risk_level,
            )
            approved, note = await approval_svc.wait_for_decision(req.id)
            if not approved:
                return {"error": f"Approval denied: {note}"}

        # 5. Build context
        from types import SimpleNamespace
        context = {
            "user": SimpleNamespace(id=user_id, role=user_role),
        }

        # 6. Execute
        try:
            output = await reg.execute(tool, validated_input, context)
        except Exception as exc:
            output = {"error": str(exc)[:1000]}

        duration_ms = int((time.monotonic() - t0) * 1000)
        output["duration_ms"] = duration_ms

        return output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
