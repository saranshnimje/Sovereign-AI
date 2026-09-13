"""
Integration tests — Incident Workbench (P1.2).

Covers the full investigate workflow over REAL endpoints: attachment
authorization (KB + sensor analysis), RAG evidence with citations,
deterministic risk, Ollama-unavailable honesty, LLM-cannot-alter-numbers,
high-risk approval via the EXISTING queue, and audit events.
"""
import json

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _hot_csv(rows=240):
    """Sensor CSV that deterministically breaches temperature limits."""
    lines = ["timestamp,bearing_temp_C,vibration_mm_s,motor_rpm"]
    for i in range(rows):
        wear = max(0.0, (i - rows * 0.5) / (rows * 0.5))
        t = 62 + 35 * wear + (i % 7) * 0.05
        v = 3.0 + 4.5 * wear + ((i % 11) / 10 if i % 17 == 0 else 0)
        lines.append(f"2026-01-20T{i//60:02d}:{i%60:02d}:00,{t:.2f},{v:.2f},{1492 - i//40}")
    return ("\n".join(lines) + "\n").encode()


async def _mk_user(client, email, username, password="StrongPass123!"):
    await client.post("/api/v1/auth/register", json={
        "email": email, "username": username, "password": password})
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _register(client, email, username, password="StrongPass123!"):
    await client.post("/api/v1/auth/register", json={
        "email": email, "username": username, "password": password})


async def _login(client, email, password="StrongPass123!"):
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": password})
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _promote(client, admin_headers, email, role="analyst"):
    users = (await client.get("/api/v1/auth/users", headers=admin_headers)).json()
    uid = next((u["id"] for u in users if u["email"] == email), None)
    assert uid, f"user {email} must be registered before promotion"
    await client.put(f"/api/v1/auth/users/{uid}", json={"role": role},
                     headers=admin_headers)
    return uid


async def _make_kb(client, headers, name="Maintenance Manuals"):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        r = await client.post("/api/v1/knowledge-bases/", json={"name": name},
                              headers=headers)
    assert r.status_code == 201
    return r.json()["id"]


async def _make_sensor_analysis(client, headers):
    from services.sensor_analysis_service import SensorAnalysisError  # noqa: F401

    with patch(
        "services.document_service.EmbeddingService.embed_texts",
        new=AsyncMock(return_value=[[0.1] * 768]),
    ), patch(
        "services.qdrant_service.QdrantService.create_collection", return_value="kb_x"
    ), patch("services.qdrant_service.QdrantService.upsert_vectors"):
        r = await client.post(
            "/api/v1/sensor-analyses",
            files={"file": ("bearing_hot.csv", _hot_csv(), "text/csv")},
            data={"generate_explanation": "false"},
            headers=headers,
        )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "completed", body.get("error_message")
    return body["id"], body["result"]


def _fake_doc_hits():
    payload = {
        "id": "chunk-1", "score": 0.91,
        "doc_id": "doc-1", "chunk_id": "chunk-1",
        "filename": "bearing_manual.pdf", "page_number": 12,
        "content": "Bearing temperature above 85 C indicates lubrication breakdown; "
                   "inspect and re-grease per schedule 3B.",
    }
    return [payload] * 3


async def _create_incident(client, headers, kb_id=None, sensor_id=None, **kw):
    payload = {
        "title": kw.pop("title", "Bearing B-204 overheating"),
        "machine": kw.pop("machine", "Press A"),
        "asset_tag": kw.pop("asset_tag", "B-204"),
        "description": kw.pop(
            "description",
            "Why is Bearing B-204 overheating and what maintenance action should be taken?"),
        "kb_id": kb_id,
        "sensor_analysis_id": sensor_id,
        **kw,
    }
    return await client.post("/api/v1/incidents", json=payload, headers=headers)


_RAG_PATCH_KW = dict(
    new=AsyncMock(return_value=[0.1] * 768),
)

