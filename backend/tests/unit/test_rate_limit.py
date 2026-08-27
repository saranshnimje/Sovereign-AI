"""
Unit + integration tests for rate limiting (P0.6).

The general suite runs with RATE_LIMIT_ENABLED=false (see conftest).
These tests explicitly enable it, exercise REAL endpoints, verify 429 +
Retry-After, and restore state afterwards.
"""
import os

import pytest
from httpx import AsyncClient


@pytest.fixture
def enable_rate_limits(monkeypatch):
    """Enable limiting and shrink the auth window for fast testing."""
    from utils import rate_limit as rl

    # Drive via env + targeted cache resets. NOTE: other test modules may
    # importlib.reload(config), leaving multiple get_settings objects around;
    # clear the EXACT one the rate-limit dependency dereferences.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "5")
    monkeypatch.delenv("DATA_DIR", raising=False)

    rl.get_settings.cache_clear()          # what the limiter actually reads
    try:
        import config
        config.get_settings.cache_clear()
    except AttributeError:
        pass

    rl.limiters["auth"].reset()
    yield

    rl.limiters["auth"].reset()
    rl.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_burst_returns_429_with_retry_after(client: AsyncClient, enable_rate_limits):
    await client.post("/api/v1/auth/register", json={
        "email": "rl@test.com", "username": "rluser", "password": "StrongPass123!"
    })
    login = {"email": "rl@test.com", "password": "wrongpass"}

    statuses: list[int] = []
    retry_after: str | None = None
    for _ in range(10):
        r = await client.post("/api/v1/auth/login", json=login)
        statuses.append(r.status_code)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            break

    assert 429 in statuses, f"expected a 429 among {statuses}"
    assert statuses.count(429) == 1 or all(s == 429 for s in statuses[statuses.index(429):])
    assert retry_after is not None and int(retry_after) >= 1


@pytest.mark.asyncio
async def test_limiter_allows_within_burst(client: AsyncClient, enable_rate_limits):
    from utils.rate_limit import limiters, _client_ip
    limiter = limiters["auth"]

    class FakeRequest:
        headers = {}
        class C:
            host = "203.0.113.9"
        client = C()

    ip = _client_ip(FakeRequest())
    assert all(limiter.allow(ip, 5, 60.0) for _ in range(5))
    assert not limiter.allow(ip, 5, 60.0)          # 6th blocked
    assert limiter.retry_after(ip, 60.0) >= 1


@pytest.mark.asyncio
async def test_disabled_limiter_never_blocks(client: AsyncClient):
    """Default suite configuration: RATE_LIMIT_ENABLED=false ⇒ no 429s."""
    for i in range(12):
        r = await client.post("/api/v1/auth/login", json={
            "email": f"nobody{i}@nowhere.test", "password": "NotTheRightPass1!"})
        # Point of this test: no request may be rejected for RATE (429).
        assert r.status_code != 429, f"got 429 with limiter disabled: {r.status_code}"


@pytest.mark.asyncio
async def test_x_real_ip_keys_buckets_separately(enable_rate_limits):
    """Two clients behind the proxy get independent buckets."""
    from utils.rate_limit import limiters, _client_ip

    class FakeRequest:
        def __init__(self, ip):
            self.headers = {"X-Real-IP": ip} if ip else {}
            self.client = None

    a = _client_ip(FakeRequest("198.51.100.1"))
    b = _client_ip(FakeRequest("198.51.100.2"))
    c = _client_ip(FakeRequest(None))

    assert a != b != c and a != c
    limiter = limiters["auth"]
    assert all(limiter.allow(a, 5, 60.0) for _ in range(5))
    assert not limiter.allow(a, 5, 60.0)
    assert limiter.allow(b, 5, 60.0)               # different bucket unaffected
