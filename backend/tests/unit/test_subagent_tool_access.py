"""Regression tests for sub-agent tool access and tenant propagation."""
from __future__ import annotations

import asyncio

import pytest

from services.subagent_manager import SubAgentManager


class _Tool:
    def __init__(self, name: str):
        self.name = name


class _Registry:
    def __init__(self, names: list[str]):
        self.names = names
        self.prompt_names: list[str] = []

    def list_enabled(self, user_role: str):
        return [_Tool(name) for name in self.names]

    def get(self, name: str):
        return _Tool(name) if name in self.names else None

    def get_tool_list_for_prompt(self, allowed_names, user_role):
        self.prompt_names = list(allowed_names)
        return "\n".join(f"- {name}" for name in allowed_names)

    def check_permission(self, tool, user_role):
        return None

    def validate_input(self, tool, raw_input):
        return raw_input


class _Response:
    content = '{"type":"complete","result":"done"}'


class _LLM:
    def __init__(self):
        self.prompts = []

    async def chat(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return _Response()


@pytest.mark.asyncio
async def test_subagent_gets_all_role_permitted_tools():
    names = ["calculator", "web_search", "search_kb", "search_org_data", "file_read"]
    registry = _Registry(names)
    llm = _LLM()
    manager = SubAgentManager(llm_client=llm, tool_registry=registry)

    session = await manager.spawn(
        parent_id="run-1",
        task="Inspect available user data and report what you find.",
        agent_type="researcher",
        user_role="analyst",
        user_id="user-1",
    )
    result = await manager.get_result(session.id, timeout=2)

    assert result is not None
    assert set(registry.prompt_names) == set(names)
    assert all(f"- {name}" in llm.prompts[0] for name in names)


@pytest.mark.asyncio
async def test_subagent_explicit_tools_can_only_narrow_permissions():
    registry = _Registry(["calculator", "web_search"])
    manager = SubAgentManager(llm_client=_LLM(), tool_registry=registry)

    with pytest.raises(RuntimeError, match="not permitted"):
        await manager.spawn(
            parent_id="run-1",
            task="Use an unauthorized tool.",
            agent_type="researcher",
            tools=["python_exec"],
            user_role="analyst",
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_subagent_requires_authenticated_user_identity():
    manager = SubAgentManager(llm_client=_LLM(), tool_registry=_Registry(["calculator"]))

    with pytest.raises(RuntimeError, match="authenticated user identity"):
        await manager.spawn(
            parent_id="run-1",
            task="Do work.",
            agent_type="researcher",
            user_role="analyst",
            user_id=None,
        )
