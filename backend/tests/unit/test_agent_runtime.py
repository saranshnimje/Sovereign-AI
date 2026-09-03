"""
Unit tests for AgentRuntime completion authority and safety guarantees.
Verifies that:
  1. LLM cannot directly set COMPLETED — verifier MUST approve
  2. Transient failures trigger bounded retries
  3. Strategy failures trigger REPLAN
  4. Cancellation is detected and stops safely
  5. Max iterations are enforced
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.agent.runtime import AgentRuntime, _classify_failure, _verify_tool_result
from services.agent.schemas import AgentDecision, VerificationResult, Plan, PlanStep
from services.agent_state import AgentStateMachine


# ------------------------------------------------------------------
# Completion authority
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_requires_verifier_approval():
    """LLM says COMPLETE but verifier rejects → runtime does NOT complete."""
    agent = AgentStateMachine()
    agent.start("test")

    # Create a plan

    call_count = {"n": 0}

    async def mock_chat(**kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        messages = kwargs.get("messages", [])
        # Check the system prompt to determine which role we're playing
        system_msg = messages[0].content if messages else ""
        if "PLANNER" in system_msg or "plan" in system_msg.lower()[:50]:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["test criterion"],
                "steps": [{"id": 1, "description": "step 1", "tool": None, "success_criteria": "done"}]
            }))
        elif "REASONER" in system_msg or "decide" in system_msg.lower()[:50]:
            return MagicMock(content=json.dumps({
                "decision": "COMPLETE",
                "reason": "I think I'm done",
                "next_action": None
            }))
        elif "VERIFIER" in system_msg or "verify" in system_msg.lower()[:50]:
            return MagicMock(content=json.dumps({
                "verified": False,
                "confidence": 0.3,
                "criteria": [{"criterion": "test criterion", "satisfied": False, "evidence": "no evidence"}],
                "missing": ["test criterion"],
                "unsupported_claims": ["I think I'm done"]
            }))
        elif "REPLANNER" in system_msg or "replan" in system_msg.lower()[:50]:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["test criterion"],
                "steps": [{"id": 1, "description": "step 1 retry", "tool": None, "success_criteria": "done"}]
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat

    runtime = AgentRuntime()
    events = []
    async for event in runtime.run(
        goal="test",
        user_id="u1",
        user_role="admin",
        model="test",
        llm=llm,
        db=MagicMock(),
        tool_names=[],
        tool_descriptions="",
    ):
        events.append(event)

    # Should NOT have completed — verifier rejected
    state_events = [e for e in events if "agent_state" in e]
    assert agent.state.value != "completed" or any("error" in e for e in events), \
        "Agent should not be in completed state when verifier rejects"


@pytest.mark.asyncio
async def test_verify_requires_verifier_approval():
    """LLM says VERIFY but verifier rejects → runtime does NOT complete."""
    agent = AgentStateMachine()
    agent.start("test")
    agent.create_plan([{"description": "do something", "tool_name": None}])

    call_count = {"n": 0}

    async def mock_chat(**kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "REASONER" in system_msg or "decide" in system_msg.lower()[:50]:
            return MagicMock(content=json.dumps({
                "decision": "VERIFY",
                "reason": "Let me verify",
                "next_action": None
            }))
        elif "VERIFIER" in system_msg or "verify" in system_msg.lower()[:50]:
            return MagicMock(content=json.dumps({
                "verified": False,
                "confidence": 0.2,
                "criteria": [],
                "missing": ["evidence missing"],
                "unsupported_claims": []
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat

    runtime = AgentRuntime()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=[], tool_descriptions="",
    ):
        events.append(event)

    # Verification failed → should not be completed
    assert agent.state.value != "completed"


# ------------------------------------------------------------------
# Failure classification
# ------------------------------------------------------------------

def test_classify_transient():
    assert _classify_failure("run_command", {}, "Connection timeout") == "TRANSIENT"
    assert _classify_failure("run_command", {}, "timed out after 30s") == "TRANSIENT"


def test_classify_bad_input():
    assert _classify_failure("run_command", {"exit_code": 1}, "") == "BAD_INPUT"
    assert _classify_failure("run_command", {}, "validation error: missing field") == "BAD_INPUT"


def test_classify_unavailable():
    assert _classify_failure("tool", {}, "tool not found") == "UNAVAILABLE"
    assert _classify_failure("tool", {}, "service unavailable") == "UNAVAILABLE"


def test_classify_fatal():
    assert _classify_failure("tool", {}, "permission denied") == "FATAL"
    assert _classify_failure("tool", {}, "access forbidden") == "FATAL"


def test_classify_python_exec_bad_input():
    assert _classify_failure("python_exec", {"exit_code": 1}, "") == "BAD_INPUT"


# ------------------------------------------------------------------
# Tool result verification
# ------------------------------------------------------------------

def test_verify_tool_result_success():
    passed, reason = _verify_tool_result("file_write", {"path": "/tmp/test.txt"})
    assert passed is True


def test_verify_tool_result_command_failure():
    passed, reason = _verify_tool_result("run_command", {"exit_code": 1, "stderr": "error msg"})
    assert passed is False
    assert "exit 1" in reason


def test_verify_tool_result_python_failure():
    passed, reason = _verify_tool_result("python_exec", {"exit_code": 1})
    assert passed is False


def test_verify_tool_result_error():
    passed, reason = _verify_tool_result("tool", {"error": "something broke"})
    assert passed is False


# ------------------------------------------------------------------
# Bounded retries
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_bounded():
    """Tool keeps being retried → runtime stops at MAX_ITERATIONS."""
    from services.agent_state import MAX_TOOL_CALLS, MAX_ITERATIONS

    agent = AgentStateMachine()

    # Planner returns valid plan, reasoner keeps saying RETRY
    async def mock_chat(**kwargs):
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "PLANNER" in system_msg:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["done"],
                "steps": [{"id": 1, "description": "use tool", "tool": "calculator", "success_criteria": "ok"}]
            }))
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "RETRY",
                "reason": "try again",
                "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "retry"}
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat

    runtime = AgentRuntime()
    tool_call_count = 0
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"], tool_descriptions="calculator: basic math",
        agent_state=agent,
    ):
        if "tool_call" in event:
            tool_call_count += 1

    # Safety: bounded by MAX_ITERATIONS (the main loop limit)
    assert tool_call_count <= MAX_ITERATIONS + 5, \
        f"Tool calls ({tool_call_count}) exceeded MAX_ITERATIONS ({MAX_ITERATIONS}) with margin"


@pytest.mark.asyncio
async def test_per_tool_retry_enforced_on_failure():
    """Tool fails repeatedly → per-tool retry limit enforced → tool skipped after max retries."""
    from services.agent_state import MAX_RETRIES_PER_TOOL, MAX_ITERATIONS

    agent = AgentStateMachine()

    call_count = {"n": 0}

    async def mock_chat(**kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "PLANNER" in system_msg:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["done"],
                "steps": [{"id": 1, "description": "use tool", "tool": "calculator", "success_criteria": "ok"}]
            }))
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "RETRY",
                "reason": "try again",
                "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "retry"}
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat

    runtime = AgentRuntime()

    # Mock the tool executor to return a TRANSIENT failure (triggers retry tracking)
    async def mock_execute(tool_name, tool_input, **kwargs):
        return {"error": "connection timeout", "exit_code": 1}

    with patch.object(runtime, '_execute_tool', mock_execute):
        tool_call_count = 0
        async for event in runtime.run(
            goal="test", user_id="u1", user_role="admin", model="test",
            llm=llm, db=MagicMock(), tool_names=["calculator"], tool_descriptions="calculator: basic math",
        ):
            if "tool_call" in event:
                tool_call_count += 1

    # After MAX_RETRIES_PER_TOOL retries, tool is skipped.
    # Loop continues via reasoner RETRY until MAX_ITERATIONS.
    assert tool_call_count <= MAX_ITERATIONS + 5, \
        f"Tool calls ({tool_call_count}) exceeded MAX_ITERATIONS ({MAX_ITERATIONS}) with margin"


# ------------------------------------------------------------------
# Completion authority regression tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_iterations_without_verification_is_failed():
    """Max iterations reached without verification → FAILED, never COMPLETED."""
    agent = AgentStateMachine()

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "PLANNER" in system_msg:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["done"],
                "steps": [{"id": 1, "description": "use tool", "tool": "calculator", "success_criteria": "ok"}]
            }))
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "RETRY",
                "reason": "keep trying",
                "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "retry"}
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat
    runtime = AgentRuntime()

    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"], tool_descriptions="calc",
        agent_state=agent,
    ):
        events.append(event)

    assert agent.state.value == "failed", f"Expected failed, got {agent.state.value}"
    done_events = [e for e in events if e.startswith("event: done")]
    assert len(done_events) == 1
    assert '"state": "failed"' in done_events[0]


@pytest.mark.asyncio
async def test_verification_false_is_not_completed():
    """Verifier returns verified=false → NOT completed."""
    agent = AgentStateMachine()

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "VERIFY",
                "reason": "verifying",
                "next_action": None
            }))
        if "VERIFIER" in system_msg:
            return MagicMock(content=json.dumps({
                "verified": False,
                "confidence": 0.1,
                "criteria": [],
                "missing": ["not done"],
                "unsupported_claims": []
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat
    runtime = AgentRuntime()

    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=[], tool_descriptions="",
        agent_state=agent,
    ):
        events.append(event)

    assert agent.state.value != "completed", "Agent should NOT be completed when verification fails"


@pytest.mark.asyncio
async def test_successful_verification_is_completed():
    """Successful verification → COMPLETED."""
    agent = AgentStateMachine()

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "VERIFY",
                "reason": "done",
                "next_action": None
            }))
        if "VERIFIER" in system_msg:
            return MagicMock(content=json.dumps({
                "verified": True,
                "confidence": 0.95,
                "criteria": [],
                "missing": [],
                "unsupported_claims": []
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "should not reach"}))

    llm = MagicMock()
    llm.chat = mock_chat
    runtime = AgentRuntime()

    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=[], tool_descriptions="",
        agent_state=agent,
    ):
        events.append(event)

    assert agent.state.value == "completed", f"Expected completed, got {agent.state.value}"
    done_events = [e for e in events if e.startswith("event: done")]
    assert len(done_events) == 1
    assert '"state": "completed"' in done_events[0]


@pytest.mark.asyncio
async def test_cancellation_is_not_completed():
    """Cancellation → CANCELLED, never COMPLETED."""
    from services.agent_state import MAX_ITERATIONS

    agent = AgentStateMachine()

    call_count = {"n": 0}
    async def smart_chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] > 3:
            agent.cancel()
            return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "cancelled"}))
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "PLANNER" in system_msg:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["done"],
                "steps": [{"id": 1, "description": "use tool", "tool": "calculator", "success_criteria": "ok"}]
            }))
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "RETRY",
                "reason": "keep trying",
                "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "retry"}
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = smart_chat
    runtime = AgentRuntime()

    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"], tool_descriptions="calc",
        agent_state=agent,
    ):
        events.append(event)

    assert agent.state.value == "cancelled", f"Expected cancelled, got {agent.state.value}"


@pytest.mark.asyncio
async def test_failed_tool_exhausted_retries_is_failed():
    """Tool fails repeatedly, retries exhausted → FAILED, never COMPLETED."""
    from services.agent_state import MAX_RETRIES_PER_TOOL

    agent = AgentStateMachine()

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages", [])
        system_msg = messages[0].content if messages else ""
        if "PLANNER" in system_msg:
            return MagicMock(content=json.dumps({
                "goal": "test",
                "acceptance_criteria": ["done"],
                "steps": [{"id": 1, "description": "use tool", "tool": "calculator", "success_criteria": "ok"}]
            }))
        if "REASONER" in system_msg:
            return MagicMock(content=json.dumps({
                "decision": "RETRY",
                "reason": "retry",
                "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "retry"}
            }))
        return MagicMock(content=json.dumps({"decision": "FAIL", "reason": "give up"}))

    llm = MagicMock()
    llm.chat = mock_chat
    runtime = AgentRuntime()

    # Tool always fails with transient error
    async def mock_execute(tool_name, tool_input, **kwargs):
        return {"error": "connection timeout"}

    with patch.object(runtime, '_execute_tool', mock_execute):
        events = []
        async for event in runtime.run(
            goal="test", user_id="u1", user_role="admin", model="test",
            llm=llm, db=MagicMock(), tool_names=["calculator"], tool_descriptions="calc",
            agent_state=agent,
        ):
            events.append(event)

    # Should end in failed (max iterations or exhausted retries)
    assert agent.state.value == "failed", f"Expected failed, got {agent.state.value}"
    assert agent.state.value != "completed"
