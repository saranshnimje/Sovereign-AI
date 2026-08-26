# 01 Product Requirements Document (PRD)
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype

---

## 1. Executive Summary

### 1.1 Product Vision
Sovereign AI Workbench is a privacy-first, on-premise AI platform that enables organizations to run, manage, and use AI capabilities entirely within their own infrastructure without sending sensitive data to external cloud AI providers.

### 1.2 Problem Statement
Organizations in government, defense, healthcare, finance, legal, and research sectors cannot freely use cloud AI services due to:
- Data privacy and confidentiality requirements
- Data residency and sovereignty regulations
- Compliance mandates (GDPR, HIPAA, ITAR, etc.)
- Vendor lock-in and dependency risks
- Internet connectivity requirements for air-gapped environments
- Loss of control over AI model governance and auditability

### 1.3 Solution
A unified, modular AI workbench combining:
- Local LLM inference (via Ollama)
- Document processing and OCR (via PaddleOCR)
- Retrieval-Augmented Generation (RAG) with local vector database (Qdrant)
- AI agent orchestration with controlled tool execution
- Docker-sandboxed code execution
- Human approval workflows for high-risk operations
- Comprehensive audit logging
- Role-based access control

### 1.4 Target Users
| User Type | Description |
|-----------|-------------|
| **AI/ML Engineers** | Develop, test, and deploy local models and agents |
| **Data Analysts** | Query knowledge bases, process documents, run analyses |
| **Security/Compliance Officers** | Audit AI usage, review approvals, enforce policies |
| **System Administrators** | Manage infrastructure, models, users, and system health |
| **Domain Experts** | Interact with AI assistants for domain-specific tasks |

---

## 2. Product Scope

### 2.1 MVP Scope (SIH 2026 Prototype)
The MVP demonstrates core capabilities for evaluation:

| Feature ID | Feature | Priority | Description |
|------------|---------|----------|-------------|
| MVP-01 | Local AI Chat | P0 | Chat interface with locally running LLMs via Ollama |
| MVP-02 | Model Management | P0 | View, select, configure installed models |
| MVP-03 | Document Upload & Processing | P0 | Upload PDF, TXT, DOCX, images; extract text; run OCR |
| MVP-04 | RAG Pipeline | P0 | Chunk documents, generate embeddings, store in Qdrant, retrieve context |
| MVP-05 | Knowledge Base Query | P0 | Ask questions against indexed documents with source citations |
| MVP-06 | Basic AI Agent | P1 | Goal understanding, tool selection, execution, result synthesis |
| MVP-07 | Tool System | P1 | File ops, search, calculations, Python execution with permissions |
| MVP-08 | Docker Sandbox | P1 | Isolated execution for untrusted code with resource limits |
| MVP-09 | Human Approval | P1 | Approval gates for high-risk operations (file delete, network, system) |
| MVP-10 | Audit Logging | P0 | Immutable log of all AI actions, tool calls, approvals, errors |
| MVP-11 | Unified Dashboard | P0 | System status, model health, resource usage, recent activity |
| MVP-12 | Auth & RBAC | P0 | JWT authentication, role-based access control |

### 2.2 Out of Scope (Future Phases)
| Feature | Reason |
|---------|--------|
| Multi-tenancy | Complexity; MVP is single-org |
| Advanced agent orchestration (multi-agent) | MVP focuses on single-agent workflows |
| Model fine-tuning pipeline | Requires GPU; out of hardware scope |
| Federated learning | Research-grade; not for prototype |
| Advanced UI customization | UX polish post-MVP |
| Kubernetes deployment | Docker Compose sufficient for prototype |
| PostgreSQL migration | SQLite sufficient for prototype |
| Advanced prompt engineering UI | Core chat sufficient for MVP |
| Plugin marketplace | Architecture supports it; not in MVP |
| Mobile application | Web-first responsive design |

---

## 3. Functional Requirements

### 3.1 Authentication & Authorization (AUTH)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-AUTH-01 | User registration and login | Users can register/login via email/password; JWT tokens issued |
| FR-AUTH-02 | Role-based access control | Roles: Admin, Analyst, Viewer; permissions enforced on all endpoints |
| FR-AUTH-03 | Session management | Tokens expire after configurable TTL; refresh token rotation |
| FR-AUTH-04 | Password security | bcrypt hashing; minimum 12 chars; breach check (local list) |
| FR-AUTH-05 | Audit login events | All auth events logged with timestamp, IP, user agent, outcome |

