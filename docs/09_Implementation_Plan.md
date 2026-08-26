# 09 Implementation Plan
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0, 03_System_Architecture.md v1.0

---

## 1. Overview

This document defines the phased implementation plan for the Sovereign AI Workbench MVP targeting the SIH 2026 prototype evaluation. It covers work breakdown, priority ordering, technical dependencies between components, and a realistic timeline for a small team.

---

## 2. Implementation Philosophy

- **Build vertically, not horizontally.** Deliver working features end-to-end (frontend + backend + AI) in each phase rather than completing all backend first.
- **Prioritize the demo path.** The sequence is ordered to enable a working demonstration as early as possible.
- **Feature gates.** Each major component (RAG, agent, sandbox) can be disabled independently. This allows partial demos if some components are incomplete.
- **Test as you build.** Unit tests for critical logic (auth, hash chain, tool validation) alongside implementation — not as a separate phase.

---

## 3. Prerequisites

Before any implementation begins:

| Prerequisite | Action |
|-------------|--------|
| Docker Desktop installed | Install Docker Desktop 24+ |
| Ollama installed on host | Install from https://ollama.ai |
| Pull minimum models | `ollama pull llama3.2:3b` and `ollama pull nomic-embed-text` |
| Python 3.11+ | Verify with `python --version` |
| Node.js 20+ | Verify with `node --version` |
| Git repository created | Init repo, push to internal GitLab/GitHub |
| `.gitignore` configured | Include `.env`, `*.db`, `uploads/`, `__pycache__`, `node_modules/` |
| `.env.example` created | Document all required environment variables |

---

## 4. Phase 1 — Foundation (Week 1)

**Goal:** Running Docker Compose stack with auth, dashboard, and basic chat.

**Acceptance:** `docker compose up` → login → see dashboard → send a chat message → get a streaming response.

### 4.1 Infrastructure Setup

| Task | Owner | Effort |
|------|-------|--------|
| Create `docker-compose.yml` with frontend, backend, qdrant services | DevOps | 2h |
| Write backend `Dockerfile` (python:3.11-slim, non-root user) | DevOps | 1h |
| Write frontend `Dockerfile` (node:20-alpine build → nginx:alpine serve) | DevOps | 1h |
| Create `.env.example` with all variables | DevOps | 30m |
| Set up Alembic for DB migrations | Backend | 1h |
| Configure SQLite WAL mode on startup | Backend | 30m |

### 4.2 Backend Foundation

| Task | Dependencies | Effort |
|------|-------------|--------|
| `main.py` — FastAPI app factory with middleware | None | 1h |
| `config.py` — Pydantic BaseSettings | None | 30m |
| `database.py` — Async SQLAlchemy engine | config | 1h |
| ORM models: `User`, `RefreshToken` | database | 2h |
| `AuthService` — register, login, JWT | User model | 3h |
| Auth router — `/auth/register`, `/login`, `/refresh`, `/logout`, `/me` | AuthService | 2h |
| `get_current_user` dependency injection | AuthService | 30m |
| `require_role()` dependency | get_current_user | 30m |
| Global exception handlers | main.py | 1h |
| Request ID middleware | main.py | 30m |
| System health endpoint `/system/health` | None | 30m |
| System status endpoint `/system/status` | LLMClient, Qdrant | 1h |

### 4.3 Frontend Foundation

| Task | Dependencies | Effort |
|------|-------------|--------|
| Vite + React + TypeScript + Tailwind setup | Node | 1h |
| React Router v6 routing structure | React | 1h |
| Zustand auth store | React | 1h |
| API client with interceptors (axios) | Zustand | 2h |
| Login page component | API client | 2h |
| Application shell (sidebar, topbar) | Router | 3h |
| Protected route component | Auth store | 1h |
| Toast notification system | React | 1h |

### 4.4 Chat MVP

| Task | Dependencies | Effort |
|------|-------------|--------|
| ORM models: `Conversation`, `Message` | database | 1h |
| `LLMClient` abstraction + `OllamaClient` | httpx | 3h |
| `ChatService` — create conversation, send message, stream | LLMClient | 3h |
| Chat router — conversations CRUD + message stream | ChatService | 2h |
| Model list endpoint (proxy Ollama `/api/tags`) | LLMClient | 1h |
| Chat page component with SSE streaming | API client | 4h |
| Conversation list sidebar | Chat page | 2h |
| Model selector dropdown | Models endpoint | 1h |
| "Processing locally" indicator | Chat page | 30m |

**Phase 1 total estimated effort: ~45 hours**

---

## 5. Phase 2 — Documents & Knowledge Base (Week 2)

**Goal:** Upload a PDF, have it OCR'd and indexed, query it with RAG.

**Acceptance:** Upload `report.pdf` → status shows "Indexed" → ask a question → receive answer with source citations.

### 5.1 Document Processing

