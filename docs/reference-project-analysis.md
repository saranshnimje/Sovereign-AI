# Reference Project Analysis — sovereign-ai-workbench-main

> Forensic, read-only source-level analysis. Every claim below was verified against actual
> source code (file:line references included). Classification legend:
> **IMPLEMENTED-WORKING** · **PARTIAL** · **MOCKED** (fake data presented as real) ·
> **STUB** (dead code) · **BROKEN** (crashes) · **NOT VERIFIED**.

---

## 1. Project Identity

| Attribute | Value |
|---|---|
| Path | `C:\Users\Sonam\OneDrive\Desktop\sovereign-ai-workbench-main` |
| Git | NOT a git repository (downloaded archive) |
| Framework | FastAPI backend + Next.js 14 App Router frontend |
| Languages | Python 3 / TypeScript |
| Package manager | pip (`requirements.txt`), npm (`package.json`) |
| Frontend stack | Next.js 14, React 18, Tailwind CSS 3, recharts, lucide-react, **firebase ^12** |
| Backend stack | FastAPI, SQLAlchemy 2 (sync), Alembic (configured, **zero migrations**), python-jose JWT, passlib (pbkdf2), PyMuPDF, python-docx, pandas/numpy |
| Vector DB declared | FAISS (`VECTOR_DB_TYPE=faiss`) + Qdrant URL in config — **neither is imported anywhere** |
| Actual vector store | In-memory Python list (`rag/vector_store.py`) with hash-fake embeddings |
| AI provider | Ollama HTTP integration exists but is unreachable from main flows |
| Database | SQLite default / Postgres 15 in docker-compose |
| Docker | docker-compose.yml: postgres, qdrant, ollama, backend, frontend |

**Headline verdict:** a demo-grade presentation scaffold. The backend **cannot boot as shipped**
(import-time `NameError`), the document pipeline crashes into its own exception handler, the
"RAG" is an in-memory mock with fake embeddings, the flagship chat **never calls any LLM**,
and there are four independent authentication backdoors.

---

## 2. Backend Architecture

### 2.1 Entry point (`app/main.py`)
- No app factory; module-level singleton; `Base.metadata.create_all()` at import time.
- CORS: `allow_origins=["*"]` **with** `allow_credentials=True` (main.py:31–37). The configured
  `settings.CORS_ORIGINS` is never used.
- Cosmetic "sovereignty" headers middleware (`X-Data-Sovereignty`, etc.) — no enforcement behind them.
- **Anonymous static mount**: `app.mount("/files", StaticFiles(directory=settings.STORAGE_PATH))`
  (main.py:77) → every uploaded document downloadable by unauthenticated anyone.
- Public `/health` returns hardcoded `"healthy"`.

### 2.2 API inventory (all routers, verified)

