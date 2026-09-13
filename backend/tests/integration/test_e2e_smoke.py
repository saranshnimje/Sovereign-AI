"""
End-to-end smoke test — verifies the complete workflow through every
major module: Health → Auth → KB → Document → Sensor → Vision → 
Incident → Investigation → Chat → Dashboard → Audit.

External services (Ollama, Qdrant) are mocked. Internal state transitions
are asserted against real persisted DB records.
"""
import json
import struct
import zlib

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


DIM = 768
FAKE_VECTORS = lambda n: [[0.1] * DIM for _ in range(n)]


def _png_bytes(w: int = 8, h: int = 8) -> bytes:
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


def _hot_csv(rows=240):
    lines = ["timestamp,bearing_temp_C,vibration_mm_s,motor_rpm"]
    for i in range(rows):
        wear = max(0.0, (i - rows * 0.5) / (rows * 0.5))
        t = 62 + 35 * wear + (i % 7) * 0.05
        v = 3.0 + 4.5 * wear + ((i % 11) / 10 if i % 17 == 0 else 0)
        lines.append(f"2026-01-20T{i//60:02d}:{i%60:02d}:00,{t:.2f},{v:.2f},{1492 - i//40}")
    return ("\n".join(lines) + "\n").encode()


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


class TestE2ESmokeWorkflow:
    """
    Single test that walks through the complete Sovereign AI Workbench
    workflow — from health check through audit verification.
    """

    @pytest.mark.asyncio
    async def test_full_e2e_workflow(self, client: AsyncClient):
        # ============================================================
        # Step 1: Health Check
        # ============================================================
        r = await client.get("/api/v1/system/health")
        assert r.status_code == 200, f"Health check failed: {r.text}"
        assert r.json()["status"] == "ok"

        # ============================================================
        # Step 2: Auth Flow — Register + Login
        # ============================================================
        r = await client.post("/api/v1/auth/register", json={
            "email": "e2e@test.com", "username": "e2e_admin", "password": "StrongPassword123!"
        })
        assert r.status_code == 201, f"Register failed: {r.text}"
        user_data = r.json()
        assert user_data["email"] == "e2e@test.com"
        assert user_data["role"] == "admin"  # first user gets admin

        r = await client.post("/api/v1/auth/login", json={
            "email": "e2e@test.com", "password": "StrongPassword123!"
        })
        assert r.status_code == 200, f"Login failed: {r.text}"
        token = r.json()["access_token"]
        assert token
        headers = {"Authorization": f"Bearer {token}"}

        # Verify /me
        r = await client.get("/api/v1/auth/me", headers=headers)
        assert r.status_code == 200
        assert r.json()["email"] == "e2e@test.com"

        # ============================================================
        # Step 3: Knowledge Base + Document Flow
        # ============================================================
        with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_e2e"):
            r = await client.post("/api/v1/knowledge-bases/", json={
                "name": "E2E Maintenance Manual",
                "description": "End-to-end test knowledge base"
            }, headers=headers)
        assert r.status_code == 201, f"Create KB failed: {r.text}"
        kb = r.json()
        kb_id = kb["id"]
        assert kb["name"] == "E2E Maintenance Manual"
        assert kb["doc_count"] == 0

        # List KBs
        r = await client.get("/api/v1/knowledge-bases/", headers=headers)
        assert r.status_code == 200
        assert any(k["id"] == kb_id for k in r.json())

        # Get KB by ID
        r = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
        assert r.status_code == 200
        assert r.json()["id"] == kb_id

        # Upload document
        doc_content = b"Bearing temperature above 85C indicates lubrication breakdown. " * 30
        with patch(
            "services.document_service.EmbeddingService.embed_texts",
            new=AsyncMock(return_value=FAKE_VECTORS(3)),
        ), patch(
            "services.qdrant_service.QdrantService.create_collection", return_value="kb_x"
        ), patch(
            "services.qdrant_service.QdrantService.upsert_vectors"
        ):
            r = await client.post(
                "/api/v1/documents/upload",
                files={"file": ("bearing_manual.txt", doc_content, "text/plain")},
                data={"kb_id": kb_id, "run_ocr": "false"},
                headers=headers,
            )
        assert r.status_code == 202, f"Upload doc failed: {r.text}"
        doc = r.json()
        doc_id = doc["id"]
        assert doc["status"] == "pending"
        assert doc["kb_id"] == kb_id

        # Check document status (background task runs inline under ASGITransport)
        r = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
        assert r.status_code == 200
        doc_status = r.json()
        assert doc_status["status"] == "indexed", f"Doc status: {doc_status}"
        assert doc_status["chunk_count"] >= 1

        # ============================================================
        # Step 4: Sensor Analysis Flow
        # ============================================================
        r = await client.post(
            "/api/v1/sensor-analyses",
            files={"file": ("bearing_hot.csv", _hot_csv(), "text/csv")},
            data={"generate_explanation": "false"},
            headers=headers,
        )
        assert r.status_code == 201, f"Sensor upload failed: {r.text}"
        sensor = r.json()
        sensor_id = sensor["id"]
        assert sensor["status"] == "completed"
        assert sensor["result"] is not None
        assert sensor["result"]["file"]["rows"] == 240
        assert "risk" in sensor["result"]

        # Get analysis detail
        r = await client.get(f"/api/v1/sensor-analyses/{sensor_id}", headers=headers)
        assert r.status_code == 200
        detail = r.json()
        assert detail["status"] == "completed"

        # List analyses
        r = await client.get("/api/v1/sensor-analyses", headers=headers)
        assert r.status_code == 200
        assert any(a["id"] == sensor_id for a in r.json())

        # ============================================================
        # Step 5: Vision Inspection Flow
        # ============================================================
        # Create incident first (vision requires an incident)
        r = await client.post("/api/v1/incidents", json={
            "title": "E2E Vision Test",
            "machine": "Press A",
            "description": "Vision inspection for e2e workflow test",
        }, headers=headers)
        assert r.status_code == 201, f"Create incident for vision failed: {r.text}"
        vision_incident_id = r.json()["id"]

        # Upload image (pending — skip analysis since no local vision model)
        r = await client.post(
            f"/api/v1/incidents/{vision_incident_id}/vision",
            files={"file": ("inspection.png", _png_bytes(), "image/png")},
            data={"analyze_now": "false"},
            headers=headers,
        )
        assert r.status_code == 201, f"Vision upload failed: {r.text}"
        vision_img = r.json()
        assert vision_img["status"] == "pending"

        # List vision images
        r = await client.get(f"/api/v1/incidents/{vision_incident_id}/vision", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

        # ============================================================
        # Step 6: Incident + Investigation Flow
        # ============================================================
        r = await client.post("/api/v1/incidents", json={
            "title": "Bearing B-204 Overheating E2E",
            "machine": "Press A",
            "asset_tag": "B-204",
            "description": "Why is Bearing B-204 overheating and what maintenance action?",
            "kb_id": kb_id,
            "sensor_analysis_id": sensor_id,
        }, headers=headers)
        assert r.status_code == 201, f"Create incident failed: {r.text}"
        inc = r.json()
        inc_id = inc["id"]
        assert inc["status"] == "created"
        assert inc["risk_level"] in ("medium", "high", "critical")

        # Verify KB and sensor were attached
        r = await client.get(f"/api/v1/incidents/{inc_id}", headers=headers)
        assert r.status_code == 200
        detail = r.json()
        assert detail["kb_id"] == kb_id
        assert detail["sensor_analysis_id"] == sensor_id

        # List incidents
        r = await client.get("/api/v1/incidents", headers=headers)
        assert r.status_code == 200
        assert any(i["id"] == inc_id for i in r.json()["items"])

        # Run investigation with mocked RAG + LLM
        with patch("services.embedding_service.EmbeddingService.embed_query",
                    new=AsyncMock(return_value=[0.1] * DIM)), \
             patch("services.qdrant_service.QdrantService.search",
                   return_value=[{
                       "id": "chunk-1", "score": 0.91,
                       "doc_id": "doc-1", "chunk_id": "chunk-1",
                       "filename": "bearing_manual.pdf", "page_number": 12,
                       "content": "Bearing temperature above 85C indicates lubrication breakdown.",
                   }]), \
             patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(return_value=type("R", (), {"content": FAKE_AI})())):
            r = await client.post(f"/api/v1/incidents/{inc_id}/investigate", headers=headers)
        assert r.status_code == 200, f"Investigation failed: {r.text}"
        result = r.json()
        assert result["status"] == "completed"
        assert result["evidence"]["documents"], "RAG evidence collected"
        assert result["evidence"]["sensors"], "Sensor evidence collected"
        assert result["risk"]["level"] in ("medium", "high", "critical")
        assert result["ai_analysis"] is not None
        assert result["recommendation_action"] is not None

        # ============================================================
        # Step 7: Chat Flow — Conversation + Message
        # ============================================================
        async def _mock_chat_stream(*args, **kwargs):
            async def _tokens():
                for tok in ["Hello", " from", " E2E", " test."]:
                    yield tok
            return _tokens()

        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "llama3.2:3b",
            "title": "E2E Test Conversation",
        }, headers=headers)
        assert r.status_code == 201, f"Create conversation failed: {r.text}"
        conv = r.json()
        conv_id = conv["id"]
        assert conv["title"] == "E2E Test Conversation"

        # List conversations
        r = await client.get("/api/v1/chat/conversations", headers=headers)
        assert r.status_code == 200
        assert any(c["id"] == conv_id for c in r.json())

        # Get conversation detail
        r = await client.get(f"/api/v1/chat/conversations/{conv_id}", headers=headers)
        assert r.status_code == 200
        assert r.json()["id"] == conv_id

        # Send a message (streaming SSE)
        with patch("services.llm_client.OllamaClient.chat",
                   new=AsyncMock(side_effect=_mock_chat_stream)):
            r = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"content": "What is the bearing temperature limit?"},
                headers=headers,
            )
        assert r.status_code == 200, f"Send message failed: {r.text}"
        assert "text/event-stream" in r.headers.get("content-type", "")

        # ============================================================
        # Step 8: Dashboard — Settings Summary
        # ============================================================
        r = await client.get("/api/v1/settings/summary", headers=headers)
        assert r.status_code == 200, f"Dashboard summary failed: {r.text}"
        summary = r.json()
        assert "knowledge_base_count" in summary
        assert "document_count" in summary
        assert "sensor_analysis_count" in summary
        assert "incident_count" in summary
        assert "total_audit_events" in summary
        assert "pending_approval_count" in summary
        assert "critical_risk_count" in summary
        assert "high_risk_count" in summary
        # Verify counts reflect what we created
        assert summary["knowledge_base_count"] >= 1
        assert summary["document_count"] >= 1
        assert summary["sensor_analysis_count"] >= 1
        assert summary["incident_count"] >= 2
        assert summary["total_audit_events"] >= 1

        # ============================================================
        # Step 9: System Status
        # ============================================================
        with patch("services.system_service.httpx.AsyncClient") as mock_httpx:
            mock_resp = AsyncMock()
            mock_resp.status_code = 500  # simulate Ollama down
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=AsyncMock(get=AsyncMock(return_value=mock_resp)))
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("services.system_service.get_settings") as mock_settings:
                mock_settings.return_value.ollama_url = "http://localhost:11434"
                mock_settings.return_value.qdrant_url = "http://localhost:6333"
                r = await client.get("/api/v1/system/status", headers=headers)

        assert r.status_code == 200, f"System status failed: {r.text}"
        status = r.json()
        assert "status" in status
        assert "services" in status
        assert "resources" in status
        assert status["status"] in ("healthy", "degraded", "unhealthy")

        # ============================================================
        # Step 10: Audit — Verify Chain Integrity
        # ============================================================
        r = await client.get("/api/v1/audit/verify", headers=headers)
        assert r.status_code == 200, f"Audit verify failed: {r.text}"
        audit_result = r.json()
        assert "verified" in audit_result
        assert "entries_checked" in audit_result
        assert "message" in audit_result
        assert audit_result["entries_checked"] >= 1

        # List audit logs
        r = await client.get("/api/v1/audit/logs", headers=headers)
        assert r.status_code == 200
        logs = r.json()
        assert "items" in logs
        assert "total" in logs
        assert logs["total"] >= 1

        # ============================================================
        # Step 11: Approval Flow (if high-risk incident created one)
        # ============================================================
        if result.get("requires_approval") and result.get("approval_request_id"):
            approval_id = result["approval_request_id"]
            r = await client.get(f"/api/v1/approvals/{approval_id}", headers=headers)
            assert r.status_code == 200
            approval = r.json()
            assert approval["status"] == "pending"
            assert approval["incident_id"] == inc_id if "incident_id" in approval else True

            # Approve it
            r = await client.post(f"/api/v1/approvals/{approval_id}/approve",
                                  json={"note": "Approved via E2E test"}, headers=headers)
            assert r.status_code == 200
            assert r.json()["status"] == "approved"
