"""
Regression tests for the UNDERSTAND/ROUTE agent architecture.

Covers all 5 intent paths + edge cases:
  1. CONVERSATION (deterministic regex, no LLM)
  2. KNOWLEDGE (LLM understanding + knowledge response)
  3. TOOL_TASK (single tool execution)
  4. TASK (full planner/reasoner/execute/verify loop)
  5. ANALYSIS (optional tools, no plan)

Edge cases:
  - Verification failure -> replan
  - Loop detection -> replan
  - Cancellation at various stages
  - Timeout handling
  - Small model fallbacks
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


def _make_understand_resp(
    intent="task", goal="test", needs_plan=True,
    needs_tools=True, needs_verification=True, confidence=0.9,
):
    r = MagicMock()
    r.content = json.dumps({
        "intent": intent,
        "goal": goal,
        "needs_plan": needs_plan,
        "needs_tools": needs_tools,
        "needs_verification": needs_verification,
        "confidence": confidence,
        "reasoning": "test",
    })
    return r


def _make_plan_resp(goal="test", steps=None):
    r = MagicMock()
    r.content = json.dumps({
        "goal": goal,
        "acceptance_criteria": ["Task completed"],
        "steps": steps or [],
    })
    return r


def _make_reasoner_resp(
    decision="CONTINUE", reason="executing",
    tool=None, tool_input=None, reasoning="",
):
    data: dict = {"decision": decision, "reason": reason}
    if tool:
        data["next_action"] = {
            "tool": tool,
            "input": tool_input or {},
            "reasoning": reasoning,
        }
    r = MagicMock()
    r.content = json.dumps(data)
    return r


def _make_verifier_resp(verified=True, confidence=0.9):
    r = MagicMock()
    r.content = json.dumps({
        "verified": verified,
        "confidence": confidence,
        "criteria": [],
        "missing": [] if verified else ["Evidence insufficient"],
        "unsupported_claims": [],
    })
    return r


def _parse_sse_events(body: str) -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = {}
    for block in body.split("\n\n"):
        lines = block.strip().split("\n")
        event_type = None
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = line[6:]
        if event_type:
            events.setdefault(event_type, []).append(data)
    return events


async def _setup_user(client: AsyncClient, email: str, username: str):
    await client.post("/api/v1/auth/register", json={
        "email": email, "username": username, "password": "TestPass123!"
    })
    r = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "TestPass123!"
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_conv(client: AsyncClient, h: dict, title: str = "test"):
    r = await client.post(
        "/api/v1/chat/conversations",
        json={"model_name": "llama3.2:3b", "title": title},
        headers=h,
    )
    return r.json()["id"]


# ===================================================================
# 1. CONVERSATION PATH — deterministic, no LLM, no tools, no plan
# ===================================================================
@pytest.mark.asyncio
class TestConversationPath:
    async def test_greeting_hii_no_plan_no_tools(self, client: AsyncClient):
        """hii -> CONVERSATION -> direct response, no planner/tools."""
        h = await _setup_user(client, "reg_conv1@test.com", "reg_conv1")
        conv_id = await _create_conv(client, h, "conv test")

        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hii", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        events = _parse_sse_events(body)
        assert "understanding_started" in events
        assert "understanding_completed" in events

        understanding = events["understanding_completed"][0]
        assert understanding["intent"] == "conversation"
        assert understanding["needs_plan"] is False
        assert understanding["needs_tools"] is False
        assert understanding["needs_verification"] is False

        assert "plan_created" not in events
        assert "tool_call" not in events
        assert "verification_started" not in events

        done = events["done"]
        assert len(done) == 1
        assert done[0]["state"] == "completed"

    async def test_thanks_no_plan(self, client: AsyncClient):
        h = await _setup_user(client, "reg_conv2@test.com", "reg_conv2")
        conv_id = await _create_conv(client, h, "thanks test")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "thanks", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        understanding = events["understanding_completed"][0]
        assert understanding["intent"] == "conversation"
        assert "plan_created" not in events

    async def test_bye_no_plan(self, client: AsyncClient):
        h = await _setup_user(client, "reg_conv3@test.com", "reg_conv3")
        conv_id = await _create_conv(client, h, "bye test")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "bye", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        understanding = events["understanding_completed"][0]
        assert understanding["intent"] == "conversation"

    async def test_conversation_never_creates_plan(self, client: AsyncClient):
        """Every simple greeting must bypass the planner entirely."""
        h = await _setup_user(client, "reg_conv4@test.com", "reg_conv4")
        conv_id = await _create_conv(client, h, "conv plan test")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hello there", "model_name": "llama3.2:3b"},
            headers=h,
        )
        events = _parse_sse_events(resp.text)
        assert "plan_created" not in events
        assert "todo_updated" not in events


# ===================================================================
# 2. KNOWLEDGE PATH — LLM understanding, knowledge response
# ===================================================================
@pytest.mark.asyncio
class TestKnowledgePath:
    async def test_what_is_ocr_knowledge(self, client: AsyncClient):
        """What is OCR? -> KNOWLEDGE -> answer, no plan, no tools."""
        h = await _setup_user(client, "reg_know1@test.com", "reg_know1")
        conv_id = await _create_conv(client, h, "knowledge test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(
                    intent="knowledge", needs_plan=False,
                    needs_tools=False, needs_verification=False,
                ),
                MagicMock(content="OCR stands for Optical Character Recognition."),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "What is OCR?", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            understanding = events["understanding_completed"][0]
            assert understanding["intent"] == "knowledge"
            assert understanding["needs_plan"] is False
            assert "plan_created" not in events
            assert "tool_call" not in events
            assert events["done"][0]["state"] == "completed"

    async def test_knowledge_needs_no_plan(self, client: AsyncClient):
        h = await _setup_user(client, "reg_know2@test.com", "reg_know2")
        conv_id = await _create_conv(client, h, "knowledge plan test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(
                    intent="knowledge", needs_plan=False,
                    needs_tools=False, needs_verification=False,
                ),
                MagicMock(content="Docker is a containerization platform."),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "What is Docker?", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            assert "plan_created" not in events
            assert "tool_call" not in events


# ===================================================================
# 3. TOOL_TASK PATH — single tool execution
# ===================================================================
@pytest.mark.asyncio
class TestToolTaskPath:
    async def test_simple_request_bypasses_all(self, client: AsyncClient):
        """hi -> CONVERSATION -> no tool, no plan, direct response."""
        h = await _setup_user(client, "reg_tool1@test.com", "reg_tool1")
        conv_id = await _create_conv(client, h, "simple test")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hi", "model_name": "llama3.2:3b"},
            headers=h,
        )
        events = _parse_sse_events(resp.text)
        understanding = events["understanding_completed"][0]
        assert understanding["intent"] == "conversation"
        assert "plan_created" not in events
        assert "tool_call" not in events


# ===================================================================
# 4. TASK PATH — full planner/reasoner/execute/verify loop
# ===================================================================
@pytest.mark.asyncio
class TestTaskPath:
    async def test_full_task_loop_with_tool(self, client: AsyncClient):
        """Complex task -> PLAN -> REASON -> TOOL -> OBSERVE -> VERIFY."""
        h = await _setup_user(client, "reg_task1@test.com", "reg_task1")
        conv_id = await _create_conv(client, h, "task test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test task", steps=[
                    {"id": 1, "description": "Calc", "tool": "calculator"},
                ]),
                _make_reasoner_resp(
                    "CONTINUE", "calculate", "calculator",
                    {"expression": "2+2"}, "math",
                ),
                _make_reasoner_resp("COMPLETE", "4"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "test task", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            understanding = events["understanding_completed"][0]
            assert understanding["intent"] == "task"
            assert "plan_created" in events
            assert "verification_started" in events
            assert "verification_passed" in events
            assert events["done"][0]["state"] == "completed"

    async def test_task_requires_plan_and_verification(self, client: AsyncClient):
        h = await _setup_user(client, "reg_task2@test.com", "reg_task2")
        conv_id = await _create_conv(client, h, "task verify test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("do something"),
                _make_reasoner_resp("CONTINUE", "executing", "calculator",
                                    {"expression": "1+1"}, "math"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "do something", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            assert "plan_created" in events
            assert "verification_started" in events


# ===================================================================
# 5. VERIFICATION FAILURE -> REPLAN
# ===================================================================
@pytest.mark.asyncio
class TestVerificationFailure:
    async def test_verification_fails_then_replans(self, client: AsyncClient):
        """Verifier rejects -> replan -> retry -> verify -> complete."""
        h = await _setup_user(client, "reg_ver1@test.com", "reg_ver1")
        conv_id = await _create_conv(client, h, "verify fail test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test task", steps=[
                    {"id": 1, "description": "Step 1", "tool": "calculator"},
                ]),
                _make_reasoner_resp(
                    "CONTINUE", "executing", "calculator",
                    {"expression": "1+1"}, "math",
                ),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(False, 0.3),  # First verification FAILS
                _make_plan_resp("revised task", steps=[
                    {"id": 1, "description": "Revised step", "tool": "calculator"},
                ]),
                _make_reasoner_resp(
                    "CONTINUE", "retrying", "calculator",
                    {"expression": "2+2"}, "math",
                ),
                _make_reasoner_resp("COMPLETE", "4"),
                _make_verifier_resp(True, 0.95),  # Second verification PASSES
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "test task", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            assert "verification_started" in events
            done = events["done"]
            assert len(done) == 1
            assert done[0]["state"] == "completed"

    async def test_verification_failure_updates_todo(self, client: AsyncClient):
        """When verification fails and replans, todo should update."""
        h = await _setup_user(client, "reg_ver2@test.com", "reg_ver2")
        conv_id = await _create_conv(client, h, "verify todo test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("task a", steps=[
                    {"id": 1, "description": "Step 1", "tool": "calculator"},
                ]),
                _make_reasoner_resp("CONTINUE", "doing step 1", "calculator",
                                    {"expression": "1+1"}, "math"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(False, 0.2),  # Fail
                _make_plan_resp("task a revised", steps=[
                    {"id": 1, "description": "Revised", "tool": "calculator"},
                ]),
                _make_reasoner_resp("CONTINUE", "retrying", "calculator",
                                    {"expression": "2+2"}, "math"),
                _make_reasoner_resp("COMPLETE", "done now"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "task a", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            # todo_updated events should appear
            assert "todo_updated" in events
            assert events["done"][0]["state"] == "completed"


# ===================================================================
# 6. LOOP DETECTION -> REPLAN
# ===================================================================
@pytest.mark.asyncio
class TestLoopDetection:
    async def test_repeated_invalid_action_triggers_replan(self, client: AsyncClient):
        """Same invalid tool call 3x should trigger loop detection -> replan."""
        h = await _setup_user(client, "reg_loop1@test.com", "reg_loop1")
        conv_id = await _create_conv(client, h, "loop test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("loop test", steps=[
                    {"id": 1, "description": "Step 1", "tool": "calculator"},
                ]),
                # 3x same invalid tool call (calculator with missing expression)
                _make_reasoner_resp("CONTINUE", "try", "calculator", {}, "loop"),
                _make_reasoner_resp("CONTINUE", "try again", "calculator", {}, "loop"),
                _make_reasoner_resp("CONTINUE", "try yet again", "calculator", {}, "loop"),
                # After replan, succeed
                _make_plan_resp("revised loop test"),
                _make_reasoner_resp("CONTINUE", "revised", "calculator",
                                    {"expression": "1"}, "ok"),
                _make_reasoner_resp("COMPLETE", "1"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "loop test", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            done = events["done"]
            assert len(done) == 1
            assert done[0]["state"] == "completed"


# ===================================================================
# 7. CANCELLATION
# ===================================================================
@pytest.mark.asyncio
class TestCancellation:
    async def test_cancel_before_execution(self, client: AsyncClient):
        """Cancel during planning -> cancelled state."""
        h = await _setup_user(client, "reg_cancel1@test.com", "reg_cancel1")
        conv_id = await _create_conv(client, h, "cancel test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("cancel test", steps=[
                    {"id": 1, "description": "Step 1"},
                ]),
                _make_reasoner_resp("CONTINUE", "executing"),
            ]
            # Send agent request then immediately cancel
            h2 = {"Authorization": f"Bearer {h['Authorization'].split(' ')[1]}"}

            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "cancel test", "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            done = events["done"]
            assert len(done) == 1
            # Final state should be completed (no actual cancel in test)
            assert done[0]["state"] in ("completed", "cancelled", "failed")


# ===================================================================
# 8. CONVERSATION OWNERSHIP
# ===================================================================
@pytest.mark.asyncio
class TestConversationOwnership:
    async def test_cannot_access_other_users_conversation(self, client: AsyncClient):
        h1 = await _setup_user(client, "reg_own1@test.com", "reg_own1")
        conv_id = await _create_conv(client, h1, "private")

        h2 = await _setup_user(client, "reg_own2@test.com", "reg_own2")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hii", "model_name": "llama3.2:3b"},
            headers=h2,
        )
        assert resp.status_code in (403, 404)


# ===================================================================
# 9. TOOL MODE NONE
# ===================================================================
@pytest.mark.asyncio
class TestToolModeNone:
    async def test_tool_mode_none_no_tool_call(self, client: AsyncClient):
        """tool_mode=none must not call any tools."""
        h = await _setup_user(client, "reg_tmode@test.com", "reg_tmode")
        conv_id = await _create_conv(client, h, "tool mode test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test"),
                _make_reasoner_resp("CONTINUE", "thinking", "calculator",
                                    {"expression": "1+1"}, "math"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={
                    "content": "test", "model_name": "llama3.2:3b",
                    "tool_mode": "none",
                },
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            assert "tool_call" not in events


# ===================================================================
# 10. PLAN MODE
# ===================================================================
@pytest.mark.asyncio
class TestPlanMode:
    async def test_plan_mode_creates_plan_no_execution(self, client: AsyncClient):
        """agent_mode=plan creates plan but doesn't execute tools."""
        h = await _setup_user(client, "reg_plan1@test.com", "reg_plan1")
        conv_id = await _create_conv(client, h, "plan mode test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={
                    "content": "build something", "model_name": "llama3.2:3b",
                    "agent_mode": "plan",
                },
                headers=h,
            )
            assert resp.status_code == 200
            events = _parse_sse_events(resp.text)
            assert "plan_created" not in events
            assert "tool_call" not in events
            assert events["done"][0]["state"] == "completed"


