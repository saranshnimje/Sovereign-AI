# Phase 2 Implementation Notes — P0 Hardening + P1.1 Sensor Analysis + P1.2 Incident Workbench + P1.3 Vision Inspection + P1.4 Chat/RAG Polish

Companion to `implementation-roadmap.md`. Records exactly what changed during
Phase 2 (P0 security/architecture hardening) and how to operate it.

## Baseline → Result

| Metric | Before | After |
|---|---|---|
| Backend test suite | 293 passed / 3 failed (order-dependent pollution) | **375 passed / 0 failed** (320 P0 → 353 P1.1 → 375 P1.2) |
| Frontend build (`tsc && vite build`) | passing | passing (no new warnings) |
| App boot smoke | 93 routes | 95 routes (+retry, +reindex) |

## Changes by item

### Step 0 — test hygiene
`tests/conftest.py`: autouse fixture re-enables every tool on the registry
singleton before/after each test — fixes 3 pre-existing order-dependent failures
caused by integration tests disabling shared tools.

### P0.5 — secret fail-fast
- `config.py`: new `environment` setting; `_validate_production_secrets()` runs
  inside `get_settings()` — with `ENVIRONMENT=production`, boot REFUSES when
  `SECRET_KEY` is <32 chars or matches known placeholders.
- `.env.example` / compose: `ENVIRONMENT` documented & plumbed.

### P0.1 — ingestion lifecycle (background-task sessions)
- Root cause: FastAPI ≥0.106 closes request-scoped dependencies BEFORE
  BackgroundTasks run; the router handed the closed request session into
  `process_document`, so uploads could stick at `pending`.
- `routers/documents.py`: standalone `run_ingestion_task(doc_id)` opens a fresh
  `AsyncSessionLocal` session, rebuilds services, commits on success,
  rolls back + logs on failure. Never silent.
- New `POST /documents/{doc_id}/retry` (owner/admin, only for `failed`,
  requires original file present) → resets state and re-enqueues the same task.
- `services/document_service.py`: `reset_document_for_reprocess()` is the ONE
  state-reset used by retry AND reindex; `list_accessible_documents()` scoped;
  `delete_document_checked()`.
- Frontend: ⟳ retry button on failed rows (`KnowledgeBaseDetailPage.tsx`),
  `documentsApi.retry()`.

### P0.2 — ownership / IDOR enforcement
- New `services/kb_access.py`: single canonical policy. KBs are private:
  owner-or-admin; everyone else gets **404** (identical to missing ⇒ no
  existence leakage). Documents inherit KB ownership.
- Applied to: KB list/get/delete/query, upload-target KB check, document
  get/list/delete/retry, agent-run `kb_ids` validation, chat agent-mode
  fallback KB selection (tenancy-scoped), and the `search_kb` tool itself
  (LLM-supplied kb_id checked against the requesting user; foreign ⇒ honest
  empty result).
- Behavior change: viewers no longer see other users' KBs (previously global).

### P0.7/P0.8 — embedding provenance + dimension-drift guard
- Every indexed vector payload now stamps `embed_model`, `embed_version`
  (model tag), `embed_dim`.
- Ingest-side guard: embedding dims must equal `get_expected_dimension(model)`
  exactly, else job FAILS with explicit error and NOTHING is upserted
  (no truncate/pad/mixing).
- Query-side guards: query vector dim must match the KB model's expected dim;
  retrieved chunks stamped with a different `embed_model` are refused with an
  explicit "reindex required" error.
- New `POST /knowledge-bases/{kb_id}/reindex` (owner/admin): re-runs the
  canonical pipeline per stored document (skips missing files), audited.

### P0.3 — Alembic baseline
- `backend/alembic.ini`, async `backend/alembic/env.py` (URL resolved from app
  settings; SQLite batch mode), standard `script.py.mako`,
  `versions/838a7d4139b1_baseline_schema.py` (full intended schema, hand-verified).
- Verified: fresh DB `upgrade head` ⇒ 18 tables; `downgrade base` ⇒ clean;
  re-upgrade OK.
- Procedure:
  - Fresh deployment: `cd backend && alembic upgrade head` (or let
    `init_db()` create-all, then `alembic stamp head`).
  - Existing dev DB: `alembic stamp head` (schema already matches baseline).
  - Future schema changes: `alembic revision --autogenerate -m "..."` after
    editing models.

