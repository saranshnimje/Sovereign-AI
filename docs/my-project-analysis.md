# My Project Analysis — Sovereign AI Workbench

> Forensic, read-only source-level analysis. Classification legend:
> **IMPLEMENTED-WORKING** · **PARTIAL** · **STUB** · **MISSING** · **NOT VERIFIED**.
> Verified via full-file reads + targeted greps; git repo `main` @ `71302e0`.

---

## 1. Identity & Stack

| Attribute | Value |
|---|---|
| Path | `C:\Users\Sonam\OneDrive\Desktop\Sovereign AI Workbench` |
| Git | Yes — branch `main`, commit `71302e0` |
| Backend | FastAPI 0.111 (pinned), SQLAlchemy 2 async + aiosqlite, PyJWT, passlib/bcrypt, **qdrant-client**, docker SDK, psutil, structlog, PyMuPDF, python-docx, pandas |
| Frontend | Vite 5 + React 18 + TypeScript (strict) + react-router-dom v6 + zustand + axios + Tailwind |
| Vector DB | **Qdrant** (real client, collection-per-KB, COSINE) |
| LLM runtime | **Ollama** (`host.docker.internal:11434`) + multi-provider adapters |
| Sandbox | Docker-isolated Python execution |
| Deployment | docker-compose (+ dev override with hot reload), nginx prod stage with SSE tuning |

Backend ≈ **12,400 non-blank lines** (~15k physical) incl. ~3,500 lines of tests.
This is a substantially finished codebase, not scaffolding.

---

## 2. Backend Architecture

### 2.1 App factory (`backend/main.py`) — IMPLEMENTED-WORKING
- Lifespan: data dirs created → `init_db()` → seeds default Ollama provider row.
- CORS restricted to `[frontend_origin, localhost:5173, localhost]` with explicit method/allow-header lists.
- `X-Request-ID` middleware + security headers middleware
  (`nosniff`, `X-Frame-Options: DENY`, XSS, Referrer-Policy).
- Global exception handlers returning structured error envelopes `{error:{code,message,details,trace_id}}`.

### 2.2 Auth & RBAC — IMPLEMENTED-WORKING
(`services/auth_service.py`, `dependencies.py`, verified)
- bcrypt password hashing; JWT HS256 from env secret (`change-me...` default must be overridden).
- **Access token in memory only on the client**; httpOnly refresh cookie server-side;
  refresh tokens stored as hashes, rotated on every refresh, revoked on logout.
- `verify_token` re-reads the user from DB and checks `is_active` (auth_service.py:110–127).
- First registered user becomes admin (bootstrap); no open role self-selection afterwards.
- `require_role(*roles)` dependency factory; shortcuts `AdminRequired`, `AnalystRequired`.
- Roles: `viewer / analyst / admin`.

### 2.3 API surface (16 routers under `/api/v1`)
auth · chat · models · system · audit · documents · knowledge-bases · agents · approvals ·
settings · models/providers · tools · plugins · data.

Highlights (verified):
- **Chat**: POST message returns `StreamingResponse` SSE with typed events —
  `plan`, `tool` (incl. `approval_required`, `denied`, `unavailable`), `token{delta}`, `done`, `error`
  (routers/chat.py:188–294). Both direct-chat and agent-mode paths.
- **Agents**: create run, list, get (with tool-call trace), cancel, plus `/runs/{id}/stream` SSE that
  performs **ownership checks** ("Access denied" events) and streams step/status/complete/error
  (routers/agents.py:289–351).
- **Documents**: multipart upload with `BackgroundTasks` ingestion and status tracking.
- **Approvals**: pending queue, approve/reject-with-note, count badge endpoint.
- **Audit**: paginated filtered list, `/verify` hash-chain check, CSV/JSON export.
- **Providers**: CRUD for 8 provider types (ollama/openai-compat/anthropic/gemini/openrouter/nvidia/zen),
  live model discovery, per-user model preferences, model pull streaming.
- **Data module**: organizations → data sources (direct text, web URL, file upload, SQLite path);
  per-org knowledge bases.

### 2.4 Data models (12 files)
user, conversation(+messages), knowledge_base, document, provider, provider_model,
agent_run(+tool_calls), approval, audit(hash chain), data(org/source), user_prefs, tool_settings.
Tenancy = org concept in Data module + KB ownership fields; **document-level ownership checks are
inconsistent (known gap — see §6)**.