### 3.2 Local AI Chat (CHAT)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-CHAT-01 | Model selection | Dropdown to select from installed Ollama models |
| FR-CHAT-02 | Streaming responses | Server-sent events (SSE) for token-by-token streaming |
| FR-CHAT-03 | Conversation history | Persist conversations in SQLite; load previous sessions |
| FR-CHAT-04 | System prompts | Configurable system prompt per conversation |
| FR-CHAT-05 | Context management | Automatic context window management (truncate/summarize) |
| FR-CHAT-06 | Local processing indicator | Clear visual indicator that processing is local |
| FR-CHAT-07 | Conversation export | Export conversation as JSON/Markdown |

### 3.3 Model Management (MODEL)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-MODEL-01 | List installed models | Query Ollama API; display name, size, quantization, family |
| FR-MODEL-02 | Model metadata | Show parameter count, context window, capabilities |
| FR-MODEL-03 | Active model selection | Designate default chat/embedding/vision models |
| FR-MODEL-04 | Model health check | Verify model loads and responds; show status |
| FR-MODEL-05 | Model roles | Tag models as: chat, embedding, vision, reasoning |
| FR-MODEL-06 | Pull new models | Trigger `ollama pull` with progress indication |

### 3.4 Document Processing (DOC)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-DOC-01 | Multi-format upload | Accept PDF, TXT, DOCX, PNG, JPG, CSV, MD |
| FR-DOC-02 | File validation | MIME type check; size limit (configurable, default 50MB); virus scan placeholder |
| FR-DOC-03 | Text extraction | PDF: PyMuPDF; DOCX: python-docx; TXT/MD: direct; CSV: pandas |
| FR-DOC-04 | OCR processing | PaddleOCR for images and scanned PDFs; language detection |
| FR-DOC-05 | Document chunking | Configurable chunk size (default 512 tokens) and overlap (default 50) |
| FR-DOC-06 | Metadata extraction | Extract title, author, creation date, page count |
| FR-DOC-07 | Processing status | Async job queue; real-time status updates via WebSocket |
| FR-DOC-08 | Error handling | Graceful failure with detailed error logs; partial results preserved |

### 3.5 RAG Pipeline (RAG)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-RAG-01 | Embedding generation | Local embedding model (via Ollama); batch processing |
| FR-RAG-02 | Vector storage | Qdrant collections per knowledge base; HNSW index |
| FR-RAG-03 | Semantic search | Top-k retrieval with score threshold; hybrid search (future) |
| FR-RAG-04 | Context construction | Combine retrieved chunks with citations; respect token budget |
| FR-RAG-05 | Knowledge base CRUD | Create, list, delete knowledge bases; add/remove documents |
| FR-RAG-06 | Re-indexing | Full or incremental re-index of knowledge base |
| FR-RAG-07 | Retrieval logging | Log queries, retrieved chunks, scores for audit |

### 3.6 Knowledge Base Query (KBQ)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-KBQ-01 | Natural language query | User asks question; system retrieves relevant context |
| FR-KBQ-02 | Source citations | Answer includes chunk references with document name, page/section |
| FR-KBQ-03 | Confidence scoring | Display retrieval confidence; flag low-confidence answers |
| FR-KBQ-04 | Follow-up questions | Maintain conversation context within knowledge base session |
| FR-KBQ-05 | Export results | Save Q&A pairs with sources to knowledge base or export |

### 3.7 AI Agent (AGENT)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-AGENT-01 | Goal understanding | Parse user intent into structured task plan |
| FR-AGENT-02 | Tool selection | Match task requirements to available permitted tools |
| FR-AGENT-03 | Tool execution | Invoke tools via sandbox; capture stdout/stderr/return code |
| FR-AGENT-04 | Result synthesis | Incorporate tool results into reasoning; iterate if needed |
| FR-AGENT-05 | Max iterations | Configurable limit (default 10) to prevent infinite loops |
| FR-AGENT-06 | Failure handling | Graceful degradation; partial results returned with explanation |
| FR-AGENT-07 | Execution trace | Full step-by-step trace logged for audit |

