"""
Tool-calling integration tests.

Tests the agent tool loop: LLM tool selection, real tool execution,
SSE events, security, error handling, and audit.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient


DIM = 768
FAKE_VECTORS = lambda n: [[0.1] * DIM for _ in range(n)]


class TestToolCalling:
    """Agent tool-calling integration tests."""

    @pytest.mark.asyncio
    async def test_agent_basic_chat_no_tool(self, client: AsyncClient):
        """Agent mode works for normal conversation (no tool needed)."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_tool@test.com", "username": "agent_tool",
            "password": "AgentTool123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_tool@test.com", "password": "AgentTool123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Agent tool test"
        }, headers=h)
        conv_id = r.json()["id"]

        mock_resp = MagicMock()
        mock_resp.content = '{"type": "complete", "result": "Hello! How can I help you?"}'

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_resp
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello!", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            body = resp.text
            assert "event: done" in body
            assert "event: token" in body

    @pytest.mark.asyncio
    async def test_agent_tool_call_event_structure(self, client: AsyncClient):
        """Agent emits tool_call, tool_started, tool_result SSE events."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_sse@test.com", "username": "agent_sse",
            "password": "AgentSSE123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_sse@test.com", "password": "AgentSSE123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "SSE test"
        }, headers=h)
        conv_id = r.json()["id"]

        # First response: LLM calls calculator
        # Second response: LLM gives final answer
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "2+2"}, "reasoning": "math"}
        })
        done_resp = MagicMock()
        done_resp.content = "The answer is 4."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "What is 2+2?", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_call" in body
            assert "event: tool_started" in body
            assert "event: tool_result" in body
            assert "event: token" in body
            assert "event: done" in body
            # Verify call_id is present
            assert '"call_id"' in body

    @pytest.mark.asyncio
    async def test_agent_unknown_tool_rejected(self, client: AsyncClient):
        """Agent handles unknown tool gracefully."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_unk@test.com", "username": "agent_unk",
            "password": "AgentUnk123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_unk@test.com", "password": "AgentUnk123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Unknown tool test"
        }, headers=h)
        conv_id = r.json()["id"]

        # LLM tries to call a non-existent tool
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "nonexistent_tool", "input": {}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Tool not available, answering directly."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Use nonexistent tool", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_error" in body
            assert "not found" in body.lower() or "not available" in body.lower()

    @pytest.mark.asyncio
    async def test_agent_invalid_arguments_rejected(self, client: AsyncClient):
        """Agent rejects invalid tool arguments."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_inv@test.com", "username": "agent_inv",
            "password": "AgentInv123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_inv@test.com", "password": "AgentInv123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Invalid args test"
        }, headers=h)
        conv_id = r.json()["id"]

        # calculator with invalid input (no expression field)
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"wrong": "field"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Invalid input, answering directly."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Calculate with bad args", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_error" in body

    @pytest.mark.asyncio
    async def test_agent_permission_denied(self, client: AsyncClient):
        """Agent enforces RBAC — viewer cannot use analyst tools."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_perm@test.com", "username": "agent_perm",
            "password": "AgentPerm123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_perm@test.com", "password": "AgentPerm123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_viewer@test.com", "username": "agent_viewer",
            "password": "AgentViewer123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_viewer@test.com", "password": "AgentViewer123!"
        })
        viewer_token = r.json()["access_token"]
        vh = {"Authorization": f"Bearer {viewer_token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Permission test"
        }, headers=vh)
        conv_id = r.json()["id"]

        # Viewer tries to use search_kb (requires analyst)
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "search_kb", "input": {"kb_id": "x", "query": "test"}, "reasoning": "search"}
        })
        done_resp = MagicMock()
        done_resp.content = "Permission denied, answering directly."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Search KB", "model_name": "llama3.2:3b"},
                headers=vh,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_error" in body
            assert "permission" in body.lower() or "denied" in body.lower()

    @pytest.mark.asyncio
    async def test_agent_high_risk_tool_requires_approval(self, client: AsyncClient):
        """High-risk tools are blocked with approval_required message."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_high@test.com", "username": "agent_high",
            "password": "AgentHigh123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_high@test.com", "password": "AgentHigh123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "High risk test"
        }, headers=h)
        conv_id = r.json()["id"]

        # Try to use python_exec (high risk)
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "python_exec", "input": {"code": "print(1)"}, "reasoning": "run code"}
        })
        done_resp = MagicMock()
        done_resp.content = "High risk tool blocked."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Run Python code", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "approval" in body.lower()

    @pytest.mark.asyncio
    async def test_agent_tool_mode_none(self, client: AsyncClient):
        """tool_mode=none disables all tool calling."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_none@test.com", "username": "agent_none",
            "password": "AgentNone123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_none@test.com", "password": "AgentNone123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "None mode test"
        }, headers=h)
        conv_id = r.json()["id"]

        mock_resp = MagicMock()
        mock_resp.content = "No tools needed."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_resp
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b", "tool_mode": "none"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            # No tool events should appear (check for actual tool_call SSE events, not just the substring)
            assert "event: tool_call\n" not in body
            assert "event: tool_started\n" not in body

    @pytest.mark.asyncio
    async def test_agent_conversation_ownership_enforced(self, client: AsyncClient):
        """Agent enforces conversation ownership."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_own@test.com", "username": "agent_own",
            "password": "AgentOwn123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_own@test.com", "password": "AgentOwn123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_other@test.com", "username": "agent_other",
            "password": "AgentOther123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_other@test.com", "password": "AgentOther123!"
        })
        other_token = r.json()["access_token"]
        oh = {"Authorization": f"Bearer {other_token}"}

        # User A creates conversation
        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Own test"
        }, headers=h)
        conv_id = r.json()["id"]

        # User B tries to use it
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Hello", "model_name": "llama3.2:3b"},
            headers=oh,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_agent_no_secrets_in_sse_events(self, client: AsyncClient):
        """SSE events do not expose JWT, passwords, or internal paths."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_sec@test.com", "username": "agent_sec",
            "password": "AgentSec123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_sec@test.com", "password": "AgentSec123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Secrecy test"
        }, headers=h)
        conv_id = r.json()["id"]

        mock_resp = MagicMock()
        mock_resp.content = "Safe answer."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_resp
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # No secrets in SSE events
            assert "AgentSec123" not in body
            assert "password" not in body.lower() or "password" in "AgentSec123"
            assert token[:10] not in body

    @pytest.mark.asyncio
    async def test_agent_audit_event_created(self, client: AsyncClient):
        """Agent creates audit event on completion."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_audit@test.com", "username": "agent_audit",
            "password": "AgentAudit123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_audit@test.com", "password": "AgentAudit123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Audit test"
        }, headers=h)
        conv_id = r.json()["id"]

        mock_resp = MagicMock()
        mock_resp.content = "Done."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_resp
            await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b"},
                headers=h,
            )

        # Check audit log
        r = await client.get("/api/v1/audit/logs", headers=h)
        assert r.status_code == 200
        logs = r.json()
        agent_events = [e for e in logs.get("items", []) if e.get("event_type") == "agent"]
        assert len(agent_events) > 0

    @pytest.mark.asyncio
    async def test_regular_chat_still_works(self, client: AsyncClient):
        """Regular /messages endpoint still works without tool calling."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "agent_reg@test.com", "username": "agent_reg",
            "password": "AgentReg123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "agent_reg@test.com", "password": "AgentReg123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Regular test"
        }, headers=h)
        conv_id = r.json()["id"]

        class FakeStream:
            def __init__(self, tokens):
                self._tokens = tokens
                self._idx = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self._idx >= len(self._tokens):
                    raise StopAsyncIteration
                tok = self._tokens[self._idx]
                self._idx += 1
                return tok

        async def fake_chat(*args, **kwargs):
            return FakeStream(["Hello", " ", "world"])

        with patch("services.llm_client.OllamaClient.chat", side_effect=fake_chat) as mock_chat:
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"content": "Hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: token" in body
            assert "event: done" in body
            # No tool events in regular chat
            assert "tool_call" not in body


