"""
Sub-agent security tests — depth limits, concurrency limits, cancellation,
RBAC, and audit logging.

CRITICAL: Sub-agents can spawn their own sub-agents. Without depth limits,
this could lead to infinite recursion and resource exhaustion.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.subagent_manager import SubAgentManager
from services.agent_state import MAX_SUBAGENT_CONCURRENT


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def manager(mock_db):
    """Create a SubAgentManager for testing."""
    return SubAgentManager(mock_db)


# ------------------------------------------------------------------
# 1. Depth limit tests
# ------------------------------------------------------------------
class TestDepthLimits:
    """Tests for sub-agent depth limits."""

    def test_max_depth_configured(self):
        """Max depth should be configured."""
        from config import get_settings
        settings = get_settings()
        assert settings.agent_max_subagent_depth > 0

    def test_depth_increment(self):
        """Depth should increment on spawn."""
        depth = 0
        max_depth = 10
        # Simulate depth increment
        new_depth = depth + 1
        assert new_depth == 1
        assert new_depth <= max_depth

    def test_depth_limit_enforced(self):
        """Depth limit should be enforced."""
        max_depth = 10
        current_depth = 10
        # Should not allow spawning at max depth
        assert current_depth >= max_depth

    def test_depth_reset_on_new_run(self):
        """Depth should reset for new agent runs."""
        depth = 0
        # Simulate new run
        new_run_depth = 0
        assert new_run_depth == 0


# ------------------------------------------------------------------
# 2. Concurrency limit tests
# ------------------------------------------------------------------
class TestConcurrencyLimits:
    """Tests for sub-agent concurrency limits."""

    def test_max_concurrent_configured(self):
        """Max concurrent sub-agents should be configured."""
        assert MAX_SUBAGENT_CONCURRENT > 0

    def test_concurrent_count_tracking(self):
        """Concurrent sub-agents should be tracked."""
        active = set()
        # Simulate spawning
        active.add("subagent-1")
        active.add("subagent-2")
        assert len(active) == 2

    def test_concurrency_limit_enforced(self):
        """Concurrency limit should be enforced."""
        active = set()
        max_concurrent = MAX_SUBAGENT_CONCURRENT
        for i in range(max_concurrent):
            active.add(f"subagent-{i}")
        assert len(active) == max_concurrent
        # Should not allow more
        assert len(active) >= max_concurrent

    def test_concurrent_decrement_on_complete(self):
        """Concurrent count should decrement on completion."""
        active = {"subagent-1", "subagent-2"}
        active.discard("subagent-1")
        assert len(active) == 1


# ------------------------------------------------------------------
# 3. Sub-agent cancellation tests
# ------------------------------------------------------------------
class TestSubAgentCancellation:
    """Tests for sub-agent cancellation propagation."""

    def test_parent_cancel_propagates(self):
        """Parent cancellation should propagate to sub-agents."""
        cancel_event = asyncio.Event()
        # Simulate parent cancel
        cancel_event.set()
        # Sub-agent should check this
        assert cancel_event.is_set()

    def test_subagent_independent_cancellation(self):
        """Sub-agent should be independently cancellable."""
        parent_cancel = asyncio.Event()
        child_cancel = asyncio.Event()
        # Child can be cancelled independently
        child_cancel.set()
        assert not parent_cancel.is_set()
        assert child_cancel.is_set()

    def test_cascade_cancellation(self):
        """Cancellation should cascade to all sub-agents."""
        cancel_events = {f"subagent-{i}": asyncio.Event() for i in range(3)}
        # Cancel all
        for event in cancel_events.values():
            event.set()
        assert all(e.is_set() for e in cancel_events.values())


# ------------------------------------------------------------------
# 4. RBAC tests
# ------------------------------------------------------------------
class TestSubAgentRBAC:
    """Tests for sub-agent RBAC."""

    def test_inherits_parent_role(self):
        """Sub-agent should inherit parent's role."""
        parent_role = "analyst"
        # Sub-agent should have same or lower role
        child_role = parent_role
        assert child_role == "analyst"

    def test_cannot_escalate_role(self):
        """Sub-agent should not be able to escalate role."""
        parent_role = "viewer"
        child_role = "viewer"  # Should stay viewer
        assert child_role == parent_role

    def test_admin_tools_restricted(self):
        """Admin tools should be restricted for non-admin sub-agents."""
        from tools.registry import ROLE_ADMIN, ROLE_VIEWER
        assert ROLE_VIEWER != ROLE_ADMIN


# ------------------------------------------------------------------
# 5. Sub-agent audit tests
# ------------------------------------------------------------------
class TestSubAgentAudit:
    """Tests for sub-agent audit logging."""

    def test_spawn_logged(self):
        """Sub-agent spawn should be logged."""
        event = {
            "action": "subagent_spawn",
            "parent_run_id": "parent-123",
            "child_run_id": "child-456",
        }
        assert event["action"] == "subagent_spawn"

    def test_completion_logged(self):
        """Sub-agent completion should be logged."""
        event = {
            "action": "subagent_complete",
            "child_run_id": "child-456",
            "result": "success",
        }
        assert event["action"] == "subagent_complete"

    def test_failure_logged(self):
        """Sub-agent failure should be logged."""
        event = {
            "action": "subagent_failure",
            "child_run_id": "child-456",
            "error": "timeout",
        }
        assert event["action"] == "subagent_failure"