### 3.8 Tool System (TOOL)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-TOOL-01 | Tool registry | Central registry with name, description, I/O schemas, permissions |
| FR-TOOL-02 | Permission levels | Levels: Read, Write, Execute, Network, System, Admin |
| FR-TOOL-03 | Risk classification | Risk: Low, Medium, High, Critical; determines approval requirement |
| FR-TOOL-04 | Input validation | Pydantic schema validation before execution |
| FR-TOOL-05 | Output capture | Structured output; error serialization; timeout enforcement |
| FR-TOOL-06 | Built-in tools | File read/write/list, search KB, calculate, Python exec, HTTP (if permitted) |

### 3.9 Docker Sandbox (SANDBOX)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-SANDBOX-01 | Container isolation | Each execution in fresh container; no persistence by default |
| FR-SANDBOX-02 | Resource limits | CPU (cores), Memory (MB), Time (seconds), PIDs configurable per tool |
| FR-SANDBOX-03 | Filesystem restrictions | Read-only base; writable workspace mounted; no host access |
| FR-SANDBOX-04 | Network restrictions | Default deny; allowlist for specific tools |
| FR-SANDBOX-05 | Container lifecycle | Auto-cleanup on completion/failure/timeout; no orphan containers |
| FR-SANDBOX-06 | Execution logging | Log container ID, command, resource usage, exit code, duration |

### 3.10 Human Approval (APPROVAL)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-APPROVAL-01 | Approval triggers | Configurable rules: tool risk level, operation type, data sensitivity |
| FR-APPROVAL-02 | Approval request UI | Modal with operation details, risk assessment, approve/reject |
| FR-APPROVAL-03 | Approval workflow | Request → Notify approvers → Wait (timeout configurable) → Execute/Reject |
| FR-APPROVAL-04 | Approver roles | Configurable per operation type; default: Admin |
| FR-APPROVAL-05 | Audit trail | Full log of request, decision, decider, timestamp, reasoning |

### 3.11 Audit Logging (AUDIT)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-AUDIT-01 | Immutable logs | Append-only; tamper-evident (hash chaining) |
| FR-AUDIT-02 | Event categories | Auth, Model, Document, RAG, Agent, Tool, Sandbox, Approval, Config, Error |
| FR-AUDIT-03 | Structured events | JSON format: timestamp, user, action, resource, outcome, metadata |
| FR-AUDIT-04 | Log retention | Configurable retention (default 1 year); archive policy |
| FR-AUDIT-05 | Query & export | Filter by date, user, event type, outcome; export CSV/JSON |
| FR-AUDIT-06 | Real-time alerts | Configurable alerts for critical events (failed auth, sandbox escape attempt) |

### 3.12 Dashboard (DASH)

| Req ID | Requirement | Acceptance Criteria |
|--------|-------------|---------------------|
| FR-DASH-01 | System health | Ollama, Qdrant, API status; green/yellow/red indicators |
| FR-DASH-02 | Resource usage | CPU, RAM, GPU (if available), disk, network (via `psutil`) |
| FR-DASH-03 | Model status | Loaded models, VRAM/RAM usage, last used |
| FR-DASH-04 | Activity feed | Recent: chats, document uploads, agent runs, approvals |
| FR-DASH-05 | Audit summary | Event counts by type; anomaly indicators |

---

## 4. Non-Functional Requirements

### 4.1 Performance

| Req ID | Requirement | Target |
|--------|-------------|--------|
| NFR-PERF-01 | API response time (p95) | < 500ms for non-streaming endpoints |
| NFR-PERF-02 | Chat token latency | < 200ms per token (CPU), < 50ms (GPU) |
| NFR-PERF-03 | Document processing | < 30s for 50MB PDF (CPU-only) |
| NFR-PERF-04 | RAG query latency | < 2s end-to-end (retrieve + generate) |
| NFR-PERF-05 | Concurrent users | Support 10 concurrent users on modest hardware |
| NFR-PERF-06 | Startup time | < 60s for full stack via Docker Compose |

### 4.2 Scalability

