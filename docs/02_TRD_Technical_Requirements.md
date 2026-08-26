# 02 Technical Requirements Document (TRD)
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0

---

## 1. Purpose & Scope

This document specifies the technical requirements, technology choices, component interfaces, data models, API contracts, and infrastructure constraints for the Sovereign AI Workbench MVP. It is the primary reference for backend engineers, AI/ML engineers, DevOps engineers, and security engineers.

The TRD does not duplicate the PRD. It derives concrete technical specifications from the functional and non-functional requirements stated in the PRD and adds implementation-level detail.

---

## 2. Technology Stack (Rationale + Constraints)

### 2.1 Approved Technology Stack

| Layer | Technology | Version (minimum) | Justification |
|-------|-----------|-------------------|---------------|
| **Frontend** | React | 18.x | Mature component model; SSE support; wide ecosystem |
| **Frontend build** | Vite | 5.x | Fast HMR; lightweight; no unnecessary complexity |
| **Frontend styles** | Tailwind CSS | 3.x | Utility-first; no external CSS dependency |
| **Backend runtime** | Python | 3.11+ | Strong AI/ML ecosystem; async support |
| **Backend framework** | FastAPI | 0.111+ | Async-native; OpenAPI auto-generation; Pydantic integration |
| **Schema validation** | Pydantic | 2.x | Strict typed validation; serialization |
| **Relational DB** | SQLite | 3.x (via SQLAlchemy 2.x) | Zero-config; file-based; WAL mode for concurrency |
| **ORM** | SQLAlchemy | 2.x | Async SQLite support; migration path to PostgreSQL |
| **Migrations** | Alembic | 1.x | Schema versioning |
| **LLM inference** | Ollama | Latest stable | CPU + GPU support; model management; REST API |
| **Vector DB** | Qdrant | 1.9+ | Local deployment; HNSW index; filtering |
| **OCR** | PaddleOCR | 2.x | Offline capable; multi-language; lightweight CPU mode |
| **PDF parsing** | PyMuPDF (fitz) | 1.24+ | Fast; handles complex PDFs; no external binary deps |
| **DOCX parsing** | python-docx | 1.x | Standard DOCX support |
| **HTTP client** | httpx | 0.27+ | Async HTTP; used for Ollama/Qdrant API calls |
| **Sandbox** | Docker SDK for Python | 7.x | Programmatic container control |
| **Auth tokens** | python-jose (JWT) | 3.x | JWT creation/validation |
| **Password hashing** | passlib (bcrypt) | 1.7+ | bcrypt with cost factor |
| **Task queue** | asyncio + background tasks | Built-in | Sufficient for MVP; no external broker needed |
| **Metrics** | psutil | 6.x | System resource monitoring |
| **Logging** | Python stdlib logging + structlog | Latest | Structured JSON logs |
| **Containerization** | Docker + Docker Compose | 24.x / 2.x | Single-node deployment |

### 2.2 Technology Constraints

- **No cloud APIs** for core functionality. No calls to OpenAI, Anthropic, Cohere, AWS Bedrock, GCP Vertex, Azure OpenAI, or similar from production paths.
- **No telemetry by default.** Libraries that phone home (analytics, crash reporters) must be disabled or not included.
- **Ollama must run locally** — either on the host (recommended for GPU access) or in a container. The backend connects via `http://ollama:11434` (Docker network alias) or `http://host.docker.internal:11434`.
- **Qdrant runs as a Docker service** with a named volume for persistence.
- **SQLite database** file stored on a Docker volume; WAL mode enabled at startup.
- **No Redis, Celery, or message brokers** in MVP — background tasks run via FastAPI's `BackgroundTasks` or `asyncio.create_task`.
- **PostgreSQL migration** is architecturally planned: SQLAlchemy async with a connection string environment variable. Swap requires only `DATABASE_URL` change and a migration run.

### 2.3 Dependency Management

- Python dependencies locked in `requirements.txt` with pinned versions (e.g., `fastapi==0.111.0`).
- Node dependencies locked in `package-lock.json`.
- Docker images use explicit tags — no `:latest` in `docker-compose.yml`.
- Security-sensitive packages (auth, crypto) must be reviewed before version bumps.

---

## 3. System Architecture Specification

### 3.1 Deployment Topology