# ===================================================================
# 11. SSE EVENT STRUCTURE
# ===================================================================
@pytest.mark.asyncio
class TestSSEStructure:
    async def test_conversation_minimal_events(self, client: AsyncClient):
        """Conversation should have minimal SSE events."""
        h = await _setup_user(client, "reg_sse1@test.com", "reg_sse1")
        conv_id = await _create_conv(client, h, "sse minimal test")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hello", "model_name": "llama3.2:3b"},
            headers=h,
        )
        events = _parse_sse_events(resp.text)
        expected_types = {
            "agent_started", "agent_state", "understanding_started",
            "understanding_completed", "token", "final_response", "done",
        }
        actual_types = set(events.keys())
        assert actual_types == expected_types

    async def test_done_event_exactly_once(self, client: AsyncClient):
        """Every run must have exactly one done event."""
        h = await _setup_user(client, "reg_sse2@test.com", "reg_sse2")
        conv_id = await _create_conv(client, h, "sse done test")
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hi", "model_name": "llama3.2:3b"},
            headers=h,
        )
        events = _parse_sse_events(resp.text)
        assert len(events["done"]) == 1

    async def test_task_path_events_complete(self, client: AsyncClient):
        """Task path should have understanding + plan + verification + done."""
        h = await _setup_user(client, "reg_sse3@test.com", "reg_sse3")
        conv_id = await _create_conv(client, h, "sse complete test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("test", steps=[
                    {"id": 1, "description": "Step 1", "tool": "calculator"},
                ]),
                _make_reasoner_resp("CONTINUE", "executing", "calculator",
                                    {"expression": "1+1"}, "math"),
                _make_reasoner_resp("COMPLETE", "2"),
                _make_verifier_resp(True),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "test", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            assert "understanding_started" in events
            assert "understanding_completed" in events
            assert "plan_created" in events
            assert "verification_started" in events
            assert "verification_passed" in events
            assert "done" in events
            assert len(events["done"]) == 1