| Req ID | Requirement | Target |
|--------|-------------|--------|
| NFR-SCALE-01 | Document count | 10,000 documents per knowledge base |
| NFR-SCALE-02 | Vector count | 1M vectors in Qdrant |
| NFR-SCALE-03 | Conversation history | 1000 conversations per user |
| NFR-SCALE-04 | Horizontal scaling | Stateless API; can run multiple replicas behind LB |

### 4.3 Reliability

| Req ID | Requirement | Target |
|--------|-------------|--------|
| NFR-REL-01 | Uptime | 99.5% (single-node) |
| NFR-REL-02 | Data durability | SQLite WAL mode; Qdrant persistence; daily backups |
| NFR-REL-03 | Graceful degradation | Disable AI services independently; core dashboard remains |
| NFR-REL-04 | Error recovery | Automatic retry with exponential backoff for transient failures |

### 4.4 Security

| Req ID | Requirement | Target |
|--------|-------------|--------|
| NFR-SEC-01 | Data at rest | SQLite encryption (SQLCipher) optional; Qdrant local only |
| NFR-SEC-02 | Data in transit | TLS 1.3 for all external communication |
| NFR-SEC-03 | Secret management | Environment variables; no secrets in code or logs |
| NFR-SEC-04 | Input sanitization | All inputs validated; prompt injection mitigations |
| NFR-SEC-05 | Sandbox escape prevention | Dropped capabilities; non-root user; seccomp profile |
| NFR-SEC-06 | Audit log integrity | SHA-256 hash chaining; periodic verification |

### 4.5 Usability

| Req ID | Requirement | Target |
|--------|-------------|--------|
| NFR-USE-01 | Responsive design | Works on desktop (1920x1080) and tablet (768x1024) |
| NFR-USE-02 | Accessibility | WCAG 2.1 AA compliance |
| NFR-USE-03 | Dark/light mode | System preference + manual toggle |
| NFR-USE-04 | Keyboard navigation | Full keyboard operability |
| NFR-USE-05 | Error messages | User-friendly; technical details in logs |

### 4.6 Hardware Constraints

| Req ID | Requirement | Target |
|--------|-------------|--------|
| NFR-HW-01 | Minimum RAM | 8 GB (16 GB recommended) |
| NFR-HW-02 | Minimum CPU | 4 cores (8 cores recommended) |
| NFR-HW-03 | Minimum Disk | 50 GB free (models + vectors + docs) |
| NFR-HW-04 | GPU | Optional; NVIDIA CUDA if available |
| NFR-HW-05 | Offline operation | Fully functional without internet after initial model pull |

---

## 5. User Stories

### 5.1 Admin User Stories
| ID | Story |
|----|-------|
| US-ADMIN-01 | As an admin, I want to manage user accounts and roles so that I can control access |
| US-ADMIN-02 | As an admin, I want to pull and configure AI models so that analysts have the right models |
| US-ADMIN-03 | As an admin, I want to review audit logs so that I can verify compliance |
| US-ADMIN-04 | As an admin, I want to configure approval policies so that risky operations require review |
| US-ADMIN-05 | As an admin, I want to monitor system resources so that I can plan capacity |

### 5.2 Analyst User Stories
| ID | Story |
|----|-------|
| US-ANALYST-01 | As an analyst, I want to chat with a local LLM so that I can get AI assistance without data leaving |
| US-ANALYST-02 | As an analyst, I want to upload documents and make them searchable so that I can query my knowledge base |
| US-ANALYST-03 | As an analyst, I want to ask questions against my documents so that I get answers with citations |
| US-ANALYST-04 | As an analyst, I want to run an AI agent to automate multi-step tasks so that I save time |
| US-ANALYST-05 | As an analyst, I want to execute Python code in a sandbox so that I can analyze data safely |

### 5.3 Security Officer User Stories
| ID | Story |
|----|-------|
| US-SEC-01 | As a security officer, I want to see all AI interactions so that I can audit usage |
| US-SEC-02 | As a security officer, I want to approve high-risk operations so that nothing dangerous runs unattended |
| US-SEC-03 | As a security officer, I want to verify no data leaves the network so that compliance is maintained |

---

## 6. Data Requirements

### 6.1 Data Entities