```
┌──────────────────────────────────────────────────────────────────┐
│                         Host Machine                             │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   Frontend   │  │   Backend    │  │       Ollama         │  │
│  │  (Vite/React)│  │  (FastAPI)   │  │  (host or container) │  │
│  │  Port: 5173  │  │  Port: 8000  │  │  Port: 11434         │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────┘  │
│         │HTTP              │HTTP/WS                              │
│         └────────┬─────────┘                                    │
│                  │                                               │
│  ┌───────────────┴──────────────────┐                           │
│  │        Docker Compose Network    │                           │
│  │                                  │                           │
│  │  ┌────────────┐ ┌─────────────┐ │                           │
│  │  │   Qdrant   │ │  Sandbox    │ │                           │
│  │  │ Port: 6333 │ │  Containers │ │                           │
│  │  │ (volume)   │ │  (ephemeral)│ │                           │
│  │  └────────────┘ └─────────────┘ │                           │
│  │                                  │                           │
│  │  ┌────────────────────────────┐  │                           │
│  │  │     SQLite (volume)        │  │                           │
│  │  └────────────────────────────┘  │                           │
│  └──────────────────────────────────┘                           │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Backend Module Structure

The backend is a **modular monolith** — one FastAPI process, logically divided into cohesive modules. This avoids microservice complexity while keeping modules loosely coupled for future extraction.

```
backend/
├── main.py                    # FastAPI app factory; lifespan; router registration
├── config.py                  # Settings (Pydantic BaseSettings, env-driven)
├── database.py                # SQLAlchemy async engine, session factory
├── dependencies.py            # FastAPI dependency injection helpers
│
├── models/                    # SQLAlchemy ORM models (database schema)
│   ├── user.py
│   ├── conversation.py
│   ├── message.py
│   ├── document.py
│   ├── knowledge_base.py
│   ├── agent_run.py
│   ├── tool_call.py
│   ├── approval_request.py
│   └── audit_log.py
│
├── schemas/                   # Pydantic request/response schemas
│   ├── auth.py
│   ├── chat.py
│   ├── model.py
│   ├── document.py
│   ├── knowledge_base.py
│   ├── agent.py
│   ├── tool.py
│   ├── approval.py
│   └── audit.py
│
├── routers/                   # FastAPI route handlers
│   ├── auth.py
│   ├── chat.py
│   ├── models.py
│   ├── documents.py
│   ├── knowledge_bases.py
│   ├── agents.py
│   ├── tools.py
│   ├── approvals.py
│   ├── audit.py
│   └── system.py
│
├── services/                  # Business logic
│   ├── auth_service.py
│   ├── chat_service.py
│   ├── model_service.py
│   ├── document_service.py
│   ├── ocr_service.py
│   ├── rag_service.py
│   ├── embedding_service.py
│   ├── agent_service.py
│   ├── tool_service.py
│   ├── sandbox_service.py
│   ├── approval_service.py
│   ├── audit_service.py
│   └── system_service.py
│
├── tools/                     # Built-in tool implementations
│   ├── registry.py            # Tool registration and lookup
│   ├── file_read.py
│   ├── file_write.py
│   ├── file_list.py
│   ├── search_kb.py
│   ├── calculator.py
│   ├── python_exec.py
│   └── http_request.py        # Disabled by default; must be explicitly enabled
│
└── utils/
    ├── security.py            # Input sanitization, prompt injection detection
    ├── chunker.py             # Document chunking logic
    ├── hash_chain.py          # Audit log hash chaining
    └── resource_monitor.py   # psutil wrappers
