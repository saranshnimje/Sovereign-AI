# Recommended Target Architecture for My Project

> Principle: **EXISTING WORKING CAPABILITY + useful reference concepts (re-implemented) + security hardening = target**.
> No architectural replacement; my stack stays: FastAPI(async) · SQLAlchemy async · Qdrant · Ollama(+providers) ·
> Docker sandbox · Vite/React/Zustand SPA.

## 1. Core Request Flow (unchanged, hardened)

```
Browser (React SPA, memory-token + httpOnly refresh cookie)
   ↓  /api/v1/*  (nginx, SSE-safe proxy)
FastAPI
   ├─ RequestID middleware → trace_id
   ├─ Security headers
   ├─ CORS allowlist (frontend_origin only in prod)
   ↓
Authentication  get_current_user (JWT→DB user, is_active)   [ADD: rate limiter]
Authorization   require_role('admin'|'analyst'|'viewer')    [ADD: owner-or-admin on docs/KBs]
   ↓
Services layer
   ├─ chat_service      → SSE token/tool/plan/done events    [ADD: client-cancel support]
   ├─ rag_service       → embed → Qdrant search → grounded prompt → citations
   │                        [ADD: streaming answer; embedding-version stamp]
   ├─ agent_service     → ReAct loop, iteration cap, traces
   ├─ tool registry     → risk/permission/schema gates
   │     └─ high/critical risk → approval_service (pause/resume/expiry)
   ├─ sandbox_service   → Docker isolation                    [MOVE: socket-proxy/sidecar]
   ├─ audit_service     → hash chain                          [ADD: DB immutability trigger, retention job]
   └─ system/settings   → psutil health, runtime settings     [WIRE settings into services fully]
   ↓
Qdrant (collection per KB)          Ollama / provider adapters
SQLite/WAL (async)                  uploads (validated, uuid names)
```

## 2. Document Pipeline (fix + extend)

```
Upload(multipart, kb_id, run_ocr)
 → file_validator (magic bytes, MIME allowlist, size cap)
 → save uploads/{uuid}_{safe_name}
 → Document(status=pending) → BackgroundTask
      [FIX M1: create its own AsyncSession inside task]
 → text_extractor (pdf/docx/txt/csv) → ocr_service if image & enabled
 → chunker(size, overlap from settings)
 → embedding_service.embed_batch(model=KB.embedding_model)   ← stamp model id per vector payload
 → qdrant.upsert(payload: doc_id, kb_id, filename, page, content, embed_model, embed_version)
 → status=indexed | failed(error_message) → audit(document.indexed)
Search/RAG:
 query → embed(query) → Qdrant top_k(score_threshold) 
 → [P2 optional rerank] → context w/ delimiters+budget → LLM stream ([ADD]) 
 → sources=[Source N: filename, page, score] → citation chips in chat UI ([ADD])
Guards: KB/document ownership check on read/delete/download ([FIX M2]);
        refuse query when KB.embedding_model ≠ current embedder output dim ([FIX M8]).
```

## 3. Data-Analysis Pipeline (new — adapted reference concept T1)

```
CSV upload (org-scoped, validated like documents)
 → sensor_analysis_service
      pandas profile: shape, dtypes, numeric columns
      stats: mean/max/min/std per column
      rule engine: thresholds from SystemSettings
        (defaults: temp>85°C, vibration>6 mm/s, pressure outside 20–120 psi — configurable)
      anomalies[]: {column, row_index/timestamp, value, severity, rule}
      downsample series ≤50 points per chart
 → persist SensorDataset(dataset rows, metrics_summary_json)
 → GET returns stats+anomalies+series
 → DataPage "Sensor Analysis" tab renders charts + anomaly table
Every value computed live. No fabricated numbers.
```

## 4. Predictive-Maintenance Pipeline (new, honest)

```
Machines table (real CRUD, analyst/admin) + telemetry ingestion (CSV or manual readings,
time-series rows: machine_id, ts, temperature, vibration_mm_s, pressure_psi, rpm)
 → rules engine (same core as §3): threshold breaches → Alert rows
 → trend scoring: rolling mean/slope per metric → health_score 0–100 (documented formula)
 → maintenance_records history (real entries, not synthesized)
 → MaintenancePage: machine cards with real latest readings, sparkline trends,
    alert list, "Explain with AI" → agent run scoped to this machine's data + KB manual
    → grounded explanation WITH citations + human-approved work-order creation (tool: high risk).
NOT VERIFIED until built: nothing shown that isn't computed.
```

## 5. Vision Pipeline (new, honest)

```
Inspection image upload (validated; stored like documents)
 → vision role routing (existing model_service 'vision' role)
 → Ollama multimodal model (e.g., llava-family) with structured prompt:
      describe defect? severity? confidence? evidence?
 → parse JSON response; low-confidence ⇒ flagged for human review
 → InspectionRecord(model, raw_response, parsed, human_verdict nullable)
 → InspectionPage: image + structured result + human confirm/reject field
If no vision model installed: honest banner "Install a vision model" (current refusal behavior, kept).
```

## 6. Multimodal Workbench (adapt T3)

```
Chat composer gains attachments: 📄 pdf/manual · 📊 csv/sensor · 🖼 inspection image
 → each attachment uploaded through the SAME validated pipeline first
 → agent-mode message includes artifact refs in run context
 → SSE activity shows which tool consumed which artifact
 → final answer cites documents (RAG), datasets (analysis results), images (vision verdicts)
```

## 7. Sovereignty Posture (make enforceable, not cosmetic)

- Keep local-first defaults; cloud providers are explicit admin opt-in with visible ☁️ badges.
- ADD startup network policy doc + optional egress allowlist note; never send data to a provider
  without an explicit per-conversation cloud-model selection (already the UX model).
- Label every dashboard number's source (`psutil`, `qdrant count`, `db count`) — measured-only rule.

## 8. What Deliberately Does NOT Change

- Frontend framework/build stack, zustand stores, axios client + refresh queue.
- Router layout and `/api/v1` contract (additive endpoints only).
- Sandbox security profile (already exceeds any reference capability).
- Audit hash-chain design (only hardening around it).

This yields: my working platform + three honest industrial pipelines + six hardening fixes =
a demo where **every pixel is traceable to real computation**.
