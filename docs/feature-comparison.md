# Feature Comparison — Reference vs My Project

> Legend: quality graded on verified source evidence only.
> P0 = core/security/blocking · P1 = important enhancement · P2 = optional enhancement.

## 1. Master Feature Matrix

| Feature | Reference | Mine | Ref Quality | My Quality | Better | Gap (mine) | Recommendation | Priority |
|---|---|---|---|---|---|---|---|---|
| Authentication | Local JWT + 4 backdoors; Firebase decorative | JWT + refresh rotation/revocation, is_active checks | BROKEN (takeover bugs) | Strong | **Mine** | none critical | keep; add lockout | — |
| Registration | Open, role self-selection incl. ADMIN | First-user-admin bootstrap; admin-managed users | CRITICAL FLAW | Good | **Mine** | no email verification | optional invite flow | P2 |
| RBAC | 3 endpoints correct, 1 ignored check, most JWT-only | require_role factory used across routers + UI gating | Weak | Good | **Mine** | audit a few read endpoints | consistency pass | P1 |
| Org/tenant isolation | None (department soft filter) | Org concept in Data module; KB-scoped collections | Missing | Partial | **Mine** | document-level ownership inconsistent | enforce owner checks | **P0** |
| Document management | Upload broken (FAILED always); any-user delete | Validated upload, statuses, delete, KB scoping | Broken | Good | **Mine** | ownership checks; download endpoint missing | fix + add download | **P0/P1** |
| Document ingestion | Crashes into except → FAILED | Background pipeline w/ step tracking | Broken | Good-Partial | **Mine** | background session hazard | fix session lifecycle | **P0** |
| OCR | pytesseract optional + fabricated fallback text | PaddleOCR service exists, dep commented out (`[OCR_UNAVAILABLE]` honest) | Dangerous fake | Partial | **Mine** | heavy dep not installed | enable optionally in Docker profile | P1 |
| Chunking | word windows, no persistence | configurable char/token chunker, tested | Weak | Solid | **Mine** | sentence-aware option | minor | P2 |
| Embeddings | MiniLM or silent hash-fake fallback | Ollama embeddings (nomic-embed-text), batched | Fake-prone | Solid | **Mine** | embedding versioning absent | add version stamping | **P0→P1** |
| Vector DB | In-memory lists; FAISS/Qdrant claimed but never imported | Real Qdrant: collection-per-KB, COSINE, filters | MOCKED | Strong | **Mine** | dim-drift guard | guard + reindex cmd | P1 |
| RAG retrieval | keyword boost over mock store | Qdrant score-threshold semantic search | MOCKED | Strong | **Mine** | reranker absent | optional cross-encoder/rerank model via Ollama | P2 |
| Citations | strings from chunks attached to template answers | [Source N] with page numbers, relevance scores, low-confidence flag | Fabricated context | Strong | **Mine** | citations not rendered in chat UI; no citation validation vs answer | chat rendering + validator | P1 |
| Prompt-injection defense | good design trapped in dead code | delimiters + escaping + grounded system prompt live | Dead code | Good | **Mine** | adversarial test suite | add tests | P1 |
| Ollama integration | working provider but unreachable from main flows | primary path, streaming, health pings | Side-lined | Strong | **Mine** | — | — | — |
| Provider abstraction | registry of 5 types; fallbacks crash | 8 adapter types, discovery, per-role routing, prefs | Crash-prone | Strong | **Mine** | Anthropic health bug, Gemini parser | patch two adapters | P1 |
| SSE streaming | theatrical replay with sleeps | true token events (token/tool/plan/done/error) | MOCKED | Strong | **Mine** | no client stop/cancel | AbortController + server close | P1 |
| Stream cancellation | N/A | missing client-side | Missing | Gap | tie | both lack it | implement | P1 |
| Agents | sequential function calls named "LangGraph"; template outputs | ReAct loop, iterations cap, workspaces, traces, cancel, live stream | MOCKED | Good-Partial | **Mine** | canned/heuristic tool args; max 3 tools/chat | improve planner prompting | P1 |
| Tools | direct static calls, no sandbox | registry + risk + permissions + schemas | Unsafe | Strong | **Mine** | — | — | — |
| Human approval | absent entirely | full workflow w/ expiry, notes, resume | Missing | Strong | **Mine** | session-hold polling | refactor to short sessions/poll | P1 |
| CSV/data analysis | real pandas stats + thresholds | Data module orgs/sources; SQLite ingest; web/direct | Partial | Different shape | tie | pandas profiling/anomaly rules thinner than ref | adopt threshold-analyzer concept | **P1** |
| Vision inspection | filename-keyword fake | vision role routing exists; refuses honestly if no model | MOCKED | Honest gap | **Mine** | no actual inspection pipeline | build image-analysis workflow (llava/bakllava via Ollama) | P1 |
| Predictive maintenance | fabricates sensor values from status labels | not present as dedicated module | MOCKED | Missing | tie | whole feature | build REAL one (see roadmap) | P1 |
| Telemetry/sensor store | machines table ignored on read | data sources generic | Fake | Partial | **Mine** | time-series model | design ts schema | P1 |
| Incident investigation | static narrative, confidence 0.87 constant | not present | MOCKED | Missing | tie | whole feature | build evidence-based investigation agent over KB+CSV | P2 |
| Audit log | world-readable, IP always 127.0.0.1, no integrity | hash chain + verify + export + trusted IP extraction | Weak | Strong | **Mine** | retention job, seq race, DB-level immutability | harden | P1 |
| Governance/security pages | fabricated scores ("98.5") | honest status pills, real counts | Fake | Honest | **Mine** | dedicated governance view | surface audit/RBAC posture | P2 |
| Dashboard | inflated floors, hardcoded GPU stats | all-real psutil+DB metrics | Fake | Strong | **Mine** | charts/trends absent | add recharts-style trends | P1 |
| Observability | hardcoded latencies | cached psutil + service pings + activity feed | Fake | Good | **Mine** | no request metrics/prometheus | add counters/metrics | P2 |
| Model management | hardcoded catalog + fake benchmarks | live discovery + pull stream + enable/disable + prefs | Fake | Strong | **Mine** | benchmark evals (real) | optional eval harness | P2 |
| Digital factory | pre-baked synthetic floor | absent | Mocked | Missing | tie | whole feature | only if demo value justifies; must be data-driven | P2 |
| Docker/deployment | compose w/ DEMO_MODE flag nothing reads | multi-stage builds, dev override, nginx SSE tuning | Sloppy | Strong | **Mine** | docker.sock exposure | socket proxy/sidecar | **P0→P1** |
| Offline sovereignty | cosmetic headers; Unsplash CDN image; flags unenforced | local-first defaults; honest refusal when models missing | Cosmetic | Substantive | **Mine** | outbound egress allowlist not enforced at process level | document/enforce network policy | P1 |
| Testing | thin happy-path around mocks; codifies backdoor | ~3.5k lines unit+integration incl. sandbox hardening | Weak | Strong | **Mine** | no security tests; no E2E | add security suite | P1 |
| UI/UX breadth | 17 pages, rich visuals, mostly inert | 15 pages, everything wired | Veneer | Functional | split | visual polish, industrial page coverage | adopt IA concepts honestly | P1 |

