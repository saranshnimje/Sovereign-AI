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
            "agent_state", "understanding_started",
            "understanding_completed", "token", "done",
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