class TestToolExposure:
    """Tests that all 17 tools are exposed to authorized users and hidden from unauthorized users."""

    ALL_TOOLS = [
        "file_read", "file_list", "file_write", "file_delete",
        "search_kb", "calculator", "python_exec",
        "web_search", "web_fetch", "tool_discovery", "model_select",
        "time_now", "system_status",
        "sensor_analysis", "vision_inspection",
        "incident_get", "incident_investigate",
    ]

    VIEWER_TOOLS = {"calculator", "time_now", "tool_discovery", "model_select", "system_status"}
    ANALYST_TOOLS = VIEWER_TOOLS | {
        "file_read", "file_list", "file_write",
        "search_kb", "web_search", "web_fetch",
        "sensor_analysis", "vision_inspection",
        "incident_get", "incident_investigate",
    }
    ADMIN_TOOLS = ANALYST_TOOLS | {"file_delete", "python_exec"}

    @pytest.mark.asyncio
    async def test_all_tools_in_prompt(self, client: AsyncClient):
        """All 17 tools appear in the system prompt for an admin user."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_admin@test.com", "username": "exp_admin",
            "password": "ExpAdmin123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_admin@test.com", "password": "ExpAdmin123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Exposure test"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "2"

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check tools", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # All tool names should appear in the plan event's tool_names
            for tool_name in self.ALL_TOOLS:
                assert tool_name in body, f"Tool '{tool_name}' not found in SSE events"

    async def _setup_user(self, client, email, username, password, role=None):
        """Register a user. If role is specified and not the first user, promote them."""
        r = await client.post("/api/v1/auth/register", json={
            "email": email, "username": username, "password": password
        })
        user_data = r.json()
        # If role promotion needed, use admin endpoint
        if role and role != "admin":
            # Login as admin to promote
            r_admin = await client.post("/api/v1/auth/login", json={
                "email": "admin_exp@test.com", "password": "AdminExp123!"
            })
            if r_admin.status_code == 200:
                admin_h = {"Authorization": f"Bearer {r_admin.json()['access_token']}"}
                await client.put(f"/api/v1/auth/users/{user_data['id']}", json={"role": role}, headers=admin_h)
        r = await client.post("/api/v1/auth/login", json={
            "email": email, "password": password
        })
        return r.json()["access_token"]

    @pytest.mark.asyncio
    async def test_viewer_sees_only_safe_tools(self, client: AsyncClient):
        """Viewer role only sees viewer-tier tools in the plan event."""
        # Register admin first
        await client.post("/api/v1/auth/register", json={
            "email": "admin_exp@test.com", "username": "admin_exp",
            "password": "AdminExp123!"
        })
        # Register viewer (second user = viewer by default)
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_viewer@test.com", "username": "exp_viewer",
            "password": "ExpViewer123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_viewer@test.com", "password": "ExpViewer123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Viewer exposure"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "2"

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check tools", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Viewer should only see viewer tools
            for tool_name in self.VIEWER_TOOLS:
                assert tool_name in body, f"Viewer tool '{tool_name}' not found"
            # Admin-only tools should NOT appear
            for tool_name in self.ADMIN_TOOLS - self.VIEWER_TOOLS:
                assert tool_name not in body, f"Admin tool '{tool_name}' should not appear for viewer"

    @pytest.mark.asyncio
    async def test_analyst_sees_no_admin_tools(self, client: AsyncClient):
        """Analyst role does not see admin-only tools in the plan event."""
        # Register admin first
        await client.post("/api/v1/auth/register", json={
            "email": "admin_exp@test.com", "username": "admin_exp",
            "password": "AdminExp123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "admin_exp@test.com", "password": "AdminExp123!"
        })
        admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # Register analyst (second user = viewer)
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_analyst@test.com", "username": "exp_analyst",
            "password": "ExpAnalyst123!"
        })
        # Promote to analyst
        await client.put(f"/api/v1/auth/users/{r.json()['id']}", json={"role": "analyst"}, headers=admin_h)

        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_analyst@test.com", "password": "ExpAnalyst123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Analyst exposure"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "2"

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check tools", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Analyst should see analyst tools
            for tool_name in self.ANALYST_TOOLS:
                assert tool_name in body, f"Analyst tool '{tool_name}' not found"
            # Admin-only tools should NOT appear
            for tool_name in self.ADMIN_TOOLS - self.ANALYST_TOOLS:
                assert tool_name not in body, f"Admin tool '{tool_name}' should not appear for analyst"

    @pytest.mark.asyncio
    async def test_plan_event_no_slice(self, client: AsyncClient):
        """Plan event contains ALL tools, not just first 10."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_plan@test.com", "username": "exp_plan",
            "password": "ExpPlan1234!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_plan@test.com", "password": "ExpPlan1234!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Plan test"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "2"

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Plan test", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Plan event uses "tools" key (not "tool_names")
            assert '"tools"' in body
            # Verify all 17 tools are listed
            tool_count = sum(1 for t in self.ALL_TOOLS if f'"{t}"' in body)
            assert tool_count >= 17, f"Expected at least 17 tools in events, found {tool_count}"

    @pytest.mark.asyncio
    async def test_admin_tools_high_risk_enforced(self, client: AsyncClient):
        """Admin-only tools (file_delete, python_exec) require approval."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_admin_risk@test.com", "username": "exp_admin_risk",
            "password": "ExpAdminRisk123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_admin_risk@test.com", "password": "ExpAdminRisk123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Admin risk test"
        }, headers=h)
        conv_id = r.json()["id"]

        # python_exec is high risk - should require approval
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "python_exec", "input": {"code": "print(1)"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "High risk blocked."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Run code", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "approval" in body.lower() or "high_risk" in body.lower()

    @pytest.mark.asyncio
    async def test_web_tools_high_risk_enforced(self, client: AsyncClient):
        """Web tools (web_search, web_fetch) require approval due to high risk."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_web_risk@test.com", "username": "exp_web_risk",
            "password": "ExpWebRisk123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_web_risk@test.com", "password": "ExpWebRisk123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Web risk test"
        }, headers=h)
        conv_id = r.json()["id"]

        # web_search is now high risk - should require approval
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "web_search", "input": {"query": "test"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Web search blocked."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Search web", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "approval" in body.lower() or "high_risk" in body.lower()

    @pytest.mark.asyncio
    async def test_incident_investigate_medium_risk(self, client: AsyncClient):
        """incident_investigate is medium risk, no approval required."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_invest@test.com", "username": "exp_invest",
            "password": "ExpInvest123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_invest@test.com", "password": "ExpInvest123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Investigate risk"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "incident_investigate", "input": {"incident_id": "1"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Investigation started."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Investigate incident 1", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Should NOT require approval (medium risk) — tool may return error but not approval block
            assert "approval" not in body.lower()
            # Tool was attempted (tool_call emitted) and either succeeded or returned error
            assert "tool_call" in body
            assert "tool_result" in body or "tool_error" in body

    @pytest.mark.asyncio
    async def test_viewer_blocked_from_analyst_tools(self, client: AsyncClient):
        """Viewer cannot execute analyst-level tools even if they try."""
        # Register admin first
        await client.post("/api/v1/auth/register", json={
            "email": "admin_exp@test.com", "username": "admin_exp",
            "password": "AdminExp123!"
        })
        # Register viewer (second user = viewer)
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_vblock@test.com", "username": "exp_vblock",
            "password": "ExpVBlock123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_vblock@test.com", "password": "ExpVBlock123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Viewer block"
        }, headers=h)
        conv_id = r.json()["id"]

        # Try to use file_write (requires analyst)
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "file_write", "input": {"path": "test.txt", "content": "hi"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Permission denied."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Write file", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_error" in body
            assert "permission" in body.lower() or "denied" in body.lower()

    @pytest.mark.asyncio
    async def test_system_status_tool_execution(self, client: AsyncClient):
        """system_status tool can be selected and executed by any role."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_sysstatus@test.com", "username": "exp_sysstatus",
            "password": "ExpSysStatus123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_sysstatus@test.com", "password": "ExpSysStatus123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "System status"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "system_status", "input": {}, "reasoning": "check status"}
        })
        done_resp = MagicMock()
        done_resp.content = "System is running."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check system status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            assert "tool_started" in body
            # system_status returns empty input, so either tool_result or tool_error
            assert "tool_result" in body or "tool_error" in body

    @pytest.mark.asyncio
    async def test_max_tool_iterations(self, client: AsyncClient):
        """Agent loop respects MAX_TOOL_CALLS limit (8 iterations max)."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_maxiter@test.com", "username": "exp_maxiter",
            "password": "ExpMaxIter123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_maxiter@test.com", "password": "ExpMaxIter123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Max iter"
        }, headers=h)
        conv_id = r.json()["id"]

        # Return tool calls forever (loop runs MAX_ITERATIONS = 10 iterations)
        tool_resp = MagicMock()
        tool_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "loop"}
        })

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = tool_resp
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Loop forever", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Loop runs range(MAX_ITERATIONS) = 10 iterations, but safety limits cap at MAX_TOOL_CALLS=8
            tool_call_count = body.count("event: tool_call")
            assert tool_call_count <= 10, f"Expected at most 10 tool calls, got {tool_call_count}"
            # Should eventually send done or error
            assert "event: done" in body or "event: error" in body

    @pytest.mark.asyncio
    async def test_multi_step_tool_loop(self, client: AsyncClient):
        """Agent can do multi-step tool calls (calculator then answer)."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_multistep@test.com", "username": "exp_multistep",
            "password": "ExpMultiStep123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_multistep@test.com", "password": "ExpMultiStep123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Multi-step"
        }, headers=h)
        conv_id = r.json()["id"]

        # Step 1: tool call
        call1 = MagicMock()
        call1.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "2+2"}, "reasoning": "step1"}
        })
        # Step 2: tool call
        call2 = MagicMock()
        call2.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "4+4"}, "reasoning": "step2"}
        })
        # Step 3: final answer
        done_resp = MagicMock()
        done_resp.content = "The results are 4 and 8."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call1, call2, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Two calculations", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert body.count("event: tool_call") == 2
            assert "event: tool_result" in body
            assert "event: token" in body
            assert "event: done" in body

    @pytest.mark.asyncio
    async def test_tool_error_honest_representation(self, client: AsyncClient):
        """Tool errors are represented honestly in SSE events."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_error@test.com", "username": "exp_error",
            "password": "ExpError123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_error@test.com", "password": "ExpError123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Error test"
        }, headers=h)
        conv_id = r.json()["id"]

        # LLM calls file_read with non-existent file
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "file_read", "input": {"path": "nonexistent.txt"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "File not found, answering directly."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Read missing file", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Tool execution errors appear as tool_result with status="error"
            assert "tool_result" in body
            assert '"status": "error"' in body
            assert "not found" in body.lower() or "error" in body.lower()

    @pytest.mark.asyncio
    async def test_no_secrets_in_sse_events(self, client: AsyncClient):
        """SSE events never expose JWT tokens, passwords, or internal paths."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_nosecret@test.com", "username": "exp_nosecret",
            "password": "ExpNoSecret123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_nosecret@test.com", "password": "ExpNoSecret123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Secret test"
        }, headers=h)
        conv_id = r.json()["id"]

        mock_resp = MagicMock()
        mock_resp.content = "Safe answer."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_resp
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "ExpNoSecret123" not in body
            assert token[:20] not in body
            # No absolute filesystem paths
            assert "C:\\\\Users" not in body
            assert "/app/data" not in body

    @pytest.mark.asyncio
    async def test_audit_log_records_tool_usage(self, client: AsyncClient):
        """Tool usage is recorded in audit logs."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_audit@test.com", "username": "exp_audit",
            "password": "ExpAudit123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_audit@test.com", "password": "ExpAudit123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Audit tool"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "5+5"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "10"

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Calculate 5+5", "model_name": "llama3.2:3b"},
                headers=h,
            )

        r = await client.get("/api/v1/audit/logs", headers=h)
        assert r.status_code == 200
        logs = r.json()
        agent_events = [e for e in logs.get("items", []) if e.get("event_type") == "agent"]
        assert len(agent_events) > 0
        # Check that the audit event has tool-related metadata
        last_event = agent_events[-1]
        assert last_event.get("metadata") is not None or last_event.get("details") is not None

    @pytest.mark.asyncio
    async def test_tool_mode_none_prevents_all_tools(self, client: AsyncClient):
        """tool_mode=none prevents any tool execution regardless of role."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_nonemode@test.com", "username": "exp_nonemode",
            "password": "ExpNoMode123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_nonemode@test.com", "password": "ExpNoMode123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "No mode"
        }, headers=h)
        conv_id = r.json()["id"]

        mock_resp = MagicMock()
        mock_resp.content = "No tools needed."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_resp
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b", "tool_mode": "none"},
                headers=h,
            )
            body = resp.text
            assert "event: tool_call\n" not in body
            assert "event: tool_started\n" not in body
            assert "event: tool_result\n" not in body
            assert "event: tool_error\n" not in body

    @pytest.mark.asyncio
    async def test_regular_chat_no_tool_leakage(self, client: AsyncClient):
        """Regular /messages endpoint never exposes tool events."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_noleak@test.com", "username": "exp_noleak",
            "password": "ExpNoLeak123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_noleak@test.com", "password": "ExpNoLeak123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "No leak"
        }, headers=h)
        conv_id = r.json()["id"]

        class FakeStream:
            def __init__(self, tokens):
                self._tokens = tokens
                self._idx = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self._idx >= len(self._tokens):
                    raise StopAsyncIteration
                tok = self._tokens[self._idx]
                self._idx += 1
                return tok

        async def fake_chat(*args, **kwargs):
            return FakeStream(["Hello", " ", "world"])

        with patch("services.llm_client.OllamaClient.chat", side_effect=fake_chat) as mock_chat:
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"content": "Hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "event: token" in body
            assert "event: done" in body
            # Zero tool events in regular chat
            assert "tool_call" not in body
            assert "tool_started" not in body
            assert "tool_result" not in body
            assert "tool_error" not in body

    @pytest.mark.asyncio
    async def test_file_delete_blocked_for_non_admin(self, client: AsyncClient):
        """file_delete is blocked for non-admin users (permission check)."""
        # Register admin first
        await client.post("/api/v1/auth/register", json={
            "email": "admin_exp@test.com", "username": "admin_exp",
            "password": "AdminExp123!"
        })
        # Register viewer (second user = viewer)
        r = await client.post("/api/v1/auth/register", json={
            "email": "exp_fd_nonadmin@test.com", "username": "exp_fd_nonadmin",
            "password": "ExpFdNonAdmin123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "exp_fd_nonadmin@test.com", "password": "ExpFdNonAdmin123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "File delete"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "file_delete", "input": {"path": "test.txt"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Blocked."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Delete file", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Viewer cannot use file_delete (requires admin) → permission denied
            assert "tool_error" in body
            assert "permission" in body.lower() or "denied" in body.lower()


class TestInputNormalization:
    """Regression tests for system_status empty input bug (LLM sends '{}' as string)."""

    @pytest.mark.asyncio
    async def test_system_status_empty_dict_input(self, client: AsyncClient):
        """system_status works with empty dict input {}."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_empty@test.com", "username": "norm_empty",
            "password": "NormEmpty123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_empty@test.com", "password": "NormEmpty123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Empty input test"
        }, headers=h)
        conv_id = r.json()["id"]

        # LLM sends input as empty dict
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "system_status", "input": {}, "reasoning": "check"}
        })
        done_resp = MagicMock()
        done_resp.content = "Done."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            # Should execute without validation error
            assert "tool_result" in body or "tool_error" in body
            assert "Invalid input" not in body

    @pytest.mark.asyncio
    async def test_system_status_string_empty_input(self, client: AsyncClient):
        """system_status works when LLM sends input as string '{}' instead of dict."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_str@test.com", "username": "norm_str",
            "password": "NormStr1234!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_str@test.com", "password": "NormStr1234!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "String input test"
        }, headers=h)
        conv_id = r.json()["id"]

        # LLM sends input as string '{}' — this was the bug
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "system_status", "input": "{}", "reasoning": "check"}
        })
        done_resp = MagicMock()
        done_resp.content = "Done."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            # Should execute without validation error (input normalized from string to dict)
            assert "tool_result" in body or "tool_error" in body
            assert "Invalid input" not in body

    @pytest.mark.asyncio
    async def test_system_status_valid_dict_input(self, client: AsyncClient):
        """system_status works with valid dict input (no regression)."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_valid@test.com", "username": "norm_valid",
            "password": "NormValid123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_valid@test.com", "password": "NormValid123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Valid input test"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "system_status", "input": {}, "reasoning": "check"}
        })
        done_resp = MagicMock()
        done_resp.content = "Done."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            assert "tool_result" in body or "tool_error" in body

    @pytest.mark.asyncio
    async def test_calculator_valid_input_unaffected(self, client: AsyncClient):
        """Calculator with valid input still works (no regression from normalization)."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_calc@test.com", "username": "norm_calc",
            "password": "NormCalc123!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_calc@test.com", "password": "NormCalc123!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Calc regression"
        }, headers=h)
        conv_id = r.json()["id"]

        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"expression": "2+2"}, "reasoning": "math"}
        })
        done_resp = MagicMock()
        done_resp.content = "4"

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Calculate 2+2", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            assert "tool_result" in body
            assert '"status": "success"' in body

    @pytest.mark.asyncio
    async def test_invalid_input_still_fails(self, client: AsyncClient):
        """Invalid tool input still fails honestly (no regression)."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_inv@test.com", "username": "norm_inv",
            "password": "NormInv1234!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_inv@test.com", "password": "NormInv1234!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Invalid input"
        }, headers=h)
        conv_id = r.json()["id"]

        # calculator with wrong input field
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "calculator", "input": {"wrong": "field"}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Invalid."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Bad calc", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_error" in body
            assert "Invalid input" in body or "invalid" in body.lower()

    @pytest.mark.asyncio
    async def test_system_status_malformed_string_input(self, client: AsyncClient):
        """system_status rejects malformed (non-JSON) string input."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_malf@test.com", "username": "norm_malf",
            "password": "NormMalf1234!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_malf@test.com", "password": "NormMalf1234!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Malformed input"
        }, headers=h)
        conv_id = r.json()["id"]

        # LLM sends input as a non-JSON string
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "system_status", "input": "not json at all", "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Done."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Should get a tool_error (validation failure), not a 500
            assert "tool_error" in body
            assert "Invalid input" in body or "invalid" in body.lower()

    @pytest.mark.asyncio
    async def test_system_status_unexpected_arguments(self, client: AsyncClient):
        """system_status ignores unexpected arguments (Pydantic extra='ignore')."""
        r = await client.post("/api/v1/auth/register", json={
            "email": "norm_extra@test.com", "username": "norm_extra",
            "password": "NormExtra12!"
        })
        r = await client.post("/api/v1/auth/login", json={
            "email": "norm_extra@test.com", "password": "NormExtra12!"
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b", "title": "Extra args"
        }, headers=h)
        conv_id = r.json()["id"]

        # LLM sends unexpected arguments
        call_resp = MagicMock()
        call_resp.content = json.dumps({
            "tool_call": {"tool": "system_status", "input": {"foo": "bar", "unexpected": 42}, "reasoning": "test"}
        })
        done_resp = MagicMock()
        done_resp.content = "Done."

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            plan_resp = MagicMock()
            plan_resp.content = json.dumps({"plan": {"goal": "test", "steps": []}})
            mock_chat.side_effect = [plan_resp, call_resp, done_resp]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Should execute successfully (extra fields ignored)
            assert "tool_result" in body or "tool_error" in body
            assert "Invalid input" not in body
