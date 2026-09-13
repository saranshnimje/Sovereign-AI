"""
Integration tests — Vision Inspection (P1.3).

Real endpoints, real authorization boundaries. Provider behaviour is
simulated explicitly (unavailable / failure / malformed / valid) so tests are
environment-independent; the LIVE model check is performed separately.
"""
import io
import json
import struct
import zlib

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


def _png_bytes(w: int = 8, h: int = 8) -> bytes:
    """Minimal valid PNG (greyscale gradient) built with stdlib only."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes((int(255 * (x / max(1, w - 1))) % 256
                                   for x in range(w))) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


async def _mk_incident(client, headers, **kw):
    payload = {
        "title": kw.pop("title", "Vision test incident"),
        "machine": kw.pop("machine", "Press A"),
        "asset_tag": kw.pop("asset_tag", "B-204"),
        "description": kw.pop("description", "Overheating on bearing B-204."),
    }
    r = await client.post("/api/v1/incidents", json=payload, headers=headers)
    assert r.status_code == 201
    return r.json()["id"]


async def _upload(client, incident_id, content=None, name="shot.png", analyze=True,
                  headers=None):
    return await client.post(
        f"/api/v1/incidents/{incident_id}/vision",
        files={"file": (name, content if content is not None else _png_bytes(),
                        "image/png")},
        data={"analyze_now": str(analyze).lower()},
        headers=headers or {},
    )


GOOD_JSON = json.dumps({
    "finding": "Blueing near raceway consistent with overheating",
    "defects": [{"type": "thermal_damage", "severity": "critical",
                 "confidence": 0.86, "description": "Discoloration ring"}],
    "recommendation": "Replace bearing and review lubrication schedule",
    "limitations": ["single photo", "no scale reference"],
})


def _ollama_llm():
    from services.llm_client import OllamaProvider

    return OllamaProvider("http://localhost:11434")


class TestUploadSecurity:
    @pytest.mark.asyncio
    async def test_valid_png_upload_pending_audited(self, auth_client, db):
        iid = await _mk_incident(auth_client, {})
        r = await _upload(auth_client, iid, analyze=False)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending"

        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_id == body["id"])
        )).scalars())
        assert any(a.action == "vision.image_uploaded" for a in rows)

    @pytest.mark.asyncio
    async def test_invalid_image_rejected(self, auth_client):
        iid = await _mk_incident(auth_client, {})
        r = await _upload(auth_client, iid,
                          content=b"this is not an image at all", name="fake.png")
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_unsupported_format_rejected(self, auth_client):
        iid = await _mk_incident(auth_client, {})
        # BMP is not in ALLOWED_MIME — should be rejected
        bmp = b"BM" + b"\x00" * 20
        r = await _upload(auth_client, iid, content=bmp, name="photo.bmp")
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_oversize_rejected(self, auth_client, monkeypatch):
        # Other suites may have importlib.reload(config), leaving several
        # get_settings objects around. Drive via env + clear the EXACT
        # cached function this router dereferences.
        import routers.vision as vr

        monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "0")
        vr.get_settings.cache_clear()
        try:
            iid = await _mk_incident(auth_client, {})
            r = await _upload(auth_client, iid)
            assert r.status_code == 422, f"expected size rejection, got {r.status_code}"
        finally:
            vr.get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_path_traversal_filename_sanitised(self, auth_client):
        iid = await _mk_incident(auth_client, {})
        r = await _upload(auth_client, iid,
                          name="../../../../etc/evil.png", analyze=False)
        assert r.status_code == 201
        body = r.json()
        assert ".." not in body["original_name"]
        assert "/" not in body["original_name"]

    @pytest.mark.asyncio
    async def test_viewer_cannot_upload(self, client):
        async def mk(email, uname):
            await client.post("/api/v1/auth/register", json={
                "email": email, "username": uname, "password": "StrongPass123!"})
            r = await client.post("/api/v1/auth/login", json={
                "email": email, "password": "StrongPass123!"})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        admin = await mk("vadm9@test.com", "vadm9")
        await client.post("/api/v1/auth/register", json={
            "email": "vvw9@test.com", "username": "vvw9", "password": "StrongPass123!"})
        r_login = await client.post("/api/v1/auth/login", json={
            "email": "vvw9@test.com", "password": "StrongPass123!"})
        assert r_login.status_code == 200
        viewer = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

        # Viewer cannot create incidents at all
        r_create = await client.post("/api/v1/incidents", json={
            "title": "nope", "description": "should be forbidden"},
            headers=viewer)
        assert r_create.status_code == 403

        # Nor upload images into an existing (admin) incident
        iid = await _mk_incident(client, admin)
        resp = await _upload(client, iid, analyze=False, headers=viewer)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_foreign_incident_upload_404(self, client):
        async def mk(email, uname):
            await client.post("/api/v1/auth/register", json={
                "email": email, "username": uname, "password": "StrongPass123!"})
            r = await client.post("/api/v1/auth/login", json={
                "email": email, "password": "StrongPass123!"})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        admin = await mk("fadm@test.com", "fadm")
        peer = await mk("fpeer@test.com", "fpq")
        users = (await client.get("/api/v1/auth/users", headers=admin)).json()
        pid = next(u["id"] for u in users if u["email"] == "fpeer@test.com")
        await client.put(f"/api/v1/auth/users/{pid}", json={"role": "analyst"},
                         headers=admin)

        inc_admin = await _mk_incident(client, admin)
        r = await _upload(client, inc_admin, analyze=False, headers=peer)
        assert r.status_code == 404


class TestOwnershipAndAccess:
    async def _setup_with_image(self, client):
        async def mk(email, uname):
            await client.post("/api/v1/auth/register", json={
                "email": email, "username": uname, "password": "StrongPass123!"})
            r = await client.post("/api/v1/auth/login", json={
                "email": email, "password": "StrongPass123!"})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        admin = await mk("oadm@test.com", "oadm")
        await client.post("/api/v1/auth/register", json={
            "email": "opeer@test.com", "username": "opq", "password": "StrongPass123!"})
        users = (await client.get("/api/v1/auth/users", headers=admin)).json()
        pid = next(u["id"] for u in users if u["email"] == "opeer@test.com")
        await client.put(f"/api/v1/auth/users/{pid}", json={"role": "analyst"},
                         headers=admin)
        peer = {"Authorization": (
            await client.post("/api/v1/auth/login", json={
                "email": "opeer@test.com", "password": "StrongPass123!"})
        ).json()["access_token"]}
        peer = {"Authorization": f"Bearer {(await client.post('/api/v1/auth/login', json={'email': 'opeer@test.com', 'password': 'StrongPass123!'})).json()['access_token']}"}

        iid = await _mk_incident(client, admin)
        img = (await _upload(client, iid, analyze=False, headers=admin)).json()
        assert "id" in img, img
        return admin, peer, iid, img["id"]

    @pytest.mark.asyncio
    async def test_foreign_image_endpoints_404(self, client):
        _admin, peer, _iid, img_id = await self._setup_with_image(client)
        for method, path in (("get", f"/api/v1/images/{img_id}"),
                             ("get", f"/api/v1/images/{img_id}/file"),
                             ("post", f"/api/v1/images/{img_id}/analyze"),
                             ("delete", f"/api/v1/images/{img_id}")):
            r = await getattr(client, method)(path, headers=peer)
            assert r.status_code == 404, f"{method} → {r.status_code}"

    @pytest.mark.asyncio
    async def test_owner_file_serve_and_viewed_audit(self, auth_client, db):
        iid = await _mk_incident(auth_client, {})
        img = (await _upload(auth_client, iid, analyze=False)).json()
        r = await auth_client.get(f"/api/v1/images/{img['id']}/file")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")

        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_id == img["id"],
                                   AuditLog.action == "vision.viewed")
        )).scalars())
        assert rows


class TestAnalysisHonesty:
    async def _image(self, auth_client):
        iid = await _mk_incident(auth_client, {})
        return (await _upload(auth_client, iid, analyze=False)).json()["id"]

    @pytest.mark.asyncio
    async def test_unconfigured_vision_reports_unavailable(self, auth_client, monkeypatch):
        img_id = await self._image(auth_client)
        import routers.vision as vr

        monkeypatch.setattr(vr, "resolve_vision_model", lambda: None)
        r = await auth_client.post(f"/api/v1/images/{img_id}/analyze")
        body = r.json()
        assert body["status"] == "unavailable"
        assert "unavailable" in body["error_message"].lower()
        assert body["result"] is None          # never fabricate

    @pytest.mark.asyncio
    async def test_provider_failure_honest(self, auth_client, monkeypatch):
        img_id = await self._image(auth_client)
        import routers.vision as vr

        monkeypatch.setattr(vr, "resolve_vision_model", lambda: "llava-test")

        async def _fail(db, role):
            return _ollama_llm()

        monkeypatch.setattr("dependencies.resolve_llm_for_role_async", _fail)
        with patch("services.llm_client.OllamaProvider.chat",
                   new=AsyncMock(side_effect=RuntimeError("vision model crashed"))):
            body = (await auth_client.post(
                f"/api/v1/images/{img_id}/analyze")).json()
        assert body["status"] == "failed"
        assert "crashed" in body["error_message"]
        assert body["result"] is None

    @pytest.mark.asyncio
    async def test_malformed_model_response_fails_validation(self, auth_client, monkeypatch):
        img_id = await self._image(auth_client)
        import routers.vision as vr

        monkeypatch.setattr(vr, "resolve_vision_model", lambda: "llava-test")

        async def _ok(db, role):
            return _ollama_llm()

        monkeypatch.setattr("dependencies.resolve_llm_for_role_async", _ok)
        with patch("services.llm_client.OllamaProvider.chat",
                   new=AsyncMock(return_value=type("R", (), {
                       "content": "I see some discoloration but no JSON"})())):
            body = (await auth_client.post(
                f"/api/v1/images/{img_id}/analyze")).json()
        assert body["status"] == "failed"
        assert "malformed" in body["error_message"].lower()

    @pytest.mark.asyncio
    async def test_structured_response_completes_and_clamps(self, auth_client, db,
                                                            monkeypatch):
        img_id = await self._image(auth_client)
        import routers.vision as vr

        monkeypatch.setattr(vr, "resolve_vision_model", lambda: "llava-test")

        async def _ok(db, role):
            return _ollama_llm()

        monkeypatch.setattr("dependencies.resolve_llm_for_role_async", _ok)
        with patch("services.llm_client.OllamaProvider.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": GOOD_JSON})())):
            body = (await auth_client.post(
                f"/api/v1/images/{img_id}/analyze")).json()

        assert body["status"] == "completed"
        res = body["result"]
        assert res["finding"].startswith("Blueing")
        assert res["defects"][0]["severity"] == "CRITICAL"
        assert res["defects"][0]["confidence"] == 0.86
        assert body["ai_model"] == "llava-test"

        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_id == img_id)
        )).scalars())
        actions = {r.action for r in rows}
        assert {"vision.analysis_started", "vision.analysis_completed"} <= actions


class TestIncidentIntegration:
    @pytest.mark.asyncio
    async def test_list_summary_does_not_leak_evidence(self, auth_client):
        """Incident list payloads carry no evidence/vision structures."""
        listing = (await auth_client.get("/api/v1/incidents")).json()
        for item in listing["items"]:
            forbidden = {"evidence", "risk", "ai_analysis", "result"}
            assert not (forbidden & set(item.keys()))

    @pytest.mark.asyncio
    async def test_investigation_includes_completed_vision_evidence(self, auth_client):
        iid = await _mk_incident(auth_client, {})

        # 1. complete a vision analysis (mocked provider, validated output)
        img = (await _upload(auth_client, iid, analyze=False)).json()
        import routers.vision as vr

        monkey_vision = lambda: "llava-test"

        async def _ok(db, role):
            return _ollama_llm()

        with patch.object(vr, "resolve_vision_model", monkey_vision), \
             patch("dependencies.resolve_llm_for_role_async", _ok), \
             patch("services.llm_client.OllamaProvider.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": GOOD_JSON})())):
            done = (await auth_client.post(
                f"/api/v1/images/{img['id']}/analyze")).json()
        assert done["status"] == "completed"

        # 2. run investigation with mocked RAG + mocked investigation LLM
        FAKE_AI = ("Evidence reviewed.\nACTION: Replace Bearing B-204.")
        with patch("services.embedding_service.EmbeddingService.embed_query",
                   new=AsyncMock(return_value=[0.1] * 768)), \
             patch("services.qdrant_service.QdrantService.search", return_value=[]), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": FAKE_AI})())):
            inv = (await auth_client.post(
                f"/api/v1/incidents/{iid}/investigate")).json()

        vision = inv["evidence"]["vision"]
        assert len(vision) == 1
        assert vision[0]["image_id"] == img["id"]
        assert vision[0]["finding"].startswith("Blueing")

    @pytest.mark.asyncio
    async def test_investigation_cannot_use_foreign_vision(self, client):
        """Peer's own incident has zero vision rows even though admin's does."""
        async def mk(email, uname):
            await client.post("/api/v1/auth/register", json={
                "email": email, "username": uname, "password": "StrongPass123!"})
            r = await client.post("/api/v1/auth/login", json={
                "email": email, "password": "StrongPass123!"})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        admin = await mk("vadm2@test.com", "vadm2")
        await client.post("/api/v1/auth/register", json={
            "email": "vpeer2@test.com", "username": "vpq2", "password": "StrongPass123!"})
        users = (await client.get("/api/v1/auth/users", headers=admin)).json()
        pid = next(u["id"] for u in users if u["email"] == "vpeer2@test.com")
        await client.put(f"/api/v1/auth/users/{pid}", json={"role": "analyst"},
                         headers=admin)
        peer = {"Authorization": f"Bearer {(await client.post('/api/v1/auth/login', json={'email': 'vpeer2@test.com', 'password': 'StrongPass123!'})).json()['access_token']}"}

        admin_inc = await _mk_incident(client, admin)
        await _upload(client, admin_inc, analyze=False)

        peer_inc = await _mk_incident(client, peer, title="Peer incident")
        with patch("services.embedding_service.EmbeddingService.embed_query",
                   new=AsyncMock(return_value=[0.1] * 768)), \
             patch("services.qdrant_service.QdrantService.search", return_value=[]), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": "x\nACTION: y"})())):
            inv = (await client.post(
                f"/api/v1/incidents/{peer_inc}/investigate", headers=peer)).json()
        assert inv["evidence"]["vision"] == []
