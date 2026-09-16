"""
Sub-agent manager — spawns, tracks, and coordinates child agents.

Sub-agents use the same ToolRegistry security boundary as the main agent.
Every child receives the complete set of tools permitted for the requesting
user role unless an explicit subset is requested. Tool execution is performed
through ToolRegistry.validate_input() + execute(), with the authenticated user
identity and a fresh database session in the execution context.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from types import SimpleNamespace
from typing import Any

from services.subagent_types import (
    SubAgentResult,
    SubAgentSession,
    AGENT_TYPE_DESCRIPTIONS,
)

logger = logging.getLogger(__name__)

MAX_DEPTH = 10
MAX_CONCURRENT = 5
MAX_ITERATIONS_PER_SUBAGENT = 30
MAX_RUNTIME_SECONDS = 300
TOOL_TIMEOUT_SECONDS = 30.0


class SubAgentManager:
    """Manages sub-agents with the same permissions/data boundary as the parent."""

    def __init__(self, llm_client=None, tool_registry=None) -> None:
        self.llm = llm_client
        self.registry = tool_registry
        self.active: dict[str, SubAgentSession] = {}
        self.completed: dict[str, SubAgentSession] = {}

    def _ensure_dependencies(self) -> None:
        if self.registry is None:
            from tools.registry import get_registry
            self.registry = get_registry()
        if self.llm is None:
            try:
                from dependencies import get_llm_client
                self.llm = get_llm_client()
            except Exception:
                self.llm = None

    async def spawn(
        self,
        parent_id: str | None,
        task: str,
        agent_type: str,
        model: str | None = None,
        tools: list[str] | None = None,
        context: str | None = None,
        depth: int = 0,
        user_role: str = "analyst",
        user_id: str | None = None,
    ) -> SubAgentSession:
        """Create and start a child agent session."""
        if depth >= MAX_DEPTH:
            raise RuntimeError(f"Sub-agent depth limit reached ({MAX_DEPTH})")
        if len(self.active) >= MAX_CONCURRENT:
            raise RuntimeError(f"Max concurrent sub-agents reached ({MAX_CONCURRENT})")
        if not user_id:
            raise RuntimeError("Sub-agent requires the authenticated user identity")

        self._ensure_dependencies()
        if self.registry is None:
            raise RuntimeError("Tool registry unavailable")

        # No static per-agent-type allow-list: every sub-agent receives every
        # enabled tool permitted by the current user's role. An explicit tools
        # argument is treated as a narrower subset, never an elevation.
        permitted = {t.name for t in self.registry.list_enabled(user_role=user_role)}
        if tools is None:
            allowed_tools = sorted(permitted)
        else:
            unknown = sorted(set(tools) - permitted)
            if unknown:
                raise RuntimeError(
                    "Requested tools are not permitted for this user: "
                    + ", ".join(unknown)
                )
            allowed_tools = sorted(set(tools))

        session_id = f"sub-{uuid.uuid4().hex[:12]}"
        session = SubAgentSession(
            id=session_id,
            parent_id=parent_id,
            task=task,
            agent_type=agent_type,
            status="running",
            model=model or "default",
            depth=depth,
            started_at=time.monotonic(),
        )
        self.active[session_id] = session

        logger.info(
            "Spawned sub-agent %s (type=%s, depth=%d, user=%s, tools=%s)",
            session_id, agent_type, depth, user_id, allowed_tools,
        )

        asyncio.create_task(
            self._execute(session, allowed_tools, context, user_role, user_id)
        )
        return session

    async def _execute(
        self,
        session: SubAgentSession,
        allowed_tools: list[str],
        context: str | None,
        user_role: str,
        user_id: str,
    ) -> None:
        """Run the child agent loop and execute real tool calls."""
        workspace = ""
        try:
            self._ensure_dependencies()
            if not self.llm:
                raise RuntimeError("No LLM client available for sub-agent")
            if not self.registry:
                raise RuntimeError("Tool registry unavailable for sub-agent")

            agent_type_desc = AGENT_TYPE_DESCRIPTIONS.get(session.agent_type, "")
            tool_list = self.registry.get_tool_list_for_prompt(
                allowed_names=allowed_tools,
                user_role=user_role,
            )

            system_prompt = (
                f"You are a specialized {session.agent_type} sub-agent inside Sovereign AI Workbench.\n"
                f"{agent_type_desc}\n\n"
                f"Task: {session.task}\n\n"
                f"Available tools (use only these canonical names):\n{tool_list or 'No tools available'}\n\n"
                "Rules:\n"
                "1. You MUST execute a tool when the task requires data, computation, files, web research, or another available capability.\n"
                "2. Never invent a tool name. Use only the canonical names listed above.\n"
                "3. Tool results are authoritative evidence; inspect them before deciding the next step.\n"
                "4. Every tool call must be represented as JSON: "
                '{"type":"tool_call","tool":"TOOL_NAME","input":{...},"reasoning":"..."}.\n'
                "5. Finish only after the task is actually complete and verified.\n"
                "6. When complete, return: "
                '{"type":"complete","result":"...","findings":[],"artifacts":[],"files_changed":[],"recommendations":[]}.\n'
                "7. High/critical-risk tools remain subject to the same approval/safety boundary and must not be bypassed.\n"
                f"8. Maximum iterations: {MAX_ITERATIONS_PER_SUBAGENT}."
            )

            messages: list[dict[str, str]] = []
            if context:
                messages.append({"role": "user", "content": f"Context:\n{context}"})
            messages.append({"role": "user", "content": session.task})

            for iteration in range(MAX_ITERATIONS_PER_SUBAGENT):
                if time.monotonic() - session.started_at > MAX_RUNTIME_SECONDS:
                    session.status = "failed"
                    session.error = f"Sub-agent timed out ({MAX_RUNTIME_SECONDS}s)"
                    break

                try:
                    resp = await asyncio.wait_for(
                        self.llm.chat(
                            model=session.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                *messages[-12:],
                            ],
                            stream=False,
                            temperature=0.0,
                            max_tokens=1536,
                        ),
                        timeout=60.0,
                    )
                    llm_text = resp.content if hasattr(resp, "content") else str(resp)
                except Exception as exc:
                    session.status = "failed"
                    session.error = str(exc)[:500]
                    break

                data = self._parse_json(llm_text)
                if data is None:
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Return ONLY valid JSON using either type=tool_call or type=complete. "
                            "Do not finish without executing required tools."
                        ),
                    })
                    continue

                if data.get("type") == "complete":
                    comp = data
                    result_status = str(comp.get("status", "completed"))
                    elapsed_ms = int((time.monotonic() - session.started_at) * 1000)
                    session.result = SubAgentResult(
                        agent_id=session.id,
                        agent_type=session.agent_type,
                        status="completed" if result_status != "failed" else "failed",
                        summary=str(comp.get("result", "")),
                        findings=comp.get("findings", []) if isinstance(comp.get("findings", []), list) else [],
                        artifacts=comp.get("artifacts", []) if isinstance(comp.get("artifacts", []), list) else [],
                        files_changed=comp.get("files_changed", []) if isinstance(comp.get("files_changed", []), list) else [],
                        recommendations=comp.get("recommendations", []) if isinstance(comp.get("recommendations", []), list) else [],
                        tool_calls_made=iteration if iteration > 0 else 0,
                        elapsed_ms=elapsed_ms,
                    )
                    session.status = session.result.status
                    break

                if data.get("type") != "tool_call":
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({"role": "user", "content": "Use type=tool_call or type=complete only."})
                    continue

                tool_name = str(data.get("tool", "")).strip()
                raw_input = data.get("input", {})
                if not isinstance(raw_input, dict):
                    raw_input = {}
                if tool_name not in allowed_tools:
                    tool_result = {
                        "error": f"Tool '{tool_name}' is not in the permitted tool set",
                        "failure_type": "FATAL",
                    }
                else:
                    tool_result = await self._execute_tool(
                        tool_name=tool_name,
                        raw_input=raw_input,
                        user_id=user_id,
                        user_role=user_role,
                        workspace=workspace,
                    )

                messages.append({"role": "assistant", "content": llm_text})
                messages.append({
                    "role": "user",
                    "content": "Tool result:\n" + json.dumps(tool_result, default=str)[:8000],
                })

                if not session.activity:
                    session.activity = []
                session.activity.append({
                    "iteration": iteration,
                    "tool": tool_name,
                    "status": "success" if not tool_result.get("error") else "failed",
                })
                if session.result is None:
                    session.result = SubAgentResult(
                        agent_id=session.id,
                        agent_type=session.agent_type,
                        status="running",
                        summary="",
                        tool_calls_made=iteration,
                    )

            else:
                elapsed_ms = int((time.monotonic() - session.started_at) * 1000)
                session.result = SubAgentResult(
                    agent_id=session.id,
                    agent_type=session.agent_type,
                    status="failed",
                    summary="Sub-agent exhausted iterations without completing.",
                    tool_calls_made=MAX_ITERATIONS_PER_SUBAGENT,
                    elapsed_ms=elapsed_ms,
                )
                session.status = "failed"

            if session.result is None and session.status == "failed":
                session.result = SubAgentResult(
                    agent_id=session.id,
                    agent_type=session.agent_type,
                    status="failed",
                    summary=session.error or "Sub-agent failed.",
                    elapsed_ms=int((time.monotonic() - session.started_at) * 1000),
                )

        except asyncio.CancelledError:
            session.status = "cancelled"
            session.error = "Sub-agent cancelled"
        except Exception as exc:
            logger.exception("Sub-agent %s failed", session.id)
            session.status = "failed"
            session.error = str(exc)[:500]
            session.result = SubAgentResult(
                agent_id=session.id,
                agent_type=session.agent_type,
                status="failed",
                summary=session.error,
                elapsed_ms=int((time.monotonic() - session.started_at) * 1000),
            )
        finally:
            session.completed_at = time.monotonic()
            if session.result is not None:
                session.result.elapsed_ms = int((time.monotonic() - session.started_at) * 1000)
            self.completed[session.id] = self.active.pop(session.id, session)
            if workspace:
                try:
                    import shutil
                    shutil.rmtree(workspace, ignore_errors=True)
                except Exception:
                    pass

    async def _execute_tool(
        self,
        *,
        tool_name: str,
        raw_input: dict[str, Any],
        user_id: str,
        user_role: str,
        workspace: str,
    ) -> dict[str, Any]:
        """Execute one child-agent tool through the canonical registry."""
        tool = self.registry.get(tool_name)
        if tool is None:
            return {"error": f"Tool '{tool_name}' not found or disabled", "failure_type": "NOT_FOUND"}
        try:
            self.registry.check_permission(tool, user_role)
            validated = self.registry.validate_input(tool, raw_input)
        except Exception as exc:
            return {"error": str(exc), "failure_type": "INVALID_TOOL_ARGUMENTS"}

        # High/critical tools are never allowed to bypass the approval boundary.
        if self.registry.requires_approval(tool):
            return {
                "error": f"Tool '{tool_name}' requires human approval and cannot be auto-executed by a child agent",
                "failure_type": "FATAL",
            }

        from database import AsyncSessionLocal
        from services.knowledge_base_service import KnowledgeBaseService
        from services.qdrant_service import QdrantService
        from services.embedding_service import EmbeddingService
        from services.rag_service import RagService

        async with AsyncSessionLocal() as db:
            context = {
                "user": SimpleNamespace(id=user_id, role=user_role),
                "db": db,
                "workspace_path": workspace,
            }
            if tool_name == "search_kb":
                try:
                    qdrant = QdrantService()
                    context["kb_service"] = KnowledgeBaseService(db, qdrant)
                    if self.llm is not None:
                        context["rag_service"] = RagService(
                            llm=self.llm,
                            embedding_svc=EmbeddingService(self.llm),
                            qdrant_svc=qdrant,
                        )
                except Exception as exc:
                    logger.debug("Could not initialize RAG context: %s", exc)

            try:
                return await asyncio.wait_for(
                    self.registry.execute(tool, validated, context),
                    timeout=TOOL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {
                    "error": f"Tool '{tool_name}' execution timed out",
                    "failure_type": "TRANSIENT",
                }
            except Exception as exc:
                return {"error": str(exc)[:1000], "failure_type": "TOOL_ERROR"}

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            # Recover a JSON object embedded in otherwise verbose model output.
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(cleaned[start:end + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    return None
            return None

    async def get_result(self, session_id: str, timeout: float = 60.0) -> SubAgentResult | None:
        if session_id in self.completed:
            return self.completed[session_id].result
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if session_id in self.completed:
                return self.completed[session_id].result
            if session_id in self.active and self.active[session_id].status != "running":
                return self.active[session_id].result
            await asyncio.sleep(0.5)
        return None

    async def cancel(self, session_id: str) -> bool:
        session = self.active.get(session_id)
        if session and session.status == "running":
            session.status = "cancelled"
            return True
        return False

    def list_active(self) -> list[SubAgentSession]:
        return list(self.active.values())

    def list_completed(self) -> list[SubAgentSession]:
        return list(self.completed.values())

    def get_session(self, session_id: str) -> SubAgentSession | None:
        return self.active.get(session_id) or self.completed.get(session_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": [s.to_dict() for s in self.active.values()],
            "completed": [s.to_dict() for s in self.completed.values()],
        }


_manager: SubAgentManager | None = None


def get_subagent_manager(llm_client=None, tool_registry=None) -> SubAgentManager:
    global _manager
    if _manager is None:
        _manager = SubAgentManager(llm_client=llm_client, tool_registry=tool_registry)
    else:
        if llm_client is not None:
            _manager.llm = llm_client
        if tool_registry is not None:
            _manager.registry = tool_registry
    return _manager
