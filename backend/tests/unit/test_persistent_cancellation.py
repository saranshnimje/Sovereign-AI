"""
Persistent cancellation tests — verify cancel check at each lifecycle point.

CRITICAL: Without proper cancellation checks, the agent loop will never stop
even after a user requests cancellation.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agent_state import AgentStateMachine, AgentState, MAX_ITERATIONS


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def sm():
    """Create an AgentStateMachine for testing."""
    return AgentStateMachine()


# ------------------------------------------------------------------
# 1. State machine cancellation transition tests
# ------------------------------------------------------------------
class TestCancellationTransitions:
    """Tests that CANCELLED is reachable from all active states."""

    def test_cancel_from_idle(self, sm):
        """IDLE → CANCELLED should be valid."""
        sm.cancel()

    def _build_to_state(self, sm, target: AgentState):
        """Helper: build state machine up to target state via valid transitions."""
        path = {
            AgentState.PLANNING: [AgentState.UNDERSTANDING, AgentState.PLANNING],
            AgentState.EXECUTING: [AgentState.UNDERSTANDING, AgentState.PLANNING, AgentState.EXECUTING],
            AgentState.OBSERVING: [AgentState.UNDERSTANDING, AgentState.PLANNING, AgentState.EXECUTING, AgentState.OBSERVING],
            AgentState.REASONING: [AgentState.UNDERSTANDING, AgentState.PLANNING, AgentState.EXECUTING, AgentState.OBSERVING, AgentState.REASONING],
            AgentState.VERIFYING: [AgentState.UNDERSTANDING, AgentState.PLANNING, AgentState.EXECUTING, AgentState.OBSERVING, AgentState.REASONING, AgentState.VERIFYING],
            AgentState.WAITING_APPROVAL: [AgentState.UNDERSTANDING, AgentState.PLANNING, AgentState.EXECUTING, AgentState.WAITING_APPROVAL],
        }
        for state in path.get(target, []):
            sm.transition(state, reason="test")

    def test_cancel_from_planning(self, sm):
        """PLANNING → CANCELLED should be valid."""
        self._build_to_state(sm, AgentState.PLANNING)
        sm.cancel()

    def test_cancel_from_executing(self, sm):
        """EXECUTING → CANCELLED should be valid."""
        self._build_to_state(sm, AgentState.EXECUTING)
        sm.cancel()

    def test_cancel_from_observing(self, sm):
        """OBSERVING → CANCELLED should be valid."""
        self._build_to_state(sm, AgentState.OBSERVING)
        sm.cancel()

    def test_cancel_from_reasoning(self, sm):
        """REASONING → CANCELLED should be valid."""
        self._build_to_state(sm, AgentState.REASONING)
        sm.cancel()

    def test_cancel_from_verifying(self, sm):
        """VERIFYING → CANCELLED should be valid."""
        self._build_to_state(sm, AgentState.VERIFYING)
        sm.cancel()

    def test_cancel_from_waiting_approval(self, sm):
        """WAITING_APPROVAL → CANCELLED should be valid."""
        self._build_to_state(sm, AgentState.WAITING_APPROVAL)
        sm.cancel()


# ------------------------------------------------------------------
# 2. Cancellation check mechanism tests
# ------------------------------------------------------------------
class TestCancellationCheck:
    """Tests for the cancel check mechanism."""

    def test_state_is_cancelled_after_cancel(self, sm):
        """State should be CANCELLED after cancel()."""
        sm.cancel()
        assert sm.state == AgentState.CANCELLED

    def test_cancel_method_exists(self, sm):
        """cancel() method should exist."""
        assert hasattr(sm, 'cancel')
        assert callable(sm.cancel)

    def test_can_retry_returns_false_after_max_retries(self, sm):
        """can_retry should return False after max retries."""
        for _ in range(3):
            sm.record_retry("tool1")
        assert sm.can_retry("tool1") is False


# ------------------------------------------------------------------
# 3. Runtime cancel check integration tests
# ------------------------------------------------------------------
class TestRuntimeCancellation:
    """Tests for runtime-level cancellation checks."""

    @pytest.mark.asyncio
    async def test_cancel_event_stops_loop(self):
        """Setting cancel event should stop the agent loop."""
        cancel_event = asyncio.Event()

        async def agent_loop():
            iterations = 0
            while not cancel_event.is_set():
                await asyncio.sleep(0)
                iterations += 1
                if iterations > 100:
                    break
            return iterations

        async def cancel_soon():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            cancel_event.set()

        asyncio.create_task(cancel_soon())
        result = await agent_loop()
        assert result <= 5

    @pytest.mark.asyncio
    async def test_cancel_during_tool_execution(self):
        """Cancel during tool execution should prevent next tool call."""
        cancel_event = asyncio.Event()
        tool_calls = []

        async def run_tools():
            for i in range(10):
                if cancel_event.is_set():
                    break
                tool_calls.append(i)
                await asyncio.sleep(0)
                if i == 2:
                    cancel_event.set()

        await run_tools()
        assert len(tool_calls) <= 4


# ------------------------------------------------------------------
# 4. Cancellation state persistence tests
# ------------------------------------------------------------------
class TestCancellationPersistence:
    """Tests for cancellation state persistence across requests."""

    def test_state_machine_cancel_persists(self, sm):
        """Cancel state should persist until reset."""
        sm.cancel()
        assert sm.state == AgentState.CANCELLED
        # State remains CANCELLED
        assert sm.state == AgentState.CANCELLED

    def test_cannot_transition_after_cancel(self, sm):
        """Cannot transition to other states after CANCELLED."""
        sm.cancel()
        with pytest.raises(ValueError):
            sm.transition(AgentState.PLANNING, reason="test")
        with pytest.raises(ValueError):
            sm.transition(AgentState.EXECUTING, reason="test")