| Router | Endpoints | Auth | Key findings |
|---|---|---|---|
| `/api/auth` | register, login, me, logout | mixed | Register: **role self-selection incl. ADMIN**; registering with an existing email **returns a valid token for that account without checking the password** (auth.py:32–35). Login auto-creates demo accounts on failed login with attacker-chosen password (auth.py:87–99). Logout does not invalidate tokens (8 h life). |
| `/api/users` | list, get, update, delete | JWT (+ADMIN on update/delete) | GET `/{user_id}` has no RBAC — any user reads any profile. Delete = soft-deactivate only. |
| `/api/chat` | query, stream, conversations CRUD | JWT | Query persists Conversation/Message/AgentRun/ToolCall then calls a **template generator — zero LLM calls**. `/stream` is theatrical SSE: scripted step events + word-by-word replay of the pre-computed answer. **IDOR**: conversation read/write not ownership-checked. |
| `/api/documents` | upload, list, get/status/metadata/chunks, delete | JWT | Upload runs broken ingestion inline → every doc ends `FAILED`. Any user can delete any doc (no owner check); deleted docs' vectors stay searchable until restart. `/chunks` leaks full text cross-department. |
| `/api/search` | semantic search | JWT | Fabricates defaults (`doc-1`, `0.85` score) and hardcodes classification `CONFIDENTIAL`. |
| `/api/agents` | list, execute | JWT | Execute path: keyword gate → mock retrieval → ComplianceAgent (**only live LLM path**) → template engine. Ollama-down fallback raises `ImportError` (missing class) → 500. |
| `/api/workflows` | list, create, execute, status | JWT | Execution and status return hardcoded fabricated results (`COMPLETED`, `100%`). |
| `/api/dashboard` | overview | JWT | Real counts inflated by floors (`max(n,14)` docs, `max(n,480)` chunks...); GPU/CPU/RAM hardcoded strings. |
| `/api/inspection` | analyze, history | JWT | **Fake vision**: filename keyword match ("bearing"/"gear" ⇒ canned defect at 0.89 confidence). Raw `file.filename` join ⇒ path traversal/overwrite risk. |
| `/api/data` | sensor upload, datasets | JWT | **REAL pandas statistics** (mean/max/min/std) + threshold anomaly rules. The one genuinely working industrial feature. Same raw-filename traversal risk. |
| `/api/maintenance` | machines, history | JWT | If rows exist it **ignores stored sensor values** and fabricates temp/vibration/pressure from the status string. |
| `/api/models` | list, configure | JWT | Hardcoded catalog + fabricated eval metrics; RBAC check executed then **return value ignored** (models_mgr.py:74) — any user can reconfigure models. |
| `/api/audit-logs` | list | JWT only | **No RBAC** — any VIEWER can read the entire compliance trail. IP always literal `"127.0.0.1"`. |
| `/api/system/health`, `/api/ai/*`, `/api/health/firebase` | health/models | **PUBLIC** | Hardcoded latencies/resources (CPU 18.4%, GPU 32.1%...); Firebase health "connected" if project-id string exists. |
| `/api/demo/seed` | seed demo data | **NO AUTH** | Creates ADMIN account with password echoed in response body (`AdminSovereign2026!`). Anyone on the network can call it (demo.py:12–36). |
| `/api/investigations` | run, list | JWT | Entire "13-step AI investigation" is a static block of literals interpolated with machine_code. Confidence fixed at 0.87. |
| `/api/factory` | machines | JWT | Pre-baked synthetic 8-machine factory floor. |
| `/api/security` | status | JWT | Fabricated posture: `security_score 98.5`, `142 blocked connections`; `SecurityEvent` table written by nothing. |
| `/api/settings` | get, set | JWT (+ADMIN enforced on set) | Runtime-only; never persisted. |

### 2.3 Authentication internals
- Passwords: pbkdf2_sha256 via passlib (fine).
- JWT: HS256, secret **hardcoded** in config.py:42 *and shipped in `.env.example`*
  (`sovereign_secret_key_sih_2026_industrial_workbench_987654321`) → anyone with repo access can forge ADMIN tokens for any deployment using defaults. 480-minute expiry. Claims `{sub,user_id,role,department}`; roles from token only, never re-read from DB; `is_active` never checked during validation.
- Firebase Auth: verifier function exists (`core/firebase.py:40`) but **is never called by any route** — Firestore never queried. Decorative.
- No refresh tokens, no rate limiting, no lockout, no email verification.

### 2.4 Data model (19 tables)
users, documents (owner_id nullable, never enforced; department soft-filter on listing only),
document_chunks (vectors duplicated as JSON), conversations, messages, agent_runs, tool_calls,
machines, maintenance_records, inspection_records, investigations, audit_logs +
**dead tables**: `models_config`, `alerts`, `security_events`, `memory_items`, `agents`.
**No organization/tenant concept anywhere.** Alembic wired but `alembic/versions/` does not exist.

---

## 3. AI / RAG / Document Pipeline

### 3.1 Two parallel, inconsistent pipelines
- **Live chat path**: AgentOrchestrator → `SovereignEngine.process_multimodal_query`
  (inference/sovereign_engine.py): optional image → fake vision; optional CSV → real pandas;
  KB search → mock store; maintenance history → DB or fabricated fallback; then
  **assembles the "answer" from f-string templates with fixed recommendations regardless of
  question** (sovereign_engine.py:118–130). Confidence hardcoded `0.88/0.82`. AgentRun rows
  persist this as `status="SUCCESS"`.