FAKE_AI = (
    "1. Evidence: temp breaches and manual excerpt found.\n"
    "2. bearing_temp_C critical.\n"
    "3. [Doc 1: bearing_manual.pdf, p.12] says inspect and re-grease.\n"
    "4. Lubrication breakdown likely.\n"
    "5. Check grease, load, alignment.\n"
    "6. Schedule inspection per manual.\n"
    "7. Limited by single sensor set.\n"
    "ACTION: Inspect and re-grease Bearing B-204 within 24 hours per manual p.12."
)


class TestCreationAndAccess:
    @pytest.mark.asyncio
    async def test_create_with_attachments_201_audited(self, auth_client, db):
        kb = await _make_kb(auth_client, {})
        sid, _res = await _make_sensor_analysis(auth_client, {})
        r = await _create_incident(auth_client, {}, kb_id=kb, sensor_id=sid)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "created"
        assert body["risk_level"] in ("medium", "high", "critical")  # hot csv attached

        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_id == body["id"])
        )).scalars())
        assert any(a.action == "incident.created" for a in rows)

    @pytest.mark.asyncio
    async def test_owner_view_and_foreign_404(self, client):
        admin = await _mk_user(client, "iadm@test.com", "iadm")
        await _register(client, "peer@test.com", "peer")
        await _promote(client, admin, "peer@test.com")
        peer = await _login(client, "peer@test.com")

        created = (await _create_incident(client, admin)).json()
        iid = created["id"]

        assert (await client.get(f"/api/v1/incidents/{iid}", headers=admin)).status_code == 200

        # Foreign user: detail / investigate / delete all 404; listing hides it
        for method, path in (("get", f"/api/v1/incidents/{iid}"),
                             ("post", f"/api/v1/incidents/{iid}/investigate"),
                             ("delete", f"/api/v1/incidents/{iid}")):
            resp = await getattr(client, method)(path, headers=peer)
            assert resp.status_code == 404, f"{method} {path} → {resp.status_code}"
        listing = (await client.get("/api/v1/incidents", headers=peer)).json()
        assert all(i["id"] != iid for i in listing["items"])

    @pytest.mark.asyncio
    async def test_attach_foreign_artifacts_rejected(self, client):
        admin = await _mk_user(client, "a2x@test.com", "a2x")
        await _register(client, "p2x@test.com", "p2x")
        await _promote(client, admin, "p2x@test.com")
        peer = await _login(client, "p2x@test.com")

        foreign_kb = await _make_kb(client, admin)
        foreign_sid, _ = await _make_sensor_analysis(client, admin)

        own = (await _create_incident(client, peer)).json()

        # PATCH attachments to foreign ids ⇒ 404
        r1 = await client.patch(f"/api/v1/incidents/{own['id']}",
                                json={"kb_id": foreign_kb}, headers=peer)
        assert r1.status_code == 404
        r2 = await client.patch(f"/api/v1/incidents/{own['id']}",
                                json={"sensor_analysis_id": foreign_sid}, headers=peer)
        assert r2.status_code == 404

        # And creating directly with a foreign id is equally rejected
        r3 = await _create_incident(client, peer, sensor_id=foreign_sid)
        assert r3.status_code == 404


