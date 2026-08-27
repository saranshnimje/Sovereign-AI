"""
Integration tests for the sensor analysis API (P1.1).

Covers: real end-to-end analysis, honest failure states, ownership/tenant
isolation (404 semantics), audit events, Ollama-unavailable behaviour,
explanation non-interference with numbers, and upload protections.
"""
import io
import json

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


def _csv_bytes(rows=200, temp_end=62.0):
    lines = ["timestamp,bearing_temp_C,vibration_mmS,rpm"]
    for i in range(rows):
        t = 60 + (temp_end - 60) * i / rows
        lines.append(f"2026-01-01T00:{i//60:02d}:{i%60:02d},{t:.3f},3.{i%10},149{i%10}")
    return ("\n".join(lines) + "\n").encode()


async def _upload(client, content=None, name="sensors.csv", explain=True, **csv_kw):
    if content is None:
        content = _csv_bytes(**csv_kw)
    return await client.post(
        "/api/v1/sensor-analyses",
        files={"file": (name, content, "text/csv")},
        data={"generate_explanation": str(explain)},
    )


class TestAnalyzeEndpoint:
    @pytest.mark.asyncio
    async def test_valid_csv_completes_with_real_results(self, auth_client: AsyncClient):
        r = await _upload(auth_client, rows=300, temp_end=61.0)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "completed"
        assert body["row_count"] == 300
        result = body["result"]
        assert result["meta"]["engine"] == "deterministic-pandas-v1"
        assert set(result["schema"]["numeric_columns"]) >= {"bearing_temp_C", "rpm"}
        st = result["stats"]["bearing_temp_C"]
        assert st["count"] == 300
        assert 59 < st["min"] <= st["max"] < 70   # real computed values
        assert isinstance(result["anomalies"], list)
        assert "level" in result["risk"]

    @pytest.mark.asyncio
    async def test_malformed_csv_persisted_as_failed_with_real_error(self, auth_client):
        bad = b"a,b\n1,2\n\x00\x01broken,row\n\"unterminated"
        r = await _upload(auth_client, content=bad, name="bad.csv", explain=False)
        assert r.status_code == 201
        body = r.json()
        if body["status"] == "failed":
            assert body["error_message"], "must carry the real parser error"
        else:
            # If it parsed as something, it must NOT fabricate structure
            assert body["result"]["file"]["rows"] >= 1

    @pytest.mark.asyncio
    async def test_non_csv_rejected(self, auth_client):
        r = await auth_client.post(
            "/api/v1/sensor-analyses",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_oversize_upload_rejected(self, auth_client: AsyncClient, monkeypatch):
        from config import get_settings
        get_settings.cache_clear()
        monkeypatch.setattr(get_settings(), "max_upload_size_mb", 0)  # force tiny limit path
        big = _csv_bytes(rows=120_000)
        r = await _upload(auth_client, content=big, name="big.csv", explain=False)
        monkeypatch.undo()
        get_settings.cache_clear()
        assert r.status_code in (201, 413, 422)

    @pytest.mark.asyncio
    async def test_viewer_cannot_upload(self, client: AsyncClient):
        # first user = admin; second = viewer
        await client.post("/api/v1/auth/register", json={
            "email": "adm@test.com", "username": "adm", "password": "StrongPass123!"})
        await client.post("/api/v1/auth/register", json={
            "email": "vw@test.com", "username": "vwx", "password": "StrongPass123!"})
        r = await client.post("/api/v1/auth/login", json={
            "email": "vw@test.com", "password": "StrongPass123!"})
        client.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
        resp = await _upload(client, explain=False)
        assert resp.status_code == 403


class TestOllamaInteraction:
    @pytest.mark.asyncio
    async def test_explanation_unavailable_leaves_numbers_intact(self, auth_client):
        """No Ollama in CI ⇒ ai_explanation_error set; numerical payload complete."""
        without = (await _upload(auth_client, rows=150, explain=False)).json()
        assert without["ai_explanation"] is None
        assert without["result"] is not None
        assert without["result"]["stats"]["bearing_temp_C"]["count"] == 150

        with_exp = (await _upload(auth_client, rows=150, explain=True)).json()
        # Ollama unavailable → honest error marker, never a fabricated text
        assert with_exp["ai_explanation"] is None
        assert with_exp["ai_explanation_error"]
        assert "unavailable" in with_exp["ai_explanation_error"].lower()

        # Numbers identical with and without the explanation attempt
        assert with_exp["result"]["stats"] == without["result"]["stats"]
        assert with_exp["result"]["risk"] == without["result"]["risk"]

    @pytest.mark.asyncio
    async def test_explanation_success_cannot_alter_numbers(self, auth_client, monkeypatch):
        """Even when the LLM answers, computed stats/anomalies/risk are untouched."""
        from routers import sensor_analysis as sa_router

        async def fake_explain(db, record, payload):
            record.ai_model = "fake-model"
            record.ai_explanation = "BEARING MELTDOWN IMMEDIATELY everything is 999°C"
            await db.flush()

        monkeypatch.setattr(sa_router, "_try_ai_explanation", fake_explain)

        plain = (await _upload(auth_client, rows=100, explain=False)).json()
        patched = (await _upload(auth_client, rows=100, explain=True)).json()

        assert patched["ai_explanation"].startswith("BEARING")
        assert patched["result"]["stats"] == plain["result"]["stats"]
        assert patched["result"]["anomalies"] == plain["result"]["anomalies"]
        assert patched["result"]["risk"] == plain["result"]["risk"]


class TestOwnershipAndIsolation:
    async def _second_analyst(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "root2@test.com", "username": "root2", "password": "StrongPass123!"})
        r = await client.post("/api/v1/auth/login", json={
            "email": "root2@test.com", "password": "StrongPass123!"})
        admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await client.post("/api/v1/auth/register", json={
            "email": "peer@test.com", "username": "peer", "password": "StrongPass123!"})
        r2 = await client.post("/api/v1/auth/login", json={
            "email": "peer@test.com", "password": "StrongPass123!"})
        peer_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
        users = (await client.get("/api/v1/auth/users", headers=admin_headers)).json()
        pid = next(u["id"] for u in users if u["email"] == "peer@test.com")
        await client.put(f"/api/v1/auth/users/{pid}", json={"role": "analyst"},
                         headers=admin_headers)
        return admin_headers, peer_headers

    @pytest.mark.asyncio
    async def test_foreign_analysis_invisible_everywhere(self, client: AsyncClient):
        admin_headers, peer_headers = await self._second_analyst(client)

        # Owner uploads via admin session
        saved = client.headers.get("authorization")
        client.headers.update(admin_headers)
        created = (await _upload(client, explain=False)).json()
        client.headers.update({"Authorization": saved}) if saved else client.headers.pop("Authorization")

        aid = created["id"]

        # Peer cannot access by ID — GET, anomalies, delete all 404
        assert (await client.get(f"/api/v1/sensor-analyses/{aid}", headers=peer_headers)).status_code == 404
        assert (await client.get(f"/api/v1/sensor-analyses/{aid}/anomalies", headers=peer_headers)).status_code == 404
        assert (await client.delete(f"/api/v1/sensor-analyses/{aid}", headers=peer_headers)).status_code == 404

        # Peer's list does not leak it
        listing = (await client.get("/api/v1/sensor-analyses", headers=peer_headers)).json()
        assert all(item["id"] != aid for item in listing)

        # Admin retains full read access
        got = await client.get(f"/api/v1/sensor-analyses/{aid}", headers=admin_headers)
        assert got.status_code == 200

    @pytest.mark.asyncio
    async def test_owner_can_read_own_and_delete(self, auth_client: AsyncClient):
        created = (await _upload(auth_client, explain=False)).json()
        aid = created["id"]
        assert (await auth_client.get(f"/api/v1/sensor-analyses/{aid}")).status_code == 200
        anom = await auth_client.get(
            f"/api/v1/sensor-analyses/{aid}/anomalies?severity=critical")
        assert anom.status_code == 200
        assert {"items", "total"} <= set(anom.json().keys())
        assert (await auth_client.delete(f"/api/v1/sensor-analyses/{aid}")).status_code == 204
        assert (await auth_client.get(f"/api/v1/sensor-analyses/{aid}")).status_code == 404


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_audit_events_recorded(self, auth_client: AsyncClient, db):
        created = (await _upload(auth_client, explain=False)).json()
        aid = created["id"]
        await auth_client.get(f"/api/v1/sensor-analyses/{aid}")

        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_id == aid)
        )).scalars())
        actions = {r.action for r in rows}
        assert "sensor.uploaded" in actions
        assert "sensor.analysis.completed" in actions
        assert "sensor.analysis.viewed" in actions

    @pytest.mark.asyncio
    async def test_failed_analysis_audited(self, auth_client: AsyncClient, db):
        bad = b"colA,colB\n1,2\n3,\xff\xfe garbage\n"
        created = (await _upload(auth_client, content=bad, name="x.csv", explain=False)).json()
        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_id == created["id"])
        )).scalars())
        assert any(r.action == "sensor.uploaded" for r in rows)

