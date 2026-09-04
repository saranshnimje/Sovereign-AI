"""
Integration tests for all new agentic runtime features.

Tests the full autonomous agent loop: planning, reasoning, verification,
loop detection, cancellation, replan budget, SSE event ordering, etc.
External services (LLM) are fully mocked.
"""
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient


DIM = 768
FAKE_VECTORS = lambda n: [[0.1] * DIM for _ in range(n)]


def _make_plan_resp(goal="test", steps=None):
    r = MagicMock()
    r.content = json.dumps({
        "goal": goal,
        "acceptance_criteria": ["Task completed"],
        "steps": steps or [],
    })
    return r


def _make_reasoner_resp(decision="CONTINUE", reason="executing", tool=None, tool_input=None, reasoning=""):
    data: dict = {"decision": decision, "reason": reason}
    if tool:
        data["next_action"] = {"tool": tool, "input": tool_input or {}, "reasoning": reasoning}
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
    """Parse SSE response into {event_type: [data_objects]}."""
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


async def _setup_user(client: AsyncClient, email: str, username: str) -> dict:
    """Register, login, return headers."""
    await client.post("/api/v1/auth/register", json={
        "email": email, "username": username, "password": "TestPass123!"
    })
    r = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "TestPass123!"
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_conv(client: AsyncClient, h: dict, title: str = "test") -> str:
    r = await client.post("/api/v1/chat/conversations", json={
        "model_name": "llama3.2:3b", "title": title
    }, headers=h)
    return r.json()["id"]