### P0.6 — rate limiting
- New `utils/rate_limit.py`: thread-safe sliding-window limiter keyed by
  trusted client IP (X-Real-IP only via nginx, else TCP peer; XFF ignored).
- Scopes (env-tunable, requests/min/IP): auth=30, upload=30, ai=120; master
  switch `RATE_LIMIT_ENABLED`. Exceeding ⇒ `429` + `Retry-After`.
- Wired: register/login/refresh, document upload, chat direct+agent sends,
  KB query, agent run creation.
- Single-process scope documented (per uvicorn worker buckets).

### P0.4 — docker socket isolation
- `docker-compose.yml`(+dev): backend NO LONGER mounts `/var/run/docker.sock`;
  new least-privilege sidecar `dockerproxy` (tecnativa/docker-socket-proxy,
  pinned) grants only CONTAINERS/IMAGES/PING/VERSION/POST(+IMAGES_CREATE);
  SECRETS/NETWORKS/SWARM/EXEC/SYSTEM/BUILD/etc. explicitly 0. Socket mounted
  `:ro` into the proxy only. Backend uses `DOCKER_HOST=tcp://dockerproxy:2375`.
- Sandbox-unavailable path raises an explicit `SandboxError` (tested).
- Regression guards: `tests/unit/test_compose_security.py` parses the real
  compose files so future edits cannot silently re-expose the socket.

## Tests added
- `tests/unit/test_secret_validation.py` (6)
- `tests/unit/test_rate_limit.py` (4)
- `tests/unit/test_compose_security.py` (5)
- `tests/integration/test_ingestion_lifecycle_api.py` (4: indexed lifecycle,
  persisted failure, retry-to-green, retry-conflict)
- `tests/integration/test_ownership_api.py` (3: cross-user isolation matrix,
  analyst-vs-analyst writes, foreign-kb agent run rejection)
- Updated legacy expectation: unknown KB on upload now 404 (was 422).

## Dependencies added
- `pyyaml==6.0.1` (test-only; compose parsing tests).

## Known issues / limitations (honest register)
1. Rate limiting is per-process; scale-out requires a shared store (Redis) later.
2. Sandbox workspace bind-mounts use container-local temp paths — works where
   backend shares the daemon host (dev); under full containerized deployments a
   shared named-volume design should replace it (flagged as follow-up, needs
   live-Docker testing which this machine cannot run).
3. `search_kb` returns an empty "not found" result rather than raising for
   foreign KBs (deliberate: avoids leaking existence to the LLM stream).
4. Pre-existing warnings untouched (pydantic model_name namespace, bcrypt
   __about__, requests/urllib3 pairing) — cosmetic, out of P0 scope.

## Manual verification checklist
1. `ENVIRONMENT=production SECRET_KEY=short python -m uvicorn main:app` → refuses to start.
2. Upload bad PDF → status FAILED with real error; ⟳ button appears; retry works.
3. Second analyst cannot GET/query/delete first analyst's KB or docs (404 everywhere).
4. `RATE_LIMIT_AUTH_PER_MIN=5 RATE_LIMIT_ENABLED=true` + rapid logins ⇒ 429 + Retry-After header.
5. `docker compose config` shows no socket on backend; only dockerproxy mounts it (:ro).

---

# P1.3 — Real Vision Inspection (implemented)

## Architecture
```
POST /api/v1/sensor-analyses  (analyst/admin, upload rate-limit)
  validate_upload() reuse → save uploads/sensor/{uuid}_{safe}.csv
  SensorAnalysis(status=pending) persisted
  asyncio.to_thread(analyze_csv_bytes)      ← DETERMINISTIC pandas engine
    decode(utf8-sig→utf8→latin-1) → delimiter-sniff parse → row/col guards
    schema detect (timestamp/numeric/ignored + coercion-failure counts)
    per-column stats: count/missing/min/max/mean/median/std/p05/p25/p75/p95/
                      roc_mean/roc_max/slope/change_pct/trend
    anomalies (transparent methods, each record carries method+baseline+score+explanation):
       threshold   — name-matched physical bounds (temp>85°C, vib>6mm/s, …) configurable map
       robust_z    — median/MAD ≥3.5 (Iglewicz–Hoaglin) w/ std & zero-variance fallbacks
       rate_change — |Δ| robust-z ≥4 AND Δ ≥2% of typical level (noise gate)
    risk = worst-driver aggregation (level healthy/watch/elevated/critical + reasons)
    trend_preview ≤80 real sampled points/column for UI charts
  status=completed(+result_json) | failed(+real error_message)   ← both audited
  optional AI explanation via role-routed Ollama chat:
     prompt forbids inventing numbers; stored in ai_explanation columns ONLY;
     on unavailability → ai_explanation_error set, numbers untouched
GET  list (own / admin all) · GET {id} (+audit viewed) · GET {id}/anomalies?severity&sensor
DEL  {id} (owner/admin, removes file, audited)
```

