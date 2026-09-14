"""
Provider Health Tracking and Failover.

Tracks provider health state and provides intelligent failover when
a provider returns 429, timeout, 5xx, or connection failures.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ProviderHealthState(str, Enum):
    """Health states for a provider."""
    CONFIGURED = "configured"         # Provider exists but not yet checked
    REACHABLE = "reachable"           # Health check passed
    MODELS_AVAILABLE = "models_available"  # Models discovered successfully
    CHAT_AVAILABLE = "chat_available"  # Chat endpoint works
    RATE_LIMITED = "rate_limited"     # 429 received
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"  # 5xx or timeout
    DISABLED = "disabled"             # Manually disabled by user
    UNKNOWN = "unknown"               # Health not yet determined


@dataclass
class ProviderHealth:
    """Health state for a single provider."""
    provider_id: str
    state: ProviderHealthState = ProviderHealthState.CONFIGURED
    last_health_check: float = 0.0  # monotonic timestamp
    last_success: float = 0.0
    last_failure: float = 0.0
    consecutive_failures: int = 0
    total_failures: int = 0
    rate_limit_until: float = 0.0  # monotonic timestamp when rate limit expires
    last_error: str = ""
    models_available: int = 0
    avg_latency_ms: float = 0.0
    _latency_samples: list[float] = field(default_factory=list)

    def record_success(self, latency_ms: float = 0) -> None:
        """Record a successful call."""
        self.last_success = time.monotonic()
        self.consecutive_failures = 0
        self.state = ProviderHealthState.CHAT_AVAILABLE
        if latency_ms > 0:
            self._latency_samples.append(latency_ms)
            if len(self._latency_samples) > 10:
                self._latency_samples = self._latency_samples[-10:]
            self.avg_latency_ms = sum(self._latency_samples) / len(self._latency_samples)

    def record_failure(self, error: str, is_rate_limit: bool = False) -> None:
        """Record a failed call."""
        self.last_failure = time.monotonic()
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_error = error[:200]

        if is_rate_limit:
            self.state = ProviderHealthState.RATE_LIMITED
            # Exponential backoff: 30s, 60s, 120s, max 300s
            backoff = min(30 * (2 ** min(self.consecutive_failures - 1, 4)), 300)
            self.rate_limit_until = time.monotonic() + backoff
            logger.warning(
                "Provider %s rate-limited, backing off %ds",
                self.provider_id, backoff,
            )
        elif self.consecutive_failures >= 3:
            self.state = ProviderHealthState.TEMPORARILY_UNAVAILABLE
            logger.warning(
                "Provider %s marked temporarily unavailable after %d consecutive failures",
                self.provider_id, self.consecutive_failures,
            )
        else:
            self.state = ProviderHealthState.TEMPORARILY_UNAVAILABLE

    def is_available(self) -> bool:
        """Check if provider is available for use."""
        if self.state == ProviderHealthState.DISABLED:
            return False
        if self.state == ProviderHealthState.RATE_LIMITED:
            if time.monotonic() < self.rate_limit_until:
                return False
            # Rate limit expired — allow retry
            self.state = ProviderHealthState.CONFIGURED
        if self.state == ProviderHealthState.TEMPORARILY_UNAVAILABLE:
            # Allow retry after 60s cooldown
            if time.monotonic() - self.last_failure < 60:
                return False
            self.state = ProviderHealthState.CONFIGURED
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "last_error": self.last_error,
            "models_available": self.models_available,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "is_available": self.is_available(),
        }


class ProviderHealthTracker:
    """Global tracker for all provider health states."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderHealth] = {}
        self._lock = asyncio.Lock()

    def get(self, provider_id: str) -> ProviderHealth:
        """Get or create health state for a provider."""
        if provider_id not in self._providers:
            self._providers[provider_id] = ProviderHealth(provider_id=provider_id)
        return self._providers[provider_id]

    def record_success(self, provider_id: str, latency_ms: float = 0) -> None:
        """Record a successful call to a provider."""
        health = self.get(provider_id)
        health.record_success(latency_ms)

    def record_failure(
        self, provider_id: str, error: str, is_rate_limit: bool = False
    ) -> None:
        """Record a failed call to a provider."""
        health = self.get(provider_id)
        health.record_failure(error, is_rate_limit)

    def get_available_providers(
        self, provider_ids: list[str] | None = None
    ) -> list[str]:
        """Return provider IDs that are available, sorted by health (best first)."""
        candidates = provider_ids or list(self._providers.keys())
        available = []
        for pid in candidates:
            health = self.get(pid)
            if health.is_available():
                available.append(pid)
        # Sort by: fewest failures, then lowest latency
        available.sort(
            key=lambda pid: (
                self.get(pid).consecutive_failures,
                self.get(pid).avg_latency_ms,
            )
        )
        return available

    def get_all_health(self) -> dict[str, dict[str, Any]]:
        """Return health state for all tracked providers."""
        return {pid: h.to_dict() for pid, h in self._providers.items()}

    def mark_disabled(self, provider_id: str) -> None:
        """Mark a provider as disabled."""
        health = self.get(provider_id)
        health.state = ProviderHealthState.DISABLED

    def mark_enabled(self, provider_id: str) -> None:
        """Mark a provider as enabled (re-enable)."""
        health = self.get(provider_id)
        if health.state == ProviderHealthState.DISABLED:
            health.state = ProviderHealthState.CONFIGURED


# Singleton instance
_health_tracker: ProviderHealthTracker | None = None

# Convenience alias for import
provider_health: ProviderHealthTracker | None = None


def get_health_tracker() -> ProviderHealthTracker:
    """Get the global provider health tracker singleton."""
    global _health_tracker, provider_health
    if _health_tracker is None:
        _health_tracker = ProviderHealthTracker()
        provider_health = _health_tracker
    return _health_tracker


def classify_provider_error(error: str) -> tuple[bool, str]:
    """Classify a provider error. Returns (is_rate_limit, friendly_message)."""
    low = error.lower()
    if "429" in low or "rate limit" in low or "too many requests" in low:
        return True, "Rate limited by provider"
    if "timeout" in low or "timed out" in low:
        return False, "Provider timed out"
    if "500" in low or "502" in low or "503" in low or "504" in low:
        return False, f"Provider server error: {error[:100]}"
    if "connection" in low and ("failed" in low or "refused" in low or "error" in low):
        return False, "Provider unreachable"
    if "401" in low or "403" in low or "unauthorized" in low or "forbidden" in low:
        return False, "Authentication failed"
    if "model" in low and ("not found" in low or "unavailable" in low):
        return False, "Model not available"
    return False, error[:100]