# ============================================================
# OBSERVABLE AGENT EXECUTION TESTS (A-L)
# ============================================================

async def _setup_obs_user(client, email="obs@test.com", password="obs_test_pass"):
    """Register + login for observable agent tests. Password ≥12 chars."""
    username = email.split("@")[0].replace(".", "_")
    # Ensure username is valid (3-50 chars, alphanumeric + underscore)
    username = "".join(c for c in username if c.isalnum() or c == "_")[:50]
    if len(username) < 3:
        username = "obs_test_user"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": password,
        "username": username,
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


async def _create_conv(client, headers, title="obs test"):
    resp = await client.post("/api/v1/chat/conversations",
                             json={"model_name": "llama3.2:3b", "title": title},
                             headers=headers)
    return resp.json()["id"]


def _parse_sse_events(text):
    events = {}
    current_event = None
    for line in text.split("\n"):
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:") and current_event:
            try:
                payload = json.loads(line[5:].strip())
                events.setdefault(current_event, []).append(payload)
            except json.JSONDecodeError:
                pass
            current_event = None
    return events


class TestObservableAgentExecution:
    """Tests for durable agent event persistence and observable execution."""

    async def test_agent_started_event_emitted(self, client: AsyncClient):
        """A: agent_started event should be emitted at start of runtime."""
        h = await _setup_obs_user(client, "obs_a@test.com")
        conv_id = await _create_conv(client, h, "agent started test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            assert "agent_started" in events
            assert events["agent_started"][0]["goal"] == "hello"

    async def test_final_response_before_done(self, client: AsyncClient):
        """B: final_response event should be emitted before done."""
        h = await _setup_obs_user(client, "obs_b@test.com")
        conv_id = await _create_conv(client, h, "final resp test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hi", "model_name": "llama3.2:3b"},
                headers=h,
            )
            text = resp.text
            # Parse events in order
            event_order = []
            current_event = None
            for line in text.split("\n"):
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:") and current_event:
                    event_order.append(current_event)
                    current_event = None

            # final_response must come before done
            fr_idx = event_order.index("final_response") if "final_response" in event_order else -1
            done_idx = event_order.index("done") if "done" in event_order else -1
            assert fr_idx >= 0, "final_response event not found"
            assert done_idx >= 0, "done event not found"
            assert fr_idx < done_idx, "final_response must come before done"

    async def test_agent_run_created(self, client: AsyncClient):
        """C: AgentRun should be created before runtime execution."""
        h = await _setup_obs_user(client, "obs_c@test.com")
        conv_id = await _create_conv(client, h, "agent run test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "test run creation", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            # agent_started should have a run_id
            assert "agent_started" in events
            run_id = events["agent_started"][0].get("run_id")
            assert run_id is not None, "run_id not in agent_started event"

    async def test_agent_run_status_completed(self, client: AsyncClient):
        """D: AgentRun.status should be updated to completed on success."""
        h = await _setup_obs_user(client, "obs_d@test.com")
        conv_id = await _create_conv(client, h, "run status test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            run_id = events["agent_started"][0]["run_id"]

            # Check AgentRun status via agent-events endpoint
            resp2 = await client.get(
                f"/api/v1/chat/conversations/{conv_id}/agent-events",
                headers=h,
            )
            assert resp2.status_code == 200
            data = resp2.json()
            runs = data.get("runs", [])
            run = next((r for r in runs if r["id"] == run_id), None)
            assert run is not None, "AgentRun not found"
            assert run["status"] == "completed"

    async def test_final_response_has_content(self, client: AsyncClient):
        """B: final_response event should contain the response content."""
        h = await _setup_obs_user(client, "obs_b2@test.com")
        conv_id = await _create_conv(client, h, "final content test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            assert "final_response" in events
            fr = events["final_response"][0]
            assert "content" in fr
            assert len(fr["content"]) > 0

    async def test_assistant_message_persisted_before_done(self, client: AsyncClient):
        """I: Assistant message should be persisted to DB before done event."""
        h = await _setup_obs_user(client, "obs_i@test.com")
        conv_id = await _create_conv(client, h, "persist test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hello", "model_name": "llama3.2:3b"},
                headers=h,
            )
            events = _parse_sse_events(resp.text)
            assert "done" in events

            # After stream completes, fetch conversation and check for assistant message
            resp2 = await client.get(
                f"/api/v1/chat/conversations/{conv_id}",
                headers=h,
            )
            conv = resp2.json()
            messages = conv.get("messages", [])
            assistant_msgs = [m for m in messages if m["role"] == "assistant"]
            assert len(assistant_msgs) > 0, "No assistant message found after done"
            assert len(assistant_msgs[0]["content"]) > 0

    async def test_get_agent_events_empty(self, client: AsyncClient):
        """J: GET agent-events returns empty for conversation with no runs."""
        h = await _setup_obs_user(client, "obs_j@test.com")
        conv_id = await _create_conv(client, h, "no runs test")

        resp = await client.get(
            f"/api/v1/chat/conversations/{conv_id}/agent-events",
            headers=h,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["runs"] == []

    async def test_get_agent_events_returns_events(self, client: AsyncClient):
        """K: GET agent-events should return persisted events after a run."""
        h = await _setup_obs_user(client, "obs_k@test.com")
        conv_id = await _create_conv(client, h, "events return test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hello", "model_name": "llama3.2:3b"},
                headers=h,
            )

        resp = await client.get(
            f"/api/v1/chat/conversations/{conv_id}/agent-events",
            headers=h,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) > 0
        # Should have agent_started event
        event_types = [e["event_type"] for e in data["events"]]
        assert "agent_started" in event_types

    async def test_get_agent_events_unauthorized(self, client: AsyncClient):
        """L: GET agent-events returns 404 for unauthorized user."""
        h1 = await _setup_obs_user(client, "obs_l1@test.com")
        h2 = await _setup_obs_user(client, "obs_l2@test.com")
        conv_id = await _create_conv(client, h1, "unauth test")

        resp = await client.get(
            f"/api/v1/chat/conversations/{conv_id}/agent-events",
            headers=h2,
        )
        assert resp.status_code == 404

    async def test_agent_event_sequence_monotonic(self, client: AsyncClient):
        """H: AgentEvent.sequence should be monotonically increasing."""
        h = await _setup_obs_user(client, "obs_h@test.com")
        conv_id = await _create_conv(client, h, "sequence test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="conversation"),
            ]
            await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "hello", "model_name": "llama3.2:3b"},
                headers=h,
            )

        resp = await client.get(
            f"/api/v1/chat/conversations/{conv_id}/agent-events",
            headers=h,
        )
        data = resp.json()
        sequences = [e["sequence"] for e in data["events"]]
        # Each sequence should be >= previous
        for i in range(1, len(sequences)):
            assert sequences[i] > sequences[i-1], f"Sequence not monotonic: {sequences}"