## Files
**New:** `models/sensor.py`, `services/sensor_analysis_service.py`, `routers/sensor_analysis.py`,
`alembic/versions/e3cffa904812_add_sensor_analyses.py`,
`tests/unit/test_sensor_service.py` (22), `tests/integration/test_sensor_api.py` (11),
`frontend/src/api/sensor.ts`, `frontend/src/pages/SensorPage.tsx`,
`scripts/generate_bearing_sample.py` (+ generated `scripts/sample_data/bearing_run.csv`).
**Modified:** `models/__init__.py`, `main.py` (router @ `/api/v1/sensor-analyses`),
`alembic/script.py.mako` (auto-import database), App.tsx route `/sensor`, AppShell nav 📈.

## Verification performed
- Engine unit tests incl. determinism, degenerate-baseline handling, malformed inputs.
- API integration tests: ownership matrix (foreign ⇒ 404 on get/list/anomalies/delete),
  viewer 403, audit rows asserted in DB for uploaded/completed/viewed,
  Ollama-unavailable ⇒ numbers intact + honest error marker, mocked-LLM cannot
  alter stats/anomalies/risk, oversize rejection.
- Alembic e3cffa904812 verified upgrade/downgrade/re-upgrade on throwaway DB.
- Full suite **353 passed / 0 failed**; frontend `tsc && vite build` clean; boot smoke 100 routes.
- Real bearing sample (1440 rows): engine derived risk=critical from data —
  bearing_temp_C increasing trend + sustained >85 °C threshold breaches + vibration spikes.

## Known limitations (P1.1)
- Threshold rules match column-name patterns (documented precedence); custom units not parsed.
- Anomaly records capped at 500 most-severe (summary always covers all).
- Explanation runs inline post-analysis (bounded by provider timeout); not streamed.
- Rate limiter/upload scope shared with document uploads (same bucket family).


---

# P1.2 — Bearing Overheating Incident Workbench (implemented)

## Architecture (reuses everything — no duplicates)
```
POST /incidents {title, machine, asset_tag, description, kb_id?, sensor_analysis_id?}
  attachments ownership-checked NOW (foreign ⇒ 404) + initial deterministic risk snapshot
POST /incidents/{id}/investigate
  status=analyzing → audit analysis_started
  DOCUMENT EVIDENCE  → existing RagService.query(generate_answer=False) on the attached KB
                       (kb_access re-checked at run time; embed+Qdrant reused)
  SENSOR EVIDENCE    → attached SensorAnalysis result_json (ownership re-checked);
                       top anomalies by severity/score + per-sensor trends
  evidence_json      ← exact snapshot used (documents w/ [Doc N: file, p.X] labels,
                       sensors, trends, insufficient_evidence flag)
  risk_json          ← DETERMINISTIC rules R1–R6 from sensor data only
  Ollama chat        → 7-question grounded prompt; forbids inventing values/pages/
                       citations/actions; requires final "ACTION:" line
  recommendation     → action text extracted from AI output, labelled AI-provided;
                       risk level stays deterministic
  high/critical      → ApprovalRequest row in the EXISTING queue
                       (operation_detail carries incident_id) → admin Approvals page
  status=completed | failed(+real error)   both audited
GET list / GET {id}(audited viewed) / PATCH attachments / DELETE
```

