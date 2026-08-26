# 03 System Architecture
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0

---

## 1. Architecture Overview

### 1.1 Architecture Style

Sovereign AI Workbench uses a **Modular Monolith** backend architecture deployed via Docker Compose.

**Rationale:**
- Microservice overhead (service discovery, distributed tracing, network latency between services) is unnecessary for an SIH prototype targeting single-node deployment with <= 10 concurrent users.
- A modular monolith retains clean internal boundaries, making it possible to extract services later without significant refactoring.
- Single FastAPI process keeps deployment simple (one container to manage, one log stream, no inter-service authentication complexity).

**Future path:** Services with independent scaling needs (e.g., document processing, agent execution) can be extracted into separate containers using an async message queue (Redis/RabbitMQ) without changing internal service interfaces.

### 1.2 Core Architectural Principles

| Principle | How it is applied |
|-----------|------------------|
| Privacy-first | No data leaves the local Docker network; all AI processing on-premise |
| Least privilege | Tool permissions, RBAC, and sandbox capabilities are minimal by default |
| Separation of concerns | AI reasoning (LLM) is strictly separated from tool execution (sandbox) |
| Fail-safe defaults | Unknown risk level → treated as High; missing approval → block execution |
| Auditability | Every state change and AI action produces an immutable audit record |
| Hardware awareness | CPU-first design; GPU accelerates but is never assumed |
| Graceful degradation | Each AI service (Ollama, Qdrant, OCR) can be disabled without taking down the API |

---

## 2. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Organization Network Boundary                    │
│                                                                          │
│   ┌──────────────┐         ┌─────────────────────────────────────────┐  │
│   │   Browser    │  HTTPS  │        Sovereign AI Workbench           │  │
│   │  (User/Admin)│────────▶│         (Docker Compose Stack)          │  │
│   └──────────────┘         └─────────────────────────────────────────┘  │
│                                                                          │
│                 All processing stays within this boundary                │
└─────────────────────────────────────────────────────────────────────────┘

External Internet: Accessed only once (initial Ollama model pull).
After that: fully air-gap capable.
```

---

## 3. Container Architecture Diagram

```
Docker Compose Stack
───────────────────────────────────────────────────────────────────
                                                                    
 ┌─────────────────────────────────────────────────────────────┐   
 │                     sovereign_network (bridge)              │   
 │                                                             │   
 │  ┌───────────────────┐    ┌──────────────────────────────┐  │   
 │  │    frontend        │    │         backend              │  │   
 │  │  (nginx:alpine)    │    │      (python:3.11-slim)      │  │   
 │  │   Port: 80         │───▶│       Port: 8000             │  │   
 │  │                    │    │                              │  │   
 │  │  React SPA         │    │  FastAPI Application         │  │   
 │  │  Static Assets     │    │  Service Layer               │  │   
 │  │                    │    │  ORM (SQLAlchemy)            │  │   
 │  └───────────────────┘    │  Docker SDK Client           │  │   
 │                            └─────────────┬────────────────┘  │   
 │                                          │                    │   
 │                          ┌───────────────┼──────────────┐    │   
 │                          │               │              │    │   
 │                   ┌──────▼───────┐  ┌────▼──────────┐  │    │   
 │                   │   qdrant     │  │ sqlite volume │  │    │   
 │                   │ (qdrant:1.9) │  │ (file on vol) │  │    │   
 │                   │ Port: 6333   │  └───────────────┘  │    │   
 │                   │ Volume:      │                      │    │   
 │                   │ qdrant_data  │  ┌───────────────┐  │    │   
 │                   └──────────────┘  │  uploads vol  │  │    │   
 │                                     └───────────────┘  │    │   
 └─────────────────────────────────────────────────────────────┘   
                                                                    
 Host (outside Docker network)                                     
 ┌──────────────────────┐   ┌────────────────────────────────┐   
 │       Ollama         │   │   Docker Engine (sandbox)      │   
 │  Port: 11434         │   │   Ephemeral sandbox containers │   
 │  GPU/CPU inference   │   │   (created + destroyed per run)│   
 └──────────────────────┘   └────────────────────────────────┘   

 Note: Backend mounts /var/run/docker.sock to manage sandbox containers.