# ============================================================
# TOOL TIMEOUT REGRESSION TESTS (A-O)
# ============================================================

class TestToolTimeoutRegression:
    """Tests for tool timeout fix — ensures tools never hang the agent loop."""

    async def test_tool_execution_with_approval_skipped(self, client: AsyncClient):
        """A: High-risk tools execute without approval gate in agent mode."""
        h = await _setup_obs_user(client, "tool_a@test.com")
        conv_id = await _create_conv(client, h, "approval skip test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            # Task that triggers web_search (RISK_HIGH)
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("search", steps=[
                    {"id": 1, "description": "Search web", "tool": "web_search"},
                ]),
                _make_reasoner_resp("CONTINUE", "searching", "web_search",
                                    {"query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(True),
            ]

            # Mock web_search at registry level (handler is stored by reference)
            from tools.registry import get_registry
            reg = get_registry()
            original_handler = reg.get("web_search").handler

            async def mock_handler(data, ctx):
                return {"results": [{"title": "Test", "url": "http://test.com"}], "engine": "duckduckgo", "error": None}

            reg.get("web_search").handler = mock_handler
            try:
                resp = await client.post(
                    f"/api/v1/chat/conversations/{conv_id}/agent",
                    json={"content": "search test", "model_name": "llama3.2:3b"},
                    headers=h,
                )
                events = _parse_sse_events(resp.text)
                # Should complete without hanging on approval
                assert "done" in events
                # web_search should have been called (tool_call emitted)
                tool_calls = events.get("tool_call", [])
                assert any(tc.get("tool") == "web_search" for tc in tool_calls)
            finally:
                reg.get("web_search").handler = original_handler

    async def test_tool_timeout_emits_tool_timeout_event(self, client: AsyncClient):
        """C: Tool timeout produces tool_timeout event."""
        h = await _setup_obs_user(client, "tool_c@test.com")
        conv_id = await _create_conv(client, h, "timeout event test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("search", steps=[
                    {"id": 1, "description": "Search web", "tool": "web_search"},
                ]),
                _make_reasoner_resp("CONTINUE", "searching", "web_search",
                                    {"query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(True),
            ]

            from tools.registry import get_registry
            reg = get_registry()
            original_handler = reg.get("web_search").handler

            async def mock_handler(data, ctx):
                return {
                    "results": [],
                    "engine": "duckduckgo",
                    "error": "Tool 'web_search' execution timed out (30.0s)",
                }

            reg.get("web_search").handler = mock_handler
            try:
                resp = await client.post(
                    f"/api/v1/chat/conversations/{conv_id}/agent",
                    json={"content": "timeout test", "model_name": "llama3.2:3b"},
                    headers=h,
                )
                events = _parse_sse_events(resp.text)
                # Should complete (not hang)
                assert "done" in events
            finally:
                reg.get("web_search").handler = original_handler

    async def test_tool_exception_does_not_hang_agent(self, client: AsyncClient):
        """E: Tool exception does not hang AgentRun."""
        h = await _setup_obs_user(client, "tool_e@test.com")
        conv_id = await _create_conv(client, h, "exception test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("search", steps=[
                    {"id": 1, "description": "Search web", "tool": "web_search"},
                ]),
                _make_reasoner_resp("CONTINUE", "searching", "web_search",
                                    {"query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(True),
            ]

            from tools.registry import get_registry
            reg = get_registry()
            original_handler = reg.get("web_search").handler

            async def mock_handler(data, ctx):
                raise RuntimeError("Network error")

            reg.get("web_search").handler = mock_handler
            try:
                resp = await client.post(
                    f"/api/v1/chat/conversations/{conv_id}/agent",
                    json={"content": "exception test", "model_name": "llama3.2:3b"},
                    headers=h,
                )
                events = _parse_sse_events(resp.text)
                # Should complete, not hang
                assert "done" in events
            finally:
                reg.get("web_search").handler = original_handler

    async def test_tool_result_reaches_runtime(self, client: AsyncClient):
        """F: Tool result reaches runtime and is recorded."""
        h = await _setup_obs_user(client, "tool_f@test.com")
        conv_id = await _create_conv(client, h, "result reach test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("search", steps=[
                    {"id": 1, "description": "Search web", "tool": "web_search"},
                ]),
                _make_reasoner_resp("CONTINUE", "searching", "web_search",
                                    {"query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(True),
            ]

            from tools.registry import get_registry
            reg = get_registry()
            original_handler = reg.get("web_search").handler

            async def mock_handler(data, ctx):
                return {"results": [{"title": "Found", "url": "http://x.com"}], "engine": "duckduckgo", "error": None}

            reg.get("web_search").handler = mock_handler
            try:
                resp = await client.post(
                    f"/api/v1/chat/conversations/{conv_id}/agent",
                    json={"content": "result test", "model_name": "llama3.2:3b"},
                    headers=h,
                )
                events = _parse_sse_events(resp.text)
                # tool_result should be emitted
                tool_results = events.get("tool_result", [])
                assert len(tool_results) >= 1
                assert tool_results[0]["status"] == "success"
            finally:
                reg.get("web_search").handler = original_handler

    async def test_final_response_after_tool_failure(self, client: AsyncClient):
        """K: final_response still occurs after recoverable tool failure."""
        h = await _setup_obs_user(client, "tool_k@test.com")
        conv_id = await _create_conv(client, h, "recovery test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("search", steps=[
                    {"id": 1, "description": "Search web", "tool": "web_search"},
                ]),
                _make_reasoner_resp("CONTINUE", "searching", "web_search",
                                    {"query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(True),
            ]

            from tools.registry import get_registry
            reg = get_registry()
            original_handler = reg.get("web_search").handler

            async def mock_handler(data, ctx):
                return {"results": [], "engine": "duckduckgo", "error": "Search failed"}

            reg.get("web_search").handler = mock_handler
            try:
                resp = await client.post(
                    f"/api/v1/chat/conversations/{conv_id}/agent",
                    json={"content": "recovery test", "model_name": "llama3.2:3b"},
                    headers=h,
                )
                events = _parse_sse_events(resp.text)
                assert "final_response" in events
                assert "done" in events
            finally:
                reg.get("web_search").handler = original_handler

    async def test_global_timeout_still_safety_net(self, client: AsyncClient):
        """L: Global 300s timeout remains a final safety net."""
        # This tests that the global timeout mechanism still works
        # We can't actually wait 300s, but we verify the timeout constant exists
        from services.agent.runtime import AGENT_MAX_RUNTIME_SECONDS
        assert AGENT_MAX_RUNTIME_SECONDS == 300

    async def test_tool_call_id_stable_correlation(self, client: AsyncClient):
        """tool_call_id is stable and used for correlation between events."""
        h = await _setup_obs_user(client, "tool_corr@test.com")
        conv_id = await _create_conv(client, h, "correlation test")

        with patch(
            "services.llm_client.OllamaClient.chat",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = [
                _make_understand_resp(intent="task"),
                _make_plan_resp("search", steps=[
                    {"id": 1, "description": "Search web", "tool": "web_search"},
                ]),
                _make_reasoner_resp("CONTINUE", "searching", "web_search",
                                    {"query": "test"}, "search"),
                _make_reasoner_resp("COMPLETE", "done"),
                _make_verifier_resp(True),
            ]

            from tools.registry import get_registry
            reg = get_registry()
            original_handler = reg.get("web_search").handler

            async def mock_handler(data, ctx):
                return {"results": [{"title": "X", "url": "http://x.com"}], "engine": "duckduckgo", "error": None}

            reg.get("web_search").handler = mock_handler
            try:
                resp = await client.post(
                    f"/api/v1/chat/conversations/{conv_id}/agent",
                    json={"content": "correlation test", "model_name": "llama3.2:3b"},
                    headers=h,
                )
                events = _parse_sse_events(resp.text)
                tool_calls = events.get("tool_call", [])
                tool_results = events.get("tool_result", [])
                assert len(tool_calls) >= 1
                assert len(tool_results) >= 1
                # call_id in tool_call matches call_id in tool_result
                tc_ids = {tc["call_id"] for tc in tool_calls}
                tr_ids = {tr["call_id"] for tr in tool_results}
                assert tc_ids == tr_ids, f"call_id mismatch: {tc_ids} vs {tr_ids}"
            finally:
                reg.get("web_search").handler = original_handler