## 2. What TO Take From the Reference (adapted, never copied)

| # | Capability | Why useful | Reference approach | Proposed approach for my project | Files/services | Deps | Security considerations | Tests | Priority |
|---|---|---|---|---|---|---|---|---|---|
| T1 | Threshold-based sensor anomaly analyzer | genuinely works there; instant SIH value | pandas mean/max/min/std + temp>85°C, vib>6 mm/s, pressure 20–120 psi rules | New `sensor_analysis_service.py`: profile CSV → stats → rule engine (configurable thresholds in SystemSettings) → anomalies list + downsampled series for chart; expose `/data/sensor-analysis`; render chart in DataPage | new service + router + DataPage section | pandas (already pinned) | validate file like documents (magic bytes, size); org-scope datasets; audit event | unit tests w/ synthetic CSV; API test | **P1** |
| T2 | Industrial information architecture | judges expect these domains | 17-page taxonomy | Add honest pages backed by real pipelines: Sensor Analysis, Predictive Maintenance (real rules), Vision Inspection (Ollama multimodal) — each wired end-to-end before shipping | frontend pages + routers | none | every number from real compute; label estimates as estimates | E2E smoke per page | **P1** |
| T3 | Multimodal query payload shape (query + pdf + csv + image refs) | good UX concept for workbench | ChatMessagePayload(query, agent_name, image_path, csv_path, pdf_path, machine_code) | Extend agent-mode chat to accept attachments stored via existing validated upload; attach to run context; cite which artifact informed which step | chat router/service, ChatPage | none | same upload validation; size caps; ownership | integration test | P1 |
| T4 | Provider offline-fallback *idea* (never their impl) | resilience narrative | SovereignOfflineEngine import crash | Implement a REAL explicit degraded mode: when LLM unreachable → SSE error event + retry hint; retrieval-only answers clearly labeled `RETRIEVAL_ONLY` | llm_client, rag_service | none | never fabricate content in fallback | unit test fallback paths | P2 |
| T5 | Use-case gallery page | great for SIH storytelling | static use-cases page | Static content page describing REAL workflows with links that deep-launch them (`/chat?...`, `/agents?goal=...`) | new frontend page | none | none | manual | P2 |
| T6 | Downsample-for-chart pattern (≤50 rows) | keeps payloads small | analyze_csv downsampling | reuse for my chart endpoints | sensor service | none | none | unit | P2 |