## Files
**New:** `models/incident.py`, `services/incident_service.py`, `routers/incidents.py`,
`alembic/versions/4f6782f5ce44_add_incidents.py`,
`tests/unit/test_incident_service.py` (13), `tests/integration/test_incident_api.py` (9),
`frontend/src/api/incidents.ts`, `frontend/src/pages/IncidentsPage.tsx`.
**Modified:** models/__init__, main.py (router @ /api/v1/incidents), App.tsx (/incidents,
analyst/admin), AppShell nav 🛠️.

## Deterministic risk rules (transparent, recorded per investigation)
R1 temp limit breached → ≥medium · R2 temp trend increasing → +1 ·
R3 vibration anomalies → ≥medium · R4 vibration trend increasing → +1 ·
R5 any critical anomaly → ≥high · R6 top driver ≥10% samples → ≥high.
LLM output never changes risk; tests enforce identical evidence/risk across
different model answers.

## Verification performed
- 22 new tests green (13 unit risk/evidence/prompt/extraction + 9 integration).
- Integration suite exercises REAL endpoints: attachment authorization matrix,
  investigate happy path (mocked RAG hits + mocked LLM) asserting citation label
  "[Doc 1: bearing_manual.pdf, p.12]", sensor numbers byte-equal to the engine's
  own anomalies, approval row created pending & linked by incident_id, analyst
  self-approval ⇒ 403 while admin approves via existing endpoint, insufficient-
  evidence flag, explicit provider-failure ⇒ honest ai_error with deterministic
  parts intact, full audit chain (created/started/completed/viewed +
  approval.request_created).
- LIVE check: with the local Ollama reachable, the real router path produced a
  genuine grounded interpretation of the bearing evidence (observed during
  test development before failure-simulation was made explicit).
- Alembic 4f6782f5ce44 verified up/down/up. Full suite **375/0**;
  frontend tsc+vite clean; boot smoke **106 routes**.

## SIH demo steps (all real)
1. operator login → Incidents → New Incident: machine "Press A", asset B-204,
   description "Why is Bearing B-204 overheating…", pick manuals KB + bearing CSV
   analysis → Create.
2. Run Evidence-Grounded Investigation → show Document Evidence citations,
   Sensor Evidence table (values = engine numbers), Deterministic Risk rules R1/R2…
3. AI Analysis section (grounded interpretation + limitations).
4. Recommendation + HIGH-RISK approval badge → second browser (admin) → Approvals →
   approve with note → back in incident, approval id resolved in audit chain.

## Known limitations (P1.2)
- Investigation is synchronous (button spinner, 180 s client timeout); streaming later.
- ACTION extraction is line-protocol based; unparsed output leaves recommendation text
  empty and UI points at AI analysis (no fabrication).
- Image attachment placeholder only — Vision is the next phase, explicitly not started.

---

# P1.4 — Chat/RAG Polish (implemented)

## Architecture
```
User question
    ↓
Chat router (resolve LLM + optional RAG retrieval)
    ↓
ChatService.stream_message() → SSE generator
    ├── evidence event (once, before tokens, if sources found)
    ├── token events (incremental, real streaming)
    ├── done event (token count, finish reason)
    └── error event (honest failures)
    ↓
Frontend MessageBubble / StreamingBubble
    ├── MarkdownRenderer (react-markdown + rehype-sanitize)
    ├── CitationChip (clickable, hover preview)
    ├── EvidencePanel (collapsible, source details)
    └── Stop/Retry controls (AbortController → CancelledError)
```

## Files modified
**Backend:**
- `services/llm_client.py` — OllamaProvider._stream_chat() now handles thinking models (qwen3, deepseek-r1) that put output in `thinking` field
- `services/chat_service.py` — stream_message() accepts rag_sources + rag_context, emits evidence event, catches CancelledError for clean abort, stores evidence in metadata_json
- `routers/chat.py` — send_message() reads rag_kb_ids from raw body, performs RAG retrieval with authorization gate, passes sources to generator