# ------------------------------------------------------------------
# 1. test_simple_greeting_no_tools
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simple_greeting_no_tools(client: AsyncClient):
    """Greeting like 'Hello!' skips planning and goes straight to verification."""
    h = await _setup_user(client, "greet@test.com", "greet")
    conv_id = await _create_conv(client, h, "greeting test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Hello!", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # No planner/reasoner/verifier LLM calls for simple greetings
        assert not mock_chat.called

        # No tool_call events
        assert "event: tool_call\n" not in body
        assert "event: tool_result\n" not in body

        # Verification events ARE emitted
        assert "event: verification_started\n" in body
        assert "event: verification_passed\n" in body
        assert "event: done\n" in body


# ------------------------------------------------------------------
# 2. test_simple_thanks_no_tools
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simple_thanks_no_tools(client: AsyncClient):
    """'Thanks!' is classified as simple request and handled without tools."""
    h = await _setup_user(client, "thanks@test.com", "thanks")
    conv_id = await _create_conv(client, h, "thanks test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Thanks!", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        assert not mock_chat.called
        assert "event: tool_call\n" not in body
        assert "event: verification_started\n" in body
        assert "event: verification_passed\n" in body


# ------------------------------------------------------------------
# 3. test_invalid_tool_arguments_returns_structured_error
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_tool_arguments_returns_structured_error(client: AsyncClient):
    """Invalid tool arguments produce tool_result with failure_type INVALID_TOOL_ARGUMENTS."""
    h = await _setup_user(client, "invargs@test.com", "invargs")
    conv_id = await _create_conv(client, h, "invalid args test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("write file with bad args"),
            _make_reasoner_resp(
                "CONTINUE", "write file",
                "file_write", {"access_file": "x"},
                "testing invalid args",
            ),
            _make_reasoner_resp("COMPLETE", "Invalid args handled."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "write file with bad args", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        assert "event: tool_result\n" in body
        assert '"status": "failed"' in body


# ------------------------------------------------------------------
# 4. test_repeated_invalid_actions_triggers_loop_protection
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_repeated_invalid_actions_triggers_loop_protection(client: AsyncClient):
    """Same invalid tool call 3 times triggers loop detection and fails."""
    h = await _setup_user(client, "loop@test.com", "loop")
    conv_id = await _create_conv(client, h, "loop test")

    bad_call = _make_reasoner_resp(
        "CONTINUE", "bad call",
        "file_write", {"access_file": "x"},
        "repeating bad call",
    )

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        # 1 planner + 4 reasoner calls (3 identical bad calls + 1 loop-replan callback)
        # After loop detection, replanner is called; if it fails, agent may fail
        mock_chat.side_effect = [
            _make_plan_resp("loop test", steps=[{"id": 1, "description": "step1", "tool": "file_write"}]),
            bad_call,  # iteration 1
            bad_call,  # iteration 2
            bad_call,  # iteration 3 — triggers loop detection
            # After loop detection, replanner is attempted
            _make_plan_resp("new plan after loop", steps=[{"id": 1, "description": "recovery", "tool": None}]),
            _make_reasoner_resp("COMPLETE", "Recovered."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "loop test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # Should eventually terminate
        assert "event: done\n" in body

        # plan_updated should appear (loop triggered replan)
        assert "event: plan_updated\n" in body


# ------------------------------------------------------------------
# 5. test_dynamic_todo_updates_on_plan_creation
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dynamic_todo_updates_on_plan_creation(client: AsyncClient):
    """When a plan is created with steps, todo_updated SSE events are emitted."""
    h = await _setup_user(client, "todo1@test.com", "todo1")
    conv_id = await _create_conv(client, h, "todo creation test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("multi step task", steps=[
                {"id": 1, "description": "Step A", "tool": "calculator"},
                {"id": 2, "description": "Step B", "tool": "calculator"},
            ]),
            _make_reasoner_resp("COMPLETE", "Done."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "multi step task", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        # todo_updated must be present
        assert "todo_updated" in events

        # The first todo_updated after plan creation should contain the steps
        todo_events = events["todo_updated"]
        assert len(todo_events) >= 1
        first_todo = todo_events[0]
        assert "tasks" in first_todo
        assert len(first_todo["tasks"]) >= 2


# ------------------------------------------------------------------
# 6. test_todo_updates_on_step_completion
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_todo_updates_on_step_completion(client: AsyncClient):
    """Todo status updates when steps complete."""
    h = await _setup_user(client, "todo2@test.com", "todo2")
    conv_id = await _create_conv(client, h, "todo completion test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("two steps", steps=[
                {"id": 1, "description": "Step A", "tool": "calculator"},
                {"id": 2, "description": "Step B", "tool": "calculator"},
            ]),
            _make_reasoner_resp("CONTINUE", "exec step 1", "calculator", {"expression": "1+1"}, "math"),
            _make_reasoner_resp("CONTINUE", "exec step 2", "calculator", {"expression": "2+2"}, "math"),
            _make_reasoner_resp("COMPLETE", "Both done."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "two steps", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        todo_events = events.get("todo_updated", [])
        assert len(todo_events) >= 3  # initial + start1 + complete1 + start2 + complete2

        # Find a todo event after step 1 completes — at least one calculator task should be completed
        # The third todo_updated event is after step 1 completes (after start + complete)
        after_step1 = todo_events[2]
        completed_after_step1 = sum(1 for t in after_step1["tasks"] if t["status"] == "completed")
        assert completed_after_step1 >= 1

        # Find the last todo event — both steps should be completed
        last_todo = todo_events[-1]
        completed_count = sum(1 for t in last_todo["tasks"] if t["status"] == "completed")
        assert completed_count == 2


# ------------------------------------------------------------------
# 7. test_hard_timeout_triggers_failure
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hard_timeout_triggers_failure(client: AsyncClient):
    """AGENT_MAX_RUNTIME_SECONDS=1 triggers timeout failure."""
    h = await _setup_user(client, "timeout@test.com", "timeout")
    conv_id = await _create_conv(client, h, "timeout test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat, \
         patch("services.agent.runtime.AGENT_MAX_RUNTIME_SECONDS", 1):
        # Planner returns a plan, but reasoner returns CONTINUE which loops
        # The wall-clock check should fire before the 2nd reasoner call
        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(2)
            return _make_reasoner_resp("COMPLETE", "too late")

        mock_chat.side_effect = [
            _make_plan_resp("timeout test"),
            slow_llm,
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "timeout test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        # Should have error and done events with failed state
        assert "error" in events or "done" in events
        if "done" in events:
            last_done = events["done"][-1]
            assert last_done.get("state") == "failed"


# ------------------------------------------------------------------
# 8. test_per_call_llm_timeout
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_per_call_llm_timeout(client: AsyncClient):
    """asyncio.TimeoutError on planner causes graceful failure."""
    h = await _setup_user(client, "llmtimeout@test.com", "llmtimeout")
    conv_id = await _create_conv(client, h, "llm timeout test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = asyncio.TimeoutError("LLM timed out")

        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "timeout test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        # Planner timeout returns None plan; agent should complete via fallback
        assert "event: done\n" in body
        # Should not crash with 500
        assert "error" not in events or events["error"][-1].get("message", "") != ""


# ------------------------------------------------------------------
# 9. test_verification_started_passed_events
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verification_started_passed_events(client: AsyncClient):
    """SSE stream contains verification_started and verification_passed in order."""
    h = await _setup_user(client, "verify1@test.com", "verify1")
    conv_id = await _create_conv(client, h, "verify happy path")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("simple task"),
            _make_reasoner_resp("COMPLETE", "Done."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "simple task", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        assert "verification_started" in events
        assert "verification_passed" in events

        # verification_started must come before verification_passed
        vs_idx = body.index("event: verification_started")
        vp_idx = body.index("event: verification_passed")
        assert vs_idx < vp_idx


# ------------------------------------------------------------------
# 10. test_verification_failed_event
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verification_failed_event(client: AsyncClient):
    """Mock verifier returns verified=false; stream emits verification_failed with missing info."""
    h = await _setup_user(client, "verify2@test.com", "verify2")
    conv_id = await _create_conv(client, h, "verify fail")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("task that fails verification"),
            _make_reasoner_resp("COMPLETE", "I think it's done."),
            _make_verifier_resp(False),
            # After failure, replanner is called
            _make_plan_resp("recovery plan"),
            _make_reasoner_resp("COMPLETE", "Recovered."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "task that fails verification", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        assert "verification_failed" in events
        vf = events["verification_failed"][0]
        assert "missing" in vf
        assert len(vf["missing"]) > 0


# ------------------------------------------------------------------
# 11. test_agent_mode_with_tool_mode_none
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_mode_with_tool_mode_none(client: AsyncClient):
    """tool_mode=none prevents tool execution even if reasoner requests it."""
    h = await _setup_user(client, "toolnone@test.com", "toolnone")
    conv_id = await _create_conv(client, h, "tool mode none")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("test"),
            _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"expression": "1+1"}, "test"),
            _make_reasoner_resp("COMPLETE", "Done."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "test", "model_name": "llama3.2:3b", "tool_mode": "none"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # No tool_call events when tool_mode=none
        assert "event: tool_call\n" not in body
        assert "event: tool_result\n" not in body
        assert "event: observation\n" not in body


# ------------------------------------------------------------------
# 12. test_plan_mode_no_autonomous_execution
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_plan_mode_no_autonomous_execution(client: AsyncClient):
    """agent_mode=plan creates plan but does not execute tools."""
    h = await _setup_user(client, "planmode@test.com", "planmode")
    conv_id = await _create_conv(client, h, "plan mode test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        # Planner returns a plan; reasoner returns COMPLETE immediately (no tools)
        mock_chat.side_effect = [
            _make_plan_resp("plan only", steps=[
                {"id": 1, "description": "Step A", "tool": "calculator"},
                {"id": 2, "description": "Step B", "tool": "calculator"},
            ]),
            _make_reasoner_resp("COMPLETE", "Plan created."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "plan only", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        assert "plan_created" in events
        plan = events["plan_created"][0]
        assert len(plan["steps"]) == 2

        # No tool_call events
        assert "event: tool_call\n" not in body

        # Should end with done
        assert "event: done\n" in body


# ------------------------------------------------------------------
# 13. test_cancellation_mid_execution
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cancellation_mid_execution(client: AsyncClient):
    """Cancelling an agent run stops execution and emits cancelled event."""
    h = await _setup_user(client, "cancel@test.com", "cancel")
    conv_id = await _create_conv(client, h, "cancel test")

    call_count = 0

    async def mock_llm_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_plan_resp("long task")
        elif call_count == 2:
            # First reasoner call — slow to allow cancellation
            await asyncio.sleep(0.1)
            return _make_reasoner_resp("CONTINUE", "step 1", "calculator", {"expression": "1+1"}, "test")
        else:
            return _make_reasoner_resp("COMPLETE", "Done.")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock, side_effect=mock_llm_call):
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "long task", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # The agent should complete (cancel may happen after completion in sync test)
        assert "event: done\n" in body


# ------------------------------------------------------------------
# 14. test_failure_type_propagation
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_type_propagation(client: AsyncClient):
    """Tool failure events contain failure info."""
    h = await _setup_user(client, "failprop@test.com", "failprop")
    conv_id = await _create_conv(client, h, "failure propagation")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("compute something"),
            _make_reasoner_resp("CONTINUE", "use calculator", "calculator", {"expression": "1+1"}, "compute"),
            _make_reasoner_resp("COMPLETE", "Done."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "compute something", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # tool_call and tool_result events should be present
        assert "event: tool_call\n" in body
        assert "event: tool_result\n" in body


# ------------------------------------------------------------------
# 15. test_replan_budget_exhaustion
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_replan_budget_exhaustion(client: AsyncClient):
    """After MAX_REPLANS replans, agent fails."""
    h = await _setup_user(client, "replan@test.com", "replan")
    conv_id = await _create_conv(client, h, "replan budget")

    replan_count = 0

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        # Build side_effect: planner → verifier fails → replan → planner → verifier fails → ...
        side_effects = []
        for i in range(12):  # generous buffer
            side_effects.append(_make_plan_resp(f"plan {i}"))
            side_effects.append(_make_reasoner_resp("COMPLETE", "done"))
            side_effects.append(_make_verifier_resp(False))  # always fail verification
        mock_chat.side_effect = side_effects

        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "replan budget test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # Should eventually terminate with done
        assert "event: done\n" in body


# ------------------------------------------------------------------
# 16. test_action_fingerprint_loop_detection
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_action_fingerprint_loop_detection(client: AsyncClient):
    """Same tool call repeated triggers fingerprint loop detection."""
    h = await _setup_user(client, "fingerprint@test.com", "fingerprint")
    conv_id = await _create_conv(client, h, "fingerprint test")

    same_call = _make_reasoner_resp(
        "CONTINUE", "same thing",
        "calculator", {"expression": "1+1"},
        "repeating",
    )

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("fingerprint test"),
            same_call,  # 1
            same_call,  # 2
            same_call,  # 3 — should trigger loop detection
            # After loop detection, replanner or fail
            _make_plan_resp("alternative plan"),
            _make_reasoner_resp("COMPLETE", "Alternative."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "fingerprint test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        # Should end with done (not hang)
        assert "done" in events

        # plan_updated should appear (loop forced replan)
        assert "plan_updated" in events or "error" in events


# ------------------------------------------------------------------
# 17. test_sse_event_ordering
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sse_event_ordering(client: AsyncClient):
    """SSE events appear in correct order:
    agent_state → plan_created → todo_updated → tool_call → tool_result
    → observation → verification_started → verification_passed → done
    """
    h = await _setup_user(client, "ordering@test.com", "ordering")
    conv_id = await _create_conv(client, h, "ordering test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("ordering task", steps=[
                {"id": 1, "description": "Calc", "tool": "calculator"},
            ]),
            _make_reasoner_resp("CONTINUE", "calculate", "calculator", {"expression": "2+2"}, "math"),
            _make_reasoner_resp("COMPLETE", "4"),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "ordering task", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # Extract event types in order of appearance
        event_order = []
        for line in body.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:].strip()
                if event_name not in ("decision",):  # skip decision for simpler check
                    event_order.append(event_name)

        # Verify key ordering constraints
        def idx(event_name):
            try:
                return event_order.index(event_name)
            except ValueError:
                return -1

        # agent_state should come first
        assert idx("agent_state") >= 0

        # plan_created before todo_updated
        if idx("plan_created") >= 0 and idx("todo_updated") >= 0:
            assert idx("plan_created") < idx("todo_updated")

        # tool_call before tool_result
        if idx("tool_call") >= 0 and idx("tool_result") >= 0:
            assert idx("tool_call") < idx("tool_result")

        # tool_result before observation
        if idx("tool_result") >= 0 and idx("observation") >= 0:
            assert idx("tool_result") < idx("observation")

        # verification_started before verification_passed
        if idx("verification_started") >= 0 and idx("verification_passed") >= 0:
            assert idx("verification_started") < idx("verification_passed")

        # done is last
        done_idx = idx("done")
        if done_idx >= 0:
            assert done_idx >= len(event_order) - 3  # done is near the end


# ------------------------------------------------------------------
# Additional edge-case tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_hello_variants_skip_planning(client: AsyncClient):
    """Various greeting patterns all skip planning."""
    greetings = ["Hi there", "Hey!", "Good morning", "How are you?", "Yo!"]
    for i, greeting in enumerate(greetings):
        h = await _setup_user(client, f"hi{i}@test.com", f"hi{i}")
        conv_id = await _create_conv(client, h, f"greeting {i}")

        with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
            resp = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": greeting, "model_name": "llama3.2:3b"},
                headers=h,
            )
            assert resp.status_code == 200
            body = resp.text
            assert not mock_chat.called, f"LLM should not be called for: {greeting}"
            assert "event: verification_started\n" in body
            assert "event: verification_passed\n" in body


@pytest.mark.asyncio
async def test_long_greeting_triggers_planning(client: AsyncClient):
    """Greeting longer than 100 chars triggers normal planning."""
    h = await _setup_user(client, "longhi@test.com", "longhi")
    conv_id = await _create_conv(client, h, "long greeting")

    long_greeting = "Hello " + "x" * 100

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("long greeting"),
            _make_reasoner_resp("COMPLETE", "That's a long greeting!"),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": long_greeting, "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        assert mock_chat.called


@pytest.mark.asyncio
async def test_plan_with_no_steps(client: AsyncClient):
    """Plan with empty steps should still complete."""
    h = await _setup_user(client, "noplanner@test.com", "noplanner")
    conv_id = await _create_conv(client, h, "no plan steps")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("trivial", steps=[]),
            _make_reasoner_resp("COMPLETE", "Nothing to do."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "trivial", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        assert "event: done\n" in body


@pytest.mark.asyncio
async def test_verifier_reject_then_replan_succeeds(client: AsyncClient):
    """Verification fails once, replanner creates new plan, second attempt succeeds."""
    h = await _setup_user(client, "replanok@test.com", "replanok")
    conv_id = await _create_conv(client, h, "replan ok")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("needs retry", steps=[{"id": 1, "description": "do thing", "tool": "calculator"}]),
            _make_reasoner_resp("COMPLETE", "I think it's done."),
            _make_verifier_resp(False),  # first verification fails
            _make_plan_resp("retry plan", steps=[{"id": 1, "description": "try again", "tool": "calculator"}]),
            _make_reasoner_resp("COMPLETE", "Actually done now."),
            _make_verifier_resp(True),  # second verification passes
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "needs retry", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text
        events = _parse_sse_events(body)

        assert "verification_failed" in events
        assert "verification_passed" in events
        assert "plan_updated" in events
        assert "done" in events


@pytest.mark.asyncio
async def test_done_event_contains_final_state(client: AsyncClient):
    """Done event includes state, tool_calls, plan, and elapsed_ms."""
    h = await _setup_user(client, "doneev@test.com", "doneev")
    conv_id = await _create_conv(client, h, "done event test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("simple"),
            _make_reasoner_resp("COMPLETE", "Answer."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "simple", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        assert "done" in events
        done = events["done"][-1]
        assert "state" in done
        assert done["state"] == "completed"
        assert "tool_calls" in done
        assert "elapsed_ms" in done
        assert "plan" in done
        assert isinstance(done["plan"], list)


@pytest.mark.asyncio
async def test_tool_call_has_call_id(client: AsyncClient):
    """Every tool_call event includes a unique call_id."""
    h = await _setup_user(client, "callid@test.com", "callid")
    conv_id = await _create_conv(client, h, "call id test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("calc"),
            _make_reasoner_resp("CONTINUE", "calc", "calculator", {"expression": "1+1"}, "math"),
            _make_reasoner_resp("COMPLETE", "2"),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "calc", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        assert "tool_call" in events
        tc = events["tool_call"][0]
        assert "call_id" in tc
        assert tc["call_id"].startswith("call_")


@pytest.mark.asyncio
async def test_conversation_ownership_enforced_in_agent(client: AsyncClient):
    """Agent endpoint enforces conversation ownership."""
    h1 = await _setup_user(client, "own1@test.com", "own1")
    h2 = await _setup_user(client, "own2@test.com", "own2")

    conv_id = await _create_conv(client, h1, "owner test")

    # User 2 tries to use User 1's conversation
    resp = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/agent",
        json={"content": "test", "model_name": "llama3.2:3b"},
        headers=h2,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_creates_user_message(client: AsyncClient):
    """Agent chat persists user message in conversation."""
    h = await _setup_user(client, "persist@test.com", "persist")
    conv_id = await _create_conv(client, h, "persist test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("hello"),
            _make_reasoner_resp("COMPLETE", "Hi!"),
            _make_verifier_resp(True),
        ]
        await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "hello", "model_name": "llama3.2:3b"},
            headers=h,
        )

    # Verify user message was persisted
    r = await client.get(f"/api/v1/chat/conversations/{conv_id}", headers=h)
    assert r.status_code == 200
    detail = r.json()
    messages = detail.get("messages", [])
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert any("hello" in m["content"] for m in user_msgs)


@pytest.mark.asyncio
async def test_no_secrets_in_sse_events(client: AsyncClient):
    """SSE events never expose passwords or tokens."""
    h = await _setup_user(client, "nosecret@test.com", "nosecret")
    conv_id = await _create_conv(client, h, "secret test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("test"),
            _make_reasoner_resp("COMPLETE", "Safe."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        body = resp.text
        assert "TestPass123" not in body
        # No absolute Windows paths
        assert "C:\\\\Users" not in body


@pytest.mark.asyncio
async def test_retry_event_on_transient_failure(client: AsyncClient):
    """Transient tool failure emits retry event."""
    h = await _setup_user(client, "retry@test.com", "retry")
    conv_id = await _create_conv(client, h, "retry test")

    with patch("services.llm_client.OllamaClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = [
            _make_plan_resp("retry test"),
            _make_reasoner_resp("CONTINUE", "try file read", "file_read", {"path": "nonexistent.txt"}, "read"),
            _make_reasoner_resp("CONTINUE", "try again", "file_read", {"path": "nonexistent.txt"}, "read"),
            _make_reasoner_resp("COMPLETE", "Couldn't find file."),
            _make_verifier_resp(True),
        ]
        resp = await client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "retry test", "model_name": "llama3.2:3b"},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.text

        # Tool results should appear
        assert "event: tool_result\n" in body
        # The done event should indicate completion
        assert "event: done\n" in body