```

---

## 4. Backend Internal Architecture

### 4.1 Layer Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                        HTTP Layer                               │
│   FastAPI Router  │  Middleware (Auth, CORS, RateLimit, Logs)  │
└─────────────────────────────────┬──────────────────────────────┘
                                  │
┌─────────────────────────────────▼──────────────────────────────┐
│                      Routers (Route Handlers)                   │
│  /auth  /chat  /models  /documents  /knowledge-bases           │
│  /agents  /tools  /approvals  /audit  /system                  │
└─────────────────────────────────┬──────────────────────────────┘
                                  │  calls
┌─────────────────────────────────▼──────────────────────────────┐
│                        Service Layer                            │
│                                                                 │
│  AuthService      ChatService      ModelService                 │
│  DocumentService  OCRService       RAGService                   │
│  EmbeddingService AgentService     ToolService                  │
│  SandboxService   ApprovalService  AuditService                 │
│  SystemService                                                  │
└──────┬─────────────────┬────────────────────┬──────────────────┘
       │                 │                    │
┌──────▼──────┐   ┌──────▼──────┐   ┌────────▼───────┐
│  Data Layer │   │  AI Layer   │   │  Infra Layer   │
│             │   │             │   │                │
│ SQLAlchemy  │   │ LLMClient   │   │ Docker SDK     │
│ (SQLite)    │   │ (→ Ollama)  │   │ (Sandbox)      │
│             │   │             │   │                │
│ QdrantClient│   │ PaddleOCR   │   │ psutil         │
│ (→ Qdrant)  │   │ (in-process)│   │ (Metrics)      │
└─────────────┘   └─────────────┘   └────────────────┘
```

### 4.2 Middleware Stack (request order)

```
Request
  │
  ▼
1. CORS Middleware           → enforce FRONTEND_ORIGIN allowlist
  │
  ▼
2. Request ID Middleware     → inject X-Request-ID (UUID) for tracing
  │
  ▼
3. Rate Limit Middleware     → per-IP, per-user rate limits (in-memory sliding window)
  │
  ▼
4. Auth Middleware           → JWT verification for protected routes
  │
  ▼
5. Request Logging Middleware → structured log: method, path, user, duration
  │
  ▼
6. Route Handler
  │
  ▼
7. Exception Handler         → map exceptions to standardized error responses
  │
  ▼
Response
```

### 4.3 Dependency Injection Map

FastAPI's `Depends()` system provides:

| Dependency | Provides | Used by |
|------------|---------|---------|
| `get_db` | `AsyncSession` | All DB-touching services |
| `get_current_user` | `User` | All auth-required endpoints |
| `require_role("admin")` | `User` (verified admin) | Admin-only endpoints |
| `require_role("analyst")` | `User` (analyst or admin) | Write endpoints |
| `get_llm_client` | `LLMClient` | Chat, RAG, Agent services |
| `get_qdrant_client` | `QdrantClient` | RAG, Embedding services |
| `get_audit_service` | `AuditService` | All services |
| `get_sandbox_service` | `SandboxService` | Agent, Tool services |

---

## 5. Data Flow Architecture

### 5.1 Chat Flow

```
Browser
  │ POST /api/v1/chat/conversations/{id}/messages
  │ {"content": "Summarize Q3 report"}
  ▼
Auth Middleware (verify JWT)
  │
  ▼
ChatRouter.send_message()
  │
  ▼
ChatService.handle_message()
  │
  ├─── [Optional] RAGService.retrieve_context(kb_ids, query)
  │         │
  │         ├── embed_query → Ollama /api/embeddings
  │         ├── search → Qdrant collection
  │         └── return chunks + citations
  │
  ├─── build_prompt(messages, system_prompt, [context])
  │
  ├─── LLMClient.chat(model, messages, stream=True)
  │         │
  │         └── httpx.stream → Ollama /api/chat
  │
  ├─── AuditService.log(event=CHAT, action=message.sent)
  │
  └─── SSE stream → Browser (token by token)
```

### 5.2 Document Processing Flow