- **Provider abstraction** (`app/ai/llm/providers/`): registry of ollama/vllm/llama_cpp/huggingface/cloud.
  `OllamaProvider` is a genuinely working HTTP client including true token streaming
  (ollama_provider.py:16–97) — reachable only via `/api/agents/{id}/execute`. But **every provider's
  failure fallback imports `SovereignOfflineEngine`, which does not exist anywhere** (6 references in
  5 files) → any Ollama outage ⇒ ImportError ⇒ 500.

### 3.2 RAG reality
- Embeddings: SentenceTransformer `all-MiniLM-L6-v2` (384-dim) when installed; silent fallback to a
  sin/cos character-hash vector otherwise. Config advertises `bge-m3` (unused mismatch).
- Vector store: two Python lists, cosine + keyword-overlap boost (`overlap*0.05`). **No persistence**
  (index evaporates on restart). Department filter supported; no per-user/per-document security filter;
  deleted documents remain searchable. **FAISS/Qdrant never imported despite config claiming them.**
- Chunking: word windows 400/40 (working path); intended-but-broken path 500/50. No sentence awareness.
- Parsing: PyMuPDF pages, python-docx headings, txt/csv/md raw. XLSX/PNG/JPG whitelisted for upload
  but have **no parser** → guaranteed FAILED. OCR: pytesseract optional; fallback **fabricates text**
  ("[OCR Fallback Annotation]: ... surface analysis indicates mechanical component state") which enters
  the knowledge base as if real.
- Reranking: keyword-overlap scoring only — inside dead code (`ai_service.py`, never called by any router).
- Citations: `"{filename}, Page {n}"` from chunk metadata — real strings, but attached to template answers.
- Prompt injection defense: good design (`<<<>>>` scrubbing, enterprise system prompt) — in the same dead code.

### 3.3 Agents & tools
- "LangGraphOrchestrator" is plain sequential Python calls; langgraph absent from requirements.
- Tools are direct static method calls in-request. **No sandbox, no tool approval flow, no human-in-the-loop.**
- Workflow execution results are fabricated literals.

### 3.4 Document lifecycle verdict
```
Upload → uuid+secure_filename save → SYNCHRONOUS ingestion:
  parse()   ← AttributeError (method is parse_file)
  chunk()   ← AttributeError (method is chunk_document_pages)
  both swallowed by except → status="FAILED"
```
Plus: `import werkzeug` used but werkzeug missing from requirements.txt → clean-install uploads 500 before even reaching the pipeline. No background jobs anywhere.

---

## 4. Frontend (Next.js)

### 4.1 Verdict summary
Of 17 pages: **14 STATIC-MOCK**, **3 PARTIALLY REAL** (login, workbench, settings).

- **No state management library, no React Context.** Auth = ad-hoc `localStorage.getItem('sovereign_user')`
  reads; the plain JSON object (including `role`) is trusted client-side; nothing actually gates on role.
- **Login fabricates sessions**: typing any string containing "admin" mints a local session without any
  server call when backend is absent; tokens are forged client-side
  (`'airgapped_jwt_token_local_session_' + Date.now()`, login/page.tsx:124).
- **Demo admin passwords ship in the client bundle** (`AdminSovereign2026!`, login/page.tsx:67).
- Workbench sends `'Authorization': 'Bearer demo-token'` (workbench/page.tsx:150); hardcodes its own
  user label `'Rajesh Sharma (Senior Eng.)'` (page.tsx:328); model selector updates state that is never
  sent to the API (lines 282–284 vs POST body 152–159).
- **9 buttons rendered with no onClick handler** (Upload Sensor CSV, Upload Industrial Manual,
  Upload Inspection Photo, Execute New AI Investigation, Register New Industrial Asset, Switch Active
  Model, three attach buttons in workbench).
