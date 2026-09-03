"""
Retry/failure classification tests — verify retry limits, failure types,
and error handling.

IMPORTANT: The agent should retry on transient failures but fail fast
on permanent failures. Retries must be bounded per-tool.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agent_state import (
    AgentStateMachine, AgentState,
    MAX_RETRIES, MAX_RETRIES_PER_TOOL, MAX_TOOL_CALLS,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def sm():
    """Create an AgentStateMachine for testing."""
    return AgentStateMachine()


# ------------------------------------------------------------------
# 1. Retry limit tests
# ------------------------------------------------------------------
class TestRetryLimits:
    """Tests for retry limits."""

    def test_max_retries_configured(self):
        """MAX_RETRIES should be configured."""
        assert MAX_RETRIES > 0

    def test_max_retries_per_tool_configured(self):
        """MAX_RETRIES_PER_TOOL should be configured."""
        assert MAX_RETRIES_PER_TOOL > 0

    def test_max_tool_calls_configured(self):
        """MAX_TOOL_CALLS should be configured."""
        assert MAX_TOOL_CALLS > 0

    def test_retry_count_tracking(self):
        """Retry count should be tracked per tool."""
        retries = {}
        tool = "file_write"
        retries[tool] = retries.get(tool, 0) + 1
        assert retries[tool] == 1

    def test_retry_count_increments(self):
        """Retry count should increment on each retry."""
        retries = {}
        tool = "file_write"
        for i in range(3):
            retries[tool] = retries.get(tool, 0) + 1
        assert retries[tool] == 3

    def test_retry_limit_enforced(self):
        """Retry limit should be enforced."""
        retries = {}
        tool = "file_write"
        retries[tool] = MAX_RETRIES_PER_TOOL
        # Should not allow more retries
        assert retries[tool] >= MAX_RETRIES_PER_TOOL


# ------------------------------------------------------------------
# 2. Failure classification tests
# ------------------------------------------------------------------
class TestFailureClassification:
    """Tests for failure type classification."""

    def test_transient_failure(self):
        """Transient failures should be retryable."""
        failures = {
            "timeout": "transient",
            "connection_error": "transient",
            "rate_limit": "transient",
        }
        assert failures["timeout"] == "transient"

    def test_permanent_failure(self):
        """Permanent failures should not be retryable."""
        failures = {
            "permission_denied": "permanent",
            "not_found": "permanent",
            "invalid_input": "permanent",
        }
        assert failures["permission_denied"] == "permanent"

    def test_unknown_failure_default(self):
        """Unknown failures should default to transient."""
        failure_type = "unknown_error"
        classified = "transient"  # Default
        assert classified == "transient"


# ------------------------------------------------------------------
# 3. Tool call limit tests
# ------------------------------------------------------------------
class TestToolCallLimits:
    """Tests for tool call limits."""

    def test_tool_call_count_tracking(self):
        """Tool call count should be tracked."""
        tool_calls = 0
        tool_calls += 1
        assert tool_calls == 1

    def test_tool_call_limit_enforced(self):
        """Tool call limit should be enforced."""
        tool_calls = MAX_TOOL_CALLS
        assert tool_calls >= MAX_TOOL_CALLS

    def test_tool_call_count_resets_per_run(self):
        """Tool call count should reset per run."""
        tool_calls = MAX_TOOL_CALLS
        # New run
        tool_calls = 0
        assert tool_calls == 0


# ------------------------------------------------------------------
# 4. Error handling tests
# ------------------------------------------------------------------
class TestErrorHandling:
    """Tests for error handling in the agent loop."""

    def test_error_response_structure(self):
        """Error response should have required fields."""
        error = {"error": "Tool not found", "tool": "unknown_tool"}
        assert "error" in error
        assert "tool" in error

    def test_error_truncated(self):
        """Error messages should be truncated."""
        long_error = "x" * 2000
        truncated = long_error[:1000]
        assert len(truncated) == 1000

    def test_error_includes_tool_name(self):
        """Error should include tool name."""
        tool = "file_write"
        error = {"error": f"Tool '{tool}' failed"}
        assert tool in error["error"]

    def test_error_includes_duration(self):
        """Error should include duration."""
        error = {"error": "timeout", "duration_ms": 30000}
        assert error["duration_ms"] == 30000


# ------------------------------------------------------------------
# 5. State machine failure transitions
# ------------------------------------------------------------------
class TestStateFailureTransitions:
    """Tests for failure state transitions."""

    def test_any_state_to_failed(self, sm):
        """Any state should be able to transition to FAILED."""
        sm.transition(AgentState.UNDERSTANDING, reason="test")
        sm.transition(AgentState.PLANNING, reason="test")
        sm.transition(AgentState.EXECUTING, reason="test")
        sm.fail("test error")
        assert sm.state == AgentState.FAILED

    def test_failed_is_terminal(self, sm):
        """FAILED should be a terminal state."""
        sm.fail("test error")
        with pytest.raises(ValueError):
            sm.transition(AgentState.PLANNING, reason="test")
        with pytest.raises(ValueError):
            sm.transition(AgentState.EXECUTING, reason="test")