```
Browser
  │ POST /api/v1/documents/upload (multipart)
  ▼
DocumentRouter.upload()
  │
  ├── FileValidation (MIME, size, filename sanitize)
  ├── Save file to /app/data/uploads/{kb_id}/
  ├── Create Document record (status=pending)
  ├── AuditService.log(document.upload.received)
  └── BackgroundTasks.add_task(process_document, doc_id)
  │
  ▼ (async background)
DocumentService.process_document(doc_id)
  │
  ├── Update status → "processing"
  │
  ├── TextExtraction (by MIME type)
  │     PDF    → PyMuPDF
  │     DOCX   → python-docx
  │     TXT/MD → direct
  │     CSV    → pandas
  │     Image  → skip to OCR
  │
  ├── OCRService.run_ocr_if_needed()
  │     (if scanned PDF or image → PaddleOCR)
  │
  ├── TextCleaner.clean()
  │
  ├── Chunker.chunk(text, chunk_size=512, overlap=50)
  │
  ├── EmbeddingService.embed_batch(chunks)
  │     → Ollama /api/embeddings (batched)
  │
  ├── QdrantClient.upsert_points(collection, points)
  │
  ├── Update Document: status=indexed, chunk_count=N
  ├── Update KnowledgeBase: chunk_count += N, doc_count += 1
  │
  └── AuditService.log(document.indexed)
```

### 5.3 Agent Execution Flow

```
Browser
  │ POST /api/v1/agents/runs
  │ {"goal": "Analyze sales.csv and find top 3 products"}
  ▼
AgentRouter
  │
  ▼
AgentService.start_run()
  │
  ├── Create AgentRun record (status=pending)
  ├── AuditService.log(agent.run.start)
  └── create_task(execute_agent_run, run_id)
  │
  ▼ (async)
AgentService.execute_agent_run(run_id)
  │
  ├── [PLANNING] LLMClient.chat(goal→plan)
  │     Returns JSON: [{step, description, tool, input}, ...]
  │
  └── [EXECUTION LOOP: max N iterations]
        │
        ├── LLMClient.chat(current_state→next_action)
        │     Returns JSON: {tool_name, tool_input, reasoning}
        │
        ├── ToolRegistry.get_tool(tool_name)
        │     → validate permissions for current user/role
        │
        ├── PydanticValidation(tool.input_schema, tool_input)
        │
        ├── RiskAssessment(tool.risk_level)
        │     Low/Medium → direct
        │     High/Critical → ApprovalService.request_approval()
        │                      (block until approved/rejected/timeout)
        │
        ├── Execution
        │     sandboxed  → SandboxService.run(container_config, command)
        │     in-process → ToolService.execute(tool, input)
        │
        ├── Capture result → ToolCall record
        ├── AuditService.log(tool.executed)
        │
        └── LLMClient.chat(result→next_step_or_done)
              done → ResultSynthesis → AgentRun.status=completed
              continue → next iteration
```

---

## 6. Service Component Specifications

### 6.1 AuthService

**Responsibilities:** User registration, login, JWT issuance, token refresh/revocation, password management.

**Dependencies:** `users` table, `refresh_tokens` table, passlib, python-jose.

**Key invariants:**
- Passwords are never stored or logged in plaintext.
- JWT `sub` claim = `user_id` (UUID).
- Refresh token rotation: each use issues a new refresh token and invalidates the old one.
- Login failures are rate-limited (5 attempts / 15 min per IP).

### 6.2 ChatService

**Responsibilities:** Manage conversations and messages; stream LLM responses; optionally inject RAG context.

**Dependencies:** `conversations` table, `messages` table, `LLMClient`, `RAGService` (optional).

**Key invariants:**
- Context window management: if total token count exceeds `model.context_length * 0.8`, truncate oldest messages (keep system prompt always).
- Local processing indicator metadata added to every assistant message.
- SSE stream must be properly terminated on client disconnect.

### 6.3 DocumentService

**Responsibilities:** File upload validation, storage, orchestrate the processing pipeline, status tracking.

**Dependencies:** `documents` table, `OCRService`, `EmbeddingService`, `QdrantClient`, filesystem.

**Key invariants:**
- File stored before processing starts (processing failure does not lose the file).
- Processing is idempotent: re-processing a document clears old vectors before inserting new ones.
- Partial results preserved on failure: any successfully extracted/chunked data is retained.

### 6.4 OCRService

**Responsibilities:** Run PaddleOCR on images and scanned PDFs; return structured text with confidence.