**Frontend:**
- `package.json` — added react-markdown, remark-gfm, rehype-sanitize
- `src/api/chat.ts` — typed MessageResponse.metadata with CitationSource[] + evidence structure
- `src/components/chat/MarkdownRenderer.tsx` — NEW: safe markdown rendering with rehype-sanitize
- `src/components/chat/CitationChip.tsx` — NEW: clickable citation with hover preview
- `src/components/chat/MessageBubble.tsx` — NEW: markdown + citation chips for persistent messages
- `src/components/chat/StreamingBubble.tsx` — NEW: live markdown + citations + stop button
- `src/components/chat/EvidencePanel.tsx` — NEW: collapsible evidence summary
- `src/pages/ChatPage.tsx` — refactored to use new components, AbortController, stop/retry, evidence panel
- `src/index.css` — added line-clamp utilities for citation previews

**Tests:**
- `tests/integration/test_chat_security.py` — NEW: 18 tests (15 security scenarios + 3 structural)

## SSE protocol (enhanced)
```
event: token    data: {"delta": "..."}              — incremental text
event: evidence data: {"sources": [...], "source_count": N}  — RAG evidence (once)
event: done     data: {"finish_reason": "stop", "token_count": N}
event: error    data: {"code": "...", "message": "..."}
```

Evidence event is emitted BEFORE the first token when RAG sources are provided.
Each source has: index, source_type (document/sensor/vision), label, doc_id,
filename, page_number, score, content_preview.

## Cancellation implementation
Frontend: `AbortController` → `fetch({ signal })` → `reader.cancel()`
Backend: FastAPI detects client disconnect → `asyncio.CancelledError` raised
inside generator → caught cleanly, no partial message saved, error event emitted.

Verified: CancelledError is caught before db.flush(), so no orphaned rows.

## Markdown security
- `rehype-sanitize` strips all dangerous HTML: `<script>`, `<iframe>`, event handlers,
  `javascript:` URLs, `<object>`, `<embed>`, `<form>`, etc.
- Only safe HTML elements pass through (headings, paragraphs, lists, tables, code, links).
- Links get `target="_blank" rel="noopener noreferrer"` for external safety.
- No XSS vulnerability from model output — sanitization happens at render time.

## Citation architecture
- **Backend:** RAG retrieval attaches `citation_label` (e.g., "[Doc 1: file.pdf, p.12]")
  and structured metadata to each source. Evidence event carries full source array.
- **Frontend:** CitationChip renders clickable labels. Regex matches `[Source N]` and
  `[Doc N: ...]` patterns in streamed text. Sources matched by index from evidence event.
- **Authorization:** KB access filtered by `user_id` — User B cannot see User A's sources.
  Foreign KB IDs silently filtered (honest degradation, no information leakage).

## Thinking model support
OllamaProvider._stream_chat() now checks `msg.thinking` when `msg.content` is empty.
This handles qwen3, deepseek-r1, and other "thinking" models that separate reasoning
from response. Non-streaming path already had this fix.

## Verification
- 18 new tests pass (15 security + 3 structural: SSE structure, ownership CRUD).
- **419/0** backend tests. **Frontend tsc+vite clean**. **Boot smoke 112 routes**.
- **LIVE CHECK PASSED**: real Ollama qwen3:14b streaming 439 tokens incrementally,
  440 SSE events parsed, assistant message persisted (1865 chars).

## SIH demo steps
1. Login → Chat → select model (qwen3:14b or any available) → Ctrl+Enter to send.
2. Real streaming tokens appear with blinking cursor and ■ Stop button.
3. Markdown renders: **bold**, *italic*, `code`, lists, tables, headings.
4. If RAG KB is configured: evidence panel shows sources, citation chips inline.
5. Stop button → generation aborts → "Stopped" state → Retry button re-sends.
6. Error states show with retry option (Ollama down, timeout, etc.).

## Known limitations (P1.4)
- RAG retrieval in chat is triggered by `rag_kb_ids` in the request body (not yet
  wired to a UI KB selector — the frontend currently does not send rag_kb_ids).
  The investigation workflow (P1.2) already uses RAG via the incident flow.
- Citation regex is simple `[Source N]` / `[Doc N: ...]` matching. If the model
  uses different notation, citations render as plain text (honest, no fabrication).
- Evidence panel only shows for the last assistant message (not all messages).
- Thinking model output includes internal reasoning — visible in chat. Could be
  filtered later with a `/no_think` parameter or post-processing.

---

## P1.5 — Settings Wiring

### Problem
The SettingsPage UI allowed admins to edit system settings (RAG, sandbox, agent),
but most backend services read from `config.Settings` (env-based, cached at startup)
instead of `SystemSettings` (JSON-based, live). Changes saved via the UI had no effect.

