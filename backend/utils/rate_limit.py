"""
In-process sliding-window rate limiter for security-sensitive endpoints.

Design notes
------------
- Sliding window counters kept in memory, keyed by client IP + scope.
- Client IP resolution mirrors AuditService._extract_client_ip: trusts
  X-Real-IP ONLY as set by our nginx reverse proxy; direct connections use
  the TCP peer address. X-Forwarded-For is deliberately ignored (spoofable).
- Single-node scope: with multiple uvicorn workers each process enforces
  its own bucket (documented limitation; acceptable for the on-prem MVP).
- Limits come from Settings so operators can tune/disable via environment.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from config import get_settings


class SlidingWindowLimiter:
    """Thread-safe fixed-history sliding-window counter."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_gc = time.monotonic()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        """Return True when `key` may proceed within limit/window."""
        now = time.monotonic()
        cutoff = now - window_s
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            allowed = len(q) < limit
            if allowed:
                q.append(now)
            # Opportunistic GC to bound memory under churn
            if now - self._last_gc > 300:
                for k in list(self._hits.keys()):
                    old = self._hits[k]
                    while old and old[0] <= cutoff:
                        old.popleft()
                    if not old:
                        del self._hits[k]
                self._last_gc = now
            return allowed

    def retry_after(self, key: str, window_s: float) -> int:
        """Seconds until the oldest hit leaves the window (min 1)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 1
            remaining = q[0] + window_s - now
            return max(1, int(remaining) + 1)

    def reset(self) -> None:
        """Clear all buckets (used by tests and admin tooling)."""
        with self._lock:
            self._hits.clear()


# Shared limiter instances, one per scope family
limiters: dict[str, SlidingWindowLimiter] = {
    "auth": SlidingWindowLimiter(),
    "upload": SlidingWindowLimiter(),
    "ai": SlidingWindowLimiter(),
}


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("X-Real-IP")
    if real_ip and real_ip.strip():
        return f"xri:{real_ip.strip()}"
    return f"tcp:{getattr(request.client, 'host', 'unknown')}"


def rate_limit(scope: str):
    """
    Dependency factory enforcing a per-client-IP sliding-window limit.

    Scopes and defaults (Settings-overridable):
      auth   — 30 / minute   (login, register, refresh)
      upload — 30 / minute   (document uploads)
      ai     — 120 / minute  (chat messages, KB queries, agent runs)

    Raises HTTPException 429 with Retry-After when exceeded.
    """

    async def _check(request: Request) -> None:
        s = get_settings()
        if not s.rate_limit_enabled:
            return

        limit_for_scope = {
            "auth": s.rate_limit_auth_per_min,
            "upload": s.rate_limit_upload_per_min,
            "ai": s.rate_limit_ai_per_min,
        }
        limit = limit_for_scope.get(scope)
        if not limit or limit <= 0:
            return

        limiter = limiters[scope]
        key = _client_ip(request)
        window_s = 60.0
        if not limiter.allow(key, limit, window_s):
            raise HTTPException(
                429,
                detail=f"Rate limit exceeded ({limit}/min). Try again shortly.",
                headers={"Retry-After": str(limiter.retry_after(key, window_s))},
            )

    return _check


# Ready-made dependencies for routers
auth_rate_limit = rate_limit("auth")
upload_rate_limit = rate_limit("upload")
ai_rate_limit = rate_limit("ai")