**Dependencies:** PaddleOCR library, PyMuPDF (for PDF page rendering).

**Key invariants:**
- CPU mode only (`use_gpu=False`); never fails due to missing GPU.
- Confidence below threshold (0.7) flagged in output metadata.
- OCR results annotated with `[OCR:page_N]` markers for traceability.

### 6.5 RAGService

**Responsibilities:** Semantic search over knowledge base; context construction for LLM; retrieval logging.

**Dependencies:** `EmbeddingService`, `QdrantClient`, `LLMClient`.

**Key invariants:**
- Token budget respected: context window = `min(4096, model_context_length * 0.6)`.
- Source citations always included in response.
- Low confidence results (score < threshold) flagged in response.

### 6.6 AgentService

**Responsibilities:** Parse user goals into plans; manage the tool-call reasoning loop; enforce iteration limits.

**Dependencies:** `LLMClient`, `ToolRegistry`, `SandboxService`, `ApprovalService`, `AuditService`.

**Key invariants:**
- LLM is **never** trusted with direct system access; all actions go through `ToolRegistry`.
- Max iterations enforced hard (configurable, default 10); run terminated with partial result if exceeded.
- All tool inputs validated by Pydantic **before** execution.
- Agent cannot access tools not in its `allowed_tools` list.

### 6.7 ToolService / ToolRegistry

**Responsibilities:** Maintain the tool registry; validate permissions; execute non-sandboxed tools.

**Key invariants:**
- Each tool has: `name`, `description`, `input_schema`, `output_schema`, `risk_level`, `requires_sandbox`, `required_role`, `enabled` flag.
- `HTTPRequestTool` is **disabled by default**; requires explicit admin enablement.
- Tool descriptions are shown to the LLM; must be accurate (garbage descriptions = poor agent behavior).

**Built-in tool registry (MVP):**

| Tool | Risk | Sandbox | Default |
|------|------|---------|---------|
| `file_read` | Low | No | Enabled |
| `file_list` | Low | No | Enabled |
| `file_write` | Medium | No | Enabled |
| `file_delete` | High | No | Enabled (requires approval) |
| `search_kb` | Low | No | Enabled |
| `calculator` | Low | No | Enabled |
| `python_exec` | High | Yes | Enabled |
| `http_request` | Critical | Yes | **Disabled** |

### 6.8 SandboxService

**Responsibilities:** Create, manage, and clean up Docker containers for sandboxed execution.

**Dependencies:** Docker SDK for Python, Docker Engine (via socket mount).

**Key invariants:**
- Container is created fresh per execution (no container reuse).
- Container is auto-removed after execution, timeout, or failure.
- Backend validates that the Docker socket is accessible at startup; degrades gracefully if not.
- Sandbox execution result includes: `stdout`, `stderr`, `exit_code`, `duration_ms`, `timed_out`, `container_id`.

### 6.9 ApprovalService

**Responsibilities:** Create approval requests; notify waiting agent runs; record decisions.

**Dependencies:** `approval_requests` table, `AuditService`.

**Key invariants:**
- Agent run is blocked (async wait with timeout) until approval decision arrives.
- Expired approvals auto-reject after `expires_at`.
- Approved operations are not re-approved within the same agent run (idempotent approval).

### 6.10 AuditService

**Responsibilities:** Write immutable, hash-chained audit log entries.

**Dependencies:** `audit_logs` table.

**Key invariants:**
- Always append-only; no `UPDATE` or `DELETE` on `audit_logs`.
- Hash chain computed synchronously before insert to guarantee ordering.
- Never throws an exception to the caller (internal errors logged separately; audit failure is a warning, not a 500).
- Sensitive data (passwords, tokens, file contents) never included in audit metadata.

---

## 7. External Service Integration Architecture

### 7.1 Ollama Integration

```
Backend
  │
  ├── LLMClient (httpx.AsyncClient)
  │     base_url: http://host.docker.internal:11434  (or OLLAMA_URL env var)
  │
  ├── POST /api/chat          → chat completion (streaming)
  ├── POST /api/embeddings    → embedding generation
  ├── GET  /api/tags          → list installed models
  ├── POST /api/pull          → pull new model (admin only)
  └── HEAD /                  → health check
```

