"""
Agent Service — orchestrates the LLM reasoning loop.

SECURITY CHAIN (enforced here, NON-NEGOTIABLE):
  LLM proposes action
    → ToolRegistry.get()          (must exist and be enabled)
    → ToolRegistry.check_permission()  (user role must qualify)
    → ToolRegistry.validate_input()    (Pydantic schema — rejects malformed input)
    → Risk assessment
    → If High/Critical → ApprovalService.create_request() + wait_for_decision()
         Denied/Expired → step skipped
    → ToolRegistry.execute() with VALIDATED input
         sandboxed → SandboxService.run_python()
         in-process → tool.handler()
    → Result captured → ToolCall recorded
    → AuditService.log()
    → LLM receives result and reasons about next step

The LLM NEVER directly executes shell commands, Python, or filesystem ops.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.agent import AgentRun, ApprovalRequest, ToolCall
from models.base import generate_uuid
from services.approval_service import ApprovalService
from services.audit_service import AuditService
from services.llm_client import ChatMessage, ModelUnavailableError, OllamaClient
from services.sandbox_service import SandboxService
from tools.registry import get_registry, RISK_HIGH, RISK_CRITICAL

logger = logging.getLogger(__name__)

# Agent system prompt — injected before every LLM call
_SYSTEM_PROMPT_TEMPLATE = """\
You are an AI agent inside Sovereign AI Workbench.
You MUST respond with ONLY a valid JSON object — no prose, no markdown fences.

Available tools:
{tool_list}

Response format — choose ONE:

To call a tool:
{{"type": "tool_call", "tool": "TOOL_NAME", "input": {{...}}, "reasoning": "why"}}

When the goal is fully complete:
{{"type": "complete", "result": "final answer or summary"}}

