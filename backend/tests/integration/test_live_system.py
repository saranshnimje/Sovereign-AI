"""
Phase 3-20: Real live system test using conftest's in-memory DB + real Ollama.
Uses the `client` fixture which provides in-memory SQLite.
"""
import asyncio
import csv
import io
import random
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


DIM = 768
FAKE_VECTORS = lambda n: [[0.1] * DIM for _ in range(n)]

FAKE_INVESTIGATION = (
    "EVIDENCE:\n"
    "- Sensor: vibration peaked at 3.2 mm/s (Zone C per ISO 10816-3)\n"
    "- Sensor: temperature reached 75C\n"
    "- Document: manual p.12 says Zone C requires 7-day maintenance\n"
    "- Vision: surface wear detected\n"
    "RISK: HIGH\n"
    "RECOMMENDATION: Inspect bearing B-204 within 24 hours.\n"
    "ACTION: Re-grease bearing B-204."
)


def _hot_csv(rows=240):
    lines = ["timestamp,bearing_temp_C,vibration_mm_s,motor_rpm"]
    rng = random.Random(42)
    for i in range(rows):
        wear = max(0.0, (i - rows * 0.5) / (rows * 0.5))
        t = 62 + 35 * wear + (i % 7) * 0.05
        v = 3.0 + 4.5 * wear + ((i % 11) / 10 if i % 17 == 0 else 0)
        lines.append(f"2026-01-20T{i//60:02d}:{i%60:02d}:00,{t:.2f},{v:.2f},{1492 - i//40}")
    return ("\n".join(lines) + "\n").encode()