**Error handling:**
- Connection refused → mark Ollama as "unavailable"; return 503 with degraded status
- Model not found → return 404 with suggestion to pull model
- Timeout → configurable per-request timeout (default: 120s for generation, 30s for embeddings)

### 7.2 Qdrant Integration

```
Backend
  │
  └── QdrantClient (qdrant-client Python SDK)
        url: http://qdrant:6333  (or QDRANT_URL env var)
        
  Operations:
  ├── create_collection(name, vector_params)
  ├── upsert(collection, points: list[PointStruct])
  ├── search(collection, query_vector, limit, score_threshold)
  ├── delete_collection(name)
  └── get_collection_info(name)
```

**Error handling:**
- Collection not found → treat as empty; suggest re-indexing
- Connection refused → mark Qdrant as "unavailable"; RAG and KB features degrade gracefully

### 7.3 Docker SDK Integration

```
Backend
  │
  └── docker.from_env()  (reads /var/run/docker.sock)
  
  Operations:
  ├── containers.run(image, command, **config)
  ├── container.wait(timeout)
  ├── container.logs()
  └── container.remove(force=True)
```

**Security:**
- Docker socket access is a privileged operation; sandbox service is the only code that uses it
- Sandbox containers cannot access the Docker socket themselves
- All container parameters are set programmatically; no user input reaches Docker API directly

---

## 8. Security Architecture

### 8.1 Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│  TRUSTED ZONE                                                    │
│                                                                  │
│  ┌──────────────────────────────────────────────┐               │
│  │  Backend (FastAPI)                            │               │
│  │  ├── Authenticated user session              │               │
│  │  ├── Service layer (controlled execution)    │               │
│  │  └── Audit service (always runs)             │               │
│  └──────────────────────────────────────────────┘               │
│                                                                  │
│  ┌────────────────┐   ┌────────────┐   ┌─────────────────────┐  │
│  │  SQLite DB     │   │  Qdrant    │   │  File Storage       │  │
│  │  (local vol)   │   │ (local)    │   │  (local vol)        │  │
│  └────────────────┘   └────────────┘   └─────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  SEMI-TRUSTED ZONE                                               │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Ollama (host process)                                     │  │
│  │  Input: controlled prompts only                           │  │
│  │  Output: text responses (must not be blindly executed)    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Browser (Frontend)                                        │  │
│  │  Input: user actions (validated server-side)              │  │
│  │  Output: rendered UI (XSS protections applied)            │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  UNTRUSTED ZONE                                                  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  LLM Output / Agent Reasoning                              │  │
│  │  → Never directly executed                                │  │
│  │  → Must be parsed + validated + approved before action    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Sandbox Containers                                        │  │
│  │  → No network, no host filesystem, minimal capabilities   │  │
│  │  → All output treated as untrusted until validated         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Uploaded Documents                                        │  │
│  │  → Validated before processing                            │  │
│  │  → Malicious content contained within processing pipeline │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Defense in Depth

| Threat | Control Layer 1 | Control Layer 2 | Control Layer 3 |
|--------|----------------|----------------|----------------|
| Unauthorized access | JWT authentication | RBAC on every endpoint | Rate limiting on auth |
| Prompt injection | Input sanitization | Injection detection heuristic | Audit log + alert |
| Agent privilege escalation | Tool whitelist per run | Risk-based approval gates | Audit all tool calls |
| Malicious file upload | MIME + size validation | Isolated processing pipeline | No execution of uploaded code |
| Sandbox escape | Non-root container | `cap_drop=ALL` | `network=none` + seccomp |
| Data exfiltration | No network in sandbox | HTTP tool disabled by default | Audit all outputs |
| SQL injection | SQLAlchemy ORM | No raw SQL | Input validation |
| XSS | React (JSX escaping) | Content-Security-Policy header | No `dangerouslySetInnerHTML` |
| CSRF | SameSite cookies | Bearer token auth | CORS restrict |
| Brute force | Account lockout | Per-IP rate limit | Failed login audit |

---

## 9. Scalability Architecture

### 9.1 Current Architecture (MVP, Single Node)

```
Single Host
  ├── Docker Compose (1 instance each)
  ├── Ollama (1 instance, host)
  ├── SQLite (1 file, 1 writer)
  └── Qdrant (1 node, embedded)
```