Rules:
1. Only use tools from the list above.
2. Tool input must exactly match the schema shown.
3. High-risk tools (file_delete, python_exec) will pause for human approval.
4. If a tool fails, explain what happened and try an alternative approach.
5. Maximum iterations remaining: {remaining}
6. Previous steps summary: {summary}
"""

# Maximum characters of stdout/stderr to include in the LLM context
_MAX_OUTPUT_IN_CONTEXT = 2000


class AgentService:
    def __init__(
        self,
        db: AsyncSession,
        llm: OllamaClient,
        sandbox: SandboxService | None = None,
        rag_service=None,
        kb_service=None,
    ) -> None:
        self.db = db
        self.llm = llm
        self.sandbox = sandbox
        self.rag_service = rag_service
        self.kb_service = kb_service
        self.settings = get_settings()
        self.registry = get_registry()

    # ------------------------------------------------------------------
    # Public: start a run (stores DB record, enqueues background task)
    # ------------------------------------------------------------------
    async def create_run(
        self,
        user_id: str,
        goal: str,
        model_name: str | None,
        allowed_tools: list[str] | None,
        kb_ids: list[str] | None,
        max_iterations: int,
        client_ip: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=generate_uuid(),
            user_id=user_id,
            goal=goal[:5000],
            status="pending",
            model_name=model_name,
            max_iterations=max_iterations,
            plan_json=json.dumps({
                "allowed_tools": allowed_tools,
                "kb_ids": kb_ids or [],
            }),
        )
        self.db.add(run)
        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "agent", "agent.run.start", "pending",
            user_id=user_id,
            resource_type="agent_run", resource_id=run.id,
            metadata={"goal": goal[:200]},
            ip_address=client_ip,
        )
        return run

    # ------------------------------------------------------------------
    # Public: execute_run (called as FastAPI BackgroundTask)
    # ------------------------------------------------------------------
    async def execute_run(self, run_id: str, user_role: str = "analyst") -> None:
        """Full agent loop. Runs in background. Updates DB throughout."""
        run = await self._get_run(run_id)
        if run is None:
            logger.error("execute_run: run %s not found", run_id)
            return

        # Resolve config
        plan_meta = json.loads(run.plan_json or "{}")
        allowed_tools: list[str] | None = plan_meta.get("allowed_tools")
        kb_ids: list[str] = plan_meta.get("kb_ids", [])
        model = run.model_name or self.settings.default_chat_model

        # Create isolated workspace for this run
        workspace = self._make_workspace(run_id)
        run.status = "running"
        await self.db.flush()

        # SSE event queue (for real-time streaming)
        events: asyncio.Queue = asyncio.Queue()
        run.plan_json = json.dumps({
            **plan_meta,
            "events_queue_id": run_id,  # marker; actual queue lives in memory
        })

        step_history: list[dict] = []
        iteration = 0

        try:
            while iteration < run.max_iterations:
                iteration += 1
                run.iteration_count = iteration
                await self.db.flush()

                # ---- Ask LLM for next action ----
                system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
                    tool_list=self.registry.get_tool_list_for_prompt(
                        allowed_names=allowed_tools, user_role=user_role
                    ),
                    remaining=run.max_iterations - iteration,
                    summary=self._summarise_history(step_history),
                )
                messages = self._build_messages(run.goal, step_history)

                try:
                    resp = await self.llm.chat(
                        model=model,
                        messages=messages,
                        system_prompt=system_prompt,
                        temperature=0.0,
                        max_tokens=1024,
                        stream=False,
                    )
                    llm_text = resp.content if hasattr(resp, "content") else str(resp)
                except ModelUnavailableError as exc:
                    await self._fail(run, workspace, str(exc))
                    return

                # ---- Parse LLM JSON response ----
                action = self._parse_action(llm_text)

                if action["type"] == "complete":
                    result_text = str(action.get("result", ""))
                    run.result = result_text[:10000]
                    run.status = "completed"
                    run.step_count = len(step_history)
                    await self.db.flush()
                    await self._audit_complete(run)
                    logger.info("Agent run %s completed in %d iterations", run_id, iteration)
                    break

                elif action["type"] == "tool_call":
                    step = await self._execute_tool_step(
                        run=run,
                        action=action,
                        step_number=len(step_history) + 1,
                        user_role=user_role,
                        workspace=workspace,
                        iteration=iteration,
                    )
                    step_history.append(step)
                    run.step_count = len(step_history)
                    await self.db.flush()

                    # If step was a hard stop (cancel), bail out
                    if step.get("cancelled"):
                        await self._cancel(run, workspace)
                        return

                else:
                    # Unrecognised action — log and let LLM retry
                    step_history.append({
                        "iteration": iteration,
                        "type": "error",
                        "error": f"Unrecognised LLM output: {llm_text[:200]}",
                    })

            else:
                # Max iterations reached
                partial = self._synthesise_partial(step_history)
                run.result = partial
                run.status = "failed"
                run.error_message = f"Max iterations ({run.max_iterations}) reached"
                run.step_count = len(step_history)
                await self.db.flush()
                audit = AuditService(self.db)
                await audit.log(
                    "agent", "agent.run.max_iterations", "failure",
                    resource_type="agent_run", resource_id=run_id,
                    metadata={"iterations": iteration},
                )

        except asyncio.CancelledError:
            await self._cancel(run, workspace)
        except Exception as exc:
            logger.exception("Unexpected error in agent run %s: %s", run_id, exc)
            await self._fail(run, workspace, str(exc))
        finally:
            self._cleanup_workspace(workspace)

    # ------------------------------------------------------------------
    # Tool step execution — enforces the full security chain
    # ------------------------------------------------------------------
    async def _execute_tool_step(
        self,
        run: AgentRun,
        action: dict,
        step_number: int,
        user_role: str,
        workspace: str,
        iteration: int,
    ) -> dict:
        tool_name: str = action.get("tool", "")
        raw_input: dict = action.get("input", {})
        reasoning: str = action.get("reasoning", "")

        # ---- 1. Lookup tool ----
        tool = self.registry.get(tool_name)
        if tool is None:
            return self._step_error(step_number, tool_name, raw_input,
                                    f"Tool '{tool_name}' not found or not enabled")

        # ---- 2. Permission check ----
        try:
            self.registry.check_permission(tool, user_role)
        except PermissionError as exc:
            return self._step_error(step_number, tool_name, raw_input, str(exc))

        # ---- 3. Input validation (Pydantic) ----
        try:
            validated_input = self.registry.validate_input(tool, raw_input)
        except Exception as exc:
            return self._step_error(
                step_number, tool_name, raw_input,
                f"Input validation failed: {exc}"
            )

        # ---- 4. Risk assessment → approval gate ----
        if self.registry.requires_approval(tool):
            approval_svc = ApprovalService(self.db)
            req = await approval_svc.create_request(
                agent_run_id=run.id,
                requester_id=run.user_id,
                tool_name=tool_name,
                tool_input=validated_input.model_dump(),
                risk_level=tool.risk_level,
            )
            logger.info(
                "Run %s step %d awaiting approval (tool=%s, risk=%s)",
                run.id, step_number, tool_name, tool.risk_level,
            )

            approved, note = await approval_svc.wait_for_decision(req.id)

            if not approved:
                # Record rejected tool call
                tc = await self._record_tool_call(
                    run.id, step_number, tool_name,
                    validated_input.model_dump(),
                    None, "rejected", None, None, False, None,
                )
                audit = AuditService(self.db)
                await audit.log(
                    "tool", "tool.call.rejected", "failure",
                    user_id=run.user_id,
                    resource_type="tool_call", resource_id=tc.id,
                    metadata={"tool": tool_name, "note": note},
                )
                return {
                    "iteration": iteration,
                    "step": step_number,
                    "tool": tool_name,
                    "status": "rejected",
                    "output": {"error": f"Approval denied: {note}"},
                }

            # Approval granted — restore run status
            run.status = "running"
            await self.db.flush()

        # ---- 5. Build execution context ----
        from types import SimpleNamespace

        context = {
            "workspace_path": workspace,
            "sandbox_service": self.sandbox,
            "rag_service": self.rag_service,
            "kb_service": self.kb_service,
            # Tenancy: tools (e.g. search_kb) scope KB access to the run owner
            "user": SimpleNamespace(id=run.user_id, role=user_role),
        }

        # ---- 6. Execute via registry (VALIDATED input, not raw LLM text) ----
        t0 = time.monotonic()
        sandbox_used = tool.requires_sandbox
        container_id: str | None = None
        output: dict
        status_str: str
        exit_code: int | None = None

        try:
            if tool.requires_sandbox:
                # Execution goes through SandboxService
                if not self.sandbox or not self.sandbox.available:
                    raise RuntimeError(
                        "Docker sandbox unavailable. "
                        "Ensure Docker is running on the host."
                    )
            # Execute through the registry handler
            output = await self.registry.execute(tool, validated_input, context)
            status_str = "success"
            container_id = output.get("container_id")
            if "exit_code" in output:
                exit_code = output["exit_code"]

        except Exception as exc:
            output = {"error": str(exc)[:1000]}
            status_str = "failed"

        duration_ms = int((time.monotonic() - t0) * 1000)

        # ---- 7. Record tool call ----
        tc = await self._record_tool_call(
            run.id, step_number, tool_name,
            validated_input.model_dump(), output,
            status_str, exit_code, duration_ms,
            sandbox_used, container_id,
        )

        # ---- 8. Audit ----
        audit = AuditService(self.db)
        await audit.log(
            "tool",
            f"tool.call.{status_str}",
            "success" if status_str == "success" else "failure",
            user_id=run.user_id,
            resource_type="tool_call", resource_id=tc.id,
            metadata={
                "tool": tool_name,
                "risk": tool.risk_level,
                "sandbox": sandbox_used,
                "duration_ms": duration_ms,
            },
        )

        # Trim output for LLM context
        trimmed = self._trim_output(output)
        return {
            "iteration": iteration,
            "step": step_number,
            "tool": tool_name,
            "input": validated_input.model_dump(),
            "output": trimmed,
            "status": status_str,
            "duration_ms": duration_ms,
            "reasoning": reasoning,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_messages(self, goal: str, history: list[dict]) -> list[ChatMessage]:
        parts = [f"GOAL: {goal}"]
        for step in history[-10:]:  # keep last 10 steps in context
            if step.get("type") == "error":
                parts.append(f"ERROR: {step.get('error', '')}")
            elif step.get("tool"):
                out = json.dumps(step.get("output", {}))
                if len(out) > _MAX_OUTPUT_IN_CONTEXT:
                    out = out[:_MAX_OUTPUT_IN_CONTEXT] + "...[truncated]"
                parts.append(
                    f"Step {step['step']}: called {step['tool']} → {step['status']}\n"
                    f"Output: {out}"
                )
        return [ChatMessage(role="user", content="\n\n".join(parts))]

    def _summarise_history(self, history: list[dict]) -> str:
        if not history:
            return "No steps taken yet."
        lines = []
        for s in history[-5:]:
            if s.get("tool"):
                lines.append(f"- {s['tool']}: {s['status']}")
            elif s.get("type") == "error":
                lines.append(f"- ERROR: {s.get('error', '')[:80]}")
        return "\n".join(lines) or "No steps taken yet."

    @staticmethod
    def _parse_action(text: str) -> dict:
        """Extract JSON from LLM response. Handles markdown fences gracefully."""
        # Strip markdown code fences
        text = re.sub(r"```(?:json)?\n?", "", text)
        text = re.sub(r"```\n?", "", text)
        # Find outermost {...}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                if "type" in data:
                    return data
            except json.JSONDecodeError:
                pass
        return {"type": "error", "message": f"Could not parse: {text[:200]}"}

    @staticmethod
    def _trim_output(output: dict) -> dict:
        """Cap large output fields so they don't flood the LLM context."""
        trimmed = {}
        for k, v in output.items():
            if isinstance(v, str) and len(v) > _MAX_OUTPUT_IN_CONTEXT:
                trimmed[k] = v[:_MAX_OUTPUT_IN_CONTEXT] + "...[truncated]"
            else:
                trimmed[k] = v
        return trimmed

    @staticmethod
    def _synthesise_partial(history: list[dict]) -> str:
        completed = [s for s in history if s.get("status") == "success"]
        if not completed:
            return "No steps completed before max iterations."
        return f"Partial result after {len(history)} steps. " + \
               f"Last completed: {completed[-1].get('tool', 'unknown')}"

    @staticmethod
    def _step_error(step: int, tool: str, raw_input: dict, msg: str) -> dict:
        return {
            "step": step,
            "tool": tool,
            "input": raw_input,
            "output": {"error": msg},
            "status": "failed",
        }

    def _make_workspace(self, run_id: str) -> str:
        ws = os.path.join(
            self.settings.sandbox_workspace,
            f"run_{run_id}_{uuid.uuid4().hex[:8]}"
        )
        os.makedirs(ws, exist_ok=True)
        return ws

    @staticmethod
    def _cleanup_workspace(workspace: str) -> None:
        try:
            if os.path.isdir(workspace):
                shutil.rmtree(workspace, ignore_errors=True)
        except Exception as exc:
            logger.warning("Could not clean workspace %s: %s", workspace, exc)

    async def _get_run(self, run_id: str) -> AgentRun | None:
        result = await self.db.execute(select(AgentRun).where(AgentRun.id == run_id))
        return result.scalar_one_or_none()

    async def _record_tool_call(
        self,
        run_id: str, step: int, tool_name: str,
        input_data: dict, output_data: dict | None,
        status: str, exit_code: int | None, duration_ms: int | None,
        sandbox_used: bool, container_id: str | None,
    ) -> ToolCall:
        tc = ToolCall(
            id=generate_uuid(),
            agent_run_id=run_id,
            step_number=step,
            tool_name=tool_name,
            input_json=json.dumps(input_data),
            output_json=json.dumps(output_data) if output_data is not None else None,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            sandbox_used=sandbox_used,
            container_id=container_id,
        )
        self.db.add(tc)
        await self.db.flush()
        return tc

    async def _audit_complete(self, run: AgentRun) -> None:
        audit = AuditService(self.db)
        await audit.log(
            "agent", "agent.run.completed", "success",
            user_id=run.user_id,
            resource_type="agent_run", resource_id=run.id,
            metadata={"iterations": run.iteration_count, "steps": run.step_count},
        )

    async def _fail(self, run: AgentRun, workspace: str, error: str) -> None:
        run.status = "failed"
        run.error_message = error[:1000]
        await self.db.flush()
        audit = AuditService(self.db)
        await audit.log(
            "agent", "agent.run.failed", "failure",
            user_id=run.user_id,
            resource_type="agent_run", resource_id=run.id,
            metadata={"error": error[:500]},
        )
        self._cleanup_workspace(workspace)

    async def _cancel(self, run: AgentRun, workspace: str) -> None:
        run.status = "cancelled"
        await self.db.flush()
        audit = AuditService(self.db)
        await audit.log(
            "agent", "agent.run.cancelled", "success",
            user_id=run.user_id,
            resource_type="agent_run", resource_id=run.id,
        )
        self._cleanup_workspace(workspace)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    async def get_run(self, run_id: str) -> AgentRun | None:
        return await self._get_run(run_id)

    async def list_runs(
        self, user_id: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[AgentRun]:
        from sqlalchemy.orm import selectinload
        q = select(AgentRun).order_by(AgentRun.created_at.desc())
        if user_id:
            q = q.where(AgentRun.user_id == user_id)
        result = await self.db.execute(q.offset(offset).limit(limit))
        return list(result.scalars().all())

    async def cancel_run(self, run_id: str, user_id: str) -> AgentRun | None:
        run = await self._get_run(run_id)
        if run and run.status in ("pending", "running", "awaiting_approval"):
            run.status = "cancelled"
            await self.db.flush()
            audit = AuditService(self.db)
            await audit.log(
                "agent", "agent.run.cancelled", "success",
                user_id=user_id,
                resource_type="agent_run", resource_id=run_id,
            )
        return run

    async def get_tool_calls(self, run_id: str) -> list[ToolCall]:
        result = await self.db.execute(
            select(ToolCall)
            .where(ToolCall.agent_run_id == run_id)
            .order_by(ToolCall.step_number)
        )
        return list(result.scalars().all())