class TestInvestigationWorkflow:
    async def _prepared(self, client, admin):
        kb = await _make_kb(client, admin)
        sid, sensor_result = await _make_sensor_analysis(client, admin)
        inc = (await _create_incident(client, admin, kb_id=kb, sensor_id=sid)).json()
        return inc, kb, sid, sensor_result

    @pytest.mark.asyncio
    async def test_full_workflow_with_citations_approval(self, auth_client, db):
        inc, kb, sid, sensor_result = await self._prepared(auth_client, {})

        with patch("services.embedding_service.EmbeddingService.embed_query", **_RAG_PATCH_KW), \
             patch("services.qdrant_service.QdrantService.search",
                   return_value=_fake_doc_hits()), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": FAKE_AI})())):
            r = await auth_client.post(f"/api/v1/incidents/{inc['id']}/investigate")

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"

        # --- document evidence + citations ---
        docs = body["evidence"]["documents"]
        assert len(docs) >= 1
        assert "[Doc 1: bearing_manual.pdf, p.12]" == docs[0]["citation_label"]

        # --- sensor evidence mirrors the engine's own numbers ---
        sensors = body["evidence"]["sensors"]
        assert len(sensors) >= 1
        src_anomalies = {(a["sensor"], a["timestamp"], a["value"])
                         for a in sensor_result["anomalies"]}
        for s in sensors:
            assert (s["sensor"], s["timestamp"], s["value"]) in src_anomalies

        # --- deterministic risk present & labelled ---
        assert body["risk"]["level"] in ("medium", "high", "critical")
        assert body["risk"]["rules_hit"], "rules must be transparent"

        # --- AI interpretation + ACTION extraction ---
        assert body["ai_analysis"].startswith("1. Evidence")
        assert body["recommendation_action"] == (
            "Inspect and re-grease Bearing B-204 within 24 hours per manual p.12.")
        assert body["recommendation_risk_level"] == body["risk"]["level"]

        # --- high deterministic risk ⇒ existing approval queue ---
        assert body["requires_approval"] is True
        assert body["approval_request_id"]
        from sqlalchemy import select

        from models.agent import ApprovalRequest
        req = (await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == body["approval_request_id"])
        )).scalar_one()
        assert req.status == "pending"
        detail = json.loads(req.operation_detail_json)
        assert detail["incident_id"] == inc["id"]
        assert detail["deterministic_risk"] == body["risk"]["level"]

    @pytest.mark.asyncio
    async def test_insufficient_evidence_flagged(self, auth_client):
        kb = await _make_kb(auth_client, {}, name="Empty KB")
        inc = (await _create_incident(
            auth_client, {}, kb_id=kb, description="mystery failure?")).json()

        with patch("services.embedding_service.EmbeddingService.embed_query", **_RAG_PATCH_KW), \
             patch("services.qdrant_service.QdrantService.search", return_value=[]), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": "insufficient"})())):
            body = (await auth_client.post(
                f"/api/v1/incidents/{inc['id']}/investigate")).json()

        assert body["status"] == "completed"
        assert body["evidence"]["insufficient_evidence"] is True
        assert body["evidence"]["documents"] == []
        assert body["risk"]["level"] == "unknown"

    @pytest.mark.asyncio
    async def test_ollama_unavailable_numbers_intact(self, auth_client):
        """Provider failure ⇒ honest ai_error; deterministic parts unaffected.
        (Failure is simulated explicitly so the test is environment-independent —
        a live Ollama must not change what this asserts.)"""
        kb = await _make_kb(auth_client, {}, name="Manuals B")
        sid, sensor_result = await _make_sensor_analysis(auth_client, {})
        inc = (await _create_incident(auth_client, {}, kb_id=kb, sensor_id=sid)).json()

        with patch("services.embedding_service.EmbeddingService.embed_query", **_RAG_PATCH_KW), \
             patch("services.qdrant_service.QdrantService.search",
                   return_value=_fake_doc_hits()), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(side_effect=RuntimeError("connection refused"))):
            body = (await auth_client.post(
                f"/api/v1/incidents/{inc['id']}/investigate")).json()

        assert body["status"] == "completed"
        assert body["ai_analysis"] is None
        assert body["ai_error"] and "unavailable" in body["ai_error"].lower()
        # Deterministic parts unaffected by LLM absence
        assert body["evidence"]["documents"], "RAG evidence still collected"
        assert body["risk"]["level"] != "unknown"
        assert body["recommendation_risk_level"] == body["risk"]["level"]

    @pytest.mark.asyncio
    async def test_llm_cannot_alter_evidence_or_risk(self, auth_client):
        inc, *_ = await self._prepared(auth_client, {})

        outputs = [
            type("R", (), {"content": FAKE_AI})(),
            type("R", (), {"content": "TOTALLY DIFFERENT text claiming temp is -50C "
                                      "and everything is fine.\nACTION: do nothing"})(),
        ]
        results = []
        with patch("services.embedding_service.EmbeddingService.embed_query", **_RAG_PATCH_KW), \
             patch("services.qdrant_service.QdrantService.search",
                   return_value=_fake_doc_hits()), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(side_effect=outputs)):
            for _ in range(2):
                r = await auth_client.post(
                    f"/api/v1/incidents/{inc['id']}/investigate")
                results.append(r.json())

        e1, e2 = results[0]["evidence"], results[1]["evidence"]
        assert e1 == e2, "evidence snapshot must be identical regardless of model output"
        assert results[0]["risk"] == results[1]["risk"]
        assert results[0]["recommendation_risk_level"] == results[1]["recommendation_risk_level"]
        assert results[0]["ai_analysis"] != results[1]["ai_analysis"]

    @pytest.mark.asyncio
    async def test_unauthorized_cannot_approve(self, client):
        admin = await _mk_user(client, "a3x@test.com", "a3x")
        await _register(client, "p3x@test.com", "p3x")
        await _promote(client, admin, "p3x@test.com")
        peer = await _login(client, "p3x@test.com")

        kb = await _make_kb(client, admin, name="M3")
        sid, _ = await _make_sensor_analysis(client, admin)
        inc = (await _create_incident(client, admin, kb_id=kb, sensor_id=sid)).json()

        with patch("services.embedding_service.EmbeddingService.embed_query", **_RAG_PATCH_KW), \
             patch("services.qdrant_service.QdrantService.search",
                   return_value=_fake_doc_hits()), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": FAKE_AI})())):
            done = (await client.post(
                f"/api/v1/incidents/{inc['id']}/investigate", headers=admin)).json()

        rid = done["approval_request_id"]
        assert rid

        # Analyst attempts to approve an admin-gated request
        r = await client.post(f"/api/v1/approvals/{rid}/approve",
                              json={"note": "self-approve"}, headers=peer)
        assert r.status_code == 403

        # Admin approves successfully (existing queue endpoint)
        ok = await client.post(f"/api/v1/approvals/{rid}/approve",
                               json={"note": "proceed"}, headers=admin)
        assert ok.status_code == 200
        assert ok.json()["status"] == "approved"