**Limits:** ~10 concurrent users; ~10k docs per KB; ~1M vectors.

### 9.2 Upgrade Path (Future, No Code Changes Required)

**Step 1 — PostgreSQL:**
- Change `DATABASE_URL` environment variable to PostgreSQL connection string.
- Run `alembic upgrade head`.
- No application code changes (SQLAlchemy abstraction).

**Step 2 — Redis Job Queue:**
- Extract `BackgroundTasks` into Celery workers.
- Add Redis container to Docker Compose.
- Improves reliability: jobs survive API restarts.

**Step 3 — Horizontal API Scaling:**
- Backend is stateless (JWT, no in-memory session).
- Add a load balancer (nginx, Traefik) in front of multiple backend replicas.
- SQLite must be replaced with PostgreSQL before this step.

**Step 4 — Kubernetes:**
- Backend: Deployment (stateless pods).
- Qdrant: StatefulSet with persistent volume.
- Ollama: DaemonSet or dedicated node with GPU.

---

## 10. Resilience and Error Handling Architecture

### 10.1 Service Startup Order

```
Docker Compose depends_on + healthcheck:

qdrant (healthcheck: /healthz)
    ↑
backend (depends_on: qdrant; healthcheck: /api/v1/system/health)
    ↑
frontend (depends_on: backend; static serve; no healthcheck needed)

Ollama: started on host manually before compose up
```

### 10.2 Graceful Degradation Table

| Service Unavailable | Impact | Degraded Behavior |
|--------------------|--------|------------------|
| Ollama | Chat, RAG generation, Agent reasoning | Return 503 with "LLM unavailable"; dashboard shows warning |
| Qdrant | RAG search, KB query, embedding storage | Return 503 for RAG/KB; chat still works without context |
| PaddleOCR | OCR on scanned docs/images | Document status = "indexed_without_ocr"; text-based extraction still works |
| Docker (sandbox) | Sandboxed tool execution | Agent runs fail at sandboxed steps; non-sandboxed tools still work |
| SQLite | All DB operations | Full API unavailable; 503 with error |

### 10.3 Retry Policy

| Operation | Retry | Backoff |
|-----------|-------|---------|
| Ollama API call (non-streaming) | 3 attempts | Exponential: 1s, 2s, 4s |
| Qdrant API call | 3 attempts | Exponential: 0.5s, 1s, 2s |
| Embedding generation | 2 attempts | Linear: 2s |
| No retry: streaming chat | — | Fail-fast; resume is user action |
| No retry: tool execution | — | Log and report failure |

---

## 11. Storage Architecture

### 11.1 Volume Architecture

```
Docker Volumes:
├── backend_data/
│   ├── sqlite/
│   │   └── sovereign.db       (SQLite WAL mode)
│   ├── uploads/
│   │   └── {kb_id}/
│   │       └── {doc_id}_{filename}
│   └── sandbox_workspace/     (temp; auto-cleaned)
│
└── qdrant_data/
    └── (Qdrant internal storage format)
```

### 11.2 Data Lifecycle

| Data Type | Created | Updated | Deleted | Retention |
|-----------|---------|---------|---------|-----------|
| User accounts | Registration | Profile update | Admin action | Indefinite |
| Conversations + messages | Chat start | Never | User action | Indefinite |
| Documents | Upload | Processing pipeline | User/admin | Per KB lifecycle |
| Knowledge base vectors | Indexing | Re-index | KB delete | Per KB lifecycle |
| Agent run traces | Run start | Each step | Never | Configurable (default: indefinite) |
| Audit logs | Every action | Never | Never | 365 days default; configurable |
| Sandbox workspaces | Run start | — | Run end (auto) | Per execution |

---

## 12. Configuration Architecture

### 12.1 Configuration Hierarchy

```
Environment Variables (highest priority)
    ↓
.env file (Docker Compose)
    ↓
Application defaults (config.py BaseSettings)
    ↓
Database-stored settings (future: admin-configurable via UI)
```

### 12.2 Runtime Configuration (config.py)

