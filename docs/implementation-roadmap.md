# Implementation Roadmap — My Project

> Ordered for risk-first delivery. Each phase lists objective, files, steps, tests,
> acceptance criteria, risks. NO implementation starts until this analysis phase is accepted.

## PHASE 0 — Safety / Baseline (0.5 day)
**Objective:** guarantee reversibility and a green baseline.
- Files: none modified; create git branch `hardening-v1`; tag current commit.
- Steps: run existing test suite (`pytest backend/tests`); record pass/fail baseline;
  verify `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` boots;
  capture screenshots of working flows.
- Acceptance: baseline documented in commit message/PR description.
- Risks: OneDrive file locks during test runs → run from local path if needed.

## PHASE 1 — Architecture Cleanup & P0 Hardening (2–3 days)
**Objective:** close the five concrete security/reliability holes before new features.
- Files: `services/document_service.py`, `routers/documents.py`, `routers/knowledge_bases.py`,
  `database.py`, `config.py`, `main.py`, `docker-compose*.yml`, `Dockerfile(backend)`,
  new `alembic/versions/0001_baseline.py`, new middleware/rate-limit module.
- Steps:
  1. M1: background ingestion task creates its own AsyncSession (inject factory, not session).
  2. M2: owner-or-admin checks on document get/delete/download + KB mutations.
  3. Add authenticated document download endpoint (replaces nothing today — fills gap).
  4. Alembic baseline migration + CI check that models match migrations.
  5. Secret fail-fast: refuse boot when secret_key is default and ENVIRONMENT=production.
  6. Rate limiting on `/auth/login|register|refresh`, chat, uploads (in-process token bucket).
  7. docker.sock: introduce least-privilege socket proxy container OR move sandbox exec to sidecar
     service reachable over internal HTTP; API loses direct socket.
  8. Audit hardening: unique constraint on sequence_num w/ retry; SQLite trigger blocking
     UPDATE/DELETE on audit_logs; retention purge job honoring setting.
- Tests: unit (ownership matrix), integration (download authz, rate-limit 429s),
  audit tamper simulation → verify_chain false.
- Acceptance: all existing tests still pass; new security tests pass;
  unauthenticated download returns 401; non-owner delete returns 403.
- Risks: socket-proxy changes dev workflow → keep compose profile fallback with warning.

## PHASE 2 — Dashboard & Observability Uplift (1–2 days)
**Objective:** make the landing page prove system health at a glance (all real data).
- Files: `frontend/src/pages/DashboardPage.tsx`, `backend/services/system_service.py`,
  `routers/system.py`.
- Steps: trend sparklines (CPU/RAM last N samples cached server-side); KB/doc/run counts with
  links; pending-approvals alert card; service latency panel (real pings); "sovereignty" card =
  provider list with Local/Cloud badges (measured config, not slogans).
- Tests: component smoke via vitest (add minimal harness) or manual checklist.
- Acceptance: zero hardcoded numbers; graceful degradation per-promise failure (existing).
- Risks: polling load → reuse 5 s server cache.

## PHASE 3 — Sensor Data Analysis (3–4 days) *(reference concept T1, re-implemented)*
**Objective:** real CSV analytics with anomaly rules and charts.
- Files: new `backend/services/sensor_analysis_service.py`, extend `routers/data.py`
  (`POST /data/sensor-analysis`, `GET /data/datasets/{id}`), SystemSettings thresholds,
  `DataPage.tsx` new tab, chart rendering (lightweight SVG or recharts-free custom bars to avoid
  new deps — decide by bundle budget).
- Steps: validation → pandas profile/stats → rule engine (configurable defaults:
  temp>85°C, vib>6 mm/s, pressure ∉20–120 psi) → severity scoring → ≤50-pt downsampled series
  → persist dataset + summary → audit event.
- Dependencies: pandas (pinned already). None added.
- Security: same upload validator; org scoping; size cap.
- Tests: unit synthetic CSVs (clean/noisy/malformed); integration endpoint authz; threshold edge cases.
- Acceptance: uploading the reference repo's sample telemetry yields stats+anomalies computed live;
  UI shows charts + anomaly table with rule explanations.
- Risks: pandas import weight in container (~already present); large CSVs → stream/chunk read cap.

## PHASE 4 — Predictive Maintenance (3–4 days)
**Objective:** honest machine-health module on real stored readings.
- Files: new models `machine.py`(or reuse data org pattern), `telemetry.py`, `alert.py`;
  `maintenance_service.py`; router `maintenance.py`; frontend MaintenancePage; agent tool
  `machine_report` (read-only, low risk).
- Steps: machine CRUD (analyst/admin); telemetry ingest (CSV bulk + manual entry);
  rolling stats & slope → health_score formula documented in code/UI tooltip;
  alerts on threshold breach; history table; "Explain with AI" launches agent run bound to
  machine context + KB manual → grounded answer with citations; work-order creation as
  high-risk approval-gated tool (uses existing approvals!).
- Tests: health-score math property tests; alert dedupe; agent tool gating; E2E happy path.
- Acceptance: every displayed number derives from stored telemetry; work order requires admin approval.
- Risks: scope creep into full CMMS → keep minimal.

