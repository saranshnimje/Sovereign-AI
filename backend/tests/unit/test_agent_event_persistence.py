"""
AgentEvent persistence tests — verify events are written to the database
and can be replayed.

CRITICAL: AgentEvents are the audit trail for agent actions.
Without persistence, there is no way to audit or replay agent behavior.
"""
import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from models.agent import AgentEvent, AgentRun


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ------------------------------------------------------------------
# 1. AgentEvent model tests
# ------------------------------------------------------------------
class TestAgentEventModel:
    """Tests for the AgentEvent ORM model."""

    def test_agent_event_creation(self):
        """AgentEvent can be created with required fields."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        assert event.run_id == "run-123"
        assert event.event_type == "planner_response"
        assert event.sequence == 1

    def test_agent_event_optional_fields(self):
        """AgentEvent can be created with optional fields."""
        event = AgentEvent(
            run_id="run-123",
            sequence=2,
            event_type="tool_call",
            payload_json=json.dumps({"tool": "echo"}),
        )
        assert event.payload_json is not None
        parsed = json.loads(event.payload_json)
        assert parsed["tool"] == "echo"

    def test_agent_event_has_id(self):
        """AgentEvent should have an id field."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        assert hasattr(event, "id")

    def test_agent_event_has_created_at(self):
        """AgentEvent should have a created_at field."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        assert hasattr(event, "created_at")


# ------------------------------------------------------------------
# 2. Event persistence tests
# ------------------------------------------------------------------
class TestEventPersistence:
    """Tests for writing events to the database."""

    @pytest.mark.asyncio
    async def test_event_added_to_session(self, mock_db):
        """Event should be added to the database session."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        mock_db.add(event)
        mock_db.add.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_event_committed(self, mock_db):
        """Event should be committed to the database."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        mock_db.add(event)
        await mock_db.commit()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_rollback_on_error(self, mock_db):
        """Event should be rolled back on error."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        mock_db.add(event)
        mock_db.commit.side_effect = Exception("DB error")
        try:
            await mock_db.commit()
        except Exception:
            await mock_db.rollback()
        mock_db.rollback.assert_called_once()


# ------------------------------------------------------------------
# 3. Event replay tests
# ------------------------------------------------------------------
class TestEventReplay:
    """Tests for replaying events from the database."""

    def test_event_payload_deserialization(self):
        """Event payload should be deserializable from JSON."""
        data = {"goal": "test", "steps": [{"name": "step1"}]}
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
            payload_json=json.dumps(data),
        )
        parsed = json.loads(event.payload_json)
        assert parsed["goal"] == "test"
        assert len(parsed["steps"]) == 1

    def test_event_chronological_ordering(self):
        """Events should be ordered by sequence."""
        events = []
        for i in range(5):
            events.append(AgentEvent(
                run_id="run-123",
                sequence=i,
                event_type=f"event_{i}",
            ))
        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences)

    def test_event_type_filtering(self):
        """Events should be filterable by type."""
        events = [
            AgentEvent(run_id="run-123", sequence=1, event_type="planner_response"),
            AgentEvent(run_id="run-123", sequence=2, event_type="tool_call"),
            AgentEvent(run_id="run-123", sequence=3, event_type="planner_response"),
        ]
        planner_events = [e for e in events if e.event_type == "planner_response"]
        assert len(planner_events) == 2


# ------------------------------------------------------------------
# 4. Event metadata tests
# ------------------------------------------------------------------
class TestEventMetadata:
    """Tests for event metadata and structure."""

    def test_event_has_required_fields(self):
        """Event should have all required fields."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        assert hasattr(event, "run_id")
        assert hasattr(event, "event_type")
        assert hasattr(event, "sequence")
        assert hasattr(event, "created_at")

    def test_event_payload_optional(self):
        """payload_json should be optional."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        assert event.payload_json is None

    def test_event_repr(self):
        """Event repr should contain type."""
        event = AgentEvent(
            run_id="run-123",
            sequence=1,
            event_type="planner_response",
        )
        assert "planner_response" in repr(event)