### 2.5 RAG pipeline — IMPLEMENTED-WORKING (verified by direct read)
`services/rag_service.py`: embed query (Ollama `/api/embed`) → Qdrant search (score threshold) →
context build with **per-source `<document>` delimiters, `<>` escaping, 800-char chunk cap,
token budgeting** → Ollama chat with strict grounded-answer system prompt ([Source N] citations,
"say clearly if not found") → RagResult(answer, sources, timings, low_confidence flag).
Non-streaming answer (gap). No reranker (gap).

### 2.6 Qdrant integration — IMPLEMENTED-WORKING (verified)
`services/qdrant_service.py`: collection name derived only from KB UUID (never raw user input);
COSINE vectors; payload carries doc_id/filename/page_number/content; delete-by-doc_id filter;
health check. Sync client used on async loop (perf debt).

### 2.7 Document ingestion — PARTIAL
Upload validation via magic-bytes sniffer (no libmagic dependency), extension+MIME allowlist,
50 MB limit. Extraction PDF/DOCX/TXT/CSV working; OCR service exists but PaddleOCR dep commented out
→ emits `[OCR_UNAVAILABLE]`. Chunker (char//4 token estimate, configurable size/overlap).
Step-tracked statuses. **Known hazard**: BackgroundTasks + session lifetime under FastAPI ≥0.106;
no embedding-version tracking (switching embedding model breaks retrieval dimension match).

### 2.8 Tools + sandbox — IMPLEMENTED-WORKING
Tool registry with categories, risk levels (low→critical), permission gates, enable/disable,
input schemas, plugin provenance. Tools: web_search/web_fetch (with SSRF guard), calculator,
time, KB search, file_read/write/list/delete, python_exec, meta tools.
**Sandbox profile (non-negotiables enforced)**: fresh container per run, UID 1000, cap_drop ALL,
network none, read-only rootfs, writable temp workspace cleaned after, pids_limit 50, memory 256 MB,
CPU quota 50%, hard timeout 30 s, auto-remove, stdout/stderr caps (sandbox_service.py:1–20).

### 2.9 Human approval workflow — IMPLEMENTED-WORKING
High/critical-risk tool calls create Approval rows; agent pauses (`awaiting_approval`);
expiry ⇒ auto-reject; approve resumes execution. Admin Approvals page polls every 10 s with
risk badges, countdown, mandatory rejection note. Caveat: polling holds a session up to 5 min;
`tool_call_id` linkage not always set.

### 2.10 Audit — IMPLEMENTED-WORKING (verified)
Append-only hash chain: SHA-256 over `{seq}:{ts}:{user}:{action}:{outcome}:{prev_hash}`,
GENESIS genesis entry, `verify_chain()` recomputes everything, admin-only access, CSV/JSON export.
Real client-IP extraction (trusted X-Real-IP from nginx only; XFF deliberately ignored as spoofable).
Caveats: sequence allocation has a race under concurrency; immutability is convention-only (no DB trigger);
retention setting exists but no purge job.

### 2.11 Health/observability — IMPLEMENTED-WORKING
psutil CPU/RAM/disk, service health (Ollama/Qdrant pings), loaded-model listing, cached 5-second
status, activity feed. GPU stubbed False.

### 2.12 Config/settings
pydantic-settings `.env` driven; SystemSettings table for runtime RAG/sandbox/approval settings —
**but many services still read env-derived config directly, so UI settings partially illusionary (P1 fix)**.
structlog imported but never configured (decorative); stdlib logging everywhere.

---

## 3. Frontend (Vite + React SPA)

### 3.1 Routing & guards — FULLY WIRED
15 real pages + 1 intentional placeholder. `RequireAuth` (checks in-memory token) and
`RequireRole` (viewer/analyst/admin) route guards; bootstrap flow: memory token → else httpOnly
refresh-cookie POST `/auth/refresh` → `me()`. Axios interceptor injects Bearer; **single-flight
refresh queue** retries concurrent 401s once, then hard-redirects to /login.

### 3.2 Pages (all traced to real endpoints)
| Page | Status | Notes |
|---|---|---|
| Login | FULLY WIRED | dual-mode sign-in / first-admin creation via setup-status |
| Dashboard | FULLY WIRED | 30 s poll: system status, summary counts, activity feed; skeletons; empty states |
| Chat | FULLY WIRED | conversation rail (search/rename/delete), provider-grouped model selector w/ Local🔒 vs Cloud☁️, agent settings (tool/plugin modes persisted per-user), two streamed send paths, streaming cursor, optimistic bubbles, Ctrl+Enter |
| Knowledge Bases | FULLY WIRED | card grid, create modal, illustrated empty state |
| KB Detail | FULLY WIRED | drag-drop upload w/ client validation + OCR toggle, 4 s status polling, RAG query panel with Answer + SourceCards (relevance bars, page numbers, expandable chunks), Embed/Retrieve/Generate timings, low-confidence warning |
| Agents | FULLY WIRED | goal form (max iterations clamp), security explainer, tool grid w/ risk+sandbox badges, run history, detail trace with expandable JSON I/O, cancel, live SSE updates, approval-required banner |
| Approvals | FULLY WIRED (admin) | risk badges, expiry countdown, required reject note, optimistic removal, sidebar badge |
| Audit | FULLY WIRED (admin) | filters (type/outcome/date/IP), pagination, row detail, Verify Integrity banner, CSV/JSON export |
| Models | FULLY WIRED | discovery/catalog/pull-stream terminal, enable/disable, use-in-chat deep-link |
| Providers | FULLY WIRED | backend-driven presets, masked API keys, test-connection trick, local/cloud grouping |
| Tools | FULLY WIRED | category groups, risk/permission chips, enable/disable, test probe |
| Plugins | FULLY WIRED | provides ✓/✗, protected core-utilities id |
| Data | FULLY WIRED | orgs → sources (direct/web/location/sqlite/api), indexed docs table; loose typing on two responses |
| Settings | FULLY WIRED (admin) | validated ranges, users management with self-demotion protection |

### 3.3 Honest gaps (not fakery)
- No markdown/code rendering in chat (plain pre-wrap text) — no library installed.
- **No stop-generation button** (no AbortController on chat stream).
- No temperature/top_p controls; no KB scope picker inside chat (agent kb_ids never sent by UI).
- Citations render only in KB Detail, not in chat.
- Dead exported API functions (exportConversation, getRoles/setRole, testDb/dbSchema/dbSync...).
- ESLint config file missing (lint script fails); favicon 404 (no public dir).
- i18n absent (IST date formatting is thorough though); modals lack focus trap/Esc.
- Duplicated ad-hoc Badge components across pages instead of a shared kit.

### 3.4 Hardcoded/mock audit
Remarkably clean. Only: optimistic tmp message (legit pattern), initial default model literal,
hardcoded audit event-type enum, protected plugin id string, static marketing copy. **No fake stats.**

---

## 4. Tests — IMPLEMENTED (substantive)
~3,500 lines: unit tests for auth, chunker, file validator, hash chain, qdrant service, rag service,
sandbox (hardening assertions!), tool registry, text extractor, embedding service;
integration suites for auth API, KB API, agents, providers/discovery, tools/plugins, phase4/5 APIs.

## 5. Deployment
Multi-stage Dockerfiles; dev compose with hot reload (source mounted read-only, data volume writable);
nginx prod proxy with SSE-safe settings (`proxy_buffering off`, 600 s read timeout).
docker.sock mounted into backend (needed by sandbox — see security note).
Alembic pinned but zero migrations (schema via create_all).

## 6. Known Weaknesses (honest register)

| # | Priority | Issue |
|---|---|---|
| M1 | P0 | Background-task ingestion may use closed AsyncSession (FastAPI ≥0.106 semantics) — verify/fix session injection |
| M2 | P0 | Document/KB ownership checks inconsistent (delete/get paths rely on role alone) |
| M3 | P1 | SystemSettings UI not fully wired into services (env still authoritative in places) |
| M4 | P1 | No Alembic migration baseline; schema drift risk |
| M5 | P1 | docker.sock in API container = container escape equivalent if RCE occurs; move sandbox exec to sidecar or socket-proxy |
| M6 | P1 | No rate limiting anywhere; no login lockout |
| M7 | P1 | Audit retention setting unused (no purge job); audit seq race under concurrency |
| M8 | P1 | No embedding-version tracking; switching embedder silently breaks retrieval |
| M9 | P2 | RAG answer not streamed; no reranker; no chat-side citation rendering |
| M10 | P2 | Anthropic health-check AttributeError; Gemini stream parser brittle; model_select tool uses asyncio.run() inside loop (always fails) |
| M11 | P2 | structlog decorative; LOG_LEVEL setting unused |
| M12 | P2 | Frontend hygiene: missing eslint config, favicon 404, dead exports, no stop button, no markdown rendering |
| M13 | P2 | SQLite StaticPool serializes all requests (throughput ceiling); sync Qdrant calls on event loop |

## 7. Verdict
Core loops are real and internally consistent: auth (with rotation+revocation), RBAC, SSE chat,
RAG with citations, Qdrant persistence, registry-gated tools, hardened sandbox, human approvals,
hash-chained audit, live provider discovery, honest dashboards, substantive tests. The gaps are
engineering-debt items (ownership edge cases, background sessions, migrations, streaming-RAG polish),
not fabrication. This is the opposite profile of the reference project.
