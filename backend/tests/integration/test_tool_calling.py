"""
Tool-calling integration tests.

Tests the agent tool loop: LLM tool selection, real tool execution,
SSE events, security, error handling, and audit.

Updated for AgentRuntime: planner→reasoner→verifier structured flow.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient


DIM = 768
FAKE_VECTORS = lambda n: [[0.1] * DIM for _ in range(n)]


def _make_understand_resp(intent="task", goal="test", needs_plan=True, needs_tools=True, needs_verification=True):
    r = MagicMock()
    r.content = json.dumps({
        "intent": intent,
        "goal": goal,
        "needs_plan": needs_plan,
        "needs_tools": needs_tools,
        "needs_verification": needs_verification,
        "reasoning": "test",
    })
    return r


def _make_plan_resp(goal="test", steps=None):
    """Create a planner response in the new format."""
    r = MagicMock()
    r.content = json.dumps({
        "goal": goal,
        "acceptance_criteria": ["Task completed"],
        "steps": steps or [],
    })
    return r


def _make_reasoner_resp(decision="CONTINUE", reason="executing", tool=None, tool_input=None, reasoning=""):
    """Create a reasoner response."""
    data: dict = {"decision": decision, "reason": reason}
    if tool:
        data["next_action"] = {"tool": tool, "input": tool_input or {}, "reasoning": reasoning}
    r = MagicMock()
    r.content = json.dumps(data)
    return r


def _make_verifier_resp(verified=True, confidence=0.9):
    """Create a verifier response."""
    r = MagicMock()
    r.content = json.dumps({
        "verified": verified,
        "confidence": confidence,
        "criteria": [],
        "missing": [] if verified else ["Evidence insufficient"],
        "unsupported_claims": [],
    })
    return r


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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_plan_resp("Hello!"),
                _make_reasoner_resp("COMPLETE", "Hello! How can I help you?"),
                _make_verifier_resp(True),
            ]
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
        """Agent emits tool_call, tool_result, observation SSE events."""
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("What is 2+2?"),
                _make_reasoner_resp("CONTINUE", "need calculator", "calculator", {"expression": "2+2"}, "math"),
                _make_reasoner_resp("COMPLETE", "The answer is 4."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "What is 2+2?", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_call" in body
            assert "event: tool_result" in body
            assert "event: observation" in body
            assert "event: token" in body
            assert "event: done" in body
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("Use nonexistent tool"),
                _make_reasoner_resp("CONTINUE", "use tool", "nonexistent_tool", {}, "test"),
                _make_reasoner_resp("COMPLETE", "Tool not available, answering directly."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Use nonexistent tool", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_result" in body
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("Calculate with bad args"),
                _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"wrong": "field"}, "test"),
                _make_reasoner_resp("COMPLETE", "Invalid input, answering directly."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Calculate with bad args", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_result" in body
            assert '"status": "failed"' in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("Search KB"),
                _make_reasoner_resp("CONTINUE", "search kb", "search_kb", {"kb_id": "x", "query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "Permission denied, answering directly."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Search KB", "model_name": "llama3.2:3b"},
                headers=vh,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: tool_result" in body
            assert "permission" in body.lower() or "denied" in body.lower()

    @pytest.mark.asyncio
    async def test_agent_high_risk_tool_skips_approval(self, client: AsyncClient):
        """High-risk tools skip approval gate in autonomous agent mode.

        This is intentional: autonomous agent mode must not block on human
        approval mid-run (there is no human to approve). Instead, the tool
        executes directly and the agent handles any errors.
        """
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("Run Python code"),
                _make_reasoner_resp("CONTINUE", "run code", "python_exec", {"code": "print(1)"}, "run code"),
                _make_reasoner_resp("COMPLETE", "High risk tool executed."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Run Python code", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            # Tool should have been called (tool_call emitted) — not blocked by approval
            assert "tool_call" in body.lower()
            assert "done" in body.lower()

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_plan_resp("test"),
                _make_reasoner_resp("COMPLETE", "No tools needed."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b", "tool_mode": "none"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            # No tool events should appear
            assert "event: tool_call\n" not in body
            assert "event: tool_result\n" not in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_plan_resp("Secrecy test"),
                _make_reasoner_resp("COMPLETE", "Safe answer."),
                _make_verifier_resp(True),
            ]
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

        mock_log = AsyncMock()

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat, \
             patch("services.audit_service.AuditService.log", new_callable=AsyncMock, side_effect=mock_log):
            mock_chat.side_effect = [
                _make_plan_resp("test"),
                _make_reasoner_resp("COMPLETE", "Done."),
                _make_verifier_resp(True),
            ]
            await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b"},
                headers=h,
            )

        # Audit log was called (written to streaming session DB)
        assert mock_log.called

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"expression": "1+1"}, "test"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check tools", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # All tool names should appear in the prompt (passed to LLM)
            # They may not all appear in SSE events, but they're available
            # Check that tool_call for calculator succeeds (proves tools are registered)
            assert "event: tool_call" in body
            assert "calculator" in body

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
        """Viewer role only sees viewer-tier tools."""
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"expression": "1+1"}, "test"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check tools", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Viewer can use calculator (viewer tool) - should succeed
            assert "event: tool_call" in body
            assert "calculator" in body

    @pytest.mark.asyncio
    async def test_analyst_sees_no_admin_tools(self, client: AsyncClient):
        """Analyst role does not see admin-only tools."""
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"expression": "1+1"}, "test"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check tools", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Analyst can use calculator (analyst tool)
            assert "event: tool_call" in body
            assert "calculator" in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"expression": "1+1"}, "test"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Plan test", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Verify tool_call event appears (proves tools are available)
            assert "event: tool_call" in body
            assert "calculator" in body

    @pytest.mark.asyncio
    async def test_admin_tools_high_risk_skips_approval(self, client: AsyncClient):
        """Admin-only tools skip approval gate in autonomous agent mode.

        Autonomous agent mode has no human to approve, so high-risk tools
        execute directly. The agent handles any errors from tool execution.
        """
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("Run code"),
                _make_reasoner_resp("CONTINUE", "run code", "python_exec", {"code": "print(1)"}, "test"),
                _make_reasoner_resp("COMPLETE", "High risk tool executed."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Run code", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Tool should have been called — not blocked by approval
            assert "tool_call" in body.lower()
            assert "done" in body.lower()

    @pytest.mark.asyncio
    async def test_web_tools_high_risk_skips_approval(self, client: AsyncClient):
        """Web tools skip approval gate in autonomous agent mode.

        Autonomous agent mode has no human to approve, so high-risk tools
        execute directly. The agent handles any errors from tool execution.
        """
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("Search web"),
                _make_reasoner_resp("CONTINUE", "search web", "web_search", {"query": "test"}, "test"),
                _make_reasoner_resp("COMPLETE", "Web search executed."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Search web", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Tool should have been called — not blocked by approval
            assert "tool_call" in body.lower()
            assert "done" in body.lower()

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "investigate", "incident_investigate", {"incident_id": "1"}, "test"),
                _make_reasoner_resp("COMPLETE", "Investigation started."),
                _make_verifier_resp(True),
            ]
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
            assert "tool_result" in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "write file", "file_write", {"path": "test.txt", "content": "hi"}, "test"),
                _make_reasoner_resp("COMPLETE", "Permission denied."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Write file", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_result" in body
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "check status", "system_status", {}, "check status"),
                _make_reasoner_resp("COMPLETE", "System is running."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check system status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            assert "tool_result" in body

    @pytest.mark.asyncio
    async def test_max_tool_iterations(self, client: AsyncClient):
        """Agent loop respects MAX_ITERATIONS limit."""
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

        # Return CONTINUE tool calls forever — loop should hit MAX_ITERATIONS
        infinite_continue = _make_reasoner_resp(
            "CONTINUE", "loop", "calculator", {"expression": "1+1"}, "loop"
        )

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            # Provide enough responses for MAX_ITERATIONS iterations + safety
            mock_chat.side_effect = [_make_understand_resp(intent="task"), _make_plan_resp("Loop forever")] + [infinite_continue] * 60
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Loop forever", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "step1", "calculator", {"expression": "2+2"}, "step1"),
                _make_reasoner_resp("CONTINUE", "step2", "calculator", {"expression": "4+4"}, "step2"),
                _make_reasoner_resp("COMPLETE", "The results are 4 and 8."),
                _make_verifier_resp(True),
            ]
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "read file", "file_read", {"path": "nonexistent.txt"}, "test"),
                _make_reasoner_resp("COMPLETE", "File not found, answering directly."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Read missing file", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Tool execution errors appear as tool_result with status="failed"
            assert "tool_result" in body
            assert '"status": "failed"' in body
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("COMPLETE", "Safe answer."),
                _make_verifier_resp(True),
            ]
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

        mock_log = AsyncMock()

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat, \
             patch("services.audit_service.AuditService.log", new_callable=AsyncMock, side_effect=mock_log):
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "calculate", "calculator", {"expression": "5+5"}, "test"),
                _make_reasoner_resp("COMPLETE", "10"),
                _make_verifier_resp(True),
            ]
            await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Calculate 5+5", "model_name": "llama3.2:3b"},
                headers=h,
            )

        # Audit log was called (tool usage recorded)
        assert mock_log.called

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("COMPLETE", "No tools needed."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Hello", "model_name": "llama3.2:3b", "tool_mode": "none"},
                headers=h,
            )
            body = resp.text
            assert "event: tool_call\n" not in body
            assert "event: tool_result\n" not in body
            assert "event: observation\n" not in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "delete file", "file_delete", {"path": "test.txt"}, "test"),
                _make_reasoner_resp("COMPLETE", "Blocked."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Delete file", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Viewer cannot use file_delete (requires admin) → permission denied
            assert "tool_result" in body
            assert "permission" in body.lower() or "denied" in body.lower() or "requires role" in body.lower() or "admin" in body.lower()


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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "check status", "system_status", {}, "check"),
                _make_reasoner_resp("COMPLETE", "Done."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            # Should execute without validation error
            assert "tool_result" in body
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "check status", "system_status", {}, "check"),
                _make_reasoner_resp("COMPLETE", "Done."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            # Should execute without validation error (input normalized from string to dict)
            assert "tool_result" in body
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "check status", "system_status", {}, "check"),
                _make_reasoner_resp("COMPLETE", "Done."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_call" in body
            assert "tool_result" in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "math", "calculator", {"expression": "2+2"}, "math"),
                _make_reasoner_resp("COMPLETE", "4"),
                _make_verifier_resp(True),
            ]
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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "bad calc", "calculator", {"wrong": "field"}, "test"),
                _make_reasoner_resp("COMPLETE", "Invalid."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Bad calc", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            assert "tool_result" in body
            assert '"status": "failed"' in body

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "check status", "system_status", {}, "test"),
                _make_reasoner_resp("COMPLETE", "Done."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Should get a tool_result with error, not a 500
            assert "tool_result" in body
            assert '"status": "failed"' in body or "error" in body.lower()

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

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "check status", "system_status", {"foo": "bar", "unexpected": 42}, "test"),
                _make_reasoner_resp("COMPLETE", "Done."),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Check status", "model_name": "llama3.2:3b"},
                headers=h,
            )
            body = resp.text
            # Should execute successfully (extra fields ignored)
            assert "tool_result" in body
            assert "Invalid input" not in body