### Changes
- **`document_service.py`**: Replaced `self.settings = get_settings()` with
  `load_settings()` calls for chunk_size, chunk_overlap, max_upload_size_mb.
  `upload_dir` still uses `get_settings()` (env property, not in SystemSettings).
- **`chat.py` router**: Replaced hardcoded `top_k=5, score_threshold=0.3` with
  `load_settings().default_top_k` and `load_settings().default_score_threshold`.
  Replaced `__import__` hack with proper `from services.settings_service import load_settings`.
- **`sandbox_service.py`**: Split into `_env_settings` (for `sandbox_image`) and
  runtime `load_settings()` calls for timeout, mem, cpu.
- **`approval_service.py`**: Replaced `self.settings.approval_timeout_minutes` with
  `load_settings().approval_timeout_minutes`.
- **`knowledge_base_service.py`**: Kept `get_settings()` for `default_embedding_model`
  (env-only; changing requires reindexing all KBs).
- **`SettingsPage.tsx`**: Added Sovereignty Status section (provider status, model
  roles), LIVE/STATIC honesty badges on all setting fields.

### What's LIVE vs STATIC
See `docs/settings-audit.md` for full table. Key: RAG settings (chunk, top-k,
threshold), sandbox limits, and approval timeout are LIVE. Max iterations is STATIC
(schema-level default).

### Verification
- 252 unit + integration tests pass
- TypeScript clean, Vite build succeeds
- Frontend shows sovereignty dashboard with provider/role status
- Honesty badges indicate live vs static per setting

---

## P1.6 — Dashboard Trends

### Changes
- **`schemas/settings.py`**: Added `sensor_analysis_count`, `incident_count`,
  `critical_risk_count`, `high_risk_count` to `DashboardSummary`.
- **`routers/settings.py`**: `dashboard_summary()` now queries SensorAnalysis,
  Incident counts (total, critical, high risk).
- **`DashboardPage.tsx`**: New row of metric cards for sensor/incident/risk counts.
- **`api/settings.ts`**: Updated TypeScript interface.

### Verification
- Dashboard summary includes all 9 real metrics
- No hardcoded or fabricated data

---

## P1.7 — OCR Profile

### Changes
- **`ocr_service.py`**: Improved logging (INFO level) for availability status.
- **`docs/ocr-availability.md`**: Documents OCR status, implementation, enablement.

### Status
OCR is fully implemented via PaddleOCR. Currently unavailable (not installed).
Scanned documents produce empty OCR text with honest logging. Normal text-based
documents are unaffected. To enable: uncomment `paddleocr`+`paddlepaddle` in
`requirements.txt`.

---

## P1.8 — Approval Polling Refactor

### Changes
- **`approval_service.py`**: 
  - Added `_approval_events: dict[str, asyncio.Event]` for in-process signaling.
  - `create_request()` registers an event.
  - `wait_for_decision()` uses `asyncio.wait_for(evt.wait(), timeout=...)`
    instead of sleep-looping. Calls `expire_stale()` at entry.
  - `approve()`/`reject()` signal the event for immediate wake-up.
  - Event cleanup on all exit paths.

### Security invariants preserved
- High/critical risk tools require human approval
- Expired requests auto-reject
- Admin-only approval
- Decision recorded with who/when/note

### Verification
- 24 new unit tests for approval flow
- All existing tests pass

---

## P1.9 — Final Security Test Suite

### Changes
- **`test_security_suite.py`**: 27 new integration tests covering:
  - Auth security (expired/malformed/empty tokens, Bearer prefix)
  - RBAC comprehensive (viewer/analyst/admin boundaries)
  - IDOR comprehensive (sensor, incident, conversation, list filtering)
  - Upload security (oversized, content-type, SQL injection, XSS)
  - Chat security (prompt injection, empty/long messages)
  - Audit security (required fields, append-only, verify endpoint)
  - SSE/Streaming (unauthorized, format, ownership)

### E2E Smoke Test
- **`test_e2e_smoke.py`**: 11-step automated workflow test covering the
  complete SIH demo flow from health check through audit verification.

### Verification
- 477 tests pass (was 429, +48 new)
- All security invariants verified
