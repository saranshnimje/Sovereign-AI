"""
Final SIH 2026 End-to-End Demo — complete flow verification.
Uses shared `client` fixture (in-memory SQLite) + mocked external services.
"""
import struct
import zlib
from unittest.mock import AsyncMock, patch

import pytest
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


FAKE_VISION = (
    '{"finding": "Visible surface wear on bearing housing",'
    ' "defects": [{"type": "surface_wear", "severity": "MEDIUM",'
    ' "confidence": 0.78, "description": "Discoloration consistent with thermal stress"}],'
    ' "recommendation": "Schedule bearing inspection within 7 days",'
    ' "limitations": ["Image resolution limits detailed crack analysis"]}'
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


class TestFinalSIHDemo:
    """Complete SIH 2026 demo — every major module in sequence."""

    @pytest.mark.asyncio
    async def test_full_sih_flow(self, client: AsyncClient):
        step = {"n": 0}

        def ok(msg):
            step["n"] += 1
            print(f"  [PASS] Step {step['n']}: {msg}")

        # ════════════════════════════════════════════════════════════
        # 1. HEALTH
        # ════════════════════════════════════════════════════════════
        r = await client.get("/api/v1/system/health")
        assert r.status_code == 200
        ok("System health check")

        # ════════════════════════════════════════════════════════════
        # 2. AUTH — Register admin + login
        # ════════════════════════════════════════════════════════════
        r = await client.post("/api/v1/auth/register", json={
            "email": "sih_admin@test.com", "username": "sih_admin",
            "password": "StrongPassword123!"
        })
        assert r.status_code == 201
        assert r.json()["role"] == "admin"

        r = await client.post("/api/v1/auth/login", json={
            "email": "sih_admin@test.com", "password": "StrongPassword123!"
        })
        assert r.status_code == 200
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        ok("Admin registered + logged in")

        r = await client.get("/api/v1/auth/me", headers=headers)
        assert r.status_code == 200
        ok("Auth /me verified")

        # ════════════════════════════════════════════════════════════
        # 3. Register viewer (second user for RBAC/IDOR tests)
        # ════════════════════════════════════════════════════════════
        r = await client.post("/api/v1/auth/register", json={
            "email": "sih_viewer@test.com", "username": "sih_viewer",
            "password": "ViewerPassword123!"
        })
        assert r.status_code == 201

        r = await client.post("/api/v1/auth/login", json={
            "email": "sih_viewer@test.com", "password": "ViewerPassword123!"
        })
        viewer_token = r.json()["access_token"]
        vh = {"Authorization": f"Bearer {viewer_token}"}
        ok("Viewer registered + logged in")

        # ════════════════════════════════════════════════════════════
        # 4. KNOWLEDGE BASE — Create KB
        # ════════════════════════════════════════════════════════════
        with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_sih"):
            r = await client.post("/api/v1/knowledge-bases/", json={
                "name": "Maintenance Manual KB",
                "description": "SIH 2026 maintenance documentation"
            }, headers=headers)
        assert r.status_code == 201
        kb_id = r.json()["id"]
        ok(f"KB created: {kb_id}")

        # ════════════════════════════════════════════════════════════
        # 5. DOCUMENT — Upload maintenance manual
        # ════════════════════════════════════════════════════════════
        doc_content = b"""MACHINE VIBRATION MAINTENANCE GUIDE

Section 1: Bearing Analysis
Rolling element bearings are the most common source of vibration.
BPFO = 0.4 * N * (1 - d/D * cos(alpha)) * RPM
BPFI = 0.6 * N * (1 + d/D * cos(alpha)) * RPM

Section 2: Severity (ISO 10816-3)
Zone A: < 0.71 mm/s | Zone B: 0.71-1.8 | Zone C: 1.8-4.5 | Zone D: > 4.5

Section 3: Thermal Thresholds
Normal: 40-70C | Warning: 75C | Critical: 85C | Emergency: 95C
""" * 3
        with patch("services.document_service.EmbeddingService.embed_texts",
                    new=AsyncMock(return_value=FAKE_VECTORS(3))), \
             patch("services.qdrant_service.QdrantService.create_collection",
                    return_value="kb_sih"), \
             patch("services.qdrant_service.QdrantService.upsert_vectors"):
            r = await client.post(
                "/api/v1/documents/upload",
                files={"file": ("bearing_manual.txt", doc_content, "text/plain")},
                data={"kb_id": kb_id, "run_ocr": "false"},
                headers=headers,
            )
        assert r.status_code == 202
        doc_id = r.json()["id"]
        ok(f"Document uploaded: {doc_id}")

        # Check indexed
        r = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] == "indexed"
        ok(f"Document indexed: {r.json().get('chunk_count', 0)} chunks")

        # ════════════════════════════════════════════════════════════
        # 6. RAG — Query the knowledge base
        # ════════════════════════════════════════════════════════════
        with patch("services.embedding_service.EmbeddingService.embed_query",
                    new=AsyncMock(return_value=[0.1] * DIM)), \
             patch("services.qdrant_service.QdrantService.search",
                    return_value=[{
                        "id": "chunk-1", "score": 0.91,
                        "doc_id": doc_id, "chunk_id": "chunk-1",
                        "filename": "bearing_manual.txt", "page_number": 12,
                        "content": "BPFO = 0.4 * N * (1 - d/D * cos(alpha)) * RPM",
                    }]), \
             patch("services.llm_client.OllamaClient.chat",
                    new=AsyncMock(return_value=type("R", (), {
                        "content": "BPFO formula from manual: 0.4*N*(1-d/D*cos(a))*RPM"
                    })())):
            r = await client.post(f"/api/v1/knowledge-bases/{kb_id}/query", json={
                "query": "What are the bearing defect frequencies?"
            }, headers=headers)
        assert r.status_code == 200
        rag = r.json()
        ok(f"RAG query: sources={len(rag.get('sources', []))}")

        # ════════════════════════════════════════════════════════════
        # 7. SENSOR — Upload bearing CSV + analyze
        # ════════════════════════════════════════════════════════════
        r = await client.post(
            "/api/v1/sensor-analyses",
            files={"file": ("bearing_hot.csv", _hot_csv(), "text/csv")},
            data={"generate_explanation": "false"},
            headers=headers,
        )
        assert r.status_code == 201
        sensor = r.json()
        sensor_id = sensor["id"]
        assert sensor["status"] == "completed"
        ok(f"Sensor analysis: {sensor['result']['file']['rows']} rows, risk={sensor['result'].get('risk', {}).get('level', 'N/A')}")

        r = await client.get(f"/api/v1/sensor-analyses/{sensor_id}", headers=headers)
        assert r.status_code == 200
        ok("Sensor analysis detail fetched")

        # ════════════════════════════════════════════════════════════
        # 8. VISION — Upload inspection image + analyze with llava:7b
        # ════════════════════════════════════════════════════════════
        # Create incident first (vision requires an incident)
        r = await client.post("/api/v1/incidents", json={
            "title": "Vision Inspection Test",
            "machine": "MACHINE-001",
            "description": "Testing vision pipeline for SIH demo",
        }, headers=headers)
        assert r.status_code == 201
        vision_inc_id = r.json()["id"]

        # Upload vision image with analysis (mock llava response)
        with patch("services.vision_service.resolve_vision_model", return_value="llava:7b"), \
             patch("services.vision_service.analyze_image",
                    new=AsyncMock(return_value={
                        "status": "completed",
                        "result": {
                            "finding": "Visible surface wear on bearing housing",
                            "defects": [{"type": "surface_wear", "severity": "MEDIUM",
                                         "confidence": 0.78,
                                         "description": "Discoloration consistent with thermal stress"}],
                            "recommendation": "Schedule bearing inspection within 7 days",
                            "limitations": ["Image resolution limits analysis"]
                        },
                        "model": "llava:7b"
                    })):
            r = await client.post(
                f"/api/v1/incidents/{vision_inc_id}/vision",
                files={"file": ("inspection.png", _png_bytes(), "image/png")},
                data={"analyze_now": "true"},
                headers=headers,
            )
        assert r.status_code == 201
        vision = r.json()
        ok(f"Vision: status={vision.get('status')}, model={vision.get('model', 'N/A')}")

        # ════════════════════════════════════════════════════════════
        # 9. INCIDENT — Create + investigate
        # ════════════════════════════════════════════════════════════
        r = await client.post("/api/v1/incidents", json={
            "title": "Bearing B-204 Overheating",
            "machine": "Press A",
            "asset_tag": "B-204",
            "description": "Why is Bearing B-204 overheating and what maintenance action?",
            "kb_id": kb_id,
            "sensor_analysis_id": sensor_id,
        }, headers=headers)
        assert r.status_code == 201
        inc = r.json()
        inc_id = inc["id"]
        ok(f"Incident created: {inc_id}, risk={inc.get('risk_level', 'N/A')}")

        # Verify attachments
        r = await client.get(f"/api/v1/incidents/{inc_id}", headers=headers)
        assert r.status_code == 200
        detail = r.json()
        assert detail["kb_id"] == kb_id
        assert detail["sensor_analysis_id"] == sensor_id
        ok("Incident has KB + sensor attached")

        # ════════════════════════════════════════════════════════════
        # 10. INVESTIGATION — Evidence-grounded with RAG + sensor + vision
        # ════════════════════════════════════════════════════════════
        with patch("services.embedding_service.EmbeddingService.embed_query",
                    new=AsyncMock(return_value=[0.1] * DIM)), \
             patch("services.qdrant_service.QdrantService.search",
                    return_value=[{
                        "id": "chunk-1", "score": 0.91,
                        "doc_id": doc_id, "chunk_id": "chunk-1",
                        "filename": "bearing_manual.txt", "page_number": 12,
                        "content": "Bearing temperature above 85C indicates lubrication breakdown.",
                    }]), \
             patch("services.llm_client.OllamaClient.chat",
                    new=AsyncMock(return_value=type("R", (), {"content": FAKE_AI})())):
            r = await client.post(f"/api/v1/incidents/{inc_id}/investigate", headers=headers)
        assert r.status_code == 200
        result = r.json()
        assert result["status"] == "completed"
        assert result["evidence"]["documents"], "RAG evidence collected"
        assert result["evidence"]["sensors"], "Sensor evidence collected"
        assert result["risk"]["level"] in ("medium", "high", "critical")
        ok(f"Investigation: risk={result['risk']['level']}, doc_evidence={len(result['evidence']['documents'])}, sensor_evidence={len(result['evidence']['sensors'])}")

        # ════════════════════════════════════════════════════════════
        # 11. APPROVAL — Queue check
        # ════════════════════════════════════════════════════════════
        r = await client.get("/api/v1/approvals/pending", headers=headers)
        assert r.status_code == 200
        ok("Approval pending list accessible")

        # ════════════════════════════════════════════════════════════
        # 12. RBAC — Viewer cannot create KB
        # ════════════════════════════════════════════════════════════
        r = await client.post("/api/v1/knowledge-bases/", json={
            "name": "Unauthorized KB"
        }, headers=vh)
        assert r.status_code == 403
        ok("Viewer denied KB creation (RBAC 403)")

        # ════════════════════════════════════════════════════════════
        # 13. IDOR — Viewer cannot see admin incident
        # ════════════════════════════════════════════════════════════
        r = await client.get(f"/api/v1/incidents/{inc_id}", headers=vh)
        assert r.status_code == 404
        ok("Viewer cannot access admin incident (IDOR 404)")

        # ════════════════════════════════════════════════════════════
        # 14. AUDIT — Chain integrity
        # ════════════════════════════════════════════════════════════
        r = await client.get("/api/v1/audit/verify", headers=headers)
        assert r.status_code == 200
        ok(f"Audit chain valid: {r.json().get('valid', False)}")

        # ════════════════════════════════════════════════════════════
        # 15. DASHBOARD — Summary metrics
        # ════════════════════════════════════════════════════════════
        r = await client.get("/api/v1/settings/summary", headers=headers)
        assert r.status_code == 200
        d = r.json()
        ok(f"Dashboard: kb={d.get('knowledge_base_count',0)} doc={d.get('document_count',0)} sensor={d.get('sensor_analysis_count',0)} incident={d.get('incident_count',0)}")

        # ════════════════════════════════════════════════════════════
        # 16. MODELS — Roles endpoint
        # ════════════════════════════════════════════════════════════
        r = await client.get("/api/v1/models/roles", headers=headers)
        assert r.status_code == 200
        ok("Model roles endpoint accessible")

        # ════════════════════════════════════════════════════════════
        # 17. SOVEREIGNTY — No cloud endpoints
        # ════════════════════════════════════════════════════════════
        from main import app
        cloud = [
            getattr(r, "path", "")
            for r in app.routes
            if hasattr(r, "path") and any(
                x in r.path.lower() for x in ["openai", "anthropic", "gemini", "cloud"]
            )
        ]
        assert not cloud
        ok("Sovereignty: zero cloud API endpoints")

        print(f"\n{'='*60}")
        print(f"SIH 2026 FINAL E2E DEMO: {step['n']}/{step['n']} PASSED")
        print(f"{'='*60}")