| Task | Dependencies | Effort |
|------|-------------|--------|
| ORM models: `KnowledgeBase`, `Document` | database | 1h |
| `FileValidator` class (MIME, size, filename) | None | 2h |
| `TextExtractor` — PDF, DOCX, TXT, CSV | PyMuPDF, python-docx | 3h |
| `OCRService` — PaddleOCR wrapper, async executor | PaddleOCR | 3h |
| `TextChunker` — recursive splitter | None | 2h |
| `EmbeddingService` — batch via Ollama | LLMClient | 2h |
| `DocumentService` — full processing pipeline | All above | 4h |
| Document router — upload, status, list, delete | DocumentService | 2h |
| Processing step tracking in SQLite | DocumentService | 1h |

### 5.2 Knowledge Base & RAG

| Task | Dependencies | Effort |
|------|-------------|--------|
| Qdrant client wrapper | qdrant-client | 2h |
| `RAGService` — embed query, search, context, generate | EmbeddingService, Qdrant, LLMClient | 4h |
| Knowledge base router — CRUD + query | RAGService | 2h |
| KB query with source citations | RAGService | 2h |

### 5.3 Frontend

| Task | Dependencies | Effort |
|------|-------------|--------|
| Document upload modal with drag-and-drop | UI components | 3h |
| Processing status progress steps UI | Documents API | 2h |
| Knowledge base list + create modal | KB API | 2h |
| KB detail page with document list | KB API | 2h |
| Knowledge base query interface with sources | KB query API | 3h |
| Chat page: KB selector + citations display | Chat + KB | 2h |

**Phase 2 total estimated effort: ~45 hours**

---

## 6. Phase 3 — AI Agent & Tools (Week 3)

**Goal:** Agent can read a file, run Python analysis, and return a result.

**Acceptance:** Input "Analyze sales.csv and find top 5 products" → agent reads file → runs Python → returns result → all steps visible in trace.

### 6.1 Tool System

| Task | Dependencies | Effort |
|------|-------------|--------|
| `ToolDefinition` dataclass and `ToolRegistry` | None | 2h |
| `file_read` tool | ToolRegistry | 1h |
| `file_list` tool | ToolRegistry | 1h |
| `file_write` tool | ToolRegistry | 1h |
| `file_delete` tool (requires approval) | ToolRegistry | 1h |
| `search_kb` tool | RAGService | 2h |
| `calculator` tool (safe eval) | ToolRegistry | 1h |
| `python_exec` tool schema (execution in sandbox) | ToolRegistry | 1h |
| Path traversal prevention in file tools | Security | 1h |

### 6.2 Sandbox Service

| Task | Dependencies | Effort |
|------|-------------|--------|
| `SandboxService` — Docker SDK wrapper | docker-py | 4h |
| Container hardening config (cap_drop, read_only, no-network) | docker-py | 2h |
| Workspace lifecycle (create/cleanup) | Sandbox | 1h |
| Timeout handling and container kill | Sandbox | 1h |
| Pre-pull sandbox base image in setup script | Docker | 30m |

### 6.3 Approval System

| Task | Dependencies | Effort |
|------|-------------|--------|
| ORM models: `ApprovalRequest` | database | 1h |
| `ApprovalService` — create request, async wait, decide | None | 3h |
| Approval router — pending list, approve, reject | ApprovalService | 1h |
| Approval expiry background task | ApprovalService | 1h |

### 6.4 Agent Engine

| Task | Dependencies | Effort |
|------|-------------|--------|
| ORM models: `AgentRun`, `ToolCall` | database | 1h |
| `AgentService` — execution loop | LLMClient, ToolRegistry, Sandbox, Approval | 6h |
| Agent system prompt builder | ToolRegistry | 2h |
| JSON response parser with fallback | AgentService | 2h |
| `PromptSanitizer` — injection detection | Security | 2h |
| Agent router — start run, list, detail, stream, cancel | AgentService | 2h |
| SSE agent event streaming | AgentService | 2h |

### 6.5 Frontend

| Task | Dependencies | Effort |
|------|-------------|--------|
| Agent run creation form | Agents API | 2h |
| Live agent execution trace view (SSE) | Agents API | 4h |
| Step-by-step trace with tool inputs/outputs | Trace view | 2h |
| Approvals page — pending list | Approvals API | 2h |
| Approval detail + approve/reject modal | Approvals API | 2h |
| Approval required banner in agent run view | Agent SSE | 2h |

**Phase 3 total estimated effort: ~55 hours**

---

## 7. Phase 4 — Audit, Dashboard, and Polish (Week 4)

**Goal:** Full audit log, complete dashboard, model management, and demo-ready polish.

**Acceptance:** All 12 MVP features functional; `docker compose up` on a clean machine works in < 60 seconds.

### 7.1 Audit System

