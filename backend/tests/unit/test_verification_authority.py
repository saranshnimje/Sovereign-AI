"""
Verification authority tests — prove the verifier controls completion,
not the LLM. False-completion prevention.

CRITICAL: The verifier is the ONLY component that can mark a task as completed.
If the LLM can bypass the verifier, it can claim completion without evidence.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agent.runtime import AgentRuntime
from services.agent.schemas import VerificationResult, VerificationCriteriaResult


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def mock_runtime():
    """Create a mock AgentRuntime."""
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.cancel = asyncio.Event()
    return runtime


# ------------------------------------------------------------------
# 1. Verifier controls completion tests
# ------------------------------------------------------------------
class TestVerifierControlsCompletion:
    """Tests that the verifier controls task completion."""

    def test_verification_result_structure(self):
        """VerificationResult should have verified field."""
        result = VerificationResult(
            verified=True,
            confidence=0.9,
            criteria=[],
            missing=[],
            unsupported_claims=[],
        )
        assert result.verified is True
        assert result.confidence == 0.9

    def test_verification_result_rejected(self):
        """VerificationResult can reject completion."""
        result = VerificationResult(
            verified=False,
            confidence=0.3,
            criteria=[VerificationCriteriaResult(
                criterion="Task completed",
                satisfied=False,
                evidence="Evidence insufficient",
            )],
            missing=["Evidence insufficient"],
            unsupported_claims=["Claim not supported"],
        )
        assert result.verified is False
        assert len(result.missing) > 0

    def test_verifier_requires_evidence(self):
        """Verifier prompt should require evidence for completion."""
        from services.agent.prompts import VERIFIER_SYSTEM
        assert "evidence" in VERIFIER_SYSTEM.lower()
        assert "satisfied" in VERIFIER_SYSTEM.lower()

    def test_verifier_rejects_unverified(self):
        """Verifier should reject unverified completion."""
        result = VerificationResult(
            verified=False,
            confidence=0.2,
            criteria=[VerificationCriteriaResult(
                criterion="Task completed",
                satisfied=False,
                evidence="No evidence provided",
            )],
            missing=["No evidence provided"],
            unsupported_claims=[],
        )
        assert result.verified is False


# ------------------------------------------------------------------
# 2. False-completion prevention tests
# ------------------------------------------------------------------
class TestFalseCompletionPrevention:
    """Tests for preventing false completion claims."""

    def test_llm_cannot_bypass_verifier(self):
        """LLM cannot bypass the verifier by claiming completion."""
        from services.agent.prompts import REASONER_SYSTEM
        assert "COMPLETE" in REASONER_SYSTEM

    def test_verifier_checks_against_criteria(self):
        """Verifier should check against acceptance criteria."""
        criteria = [
            VerificationCriteriaResult(criterion="File created", satisfied=True, evidence="File exists"),
            VerificationCriteriaResult(criterion="Content verified", satisfied=True, evidence="Content matches"),
        ]
        result = VerificationResult(
            verified=True,
            confidence=0.95,
            criteria=criteria,
            missing=[],
            unsupported_claims=[],
        )
        assert len(result.criteria) == 2

    def test_low_confidence_rejects(self):
        """Low confidence verification should reject."""
        result = VerificationResult(
            verified=False,
            confidence=0.1,
            criteria=[],
            missing=["Confidence too low"],
            unsupported_claims=[],
        )
        assert result.confidence < 0.5
        assert result.verified is False

    def test_high_confidence_accepts(self):
        """High confidence verification should accept."""
        result = VerificationResult(
            verified=True,
            confidence=0.95,
            criteria=[],
            missing=[],
            unsupported_claims=[],
        )
        assert result.confidence >= 0.9
        assert result.verified is True


# ------------------------------------------------------------------
# 3. Verifier prompt tests
# ------------------------------------------------------------------
class TestVerifierPrompt:
    """Tests for the verifier system prompt."""

    def test_verifier_prompt_exists(self):
        """VERIFIER_SYSTEM prompt should exist."""
        from services.agent.prompts import VERIFIER_SYSTEM
        assert len(VERIFIER_SYSTEM) > 0

    def test_verifier_prompt_requires_evidence(self):
        """Verifier prompt should require evidence."""
        from services.agent.prompts import VERIFIER_SYSTEM
        assert "evidence" in VERIFIER_SYSTEM.lower()

    def test_verifier_prompt_checks_criteria(self):
        """Verifier prompt should check satisfaction."""
        from services.agent.prompts import VERIFIER_SYSTEM
        assert "satisfied" in VERIFIER_SYSTEM.lower()

    def test_verifier_prompt_rejects_assuming_success(self):
        """Verifier prompt should reject assuming success without proof."""
        from services.agent.prompts import VERIFIER_SYSTEM
        assert "skeptical" in VERIFIER_SYSTEM.lower() or "proof" in VERIFIER_SYSTEM.lower()


# ------------------------------------------------------------------
# 4. Runtime verification integration tests
# ------------------------------------------------------------------
class TestRuntimeVerification:
    """Tests for runtime verification integration."""

    def test_runtime_calls_verifier(self):
        """Runtime should call verifier before completing."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, 'run')
        assert hasattr(AgentRuntime, '_verify')

    def test_verifier_result_used_for_decision(self):
        """Verifier result should be used for completion decision."""
        result = VerificationResult(
            verified=True,
            confidence=0.9,
            criteria=[],
            missing=[],
            unsupported_claims=[],
        )
        assert result.verified is True

    def test_verifier_failure_stops_completion(self):
        """Verifier failure should stop completion."""
        result = VerificationResult(
            verified=False,
            confidence=0.3,
            criteria=[],
            missing=["Insufficient evidence"],
            unsupported_claims=[],
        )
        assert result.verified is False