| Entity | Description | Key Attributes |
|--------|-------------|----------------|
| User | System user | id, email, password_hash, role, created_at, last_login |
| Conversation | Chat session | id, user_id, model_id, system_prompt, created_at, updated_at |
| Message | Chat message | id, conversation_id, role, content, tokens, metadata |
| Model | AI model metadata | id, name, family, size, quantization, role, status |
| Document | Uploaded document | id, kb_id, filename, mime_type, size, status, metadata |
| KnowledgeBase | Document collection | id, name, description, embedding_model, created_at |
| DocumentChunk | Text chunk with embedding | id, doc_id, kb_id, chunk_index, content, embedding, metadata |
| AgentRun | Agent execution | id, user_id, goal, status, steps, result, created_at |
| ToolCall | Tool invocation | id, agent_run_id, tool_name, input, output, status, duration |
| ApprovalRequest | Human approval | id, requester_id, operation, risk_level, status, decided_by, decided_at |
| AuditLog | Immutable audit entry | id, timestamp, user_id, event_type, action, resource, outcome, hash_chain |

### 6.2 Data Flow Summary
```
User Request
    → Auth Check (AUTH)
    → Route to Service (CHAT/DOC/RAG/AGENT)
    → [If Agent] → Plan → Tool Selection → [If High Risk] → Approval → Sandbox Exec → Result
    → [If RAG] → Embed Query → Vector Search → Context Build → LLM Generate
    → Response + Audit Log
```

---

## 7. Integration Requirements

### 7.1 External Dependencies

| Dependency | Purpose | Integration Method |
|------------|---------|-------------------|
| Ollama | Local LLM inference | REST API (localhost:11434) |
| Qdrant | Vector database | gRPC/REST (localhost:6333) |
| PaddleOCR | OCR processing | Python library (in-process) |
| Docker Engine | Sandbox execution | Docker SDK / CLI |

### 7.2 Internal Service Communication
- All backend services communicate via in-process function calls (modular monolith)
- Future: message queue (Redis/RabbitMQ) for async job processing

---

## 8. Constraints & Assumptions

### 8.1 Technical Constraints
- **No cloud dependencies** for core functionality
- **Single-node deployment** for MVP (Docker Compose)
- **SQLite** for relational data (migration path to PostgreSQL documented)
- **CPU-first** model support; GPU optional
- **Offline-capable** after initial model download

### 8.2 Assumptions
- Organization has Docker and Docker Compose installed
- At least one compatible LLM model is available via Ollama
- Users have basic technical literacy
- Network policies allow localhost communication between containers
- Initial model pull requires internet (one-time)

### 8.3 Regulatory Constraints
- Audit logs must be tamper-evident
- Personal data processing must comply with applicable regulations
- No telemetry or external reporting without explicit consent

---

## 9. Acceptance Criteria Summary

| Criterion | Demo Scenario |
|-----------|---------------|
| **AC-01** | Fresh `docker compose up` starts all services < 60s |
| **AC-02** | User registers, logs in, sees dashboard with green health checks |
| **AC-03** | User selects model, chats, receives streaming response |
| **AC-04** | User uploads PDF → OCR runs → text extracted → chunked → embedded → searchable |
| **AC-05** | User asks question → relevant chunks retrieved → LLM answers with citations |
| **AC-06** | User asks agent to "analyze sales.csv" → agent reads file → runs Python → returns chart |
| **AC-07** | Agent attempts file delete → approval request → admin approves → execution logged |
| **AC-08** | All actions appear in audit log with timestamp, user, outcome |
| **AC-09** | System runs on 8GB RAM / 4-core CPU without GPU |
| **AC-10** | Disconnect internet → all features still work |

---

## 10. Success Metrics (SIH Evaluation)

| Metric | Target |
|--------|--------|
| Feature completeness | 10/12 MVP features functional |
| Demo stability | Zero crashes during 15-min demo |
| Resource usage | < 6GB RAM, < 70% CPU on demo hardware |
| Response quality | Relevant answers with citations for RAG queries |
| Security posture | No critical vulnerabilities in static analysis |
| Documentation completeness | All 15 docs created and consistent |

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial PRD for SIH 2026 prototype |

---

*End of PRD*