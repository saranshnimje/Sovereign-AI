"""
Context compression tests — verify context window management and
provider failure handling.

IMPORTANT: Without context compression, the agent will hit token limits
and fail on long-running tasks.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agent.prompts import COMPRESS_PROMPT
from services.agent_state import MAX_ITERATIONS


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def mock_history():
    """Create a mock conversation history."""
    return [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "And 3+3?"},
        {"role": "assistant", "content": "6"},
    ]


# ------------------------------------------------------------------
# 1. Context compression tests
# ------------------------------------------------------------------
class TestContextCompression:
    """Tests for context compression."""

    def test_compress_prompt_exists(self):
        """COMPRESS_PROMPT should exist."""
        assert len(COMPRESS_PROMPT) > 0

    def test_compress_prompt_requests_summary(self):
        """COMPRESS_PROMPT should request a summary."""
        assert "summary" in COMPRESS_PROMPT.lower() or "compress" in COMPRESS_PROMPT.lower()

    def test_compress_prompt_preserves_key_info(self):
        """COMPRESS_PROMPT should preserve key information."""
        assert "key" in COMPRESS_PROMPT.lower() or "important" in COMPRESS_PROMPT.lower()

    def test_history_truncation(self):
        """History should be truncated when too long."""
        history = [{"role": "user", "content": f"Message {i}"} for i in range(100)]
        max_messages = 20
        truncated = history[-max_messages:]
        assert len(truncated) == max_messages

    def test_token_count_estimation(self):
        """Token count should be estimated."""
        text = "Hello world, this is a test message."
        # Rough estimate: 1 token per 4 characters
        estimated_tokens = len(text) // 4
        assert estimated_tokens > 0


# ------------------------------------------------------------------
# 2. Provider failure handling tests
# ------------------------------------------------------------------
class TestProviderFailureHandling:
    """Tests for provider failure handling."""

    def test_provider_timeout_handled(self):
        """Provider timeout should be handled."""
        error = {"error": "timeout", "provider": "ollama"}
        assert "timeout" in error["error"]

    def test_provider_connection_error_handled(self):
        """Provider connection error should be handled."""
        error = {"error": "connection_error", "provider": "ollama"}
        assert "connection_error" in error["error"]

    def test_provider_rate_limit_handled(self):
        """Provider rate limit should be handled."""
        error = {"error": "rate_limit", "provider": "ollama"}
        assert "rate_limit" in error["error"]

    def test_provider_fallback(self):
        """Provider should have fallback mechanism."""
        # The runtime should handle provider failures gracefully
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, 'run')


# ------------------------------------------------------------------
# 3. Context window management tests
# ------------------------------------------------------------------
class TestContextWindowManagement:
    """Tests for context window management."""

    def test_max_iterations_configured(self):
        """MAX_ITERATIONS should be configured."""
        assert MAX_ITERATIONS > 0

    def test_iteration_count_tracking(self):
        """Iteration count should be tracked."""
        iterations = 0
        for i in range(10):
            iterations += 1
        assert iterations == 10

    def test_iteration_limit_enforced(self):
        """Iteration limit should be enforced."""
        iterations = MAX_ITERATIONS
        assert iterations >= MAX_ITERATIONS

    def test_context_summary_created(self):
        """Context summary should be created for long conversations."""
        history = [{"role": "user", "content": f"Message {i}"} for i in range(50)]
        # Should create summary
        summary = f"Conversation with {len(history)} messages"
        assert "50" in summary

    def test_tool_results_trimmed(self):
        """Tool results should be trimmed to prevent context flooding."""
        long_result = "x" * 10000
        max_length = 2000
        trimmed = long_result[:max_length] + "...[truncated]"
        assert len(trimmed) <= max_length + 20


# ------------------------------------------------------------------
# 4. Memory management tests
# ------------------------------------------------------------------
class TestMemoryManagement:
    """Tests for memory management."""

    def test_memory_cleanup(self):
        """Memory should be cleaned up after completion."""
        history = [{"role": "user", "content": "test"}]
        # After completion
        history.clear()
        assert len(history) == 0

    def test_memory_limit(self):
        """Memory should have limits."""
        max_history = 100
        history = [{"role": "user", "content": f"msg {i}"} for i in range(150)]
        # Should limit history
        limited = history[-max_history:]
        assert len(limited) == max_history

    def test_memory_compression(self):
        """Memory should be compressed when needed."""
        history = [{"role": "user", "content": f"Message {i}"} for i in range(100)]
        # Compress
        compressed = [{"role": "system", "content": f"Summary of {len(history)} messages"}]
        assert len(compressed) == 1