```

### 3.3 Frontend Module Structure

```
frontend/
├── index.html
├── vite.config.ts
├── tailwind.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/                   # Typed API client wrappers
│   │   ├── client.ts          # axios/fetch base client with auth header injection
│   │   ├── auth.ts
│   │   ├── chat.ts
│   │   ├── models.ts
│   │   ├── documents.ts
│   │   ├── knowledge_bases.ts
│   │   ├── agents.ts
│   │   └── audit.ts
│   ├── components/            # Reusable UI components
│   │   ├── layout/
│   │   ├── chat/
│   │   ├── documents/
│   │   ├── knowledge/
│   │   ├── agent/
│   │   ├── approval/
│   │   ├── audit/
│   │   └── system/
│   ├── pages/                 # Route-level page components
│   │   ├── DashboardPage.tsx
│   │   ├── ChatPage.tsx
│   │   ├── ModelsPage.tsx
│   │   ├── DocumentsPage.tsx
│   │   ├── KnowledgeBasePage.tsx
│   │   ├── AgentPage.tsx
│   │   ├── AuditPage.tsx
│   │   └── SettingsPage.tsx
│   ├── stores/                # State management (Zustand or React Context)
│   ├── hooks/                 # Custom React hooks
│   └── types/                 # TypeScript type definitions
```

---

## 4. Database Schema

### 4.1 SQLite Schema (SQLAlchemy ORM)

All tables include `created_at` and `updated_at` timestamps. All IDs are UUIDs (stored as TEXT in SQLite).

#### 4.1.1 `users`
```sql
CREATE TABLE users (
    id          TEXT PRIMARY KEY,          -- UUID v4
    email       TEXT NOT NULL UNIQUE,
    username    TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,           -- bcrypt
    role        TEXT NOT NULL DEFAULT 'viewer',  -- admin | analyst | viewer
    is_active   INTEGER NOT NULL DEFAULT 1,
    last_login  DATETIME,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.2 `conversations`
```sql
CREATE TABLE conversations (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id),
    title         TEXT,
    model_name    TEXT NOT NULL,
    system_prompt TEXT,
    context_mode  TEXT NOT NULL DEFAULT 'truncate',  -- truncate | summarize
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.3 `messages`
```sql
CREATE TABLE messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,   -- user | assistant | system | tool
    content          TEXT NOT NULL,
    token_count      INTEGER,
    finish_reason    TEXT,            -- stop | length | tool_calls
    metadata         TEXT,           -- JSON: tool_calls, citations, etc.
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.4 `knowledge_bases`
```sql
CREATE TABLE knowledge_bases (
    id               TEXT PRIMARY KEY,
    owner_id         TEXT NOT NULL REFERENCES users(id),
    name             TEXT NOT NULL,
    description      TEXT,
    embedding_model  TEXT NOT NULL,   -- Ollama model name used for embeddings
    qdrant_collection TEXT NOT NULL UNIQUE,
    doc_count        INTEGER NOT NULL DEFAULT 0,
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.5 `documents`
```sql
CREATE TABLE documents (
    id            TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    uploader_id   TEXT NOT NULL REFERENCES users(id),
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    storage_path  TEXT NOT NULL,   -- absolute path inside container
    status        TEXT NOT NULL DEFAULT 'pending',
                                   -- pending | processing | indexed | failed
    error_message TEXT,
    page_count    INTEGER,
    metadata      TEXT,            -- JSON: title, author, creation_date
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.6 `agent_runs`
```sql
CREATE TABLE agent_runs (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id),
    goal         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
                                -- pending | running | completed | failed | awaiting_approval
    plan         TEXT,          -- JSON: structured task plan
    result       TEXT,          -- final synthesized result
    step_count   INTEGER NOT NULL DEFAULT 0,
    iteration_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.7 `tool_calls`
```sql
CREATE TABLE tool_calls (
    id            TEXT PRIMARY KEY,
    agent_run_id  TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_number   INTEGER NOT NULL,
    tool_name     TEXT NOT NULL,
    input_data    TEXT NOT NULL,   -- JSON
    output_data   TEXT,            -- JSON
    status        TEXT NOT NULL,   -- success | failed | timeout | rejected
    exit_code     INTEGER,
    duration_ms   INTEGER,
    sandbox_used  INTEGER NOT NULL DEFAULT 0,  -- boolean
    container_id  TEXT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.8 `approval_requests`
```sql
CREATE TABLE approval_requests (
    id              TEXT PRIMARY KEY,
    agent_run_id    TEXT REFERENCES agent_runs(id),
    tool_call_id    TEXT REFERENCES tool_calls(id),
    requester_id    TEXT NOT NULL REFERENCES users(id),
    operation       TEXT NOT NULL,   -- human-readable description
    operation_detail TEXT NOT NULL,  -- JSON: full operation spec
    risk_level      TEXT NOT NULL,   -- low | medium | high | critical
    status          TEXT NOT NULL DEFAULT 'pending',
                                     -- pending | approved | rejected | expired
    decided_by      TEXT REFERENCES users(id),
    decided_at      DATETIME,
    decision_note   TEXT,
    expires_at      DATETIME NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.9 `audit_logs`
```sql
CREATE TABLE audit_logs (
    id            TEXT PRIMARY KEY,
    sequence_num  INTEGER NOT NULL UNIQUE,  -- monotonically increasing
    timestamp     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id       TEXT REFERENCES users(id),
    session_id    TEXT,
    event_type    TEXT NOT NULL,
                  -- auth | model | document | rag | agent | tool | sandbox
                  -- approval | config | error | security
    action        TEXT NOT NULL,   -- e.g. "user.login", "agent.run.start"
    resource_type TEXT,
    resource_id   TEXT,
    outcome       TEXT NOT NULL,   -- success | failure | pending
    ip_address    TEXT,
    user_agent    TEXT,
    metadata      TEXT,            -- JSON: event-specific detail
    prev_hash     TEXT NOT NULL,   -- SHA-256 of previous entry
    entry_hash    TEXT NOT NULL    -- SHA-256 of this entry's content
);
```

### 4.2 Qdrant Schema

Each knowledge base maps to one Qdrant collection.

**Collection naming:** `kb_{knowledge_base_id}` (sanitized UUID)

**Vector configuration:**
```json
{
  "vectors": {
    "size": 768,
    "distance": "Cosine"
  }
}
```
Note: Vector size must match the embedding model. `nomic-embed-text` (recommended default) produces 768-dim vectors. This is configurable per knowledge base and stored in `knowledge_bases.embedding_model`.

**Point payload schema:**
```json
{
  "doc_id": "uuid-string",
  "kb_id": "uuid-string",
  "chunk_index": 0,
  "content": "text content of this chunk",
  "token_count": 128,
  "page_number": 1,
  "section": "optional section heading",
  "filename": "original_file.pdf",
  "created_at": "ISO-8601 timestamp"
}
```

### 4.3 File Storage

Documents are stored on a Docker volume mounted at `/app/data/uploads/` inside the backend container.

Directory structure:
```
/app/data/
├── uploads/
│   └── {kb_id}/
│       └── {doc_id}_{original_filename}
├── sqlite/
│   └── sovereign.db
└── sandbox_workspace/         # Temporary; cleaned after each run
```

---

## 5. API Specification

All endpoints are prefixed with `/api/v1`. All responses use JSON. Streaming endpoints use Server-Sent Events (SSE) with `text/event-stream` content type.

### 5.1 Authentication

**Base:** `/api/v1/auth`

| Method | Path | Auth | Request Body | Response | Description |
|--------|------|------|-------------|----------|-------------|
| POST | `/register` | None | `RegisterRequest` | `UserResponse` | Register new user |
| POST | `/login` | None | `LoginRequest` | `TokenResponse` | Login; returns JWT |
| POST | `/refresh` | Bearer | `RefreshRequest` | `TokenResponse` | Refresh access token |
| POST | `/logout` | Bearer | — | `MessageResponse` | Invalidate refresh token |
| GET | `/me` | Bearer | — | `UserResponse` | Current user info |

**Schema: `RegisterRequest`**
```json
{
  "email": "string (email)",
  "username": "string (3-50 chars, alphanumeric+underscore)",
  "password": "string (min 12 chars)"
}
```

**Schema: `TokenResponse`**
```json
{
  "access_token": "string (JWT)",
  "refresh_token": "string (JWT)",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### 5.2 Models

**Base:** `/api/v1/models`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | Bearer | List all Ollama models |
| GET | `/{model_name}` | Bearer | Get model detail/metadata |
| POST | `/pull` | Admin | Pull a new model from Ollama registry |
| GET | `/pull/{model_name}/status` | Admin | Stream pull progress (SSE) |
| PUT | `/roles` | Admin | Assign model roles |
| GET | `/health/{model_name}` | Bearer | Test model availability |

**Schema: `ModelInfo`**
```json
{
  "name": "string",
  "display_name": "string",
  "family": "string",
  "parameter_size": "string",
  "quantization": "string",
  "size_bytes": 0,
  "context_length": 0,
  "roles": ["chat", "embedding", "vision"],
  "status": "available | loading | unavailable",
  "modified_at": "ISO-8601"
}
```

### 5.3 Chat

**Base:** `/api/v1/chat`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/conversations` | Bearer | List user's conversations |
| POST | `/conversations` | Bearer | Create conversation |
| GET | `/conversations/{id}` | Bearer | Get conversation with messages |
| DELETE | `/conversations/{id}` | Bearer | Delete conversation |
| POST | `/conversations/{id}/messages` | Bearer | Send message; returns SSE stream |
| GET | `/conversations/{id}/export` | Bearer | Export as JSON/Markdown |

**Schema: `ChatMessageRequest`**
```json
{
  "content": "string",
  "model_name": "string (optional, overrides conversation default)",
  "rag_kb_ids": ["uuid (optional list of KB IDs to augment)"]
}
```

**SSE Stream events:**
```
event: token
data: {"delta": "text fragment"}

event: done
data: {"finish_reason": "stop", "token_count": 256, "duration_ms": 1200}

event: error
data: {"code": "model_unavailable", "message": "..."}
```

### 5.4 Documents

**Base:** `/api/v1/documents`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/upload` | Analyst+ | Upload document; returns doc ID and job ID |
| GET | `/{id}` | Bearer | Get document metadata and status |
| GET | `/{id}/status` | Bearer | Poll processing status |
| DELETE | `/{id}` | Analyst+ | Delete document and its chunks |
| GET | `/` | Bearer | List documents (with KB filter) |

**Upload:** `multipart/form-data` with fields: `file` (binary), `kb_id` (UUID), `run_ocr` (bool, default true).

**Schema: `DocumentStatus`**
```json
{
  "id": "uuid",
  "filename": "string",
  "status": "pending | processing | indexed | failed",
  "page_count": 0,
  "chunk_count": 0,
  "error_message": "string | null",
  "processing_steps": [
    {"step": "extraction", "status": "done", "duration_ms": 200},
    {"step": "ocr", "status": "done", "duration_ms": 4500},
    {"step": "chunking", "status": "done", "duration_ms": 50},
    {"step": "embedding", "status": "running", "duration_ms": null}
  ]
}
```

### 5.5 Knowledge Bases

**Base:** `/api/v1/knowledge-bases`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/` | Analyst+ | Create knowledge base |
| GET | `/` | Bearer | List knowledge bases |
| GET | `/{id}` | Bearer | Get KB detail |
| DELETE | `/{id}` | Admin | Delete KB and all vectors |
| POST | `/{id}/query` | Bearer | Semantic query against KB |
| POST | `/{id}/reindex` | Admin | Re-embed all documents |

**Schema: `KBQueryRequest`**
```json
{
  "query": "string",
  "top_k": 5,
  "score_threshold": 0.6,
  "include_sources": true,
  "generate_answer": true,
  "model_name": "string (optional)"
}
```

**Schema: `KBQueryResponse`**
```json
{
  "answer": "string | null",
  "sources": [
    {
      "chunk_id": "uuid",
      "doc_id": "uuid",
      "filename": "string",
      "page_number": 1,
      "content": "string",
      "score": 0.87
    }
  ],
  "query_embedding_ms": 45,
  "retrieval_ms": 12,
  "generation_ms": 980
}
```

### 5.6 Agents

**Base:** `/api/v1/agents`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/runs` | Analyst+ | Start new agent run |
| GET | `/runs` | Bearer | List agent runs |
| GET | `/runs/{id}` | Bearer | Get run detail and trace |
| GET | `/runs/{id}/stream` | Bearer | SSE stream of run events |
| POST | `/runs/{id}/cancel` | Bearer | Cancel in-progress run |

**Schema: `AgentRunRequest`**
```json
{
  "goal": "string",
  "model_name": "string (optional)",
  "allowed_tools": ["string (optional whitelist)"],
  "kb_ids": ["uuid (optional KBs agent can search)"],
  "max_iterations": 10,
  "require_approval_level": "high"
}
```

**Agent SSE events:**
```
event: plan
data: {"steps": [...]}

event: tool_call
data: {"step": 1, "tool": "search_kb", "input": {...}}

event: tool_result
data: {"step": 1, "output": {...}, "duration_ms": 120}

event: approval_required
data: {"approval_id": "uuid", "operation": "...", "risk": "high"}

event: reasoning
data: {"thought": "string", "iteration": 2}

event: complete
data: {"result": "string", "iterations": 3, "duration_ms": 5400}

event: error
data: {"code": "max_iterations", "message": "..."}
```

### 5.7 Approvals

**Base:** `/api/v1/approvals`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/pending` | Admin | List pending approval requests |
| GET | `/{id}` | Admin | Get approval request detail |
| POST | `/{id}/approve` | Admin | Approve with optional note |
| POST | `/{id}/reject` | Admin | Reject with required note |

### 5.8 Audit

**Base:** `/api/v1/audit`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/logs` | Admin | Query audit log (filters: event_type, user_id, date range, outcome) |
| GET | `/logs/{id}` | Admin | Get single log entry |
| GET | `/export` | Admin | Export filtered logs as CSV or JSON |
| GET | `/verify` | Admin | Verify hash chain integrity |

### 5.9 System

**Base:** `/api/v1/system`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check (for Docker healthcheck) |
| GET | `/status` | Bearer | System status (services, resources) |
| GET | `/resources` | Bearer | CPU, RAM, disk metrics |

**Schema: `SystemStatus`**
```json
{
  "status": "healthy | degraded | unhealthy",
  "services": {
    "ollama": {"status": "up", "latency_ms": 12},
    "qdrant": {"status": "up", "latency_ms": 5},
    "database": {"status": "up"}
  },
  "resources": {
    "cpu_percent": 34.2,
    "ram_used_gb": 5.1,
    "ram_total_gb": 16.0,
    "disk_used_gb": 25.3,
    "disk_total_gb": 100.0,
    "gpu_available": false
  },
  "models_loaded": ["llama3.2:3b", "nomic-embed-text"]
}
```

---

## 6. Service Interface Contracts

### 6.1 Document Processing Pipeline

The document processing pipeline is asynchronous. Upload returns immediately; processing runs in a background task.

```
DocumentUpload
    │
    ▼
file_validation()        → check MIME, size, sanitize filename
    │
    ▼
text_extraction()        → dispatch by MIME type
    │   PDF  → PyMuPDF
    │   DOCX → python-docx
    │   TXT/MD → direct read
    │   CSV  → pandas
    │   Image → PaddleOCR
    │
    ▼
ocr_if_needed()          → if scanned PDF or image → PaddleOCR
    │
    ▼
text_cleaning()          → normalize whitespace, remove control chars
    │
    ▼
chunking()               → RecursiveCharacterTextSplitter
    │                       chunk_size: 512 tokens (configurable)
    │                       chunk_overlap: 50 tokens (configurable)
    │
    ▼
embedding_generation()   → batch via Ollama embeddings endpoint
    │                       POST http://ollama:11434/api/embeddings
    │
    ▼
vector_storage()         → upsert points to Qdrant collection
    │
    ▼
status_update()          → update document.status = "indexed"
    │
    ▼
audit_log()              → log document.indexed event
```

### 6.2 RAG Query Pipeline

```
UserQuery
    │
    ▼
query_embedding()        → embed query text via Ollama
    │
    ▼
vector_search()          → Qdrant search (top_k, score_threshold)
    │
    ▼
chunk_retrieval()        → fetch chunk content from Qdrant payload
    │
    ▼
context_construction()   → concatenate chunks; prepend citations;
    │                       respect model token budget
    │
    ▼
llm_generation()         → send [system prompt + context + query] to Ollama
    │
    ▼
response_formatting()    → attach source citations to response
    │
    ▼
audit_log()              → log rag.query event
```

### 6.3 Agent Execution Loop

```
AgentRun.start(goal)
    │
    ▼
goal_parsing()           → LLM: parse goal into structured plan (JSON)
    │
    ▼
[LOOP: max_iterations]
    │
    ▼
tool_selection()         → LLM: choose next tool from allowed registry
    │
    ▼
input_validation()       → Pydantic validate against tool input schema
    │
    ▼
risk_assessment()        → lookup tool.risk_classification
    │
    ├── Low/Medium → direct execution
    │
    └── High/Critical → approval_request()
                            │
                            ├── Approved → continue
                            └── Rejected/Expired → abort step
    │
    ▼
execution()
    │   sandboxed tools → sandbox_service.run()
    │   non-sandboxed   → tool_service.execute()
    │
    ▼
result_capture()         → stdout/stderr/return_code/output_data
    │
    ▼
reasoning_update()       → LLM: incorporate result, decide next step
    │
    ├── continue → next iteration
    └── done → result_synthesis()
                    │
                    ▼
              audit_log() → log all steps
```

### 6.4 Sandbox Service

The sandbox service wraps Docker SDK calls.

**Container configuration per tool:**
```python
SandboxConfig(
    image="python:3.11-slim",       # base image; pre-pulled
    cpu_period=100000,              # Docker CPU quota period
    cpu_quota=50000,                # 50% of one CPU
    mem_limit="256m",               # 256 MB RAM
    pids_limit=50,                  # max processes
    timeout_seconds=30,             # hard timeout
    network_mode="none",            # no network by default
    read_only=True,                 # read-only filesystem
    workspace_mount="/workspace",   # writable workspace dir
    command=["python", "-c", "..."] # command to run
)
```

**Security hardening:**
- `cap_drop=["ALL"]` — drop all Linux capabilities
- Run as non-root user (UID 1000)
- Seccomp profile: Docker default
- No Docker socket mounted
- Auto-remove on exit

### 6.5 Audit Service

Every service function that modifies state or performs a sensitive operation must call `audit_service.log()`.

```python
async def log(
    event_type: AuditEventType,
    action: str,             # e.g. "agent.run.start", "user.login"
    outcome: str,            # "success" | "failure" | "pending"
    user_id: str | None,
    resource_type: str | None,
    resource_id: str | None,
    metadata: dict | None,
    request: Request | None  # for IP/user-agent extraction
) -> AuditLog
```

Hash chain: each entry's `entry_hash = SHA256(sequence_num + timestamp + user_id + action + outcome + prev_hash)`.

---

## 7. AI/ML Component Requirements

### 7.1 LLM Interface

All LLM calls go through a single `LLMClient` abstraction:

```python
class LLMClient:
    async def chat(
        model: str,
        messages: list[Message],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> ChatResponse | AsyncGenerator[str, None]

    async def embed(
        model: str,
        text: str | list[str]
    ) -> list[float] | list[list[float]]

    async def list_models(self) -> list[ModelInfo]

    async def health_check(self, model: str) -> bool
```

This abstraction means the underlying inference engine can be swapped (e.g., llama.cpp HTTP server) without changing service code.

### 7.2 Recommended Models (CPU-friendly)

| Role | Recommended Model | RAM Required | Notes |
|------|-------------------|-------------|-------|
| Chat (small) | `llama3.2:3b` | ~3 GB | Fast on CPU; good for demo |
| Chat (medium) | `mistral:7b-q4` | ~5 GB | Better quality; needs 8GB RAM |
| Embedding | `nomic-embed-text` | ~0.5 GB | Standard 768-dim; fast |
| Vision | `llava:7b-q4` | ~5 GB | Vision-language; for image OCR assist |

All models are optional. The system checks availability before use and degrades gracefully.

### 7.3 Embedding Configuration

- **Default embedding model:** `nomic-embed-text` (via Ollama)
- **Vector dimensions:** 768 (nomic-embed-text); configurable per KB at creation time
- **Batch size:** 32 texts per embedding request (configurable)
- **Similarity metric:** Cosine similarity
- **Re-embedding trigger:** manual only (admin action); not automatic on model change

### 7.4 Agent Prompting Requirements

The agent uses structured prompting. The LLM must:
- Return tool calls as JSON (not free text)
- Receive a system prompt that defines: available tools (names + descriptions + schemas), rules (no more than `max_iterations`), format requirements
- Never receive raw filesystem paths, credentials, or internal system details in the prompt

**Prompt injection mitigations:**
- Strip/escape HTML and special characters from user inputs before including in prompts
- Add an injection detection layer (regex + heuristic) as a pre-processing step
- Log and flag suspicious patterns (e.g., "ignore previous instructions", "system:") for audit review
- Do not include other users' data in the prompt context

### 7.5 OCR Requirements

PaddleOCR configuration:
- `use_gpu=False` by default (CPU mode)
- `lang='en'` default; configurable per document
- Run in-process (not as a separate service) for MVP
- For scanned PDFs: render pages to images (PyMuPDF) then run OCR
- Minimum confidence threshold: 0.7 (configurable); below threshold → flag for review
- OCR output appended to extracted text with `[OCR]` annotation

---

## 8. Security Technical Requirements

### 8.1 Authentication Implementation

- **Access token:** JWT, HS256, 60-minute TTL
- **Refresh token:** JWT, HS256, 7-day TTL, stored in `refresh_tokens` table (for revocation)
- **Secret key:** minimum 32-byte random secret, loaded from environment variable `SECRET_KEY`
- **Password:** bcrypt with cost factor 12; minimum 12 characters; common password check against local blocklist
- **CORS:** configured to allow only the frontend origin (`FRONTEND_ORIGIN` env var)

### 8.2 Authorization Implementation

**Roles and permissions:**

| Permission | Viewer | Analyst | Admin |
|------------|--------|---------|-------|
| View dashboard | ✓ | ✓ | ✓ |
| Chat with models | ✓ | ✓ | ✓ |
| Upload documents | — | ✓ | ✓ |
| Create knowledge bases | — | ✓ | ✓ |
| Run AI agents | — | ✓ | ✓ |
| Approve requests | — | — | ✓ |
| Pull/configure models | — | — | ✓ |
| View audit logs | — | — | ✓ |
| Manage users | — | — | ✓ |
| Delete knowledge bases | — | — | ✓ |

All permission checks use FastAPI dependency injection: `Depends(require_role("admin"))`.

### 8.3 Input Validation

- All API inputs validated via Pydantic v2 with strict mode where appropriate
- File uploads: MIME type re-validated server-side (not just client Content-Type); filename sanitized (pathlib.Path.name; no directory traversal)
- Max file size enforced at the HTTP layer (FastAPI `UploadFile` + `LimitUploadSize` middleware)
- SQL inputs: SQLAlchemy ORM parameterization; no raw string SQL
- LLM prompts: sanitized before injection into system prompts
- Qdrant queries: structured API calls; no raw query injection

### 8.4 Secrets Management

- All secrets loaded from environment variables via `pydantic_settings.BaseSettings`
- No secrets in code, git history, or application logs
- Required secrets: `SECRET_KEY`, `DATABASE_URL` (optional override), `QDRANT_URL`, `OLLAMA_URL`
- Docker Compose uses `.env` file (excluded from git via `.gitignore`)
- `.env.example` committed to git with placeholder values only

### 8.5 Audit Log Integrity

- Hash chain: `entry_hash = SHA256(f"{seq}:{ts}:{user_id}:{action}:{outcome}:{prev_hash}")`
- First entry: `prev_hash = "GENESIS"`
- Verification endpoint recalculates all hashes and reports first discrepancy
- Append-only enforced at the database layer (no UPDATE/DELETE on `audit_logs`)

---

## 9. Performance Requirements (Technical)

### 9.1 Backend Targets

| Operation | P50 target | P95 target | Notes |
|-----------|-----------|-----------|-------|
| Auth endpoints | 50ms | 100ms | bcrypt adds ~100ms to login |
| API CRUD endpoints | 30ms | 150ms | SQLite read/write |
| RAG query (retrieval only) | 100ms | 300ms | Qdrant + embedding |
| RAG query (with generation) | 1s | 3s | Model-dependent |
| Document upload (metadata) | 100ms | 200ms | File saved, background task queued |
| System status | 50ms | 100ms | Cached; max 5s staleness |

### 9.2 Caching Strategy

- System status metrics: cache 5 seconds (in-memory dict)
- Model list from Ollama: cache 30 seconds
- No query result caching in MVP (add Redis in future phases)

### 9.3 Async Architecture

- All I/O-bound operations use `async/await`
- Document processing uses `FastAPI.BackgroundTasks`
- Ollama streaming uses `httpx.AsyncClient` with `stream()` context manager
- Database: SQLAlchemy async session with `asyncio.AsyncEngine`
- No blocking `time.sleep()` calls in request handlers

---

## 10. Deployment Requirements

### 10.1 Docker Compose Services

```yaml
services:
  frontend:
    build: ./frontend
    ports: ["5173:5173"]
    depends_on: [backend]

  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [qdrant]
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////app/data/sqlite/sovereign.db
      - QDRANT_URL=http://qdrant:6333
      - OLLAMA_URL=http://host.docker.internal:11434
      - SECRET_KEY=${SECRET_KEY}
      - FRONTEND_ORIGIN=http://localhost:5173
    volumes:
      - backend_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock  # for sandbox
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/system/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  qdrant:
    image: qdrant/qdrant:v1.9.2
    ports: ["6333:6333"]
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]

volumes:
  backend_data:
  qdrant_data:
```

**Note:** Ollama runs on the host (not as a Docker service) to allow direct GPU access via CUDA. The backend accesses it via `host.docker.internal` on Mac/Windows or the host's Docker bridge IP on Linux.

### 10.2 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | None | JWT signing secret (min 32 chars) |
| `DATABASE_URL` | No | `sqlite+aiosqlite:////app/data/sqlite/sovereign.db` | DB connection string |
| `QDRANT_URL` | No | `http://qdrant:6333` | Qdrant endpoint |
| `OLLAMA_URL` | No | `http://host.docker.internal:11434` | Ollama endpoint |
| `FRONTEND_ORIGIN` | No | `http://localhost:5173` | CORS origin |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Max file upload size |
| `SANDBOX_IMAGE` | No | `python:3.11-slim` | Docker image for sandbox |
| `SANDBOX_TIMEOUT_S` | No | `30` | Sandbox execution timeout |
| `SANDBOX_MEM_LIMIT_MB` | No | `256` | Sandbox memory limit |
| `LOG_LEVEL` | No | `INFO` | Application log level |
| `AUDIT_RETENTION_DAYS` | No | `365` | Audit log retention |
| `JWT_ACCESS_TTL_MIN` | No | `60` | Access token TTL minutes |
| `JWT_REFRESH_TTL_DAYS` | No | `7` | Refresh token TTL days |

### 10.3 Docker Image Requirements

- **Backend base image:** `python:3.11-slim` (not alpine; PaddleOCR has native deps)
- **Frontend base image:** `node:20-alpine` for build; `nginx:1.27-alpine` for serving
- **Sandbox base image:** `python:3.11-slim` (pre-pulled in setup script)
- All images specify exact tags; `latest` not used in production config
- Images do not run as root (backend: UID 1000)

---

## 11. Testing Requirements

### 11.1 Unit Test Coverage Targets

| Module | Coverage Target |
|--------|----------------|
| Auth service | 90% |
| Document processing pipeline | 80% |
| RAG service | 80% |
| Agent engine | 75% |
| Tool registry | 85% |
| Sandbox service | 75% |
| Audit service | 90% |
| Hash chain | 100% |

### 11.2 Integration Test Requirements

- Auth flow: register → login → access protected endpoint → refresh → logout
- Document pipeline: upload → poll status → query
- RAG flow: create KB → upload doc → query → verify source citations
- Agent flow: start run → tool call → approval → execution → complete
- Audit: verify events logged for all above flows

### 11.3 Test Environment

- Use pytest + pytest-asyncio for backend
- Use an in-memory SQLite database for unit tests
- Mock Ollama and Qdrant with httpx `MockTransport` in unit tests
- Integration tests use Docker Compose test profile

---

## 12. Observability Requirements

### 12.1 Logging Format

All log records use structured JSON:
```json
{
  "timestamp": "2026-08-23T10:30:00Z",
  "level": "INFO",
  "logger": "sovereign.rag_service",
  "message": "RAG query completed",
  "trace_id": "uuid",
  "user_id": "uuid",
  "duration_ms": 1250,
  "kb_id": "uuid",
  "chunks_retrieved": 5
}
```

### 12.2 Health Checks

- `/api/v1/system/health` returns 200 OK with `{"status": "ok"}` when all critical services reachable
- Returns 503 with degraded/unhealthy status otherwise
- Docker Compose healthchecks for all services

### 12.3 Error Handling Standard

All API errors return:
```json
{
  "error": {
    "code": "string (machine-readable)",
    "message": "string (user-friendly)",
    "trace_id": "uuid (for log correlation)"
  }
}
```

Internal details (stack traces, SQL errors) are logged server-side only — never returned to the client.

---

## 13. Technical Assumptions & Constraints

| ID | Assumption / Constraint |
|----|------------------------|
| TA-01 | Docker Engine 24+ and Docker Compose v2 available on host |
| TA-02 | Ollama installed and running on host before `docker compose up` |
| TA-03 | At least one LLM and one embedding model pulled in Ollama |
| TA-04 | Host exposes Docker socket at `/var/run/docker.sock` for sandbox |
| TA-05 | SQLite WAL mode provides sufficient write concurrency for <= 10 simultaneous users |
| TA-06 | PaddleOCR CPU mode acceptable for demo; 5-20s per page |
| TA-07 | nomic-embed-text is the default embedding model; KB creation fails if not available |
| TA-08 | Sandbox containers require outbound internet blocked at host firewall for security |
| TA-09 | Frontend served via Vite dev server in development; nginx in production build |
| TA-10 | No external email service; approval notifications shown in UI only for MVP |

---

## 14. Future Technical Considerations (Not in MVP Scope)

| Item | Notes |
|------|-------|
| PostgreSQL migration | Change `DATABASE_URL`; run Alembic migrations |
| Redis job queue | Replace `BackgroundTasks` with Celery + Redis for reliability |
| WebSocket-based status push | Replace polling with WS for document processing |
| Multi-model embedding | Different embedding model per KB (already in schema) |
| Kubernetes deployment | Stateless backend pods; Qdrant StatefulSet |
| GPU acceleration | Ollama detects CUDA automatically; no code change required |
| Hybrid RAG search | Qdrant sparse + dense vectors |
| Plugin system | Tool registry already designed for dynamic registration |
| User provisioning (LDAP/SAML) | Auth service abstraction layer needed |

---

## 15. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial TRD derived from PRD v1.0 |

---

*End of TRD*