| Task | Dependencies | Effort |
|------|-------------|--------|
| ORM model: `AuditLog` | database | 1h |
| `AuditService` with hash chain | AuditLog | 3h |
| Integrate `audit_service.log()` into all services | All services | 3h |
| Audit log router — query, export, verify | AuditService | 2h |

### 7.2 Dashboard Completion

| Task | Dependencies | Effort |
|------|-------------|--------|
| System status service (poll Ollama, Qdrant health) | LLMClient, Qdrant | 1h |
| Resource metrics via psutil | psutil | 1h |
| Dashboard page — resource gauges, service status | System API | 3h |
| Activity feed — recent events from audit log | Audit API | 2h |
| Quick actions panel | Router links | 1h |

### 7.3 Model Management UI

| Task | Dependencies | Effort |
|------|-------------|--------|
| Models page — list with metadata | Models API | 2h |
| Model detail panel with role assignment | Models API | 2h |
| Pull model with progress SSE | Models API | 2h |
| Model health check button | Models API | 1h |

### 7.4 Settings Page

| Task | Dependencies | Effort |
|------|-------------|--------|
| User management (admin) | Auth API | 2h |
| System configuration panels | System API | 3h |

### 7.5 First-Run Setup Wizard

| Task | Dependencies | Effort |
|------|-------------|--------|
| Setup detection endpoint (`user count == 0`) | Auth | 30m |
| Setup wizard 3-step component | Frontend | 3h |

### 7.6 Polish and Bug Fixes

| Task | Effort |
|------|--------|
| Error boundary components in React | 1h |
| Empty state components for all lists | 2h |
| Responsive layout fixes (tablet viewport) | 2h |
| Dark mode implementation | 2h |
| Keyboard navigation audit | 1h |
| Loading skeleton components | 2h |
| End-to-end smoke test run | 2h |
| Docker Compose health check validation | 1h |
| Update `.env.example` and README | 1h |

**Phase 4 total estimated effort: ~45 hours**

---

## 8. Timeline Summary

| Phase | Duration | Key Milestone |
|-------|----------|--------------|
| Phase 1 — Foundation | Week 1 | Login → Chat working |
| Phase 2 — Documents & RAG | Week 2 | Upload PDF → Query KB |
| Phase 3 — Agent & Tools | Week 3 | Agent run with tool calls and approval |
| Phase 4 — Audit & Polish | Week 4 | Full MVP demo-ready |
| **Total** | **4 weeks** | **SIH prototype complete** |

---

## 9. Technical Dependency Graph

```
[Docker Compose + Ollama] ←── all services depend on this
         │
         ▼
[Database (SQLite + SQLAlchemy)] ←── all services depend on this
         │
         ▼
[Auth Service] ←── all protected endpoints depend on this
         │
         ├──▶ [Chat Service] ──▶ [LLMClient → Ollama]
         │
         ├──▶ [Document Service]
         │         │
         │         ├──▶ [TextExtractor]
         │         ├──▶ [OCRService → PaddleOCR]
         │         ├──▶ [TextChunker]
         │         └──▶ [EmbeddingService → Ollama]
         │                    │
         │                    ▼
         │              [Qdrant Client]
         │                    │
         │                    ▼
         ├──▶ [RAG Service] ──┘
         │
         ├──▶ [Tool Registry]
         │         │
         │         ├──▶ [SandboxService → Docker Engine]
         │         └──▶ [ApprovalService]
         │                    │
         │                    ▼
         └──▶ [Agent Service] ──▶ [LLMClient]
                                  [ToolRegistry]
                                  [SandboxService]
                                  [ApprovalService]
                                  [AuditService]
```

---

## 10. Risk and Mitigation for Implementation

| Risk | Impact | Mitigation |
|------|--------|------------|
| PaddleOCR install complexity on certain OSes | High | Use Docker with pre-installed PaddleOCR; document known issues |
| LLM response not valid JSON (agent parsing) | High | Implement robust JSON extraction with retry; graceful fallback |
| Ollama cold start latency | Medium | Document that first request is slow; add loading indicator |
| Docker socket availability in CI | Medium | Mock Docker SDK in unit tests |
| SQLite concurrent write lock | Low | WAL mode; only 1 background task per doc; not a problem at prototype scale |
| PaddleOCR CPU performance | Low | Document expected OCR time per page; user sees progress |
| Agent infinite loop | Low | Hard iteration limit enforced before any LLM call |

---

## 11. Definition of Done

A feature is complete when:
1. API endpoint(s) are implemented and return correct responses.
2. Frontend page/component is functional.
3. Unit tests pass for critical business logic.
4. Error cases handled (not just happy path).
5. Audit log records the action.
6. No secrets, file paths, or internal errors exposed in API responses.
7. Feature works on the minimum hardware spec (8 GB RAM, 4 CPU).

---

## 12. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial Implementation Plan |

---

*End of Implementation Plan*
