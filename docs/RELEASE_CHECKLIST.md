# Release Checklist
## Sovereign AI Workbench — SIH 2026 Prototype

**Version:** 1.0 Release Candidate  
**Date:** 2026-08-24  
**Status:** READY FOR LOCAL TESTING AND SIH DEMONSTRATION

---

## Automated Verification

| Check | Status | Notes |
|---|---|---|
| Backend unit tests (61) | ✅ PASS | 218/218 total passing |
| Backend integration tests (157) | ✅ PASS | Includes Phase 1–5 |
| TypeScript compilation | ✅ PASS | Zero errors |
| Frontend production build | ✅ PASS | Clean, no warnings |
| ESLint | ✅ PASS | Configured |
| Bandit static analysis | ✅ PASS | 0 medium/high, 10 low (all B110 intentional) |
| Docker Compose config | ✅ PASS | `docker compose config` exits 0 |

---

## Docker Runtime Validation (Verified Live)

| Check | Status | Notes |
|---|---|---|
| Qdrant starts healthy | ✅ PASS | bash TCP healthcheck |
| Backend starts healthy | ✅ PASS | curl healthcheck |
| Frontend starts | ✅ PASS | wget healthcheck |
| Service dependency order | ✅ PASS | qdrant → backend → frontend |
| Volumes persist | ✅ PASS | backend_data, qdrant_data |
| Backend health endpoint | ✅ PASS | `GET /api/v1/system/health` → `{"status":"ok"}` |
| Database service up | ✅ PASS | SQLite with StaticPool |
| Qdrant service up | ✅ PASS | HTTP reachable from backend |
| Ollama service reported | ✅ PASS | Status reported (up/down based on host) |

---

## End-to-End Feature Validation (74/74 live checks)

| Feature | Status | Notes |
|---|---|---|
| **First-run setup detection** | ✅ PASS | setup_required=true on fresh DB |
| **First user gets admin role** | ✅ PASS | Server-side enforcement |
| **Login / JWT** | ✅ PASS | Token issued, /me works |
| **Setup completed after first user** | ✅ PASS | setup_required=false after register |
| **Dashboard summary** | ✅ PASS | All 5 count fields present |
| **Activity feed** | ✅ PASS | Recent audit events |
| **System status** | ✅ PASS | Services + resources |
| **Models list** | ✅ PASS | Returns installed Ollama models |
| **Model roles** | ✅ PASS | chat + embedding roles defined |
| **Settings GET** | ✅ PASS | All fields present |
| **Settings PUT** | ✅ PASS | Saved and persisted |
| **Settings validation** | ✅ PASS | Bad values → 422 |
| **Create Knowledge Base** | ✅ PASS | 201 Created |
| **Document upload** | ✅ PASS | 202 Accepted, processing steps tracked |
| **Document processing pipeline** | ✅ PASS | Runs; fails gracefully if embedding model missing |
| **KB query endpoint** | ✅ PASS | Returns sources + answer fields |
| **Audit hash chain verified** | ✅ PASS | verified=True, 13 entries checked |
| **Audit CSV export** | ✅ PASS | Downloads correctly |
| **Tools list** | ✅ PASS | 7 tools: file_read/write/list/delete, search_kb, calculator, python_exec |
| **Agent run created** | ✅ PASS | 202 Accepted immediately |
| **SSE stream** | ✅ PASS | HTTP 200, content-type=text/event-stream |
| **Agent run detail** | ✅ PASS | tool_calls field present |
| **Approvals endpoint** | ✅ PASS | Pending list accessible |
| **Approval count badge** | ✅ PASS | Count endpoint works |
| **RBAC: viewer denied audit** | ✅ PASS | 403 Forbidden |
| **RBAC: viewer denied settings** | ✅ PASS | 403 Forbidden |
| **RBAC: viewer denied KB create** | ✅ PASS | 403 Forbidden |
| **RBAC: viewer denied agent run** | ✅ PASS | 403 Forbidden |
| **RBAC: viewer denied model roles** | ✅ PASS | 403 Forbidden |
| **Password hash never exposed** | ✅ PASS | Not in /me or /users responses |
| **User management** | ✅ PASS | Admin lists users |

---

## Known Issues

### Non-Blocking (Demo Can Proceed)

| Issue | Impact | Fix |
|---|---|---|
| `nomic-embed-text` not pulled on this machine | Document processing fails at embedding step | Run `ollama pull nomic-embed-text` before demo |
| `llama3.2:3b` not pulled on this machine | Chat and RAG generation will fail | Run `ollama pull llama3.2:3b` before demo |
| Document shows `status=failed` when embedding model missing | Graceful failure with clear error message | Pull embedding model |
| Pydantic `model_name` namespace warning | Cosmetic only, no runtime impact | Acceptable for prototype |

### Cosmetic (No Impact)