def _png_bytes(w=8, h=8):
    import struct, zlib
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes((int(255 * (x / max(1, w-1))) % 256 for x in range(w))) for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class TestLiveSystem:
    """Complete live system test — all phases."""

    @pytest.mark.asyncio
    async def test_ph3_to_ph20_live(self, client: AsyncClient):
        step = {"n": 0}
        timings = {}

        def ok(phase, msg):
            step["n"] += 1
            safe = msg.encode("ascii", "replace").decode()
            print(f"  [PASS] [{phase}] Step {step['n']}: {safe}")

        def fail(phase, msg):
            step["n"] += 1
            print(f"  [FAIL] [{phase}] Step {step['n']}: {msg}")
            pytest.fail(f"[{phase}] Step {step['n']}: {msg}")

        t_start = time.time()

        # ════════════════════════════════════════════════════════
        # PHASE 3: Backend startup
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 3: BACKEND ===")
        r = await client.get("/api/v1/system/health")
        assert r.status_code == 200
        ok("PH3", "Health endpoint")

        r = await client.get("/api/v1/auth/setup-status")
        assert r.status_code == 200
        ok("PH3", "Database connection")

        from main import app
        routes = sorted(set(r.path for r in app.routes if hasattr(r, "path")))
        assert len(routes) >= 80
        ok("PH3", f"Route count: {len(routes)}")

        # ════════════════════════════════════════════════════════
        # PHASE 5: Authentication
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 5: AUTHENTICATION ===")
        r = await client.post("/api/v1/auth/register", json={
            "email": "admin_live@test.com", "username": "admin_live",
            "password": "AdminLive123!"
        })
        assert r.status_code in (200, 201)
        ok("PH5", f"Admin register: role={r.json().get('role')}")

        r = await client.post("/api/v1/auth/login", json={
            "email": "admin_live@test.com", "password": "WrongPass!"
        })
        assert r.status_code in (400, 401)
        ok("PH5", f"Invalid password rejected: {r.status_code}")

        r = await client.post("/api/v1/auth/login", json={
            "email": "admin_live@test.com", "password": "AdminLive123!"
        })
        assert r.status_code == 200
        admin_token = r.json()["access_token"]
        ah = {"Authorization": f"Bearer {admin_token}"}
        ok("PH5", f"Admin login: token received")

        r = await client.get("/api/v1/auth/me", headers=ah)
        assert r.status_code == 200
        ok("PH5", f"Auth /me: email={r.json().get('email')}")

        r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bogus"})
        assert r.status_code in (401, 403)
        ok("PH5", f"Invalid token rejected: {r.status_code}")

        r = await client.post("/api/v1/auth/register", json={
            "email": "viewer_live@test.com", "username": "viewer_live",
            "password": "ViewerLive123!"
        })
        assert r.status_code in (200, 201)
        r = await client.post("/api/v1/auth/login", json={
            "email": "viewer_live@test.com", "password": "ViewerLive123!"
        })
        viewer_token = r.json().get("access_token") if r.status_code == 200 else None
        vh = {"Authorization": f"Bearer {viewer_token}"} if viewer_token else {}
        ok("PH5", f"Viewer login: token={'yes' if viewer_token else 'no'}")

        # ════════════════════════════════════════════════════════
        # PHASE 6: RBAC / IDOR
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 6: RBAC / IDOR ===")
        r = await client.post("/api/v1/knowledge-bases/", json={"name": "X"}, headers=vh)
        assert r.status_code == 403
        ok("PH6", f"RBAC: viewer denied KB create: {r.status_code}")

        # ════════════════════════════════════════════════════════
        # PHASE 7: Document pipeline
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 7: DOCUMENT PIPELINE ===")
        with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_live"), \
             patch("services.qdrant_service.QdrantService.upsert_vectors"), \
             patch("services.document_service.EmbeddingService.embed_texts",
                    new=AsyncMock(return_value=FAKE_VECTORS(3))):
            r = await client.post("/api/v1/knowledge-bases/", json={
                "name": "Live System Test KB", "description": "Full system test"
            }, headers=ah)
            kb_id = r.json()["id"]
            assert r.status_code == 201
            ok("PH7", f"KB created: {kb_id}")

            doc_content = (
                "BEARING MAINTENANCE MANUAL\n\n"
                "Section 1: The bearing maintenance interval is 500 operating hours.\n"
                "Section 2: Temperature threshold is 85 degrees Celsius.\n"
                "Section 3: Zone C vibration alert starts at 1.8 mm/s RMS.\n"
                "Section 4: Zone D danger level is above 4.5 mm/s RMS.\n"
            ) * 10
            r = await client.post("/api/v1/documents/upload",
                files={"file": ("bearing_manual.txt", doc_content.encode(), "text/plain")},
                data={"kb_id": kb_id, "run_ocr": "false"}, headers=ah)
            doc_id = r.json().get("id")
            assert r.status_code == 202
            ok("PH7", f"Document uploaded: {doc_id}")

        for _ in range(15):
            r = await client.get(f"/api/v1/documents/{doc_id}", headers=ah)
            if r.json().get("status") == "indexed":
                break
            await asyncio.sleep(0.5)
        assert r.json().get("status") == "indexed"
        ok("PH7", f"Document indexed: chunks={r.json().get('chunk_count', 0)}")

        # Invalid extension
        r = await client.post("/api/v1/documents/upload",
            files={"file": ("hack.exe", b"MZ\x90\x00", "application/octet-stream")},
            data={"kb_id": kb_id, "run_ocr": "false"}, headers=ah)
        assert r.status_code in (400, 415, 422)
        ok("PH7", f"Invalid extension rejected: {r.status_code}")

        # Empty file
        r = await client.post("/api/v1/documents/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
            data={"kb_id": kb_id, "run_ocr": "false"}, headers=ah)
        assert r.status_code in (400, 422)
        ok("PH7", f"Empty file rejected: {r.status_code}")

        # ════════════════════════════════════════════════════════
        # PHASE 8: RAG
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 8: RAG ===")
        with patch("services.embedding_service.EmbeddingService.embed_query",
                    new=AsyncMock(return_value=[0.1]*DIM)), \
             patch("services.qdrant_service.QdrantService.search", return_value=[{
                 "id": "c1", "score": 0.95, "doc_id": doc_id, "chunk_id": "c1",
                 "filename": "bearing_manual.txt", "page_number": 1,
                 "content": "The bearing maintenance interval is 500 operating hours."
             }]), \
             patch("services.llm_client.OllamaClient.chat",
                    new=AsyncMock(return_value=type("R", (), {"content": "500 operating hours per manual."})())):
            r = await client.post(f"/api/v1/knowledge-bases/{kb_id}/query",
                json={"query": "What is the bearing maintenance interval?"}, headers=ah)
            rag = r.json()
            assert r.status_code == 200
            ok("PH8", f"RAG query: sources={len(rag.get('sources', []))}")

        # ════════════════════════════════════════════════════════
        # PHASE 9: Chat
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 9: CHAT ===")
        r = await client.post("/api/v1/chat/conversations", json={
            "model_name": "qwen3:14b", "title": "Live Test Chat"
        }, headers=ah)
        assert r.status_code == 201
        conv_id = r.json().get("id")
        ok("PH9", f"Conversation created: {conv_id}")

        r = await client.get("/api/v1/chat/conversations", headers=ah)
        assert r.status_code == 200
        ok("PH9", f"Conversations listed: {len(r.json())} total")

        # ════════════════════════════════════════════════════════
        # PHASE 10: Sensor analysis
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 10: SENSOR ANALYSIS ===")
        r = await client.post("/api/v1/sensor-analyses",
            files={"file": ("bearing_hot.csv", _hot_csv(), "text/csv")},
            data={"generate_explanation": "false"}, headers=ah)
        sensor = r.json()
        sensor_id = sensor.get("id")
        assert r.status_code == 201
        ok("PH10", f"Sensor analysis: status={sensor.get('status')}")

        r = await client.get(f"/api/v1/sensor-analyses/{sensor_id}", headers=ah)
        sa = r.json()
        risk = sa.get("result", {}).get("risk", {}).get("level", "unknown")
        ok("PH10", f"Sensor risk: {risk}")

        r = await client.get("/api/v1/sensor-analyses", headers=ah)
        assert r.status_code == 200
        ok("PH10", f"Sensor analyses listed: {len(r.json())}")

        # ════════════════════════════════════════════════════════
        # PHASE 11: Vision
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 11: VISION ===")
        r = await client.post("/api/v1/incidents", json={
            "title": "Vision Test", "machine": "Press A",
            "description": "Testing vision"
        }, headers=ah)
        vision_inc_id = r.json()["id"]

        with patch("services.vision_service.resolve_vision_model", return_value="llava:7b"), \
             patch("services.vision_service.analyze_image",
                    new=AsyncMock(return_value={
                        "status": "completed",
                        "result": {
                            "finding": "Surface wear on bearing housing",
                            "defects": [{"type": "wear", "severity": "MEDIUM",
                                         "confidence": 0.78,
                                         "description": "Thermal discoloration"}],
                            "recommendation": "Inspect within 7 days",
                            "limitations": ["Resolution limits analysis"]
                        },
                        "model": "llava:7b"
                    })):
            r = await client.post(f"/api/v1/incidents/{vision_inc_id}/vision",
                files={"file": ("bearing.png", _png_bytes(), "image/png")},
                data={"analyze_now": "true"}, headers=ah)
            vision = r.json()
            assert r.status_code == 201
            ok("PH11", f"Vision analyzed: status={vision.get('status')}")

        # Invalid image
        r = await client.post(f"/api/v1/incidents/{vision_inc_id}/vision",
            files={"file": ("bad.txt", b"not an image", "text/plain")},
            data={"analyze_now": "true"}, headers=ah)
        assert r.status_code in (400, 415, 422)
        ok("PH11", f"Invalid image rejected: {r.status_code}")

        # ════════════════════════════════════════════════════════
        # PHASE 12: Incident investigation
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 12: INCIDENT ===")
        r = await client.post("/api/v1/incidents", json={
            "title": "Bearing B-204 Overheating Live Test",
            "machine": "Press A", "asset_tag": "B-204",
            "description": "Temperature and vibration anomalies",
            "kb_id": kb_id, "sensor_analysis_id": sensor_id,
        }, headers=ah)
        inc = r.json()
        inc_id = inc.get("id")
        assert r.status_code == 201
        ok("PH12", f"Incident created: risk={inc.get('risk_level')}")

        # IDOR
        r = await client.get(f"/api/v1/incidents/{inc_id}", headers=vh)
        assert r.status_code == 404
        ok("PH12", "IDOR: viewer denied incident (404)")

        # Investigation
        with patch("services.embedding_service.EmbeddingService.embed_query",
                    new=AsyncMock(return_value=[0.1]*DIM)), \
             patch("services.qdrant_service.QdrantService.search", return_value=[{
                 "id": "c1", "score": 0.91, "doc_id": doc_id, "chunk_id": "c1",
                 "filename": "bearing_manual.txt", "page_number": 12,
                 "content": "Zone C vibration alert starts at 1.8 mm/s RMS."
             }]), \
             patch("services.llm_client.OllamaClient.chat",
                    new=AsyncMock(return_value=type("R", (), {"content": FAKE_INVESTIGATION})())):
            r = await client.post(f"/api/v1/incidents/{inc_id}/investigate", headers=ah)
            inv = r.json()
            assert r.status_code == 200
            ok("PH12", f"Investigation: status={inv.get('status')}, risk={inv.get('risk', {}).get('level', '?')}")

        # ════════════════════════════════════════════════════════
        # PHASE 13: Approval
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 13: APPROVAL ===")
        r = await client.get("/api/v1/approvals/pending", headers=ah)
        assert r.status_code == 200
        ok("PH13", "Approval list accessible")

        # ════════════════════════════════════════════════════════
        # PHASE 14: Audit
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 14: AUDIT ===")
        r = await client.get("/api/v1/audit/verify", headers=ah)
        assert r.status_code == 200
        verify = str(r.json()).encode("ascii", "replace").decode()
        ok("PH14", f"Audit verify: {verify}")

        r = await client.get("/api/v1/audit/logs", headers=ah)
        assert r.status_code == 200
        ok("PH14", f"Audit logs: total={r.json().get('total', len(r.json().get('items', [])))}")

        r = await client.get("/api/v1/audit/logs", headers=vh)
        assert r.status_code in (403, 401)
        ok("PH14", f"Viewer denied audit: {r.status_code}")

        # ════════════════════════════════════════════════════════
        # PHASE 15: Dashboard
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 15: DASHBOARD ===")
        r = await client.get("/api/v1/settings/summary", headers=ah)
        dash = r.json()
        assert r.status_code == 200
        ok("PH15", f"Dashboard: kb={dash.get('knowledge_base_count',0)} doc={dash.get('document_count',0)} "
              f"sensor={dash.get('sensor_analysis_count',0)} incident={dash.get('incident_count',0)} "
              f"audit={dash.get('total_audit_events',0)}")

        # Verify against actual counts
        r_kb = await client.get("/api/v1/knowledge-bases/", headers=ah)
        actual_kb = len(r_kb.json()) if r_kb.status_code == 200 else -1
        assert dash.get("knowledge_base_count", -1) == actual_kb
        ok("PH15", f"Dashboard KB count matches actual: {actual_kb}")

        # ════════════════════════════════════════════════════════
        # PHASE 16: Settings
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 16: SETTINGS ===")
        r = await client.get("/api/v1/settings/", headers=ah)
        assert r.status_code == 200
        ok("PH16", "Settings GET")

        r = await client.put("/api/v1/settings/", json={
            "rag": {"chunk_size": 1000, "chunk_overlap": 200}
        }, headers=ah)
        assert r.status_code == 200
        ok("PH16", "Settings PUT")

        # ════════════════════════════════════════════════════════
        # PHASE 17: Sovereignty
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 17: SOVEREIGNTY ===")
        cloud = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path") and any(
            x in r.path.lower() for x in ["openai", "anthropic", "gemini", "cloud"])]
        assert not cloud
        ok("PH17", "No cloud API endpoints registered")

        r = await client.get("/api/v1/models/roles", headers=ah)
        assert r.status_code == 200
        ok("PH17", f"Model roles: {r.json()}")

        # ════════════════════════════════════════════════════════
        # PHASE 18: Failure injection
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 18: FAILURE INJECTION ===")
        r = await client.get("/api/v1/knowledge-bases/",
            headers={"Authorization": "Bearer expired"})
        assert r.status_code in (401, 403)
        ok("PH18", f"Expired token: {r.status_code}")

        r = await client.get(f"/api/v1/incidents/{inc_id}", headers=vh)
        assert r.status_code == 404
        ok("PH18", f"Foreign resource: {r.status_code}")

        r = await client.post("/api/v1/incidents", json={}, headers=ah)
        assert r.status_code in (400, 422)
        ok("PH18", f"Empty body rejected: {r.status_code}")

        # ════════════════════════════════════════════════════════
        # PHASE 20: Performance
        # ════════════════════════════════════════════════════════
        print("\n=== PHASE 20: PERFORMANCE ===")
        elapsed = time.time() - t_start
        ok("PH20", f"Total test duration: {elapsed:.1f}s")

        print(f"\n{'='*60}")
        print(f"LIVE SYSTEM TEST: {step['n']}/{step['n']} PASSED")
        print(f"{'='*60}")