## PHASE 5 — Vision Inspection (2–3 days)
**Objective:** real multimodal inspection using Ollama vision models.
- Files: `vision_service.py` (new), router, InspectionPage, model pull hints for llava-family,
  settings: default vision model.
- Steps: validated image upload → vision-role provider resolution (exists) → structured prompt →
  JSON parse w/ schema validation → confidence handling (<0.5 ⇒ human-review flag) →
  human verdict confirm/reject persisted → audit.
- Tests: mock LLM JSON contract; refusal path when no vision model (honest banner).
- Acceptance: with a vision model pulled, an image yields structured findings + human verdict flow;
  without one, explicit install guidance (no fake output ever).
- Risks: small-model quality → set expectations in UI copy ("assistant finding, human confirms").

## PHASE 6 — Multimodal Workbench Attachments (2 days)
**Objective:** chat/agent runs can consume pdf+csv+image artifacts end-to-end.
- Files: `routers/chat.py`, `agent_service.py`, ChatPage composer, attachment upload reuse.
- Steps: attachments uploaded first (same validators) → refs passed in message payload →
  run context assembly (KB retrieval + sensor summary + vision verdict) → SSE activity labels
  artifact consumption → final citations include artifact sources.
- Tests: integration with all three artifact types; ownership enforcement on refs.
- Acceptance: demo question answered citing manual page + CSV anomaly + image finding in one trace.
- Risks: context budget → strict per-artifact char budgets.

## PHASE 7 — Chat/RAG UX Polish (2–3 days)
**Objective:** make conversations feel production-grade honestly.
- Files: ChatPage, new `api/stream.ts` helper, `rag_service.py`, package.json (add react-markdown
  + remark-gfm + rehype-highlight — evaluate bundle; or minimal md renderer).
- Steps: stop-generation (AbortController client + server detects disconnect & stops generation);
  markdown/code rendering; citation chips under assistant messages (from RAG path when used);
  optional KB selector in agent mode (send kb_ids); streaming RAG answers (SSE through kb query).
- Tests: cancel mid-stream leaves consistent conversation state (integration).
- Acceptance: user can abort; answers render markdown; citations clickable to source chunk.
- Risks: renderer XSS → sanitize/trust config reviewed.

## PHASE 8 — Reliability & Provider Fixes (1–2 days)
- Anthropic health-check AttributeError; Gemini stream parser; remove dead exports;
  wire LOG_LEVEL + configure structlog properly (or drop dep); embedding version stamp +
  dim-drift guard + reindex command; approval poll refactor (short sessions, 2 s loop outside txn).
- Tests: adapter contract tests; reindex integration.

## PHASE 9 — Testing & Security Suite (2 days)
- New: security integration suite (authz matrix, IDOR probes, rate limits, upload fuzz basics,
  SSRF guard cases), E2E smoke script (`scripts/e2e_smoke.py`) driving login→upload→chat→approval.
- Acceptance: suite green in CI-style local run; coverage of every P0/P1 fix above.

## PHASE 10 — SIH Demo Verification (1 day)
- Scripted dry-run of §Demo below; timing each step; fallback talking points;
  record video backup. Freeze tag `sih-demo-v1`.

Total estimate: **≈19–26 focused days**, reorderable after Phase 1 (everything after is additive).

---

## SIH Demonstration Plan (Phase 18 deliverable)

Narrative: *bearing overheating incident on a gas-turbine skid, solved fully offline.*

```
1. Login (admin) → Dashboard shows REAL cpu/ram/qdrant/ollama status      [2 min]
2. Upload maintenance manual PDF → watch ingestion status → indexed       [pre-staged too]
3. Data tab → upload MACHINE-001_sensor.csv → anomalies highlight
   vibration ↑ temperature ↑ vs thresholds                                [live compute]
4. Chat (agent mode) → "Why is MACHINE-001 trending toward failure?
   Recommend actions." + attach csv (+ inspection photo)
   → SSE shows plan/tool/token events; answer cites [Source n] pages
     and references detected anomalies                                    [core moment]
5. Vision: inspection image → structured defect finding (confidence)
   → engineer confirms verdict                                            [if vision model available]
6. Agent proposes WORK ORDER (high-risk tool) → APPROVAL REQUIRED banner
7. Second browser (admin) → Approvals queue → risk badge, input JSON,
   countdown → Approve with note                                          [governance moment]
8. Run resumes; audit page → Verify Integrity ✓ chain; export CSV         [trust moment]
9. Sovereignty story: airplane-mode/wifi-off demo segment — everything
   keeps working; only cloud badges absent because no cloud configured    [closer]
```

Every claim a judge can poke at maps to code shown in this repo's docs:
no fabricated numbers (contrast: reference project's hardcoded GPU %, fake investigation reports).

## Post-demo stretch (P2 backlog)
Investigation-agent timeline view · digital-factory-lite floor map driven by real machine states ·
governance posture page · metrics endpoint · eval harness for RAG accuracy · i18n · shared UI kit.