| Issue | Impact |
|---|---|
| `version: "3.9"` removed from compose files (obsolete) | Warning eliminated |
| urllib3/charset_normalizer version mismatch warning | From existing system packages, not our code |

---

## Exact Local Startup Commands

### Prerequisites

```bash
# 1. Docker Desktop 24+ running
docker --version    # Must be 24+
docker compose version  # Must be v2+

# 2. Ollama installed and running
ollama --version
ollama serve &  # If not running as a service

# 3. Pull required models (one-time, needs internet, ~2.5 GB total)
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### First-Time Setup

```bash
# Clone / enter project directory
cd "Sovereign AI Workbench"

# Generate .env with a secure key
python -c "import secrets; key=secrets.token_hex(32); open('.env','w').write(f'SECRET_KEY={key}\nOLLAMA_URL=http://host.docker.internal:11434\nDATA_DIR=/app/data\nDEFAULT_CHAT_MODEL=llama3.2:3b\nDEFAULT_EMBEDDING_MODEL=nomic-embed-text\nLOG_LEVEL=INFO\n')"

# Build and start the stack
docker compose up --build -d

# Wait ~60 seconds, then verify
curl http://localhost/api/v1/system/health
# Expected: {"status":"ok"}
```

### Health Check

```bash
# All three services healthy
docker compose ps
# Expected: qdrant (healthy), backend (healthy), frontend (health: starting/healthy)

# Full validation
python scripts/validate_stack.py
# Expected: 74/74 PASS (or 75/75 with embedding model pulled)
```

### URLs

| Service | URL |
|---|---|
| Frontend | http://localhost |
| Backend API | http://localhost/api/v1 or http://localhost:8000/api/v1 |
| API Docs | http://localhost:8000/api/docs |
| Qdrant UI | http://localhost:6333/dashboard |

### First Login

1. Open http://localhost
2. First-run setup screen appears automatically
3. Enter: username `admin`, email `admin@yourorg.com`, password (min 12 chars)
4. Click **Create Account & Sign In**
5. Dashboard loads

### Stop / Restart

```bash
# Stop (preserves data)
docker compose down

# Stop and wipe all data (full reset)
docker compose down -v

# Restart after code changes
docker compose up --build -d
```

---

## Demo Quick-Start Workflow (5 minutes)

1. Open http://localhost → complete first-run setup
2. **Dashboard** → observe service status + resource metrics
3. **Models** → see installed model `qwen3:14b` (or your pulled models)
4. **Knowledge Bases** → create "Demo KB" → upload a PDF/TXT document
5. **Knowledge Bases** → ask a question → observe source citations
6. **Chat** → select model → send message → watch SSE streaming
7. **Agents** → new run → goal: "List files and calculate 2**10" → observe trace
8. **Audit** → click "Verify Integrity" → confirm hash chain is valid
9. **Settings** → show RBAC with role management

---

## Files Changed in Phase 5

| File | Change | Reason |
|---|---|---|
| `backend/config.py` | Added `DATA_DIR` env var, derived path properties | P0: configurable data paths |
| `backend/database.py` | StaticPool for SQLite, WAL mode at startup | P0: fix "database is locked" |
| `backend/main.py` | Use `settings.data_dir` instead of hardcoded `/app/data` | P0: consistency |
| `backend/services/settings_service.py` | Use `_get_settings_file()` from config | P0: configurable paths |
| `backend/services/model_service.py` | Use `_roles_file()` from config | P0: configurable paths |
| `backend/services/chat_service.py` | Title includes ellipsis for long messages | P1: better UX |
| `backend/routers/agents.py` | Added `/runs/{id}/stream` SSE endpoint, fresh DB session per poll | P1: live agent streaming |
| `docker-compose.yml` | Qdrant bash TCP healthcheck, frontend wget healthcheck, `DATA_DIR` env, removed `version:` | P0: runtime fixes |
| `docker-compose.dev.yml` | Removed obsolete `version:` | Cosmetic |
| `backend/requirements.txt` | Removed `python-magic-bin` (Windows-only, never used) | P0: Docker build fix |
| `.env.example` | Added `DATA_DIR` documentation | P0: developer experience |
| `frontend/src/pages/AgentPage.tsx` | SSE via fetch + auth header, removed dead EventSource | P1: correct SSE |
| `frontend/src/components/layout/AppShell.tsx` | Added Models to nav, removed Documents placeholder | UX |
| `docs/DEMO_GUIDE.md` | Created | P4: demo prep |
| `docs/HARDWARE_CHECKLIST.md` | Created | P4: hardware guidance |
| `docs/RELEASE_CHECKLIST.md` | Created (this file) | P4: release tracking |
| `scripts/validate_stack.py` | Created | P0: live validation |
| `backend/tests/unit/test_config_data_dir.py` | Created | P5: path tests |
| `backend/tests/integration/test_phase5_api.py` | Created | P5: integration tests |
