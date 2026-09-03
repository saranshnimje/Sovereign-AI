"""
Sub-agent manager — spawns, tracks, and coordinates child agents.

Each sub-agent runs in its own async task with isolated context:
- Fresh message history
- Own todo list
- Specific tool set
- Configurable model
- Depth tracking to prevent infinite nesting
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from services.subagent_types import (
    SubAgentResult,
    SubAgentSession,
    AGENT_TYPE_DESCRIPTIONS,
    AGENT_TYPE_TOOLS,
)

logger = logging.getLogger(__name__)

# Safety limits for sub-agents
MAX_DEPTH = 10
MAX_CONCURRENT = 5
MAX_ITERATIONS_PER_SUBAGENT = 30
MAX_RUNTIME_SECONDS = 300  # 5 minutes per sub-agent


class SubAgentManager:
    """Manages spawning and tracking sub-agents."""

    def __init__(self, llm_client=None, tool_registry=None) -> None:
        self.llm = llm_client
        self.registry = tool_registry
        self.active: dict[str, SubAgentSession] = {}
        self.completed: dict[str, SubAgentSession] = {}

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
    ) -> SubAgentSession:
        """Create and start a child agent session."""
        if depth >= MAX_DEPTH:
            raise RuntimeError(f"Sub-agent depth limit reached ({MAX_DEPTH})")
        if len(self.active) >= MAX_CONCURRENT:
            raise RuntimeError(f"Max concurrent sub-agents reached ({MAX_CONCURRENT})")

        session_id = f"sub-{uuid.uuid4().hex[:12]}"

        # Determine tools for this agent type
        allowed_tools = tools or AGENT_TYPE_TOOLS.get(agent_type, [])
        # Filter by user role
        if self.registry:
            allowed_tools = [
                t for t in allowed_tools
                if self.registry.get(t) is not None
            ]

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
            "Spawned sub-agent %s (type=%s, depth=%d, tools=%s)",
            session_id, agent_type, depth, allowed_tools,
        )

        # Start execution in background
        asyncio.create_task(
            self._execute(session, allowed_tools, context, user_role)
        )

        return session

    async def _execute(
        self,
        session: SubAgentSession,
        allowed_tools: list[str],
        context: str | None,
        user_role: str,
    ) -> None:
        """Run the sub-agent's autonomous loop."""
        try:
            agent_type_desc = AGENT_TYPE_DESCRIPTIONS.get(session.agent_type, "")

            # Build system prompt for sub-agent
            tool_list = ""
            if self.registry:
                tool_list = self.registry.get_tool_list_for_prompt(
                    allowed_names=allowed_tools, user_role=user_role
                )

            system_prompt = (
                f"You are a specialized {session.agent_type} sub-agent.\n"
                f"{agent_type_desc}\n\n"
                f"Your task: {session.task}\n\n"
                f"Available tools:\n{tool_list}\n\n"
                f"Rules:\n"
                f"1. Complete your assigned task autonomously\n"
                f"2. Use tools to gather information or make changes\n"
                f"3. Verify your results before finishing\n"
                f"4. When done, respond with a JSON summary:\n"
                f'{{"complete": {{"result": "your summary", "findings": [...], '
                f'"artifacts": [...], "files_changed": [...], "recommendations": [...]}}}}\n'
                f"5. If you encounter an error you cannot fix, respond with:\n"
                f'{{"complete": {{"result": "partial result: ...", "status": "failed"}}}}\n'
                f"6. Maximum iterations: {MAX_ITERATIONS_PER_SUBAGENT}\n"
            )

            messages = []
            if context:
                messages.append({"role": "user", "content": f"Context:\n{context}"})
            messages.append({"role": "user", "content": session.task})

            # Simple agent loop for sub-agent
            for iteration in range(MAX_ITERATIONS_PER_SUBAGENT):
                elapsed = time.monotonic() - session.started_at
                if elapsed > MAX_RUNTIME_SECONDS:
                    session.status = "failed"
                    session.error = f"Sub-agent timed out ({MAX_RUNTIME_SECONDS}s)"
                    break

                if not self.llm:
                    # No LLM available — return a placeholder result
                    session.result = SubAgentResult(
                        agent_id=session.id,
                        agent_type=session.agent_type,
                        status="completed",
                        summary=f"Sub-agent '{session.agent_type}' executed (no LLM for full reasoning).",
                        elapsed_ms=int(elapsed * 1000),
                    )
                    session.status = "completed"
                    break

                try:
                    resp = await asyncio.wait_for(
                        self.llm.chat(
                            model=session.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                *messages[-10:],
                            ],
                            stream=False,
                            temperature=0.0,
                            max_tokens=1024,
                        ),
                        timeout=60.0,
                    )
                    llm_text = resp.content if hasattr(resp, "content") else str(resp)
                except Exception as exc:
                    logger.warning("Sub-agent %s LLM error: %s", session.id, exc)
                    session.status = "failed"
                    session.error = str(exc)[:500]
                    break

                # Check for completion
                try:
                    cleaned = llm_text.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
                    data = json.loads(cleaned)
                    if "complete" in data:
                        comp = data["complete"]
                        elapsed_ms = int((time.monotonic() - session.started_at) * 1000)
                        session.result = SubAgentResult(
                            agent_id=session.id,
                            agent_type=session.agent_type,
                            status="completed",
                            summary=comp.get("result", ""),
                            findings=comp.get("findings", []),
                            artifacts=comp.get("artifacts", []),
                            files_changed=comp.get("files_changed", []),
                            recommendations=comp.get("recommendations", []),
                            elapsed_ms=elapsed_ms,
                        )
                        session.status = "completed"
                        break
                except (json.JSONDecodeError, KeyError):
                    pass

                # Continue the loop
                messages.append({"role": "assistant", "content": llm_text})
                messages.append({"role": "user", "content": "Continue with your task."})

            else:
                # Exhausted iterations
                elapsed_ms = int((time.monotonic() - session.started_at) * 1000)
                session.result = SubAgentResult(
                    agent_id=session.id,
                    agent_type=session.agent_type,
                    status="failed",
                    summary="Sub-agent exhausted iterations without completing.",
                    elapsed_ms=elapsed_ms,
                )
                session.status = "failed"

        except asyncio.CancelledError:
            session.status = "cancelled"
        except Exception as exc:
            logger.exception("Sub-agent %s failed: %s", session.id, exc)
            session.status = "failed"
            session.error = str(exc)[:500]
        finally:
            session.completed_at = time.monotonic()
            # Move from active to completed
            self.completed[session.id] = self.active.pop(session.id, session)

    async def get_result(self, session_id: str, timeout: float = 60.0) -> SubAgentResult | None:
        """Wait for a sub-agent to complete and return its result."""
        # Check if already completed
        if session_id in self.completed:
            return self.completed[session_id].result

        # Wait for completion
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if session_id in self.completed:
                return self.completed[session_id].result
            if session_id in self.active and self.active[session_id].status != "running":
                return self.active[session_id].result
            await asyncio.sleep(0.5)

        return None

    async def cancel(self, session_id: str) -> bool:
        """Cancel a running sub-agent."""
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


# Module-level singleton
_manager: SubAgentManager | None = None


def get_subagent_manager(
    llm_client=None, tool_registry=None
) -> SubAgentManager:
    global _manager
    if _manager is None:
        _manager = SubAgentManager(llm_client=llm_client, tool_registry=tool_registry)
    return _manager