class TestAuditChain:
    @pytest.mark.asyncio
    async def test_complete_event_chain_recorded(self, auth_client, db):
        kb = await _make_kb(auth_client, {}, name="ChainKB")
        sid, _ = await _make_sensor_analysis(auth_client, {})
        inc = (await _create_incident(auth_client, {}, kb_id=kb, sensor_id=sid)).json()

        with patch("services.embedding_service.EmbeddingService.embed_query", **_RAG_PATCH_KW), \
             patch("services.qdrant_service.QdrantService.search",
                   return_value=_fake_doc_hits()), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": FAKE_AI})())):
            await auth_client.post(f"/api/v1/incidents/{inc['id']}/investigate")
        await auth_client.get(f"/api/v1/incidents/{inc['id']}")

        from sqlalchemy import select

        from models.audit import AuditLog
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.resource_type == "incident",
                                   AuditLog.resource_id == inc["id"])
        )).scalars())
        actions = {r.action for r in rows}
        assert {"incident.created", "incident.analysis_started",
                "incident.analysis_completed", "incident.viewed"} <= actions

        # Approval request event tied to this incident exists in the chain
        appr = list((await db.execute(
            select(AuditLog).where(AuditLog.event_type == "approval",
                                   AuditLog.metadata_json.contains(inc["id"]))
        )).scalars())
        assert any(a.action == "approval.request_created" for a in appr)