- External Unsplash CDN image in the "air-gapped" inspection page (fails offline).
- **The frontend does not compile as committed** — orphaned statement fragment after `handleAuthSubmit`
  in login/page.tsx:225–251 (duplicate catch/finally, reference to undeclared variable).
- Settings page: one real endpoint (GET/POST settings, runtime-only).
- Security page self-labels: `"FIREWALL TELEMETRY — SIMULATED / DEMO"`.

### 4.2 What looks impressive but isn't backed
Rich-looking dashboards (recharts), digital-twin factory floor, investigation timelines, security center,
model manager with benchmark scores — all hardcoded arrays/objects defined inside components.

---

## 5. Industrial Features: REAL vs MOCK

| Feature | Verdict | Evidence |
|---|---|---|
| Sensor CSV analysis (pandas stats + thresholds) | **REAL** | industrial_tools.py:17–79 |
| Predictive maintenance fleet | MOCKED | maintenance.py:64–66 (values derived from status label) |
| Vision inspection | MOCKED | filename keyword match, canned confidences |
| Incident/root-cause investigation | MOCKED | static narrative, confidence 0.87 constant |
| Digital factory twin | MOCKED | pre-baked array |
| Workflow automation | MOCKED | fabricated step results |
| Dashboards / system health / security center | MOCKED | hardcoded numbers, inflated floors |
| RAG chat over manuals | MOCKED | template answers, no LLM |
| Audit trail | PARTIAL | writes exist; world-readable; fake IPs |
| User management | WORKING | but undermined by registration takeover bugs |

## 6. Tests
Six test files; thin happy-path tests around mocks; `test_backend.py` exercises the unauthenticated seed
backdoor (codifying it); no test covers the upload ingestion pipeline (which would expose breakage);
no negative/security cases.

## 7. Reliability Defect Register

| # | Severity | Finding | Location |
|---|---|---|---|
| R1 | CRITICAL | Backend fails to boot: `List` used without import → NameError at import time | agents/orchestrator.py:1,42 |
| R2 | CRITICAL | Ingestion calls non-existent methods → all uploads FAILED | services/ingestion_service.py:27,42 |
| R3 | CRITICAL | `SovereignOfflineEngine` referenced 6×, defined nowhere → all provider fallbacks crash | ollama_provider.py:52,94; vllm_provider.py:51; llama_cpp_provider.py:43; huggingface_provider.py:25; cloud_adapter.py:26 |
| R4 | HIGH | `werkzeug` imported but not in requirements.txt | document_service.py:3,26 |
| R5 | HIGH | `json.loads` without `import json`, masked by `except: pass` | ai_service.py:199,207 |
| R6 | MEDIUM | Dead tables (5), dead services (AuthService/AuditService/RAGService/AIService unused), duplicate pipelines (RAGPipeline vs IngestionService; llm_client vs OllamaProvider) | various |
| R7 | MEDIUM | DEMO_MODE env flag referenced nowhere in code | compose vs grep |
| R8 | LOW | try/except-pass blocks; swallowed delete errors | document_service.py:75–76; providers |

## 8. What Is Genuinely Good (worth studying, not copying blindly)
1. **OllamaProvider streaming implementation** — correct token-level SSE consumption pattern.
2. **CSV analyzer** — sensible pandas profiling + threshold rules + downsample-for-chart approach.
3. **Enterprise prompt design** (dead code) — anti-hallucination instructions, injection scrubbing concept.
4. **Page taxonomy breadth** — the 17-page information architecture shows what SIH judges expect to see
   (workbench, KB, data analysis, vision, maintenance, investigation, factory, governance, sovereignty,
   use-cases). The UX *concepts* are valuable even though implementations are fake.
5. Multi-provider registry concept (ollama/vllm/llama.cpp/HF/cloud) as an abstraction idea.

## 9. Bottom Line
The reference project is a **presentation shell**: strong vocabulary, broad page coverage, near-zero
functional depth, four auth backdoors, wildcard credentialed CORS, anonymous file serving, and a
backend that cannot start. Anything adopted from it must be **re-implemented against my architecture's
security model**, never ported.
