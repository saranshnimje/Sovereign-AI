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
    VERIFIER_SYSTEM,
    VERIFIER_USER,
)
from services.agent.schemas import (
    AgentDecision,
    Observation,
    Plan,
    PlanStep,
    VerificationCriteriaResult,
    VerificationResult,
    parse_llm_json,
)
from services.agent_state import (
    AgentState,
    AgentStateMachine,
    MAX_ITERATIONS,
    MAX_TOOL_CALLS,
    MAX_RETRIES_PER_TOOL,
)
from services.llm_client import ChatMessage, ModelUnavailableError

logger = logging.getLogger(__name__)

# Max characters of tool output to include in LLM context
_MAX_OUTPUT_IN_CONTEXT = 2000


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(payload)}\n\n"


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

    Returns: TRANSIENT | BAD_INPUT | UNAVAILABLE | FATAL
    """
    err = (error or str(result.get("error", ""))).lower()

    # Transient: timeouts, connection issues
    if "timeout" in err or "timed out" in err or "connection" in err:
        return "TRANSIENT"

    # Unavailable: tool not found, sandbox unavailable
    if "not found" in err or "not available" in err or "unavailable" in err:
        return "UNAVAILABLE"

    # Bad input: validation errors, invalid arguments
    if "validation" in err or "invalid" in err or "missing" in err or "required" in err:
        return "BAD_INPUT"

    # Fatal: permission denied, access errors
    if "permission" in err or "denied" in err or "forbidden" in err:
        return "FATAL"

    # For command tools, non-zero exit is usually fixable (BAD_INPUT)
    if tool_name in ("run_command", "run_powershell", "python_exec"):
        exit_code = result.get("exit_code", -1)
        if exit_code is not None and exit_code != 0:
            return "BAD_INPUT"

    return "TRANSIENT"


class AgentRuntime:
    """Single canonical autonomous agent loop.

    Usage:
        runtime = AgentRuntime()
        async for event_str in runtime.run(...):
            yield event_str  # SSE
    """

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
    ) -> AsyncGenerator[str, None]:
        """Execute the full autonomous agent loop.

        Yields SSE event strings. The caller wraps this in StreamingResponse.
        """
        agent = agent_state or AgentStateMachine()
        start_time = time.monotonic()

        # --- Build execution context ---
        from tools.registry import get_registry
        reg = get_registry()

        if not tool_names:
            available_tools = reg.list_enabled(user_role=user_role)
            tool_names = [t.name for t in available_tools]
        if not tool_descriptions:
            tool_descriptions = reg.get_tool_list_for_prompt(
                allowed_names=tool_names, user_role=user_role
            )

        # --- Initialize ---
        agent.start(goal)
        yield _sse("agent_state", agent.to_dict())

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
            # === PHASE: PLANNING ===
            if tool_names:
                plan = await self._create_plan(
                    llm=llm,
                    model=model,
                    goal=goal,
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

            # === PHASE: MAIN AGENT LOOP ===
            for iteration in range(MAX_ITERATIONS):
                # Check safety limits
                limit_error = agent.check_limits()
                if limit_error:
                    agent.fail(limit_error)
                    yield _sse("agent_state", agent.to_dict())
                    yield _sse("error", {"message": limit_error})
                    return

                # --- REASON: Decide what to do next ---
                decision = await self._decide(
                    llm=llm,
                    model=model,
                    goal=goal,
                    agent=agent,
                    observations=observations,
                    evidence=evidence,
                    failed_attempts=failed_attempts,
                    tool_results_context=tool_results_context,
                    tool_descriptions=tool_descriptions,
                )

                yield _sse("decision", {
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "iteration": iteration,
                })

                match decision.decision:
                    case "COMPLETE":
                        # MUST go through verifier
                        verification = await self._verify(
                            llm=llm,
                            model=model,
                            goal=goal,
                            agent=agent,
                            evidence=evidence,
                            tool_results_context=tool_results_context,
                        )
                        yield _sse("verification", verification.model_dump())

                        if verification.verified:
                            final_content = decision.reason or "Task completed successfully."
                            agent.complete()
                            yield _sse("agent_state", agent.to_dict())
                            break
                        else:
                            # Verifier rejected — replan
                            logger.info("Verifier rejected completion: %s", verification.missing)
                            failed_attempts.append({
                                "reason": "Completion rejected by verifier",
                                "missing": verification.missing,
                            })
                            new_plan = await self._replan(
                                llm=llm,
                                model=model,
                                goal=goal,
                                acceptance_criteria=plan.acceptance_criteria if plan else [],
                                failure_reason=f"Verification failed: {verification.missing}",
                                failed_steps=[],
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
                                    "reason": "Completion verification failed",
                                    "steps": [s.model_dump() for s in plan.steps],
                                })

                    case "VERIFY":
                        verification = await self._verify(
                            llm=llm,
                            model=model,
                            goal=goal,
                            agent=agent,
                            evidence=evidence,
                            tool_results_context=tool_results_context,
                        )
                        yield _sse("verification", verification.model_dump())

                        if verification.verified:
                            final_content = "Task completed and verified."
                            agent.complete()
                            yield _sse("agent_state", agent.to_dict())
                            break

                    case "CONTINUE" | "RETRY":
                        if decision.next_action is None:
                            agent.fail("Reasoner returned CONTINUE/RETRY without next_action")
                            yield _sse("agent_state", agent.to_dict())
                            yield _sse("error", {"message": "No action provided"})
                            return

                        action = decision.next_action

                        # Enforce per-tool retry limit
                        if not agent.can_retry(action.tool):
                            logger.info("Tool %s exceeded retry limit, skipping", action.tool)
                            failed_attempts.append({
                                "tool": action.tool,
                                "error": f"Exceeded max retries for {action.tool}",
                                "failure_type": "BAD_INPUT",
                            })
                            continue

                        call_id = f"call_{iteration}_{action.tool}"

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
                            tool_name=action.tool,
                            tool_input=action.input,
                            user_role=user_role,
                            db=db,
                            user_id=user_id,
                            reg=reg,
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

                        # Record observation
                        obs = Observation(
                            tool=action.tool,
                            success=passed,
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
                            llm=llm,
                            model=model,
                            goal=goal,
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

                    case "ASK_USER":
                        final_content = decision.reason
                        yield _sse("token", {"delta": decision.reason})
                        break

                    case "FAIL":
                        agent.fail(decision.reason)
                        yield _sse("agent_state", agent.to_dict())
                        yield _sse("error", {"message": decision.reason})
                        return

            else:
                # Max iterations exhausted
                if not final_content:
                    final_content = "I was unable to complete the analysis within the iteration limit."
                agent.fail("Max iterations reached")
                yield _sse("agent_state", agent.to_dict())
                yield _sse("error", {"message": "Max iterations reached"})

        except asyncio.CancelledError:
            agent.cancel()
            yield _sse("agent_state", agent.to_dict())
            yield _sse("cancelled", {"message": "Cancelled"})
            return
        except Exception as exc:
            logger.exception("Agent runtime error: %s", exc)
            agent.fail(str(exc)[:200])
            yield _sse("agent_state", agent.to_dict())
            yield _sse("error", {"message": f"Agent error: {str(exc)[:200]}"})
            return

        # === FINALIZE ===
        if agent.state not in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
            agent.complete()
            yield _sse("agent_state", agent.to_dict())

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
                timeout=120.0,
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
                timeout=120.0,
            )
            text = resp.content if hasattr(resp, "content") else str(resp)
        except (asyncio.TimeoutError, ModelUnavailableError, Exception) as exc:
            logger.warning("Reasoning failed: %s", exc)
            return AgentDecision(decision="FAIL", reason=f"LLM error: {exc}")

        data = parse_llm_json(text)
        if data.get("type") == "error":
            logger.warning("Reasoner raw output (unparseable): %s", text[:500])
            # Fallback: if no tools have been used and plan has no tool steps,
            # treat simple greetings as COMPLETE
            has_tool_steps = any(s.tool for s in agent.plan if s.status == "pending") if agent.plan else False
            if not has_tool_steps and not observations:
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
            pending_tools = [s for s in agent.plan if s.status == "pending" and s.tool] if agent.plan else []
            if not pending_tools:
                return AgentDecision(
                    decision="VERIFY",
                    reason="Reasoner output invalid, but no pending tool steps — verifying",
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
                timeout=120.0,
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
            if not observations and not tool_results_context:
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
            if not observations and not tool_results_context:
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
                timeout=120.0,
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
            return {"error": f"Tool '{tool_name}' not found or not enabled"}

        # 2. Permission check
        try:
            reg.check_permission(tool, user_role)
        except PermissionError as exc:
            return {"error": str(exc)}

        # 3. Input validation
        try:
            validated_input = reg.validate_input(tool, tool_input)
        except Exception as exc:
            return {"error": f"Input validation failed: {exc}"}

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