```python
class Settings(BaseSettings):
    # Core
    secret_key: str                    # required
    database_url: str = "sqlite+aiosqlite:////app/data/sqlite/sovereign.db"
    qdrant_url: str = "http://qdrant:6333"
    ollama_url: str = "http://host.docker.internal:11434"
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"

    # Auth
    jwt_access_ttl_min: int = 60
    jwt_refresh_ttl_days: int = 7

    # Uploads
    max_upload_size_mb: int = 50

    # RAG
    default_embedding_model: str = "nomic-embed-text"
    default_chunk_size: int = 512
    default_chunk_overlap: int = 50
    default_top_k: int = 5
    default_score_threshold: float = 0.6

    # Agent
    default_max_iterations: int = 10
    default_approval_level: str = "high"  # risk level that triggers approval

    # Sandbox
    sandbox_image: str = "python:3.11-slim"
    sandbox_timeout_s: int = 30
    sandbox_mem_limit_mb: int = 256
    sandbox_cpu_quota: int = 50000  # 50% of one CPU

    # Audit
    audit_retention_days: int = 365

    class Config:
        env_file = ".env"
```

---

## 13. Frontend Architecture

### 13.1 SPA Architecture

```
React 18 SPA (Vite)
  │
  ├── React Router v6 (client-side routing)
  │     Routes:
  │     /                   → DashboardPage
  │     /chat               → ChatPage
  │     /chat/:id           → ChatPage (specific conversation)
  │     /models             → ModelsPage
  │     /documents          → DocumentsPage
  │     /knowledge-bases    → KnowledgeBasePage
  │     /knowledge-bases/:id → KnowledgeBaseDetailPage
  │     /agents             → AgentPage
  │     /agents/:id         → AgentRunDetailPage
  │     /approvals          → ApprovalsPage (admin)
  │     /audit              → AuditPage (admin)
  │     /settings           → SettingsPage (admin)
  │     /login              → LoginPage (public)
  │
  ├── Zustand stores
  │     AuthStore           → current user, JWT token
  │     SystemStore         → system status, model list (polled)
  │     UIStore             → sidebar state, dark mode
  │
  ├── React Query (TanStack Query)
  │     → server state management for API calls
  │     → automatic refetch, caching, optimistic updates
  │
  └── SSE Handling
        EventSource API → chat streaming, agent progress
```

### 13.2 API Client Layer

All API calls go through a centralized typed client:

```typescript
// api/client.ts
const apiClient = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const token = AuthStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      await AuthStore.getState().refreshToken();
      return apiClient(error.config);
    }
    return Promise.reject(error);
  }
);
```

---

## 14. Non-Functional Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Async vs sync backend | Async (asyncio) | I/O-bound: LLM calls, DB, file ops benefit from async; avoids thread exhaustion |
| Monolith vs microservices | Modular monolith | MVP complexity; easy extraction later; single-node deployment |
| SQLite vs PostgreSQL | SQLite (MVP) | Zero config; file-based; WAL provides adequate concurrency for 10 users |
| In-process OCR vs service | In-process | Avoid additional container; PaddleOCR is importable; simpler for CPU-only setup |
| Document chunking strategy | RecursiveCharacterTextSplitter | Respects semantic boundaries (paragraphs → sentences → chars) |
| Embedding in Qdrant vs separate | Qdrant payload only | Embeddings stored in Qdrant as vectors; text stored as payload; no dual storage |
| Real-time events | SSE (Server-Sent Events) | One-directional; simpler than WebSocket; sufficient for streaming chat and agent progress |
| Frontend state | Zustand + React Query | Zustand for UI/auth state; React Query for server state; no Redux overhead |
| Container image size | Slim/alpine variants | Reduces attack surface and startup time on modest hardware |

---

## 15. Architecture Constraints Summary

| Constraint | Source | Impact |
|------------|--------|--------|
| No cloud API calls | PRD §4 | LLM inference and embeddings must use Ollama exclusively |
| CPU-first hardware | PRD §9 | OCR in CPU mode; small/quantized models recommended |
| Single-node deployment | PRD §10 | Docker Compose; SQLite sufficient; no distributed coordination |
| SQLite for MVP | TRD §2.2 | Max ~10 concurrent writers; adequate for 10 users |
| Docker socket mount | TRD §3.1 | Required for sandbox; acknowledged security implication; mitigated by sandbox service isolation |
| Offline capable | PRD §8.2 | No runtime internet calls; model pull is one-time |

---

## 16. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial System Architecture document |

---

*End of System Architecture*