## 3. What NOT To Take (defect register)

| # | Defect in reference | Safer alternative |
|---|---|---|
| N1 | Register-with-existing-email issues token without password (account takeover) | keep my unique-constraint registration; 409 on duplicates |
| N2 | Role self-selection at registration | keep first-admin + admin-managed roles |
| N3 | Demo auto-create-on-failed-login | never create accounts during login |
| N4 | Unauthenticated /demo/seed returning ADMIN password | seed scripts CLI-side only, never HTTP |
| N5 | CORS `*` + credentials | keep origin-allowlist CORS |
| N6 | Anonymous /files static mount | authenticated download endpoint w/ ownership checks |
| N7 | Hardcoded JWT secret in repo/env.example | env-only secret + startup fail-fast on default in prod mode |
| N8 | Client-trusted roles / localStorage identity | keep server-verified roles; memory-token doctrine |
| N9 | Template "AI answers" presented as model output | honest errors; retrieval-only labeling |
| N10 | Theatrical SSE (sleep-replay) | true token streaming only |
| N11 | Fabricated telemetry (GPU %, security score, blocked connections) | only measured values; "—" when unknown |
| N12 | OCR fallback inventing text | return explicit `[OCR_UNAVAILABLE]`, skip indexing |
| N13 | Raw filename joins (path traversal) | uuid+sanitize (already mine) |
| N14 | Ignored RBAC return values | dependency-injected role gates that raise |
| N15 | World-readable audit logs | keep admin-only + hash chain |
| N16 | Dead tables/services/duplicate pipelines | delete dead code; single pipeline per concern |
| N17 | "LangGraph" naming without library | name things what they are |
| N18 | External CDN assets in air-gapped app | self-hosted assets only |

## 4. Priority Buckets (consolidated)

**P0 (blocking/core security)** — M1 background-session fix · M2/M6-adjacent document & KB ownership
enforcement · M4 Alembic baseline · M5 docker.sock isolation plan · secret-key fail-fast ·
rate limiting on auth.
**P1** — T1 sensor analyzer · T2/T3 industrial UX + multimodal attachments · embeddings
version stamping + dim-drift guard · chat stop-button + markdown rendering + citation chips ·
streaming RAG answers · approval polling refactor · provider adapter bugfixes · security test
suite · dashboard trends · OCR optional profile · settings-wiring completion.
**P2** — investigation agent · digital-factory-lite (data-driven) · governance page ·
metrics endpoint · eval harness · i18n · focus-trapped modals · shared UI kit.
