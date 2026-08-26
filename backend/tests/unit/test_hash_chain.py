"""Unit tests for audit log hash chain logic."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from services.audit_service import AuditService, compute_hash, GENESIS_HASH


@pytest.mark.asyncio
async def test_compute_hash_returns_64_char_hex():
    h = compute_hash(1, "2026-01-01T00:00:00+00:00", None, "auth.login", "success", GENESIS_HASH)
    assert isinstance(h, str)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


@pytest.mark.asyncio
async def test_hash_is_deterministic():
    h1 = compute_hash(1, "2026-01-01T00:00:00+00:00", "uid", "auth.login", "success", GENESIS_HASH)
    h2 = compute_hash(1, "2026-01-01T00:00:00+00:00", "uid", "auth.login", "success", GENESIS_HASH)
    assert h1 == h2


@pytest.mark.asyncio
async def test_different_inputs_different_hashes():
    h1 = compute_hash(1, "ts", "u1", "action", "success", GENESIS_HASH)
    h2 = compute_hash(1, "ts", "u2", "action", "success", GENESIS_HASH)
    assert h1 != h2


@pytest.mark.asyncio
async def test_audit_log_chain_integrity(db):
    service = AuditService(db)
    for i in range(5):
        await service.log(
            event_type="auth",
            action=f"test.action.{i}",
            outcome="success",
            user_id=None,
        )
    await db.flush()

    result = await service.verify_chain()
    assert result["verified"] is True
    assert result["entries_checked"] == 5
    assert result["first_error_at_sequence"] is None


@pytest.mark.asyncio
async def test_empty_chain_is_valid(db):
    service = AuditService(db)
    result = await service.verify_chain()
    assert result["verified"] is True
    assert result["entries_checked"] == 0


@pytest.mark.asyncio
async def test_single_entry_chain(db):
    service = AuditService(db)
    await service.log("auth", "user.login", "success", user_id=None)
    await db.flush()
    result = await service.verify_chain()
    assert result["verified"] is True
    assert result["entries_checked"] == 1
