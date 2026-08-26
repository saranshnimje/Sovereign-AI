# 13 Requirements Traceability Matrix
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0 through 11_Deployment_DevOps.md v1.0

---

## 1. Purpose

This matrix traces every functional requirement from the PRD to its technical specification, implementation location, and test coverage. It is used to verify completeness before the SIH demonstration.

---

## 2. Traceability Key

| Column | Meaning |
|--------|---------|
| **FR ID** | Functional requirement ID from PRD §3 |
| **TRD Ref** | Section in TRD that specifies the technical implementation |
| **API Endpoint** | REST API endpoint implementing the requirement |
| **Backend Module** | Service/router module in backend |
| **Frontend Page** | UI component or page |
| **Test Reference** | Unit/integration test coverage |
| **MVP Status** | P0 = must have, P1 = should have |

---

## 3. Authentication & Authorization (FR-AUTH)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-AUTH-01 | User registration and login | TRD §5.1 | POST /auth/register, /login | services/auth_service.py | LoginPage | test_auth_service, test_auth integration | P0 |
| FR-AUTH-02 | Role-based access control | TRD §8.2 | All endpoints via Depends() | dependencies.py | Route guards | test_auth role checks | P0 |
| FR-AUTH-03 | Session management (TTL, refresh) | TRD §8.1 | POST /auth/refresh, /logout | services/auth_service.py | AuthStore (Zustand) | test_token_expiry | P0 |
| FR-AUTH-04 | Password security (bcrypt, min length) | TRD §8.1 | POST /auth/register | services/auth_service.py | LoginPage validation | test_weak_password | P0 |
| FR-AUTH-05 | Audit login events | TRD §6.5 | POST /auth/login | services/audit_service.py | — | test_audit_login_event | P0 |

---

## 4. Local AI Chat (FR-CHAT)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-CHAT-01 | Model selection | TRD §5.2 | GET /models | services/model_service.py | ChatPage (dropdown) | test_model_list | P0 |
| FR-CHAT-02 | Streaming responses (SSE) | TRD §5.3 | POST /chat/conversations/{id}/messages | services/chat_service.py | ChatPage (SSE) | test_chat_streaming | P0 |
| FR-CHAT-03 | Conversation history | TRD §4.1.2, §5.3 | GET /chat/conversations | models/conversation.py | ChatPage (sidebar) | test_conversation_history | P0 |
| FR-CHAT-04 | System prompts | TRD §4.1.2 | POST /chat/conversations | ConversationCreate schema | ChatPage (gear icon) | test_system_prompt | P0 |
| FR-CHAT-05 | Context management | TRD §6.2 | POST /chat/conversations/{id}/messages | services/chat_service.py | — (automatic) | test_context_truncation | P0 |
| FR-CHAT-06 | Local processing indicator | PRD §3.2 | Response metadata | ChatService (metadata) | ChatPage (🔒 badge) | manual UI test | P0 |
| FR-CHAT-07 | Conversation export | TRD §5.3 | GET /chat/conversations/{id}/export | services/chat_service.py | ChatPage (Export) | test_export | P0 |

---

## 5. Model Management (FR-MODEL)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-MODEL-01 | List installed models | TRD §5.2 | GET /models | services/model_service.py | ModelsPage | test_model_list | P0 |
| FR-MODEL-02 | Model metadata | TRD §5.2 | GET /models/{name} | services/model_service.py | ModelsPage (detail) | test_model_detail | P0 |
| FR-MODEL-03 | Active model selection | TRD §3.1 | PUT /models/roles | services/model_service.py | ModelsPage (Set As) | test_model_role | P0 |
| FR-MODEL-04 | Model health check | TRD §5.2 | GET /models/health/{name} | services/model_service.py | ModelsPage (Health) | test_model_health | P0 |
| FR-MODEL-05 | Model roles | TRD §3.1, §7.1 | PUT /models/roles | model_roles config | ModelsPage | test_model_roles | P0 |
| FR-MODEL-06 | Pull new models | TRD §5.2 | POST /models/pull | services/model_service.py | ModelsPage (Pull) | test_model_pull | P0 |

---

## 6. Document Processing (FR-DOC)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-DOC-01 | Multi-format upload | TRD §6.1 | POST /documents/upload | services/document_service.py | DocumentsPage (upload modal) | test_upload_formats | P0 |
| FR-DOC-02 | File validation | TRD §8.2 | POST /documents/upload | utils/security.py (FileValidator) | Upload modal (client-side) | test_file_validation | P0 |
| FR-DOC-03 | Text extraction | TRD §5.1 | Background task | services/document_service.py (TextExtractor) | Processing progress UI | test_text_extraction | P0 |
| FR-DOC-04 | OCR processing | TRD §6.2, §7.2 | Background task | services/ocr_service.py | Processing progress UI | test_ocr_service (manual) | P0 |
| FR-DOC-05 | Document chunking | TRD §6.1 | Background task | utils/chunker.py | — | test_chunker | P0 |
| FR-DOC-06 | Metadata extraction | TRD §4.1.5 | Background task | services/document_service.py | DocumentsPage (metadata) | test_metadata_extraction | P0 |
| FR-DOC-07 | Processing status updates | TRD §5.4 | GET /documents/{id}/status | models/document.py | Processing progress steps | test_document_status | P0 |
| FR-DOC-08 | Error handling / partial results | TRD §6.3 | Background task | services/document_service.py | Error state UI | test_processing_failure | P0 |

---

## 7. RAG Pipeline (FR-RAG)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-RAG-01 | Embedding generation | TRD §4.2, §6.1 | Background task | services/embedding_service.py | — | test_embedding | P0 |
| FR-RAG-02 | Vector storage (Qdrant) | TRD §4.2 | Background task | Qdrant client | — | test_qdrant_upsert | P0 |
| FR-RAG-03 | Semantic search | TRD §6.2 | POST /knowledge-bases/{id}/query | services/rag_service.py | KB query UI | test_kb_query | P0 |
| FR-RAG-04 | Context construction | TRD §6.2 | POST /kb/{id}/query | services/rag_service.py | — (server-side) | test_context_construction | P0 |
| FR-RAG-05 | Knowledge base CRUD | TRD §5.5 | POST/GET/DELETE /knowledge-bases | services/kb_service.py | KBPage | test_kb_crud | P0 |
| FR-RAG-06 | Re-indexing | TRD §5.5 | POST /knowledge-bases/{id}/reindex | services/document_service.py | KBPage (Reindex) | test_reindex | P0 |
| FR-RAG-07 | Retrieval logging | TRD §6.5 | POST /knowledge-bases/{id}/query | services/audit_service.py | Audit log | test_rag_audit | P0 |

---

## 8. Knowledge Base Query (FR-KBQ)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-KBQ-01 | Natural language query | TRD §5.5 | POST /knowledge-bases/{id}/query | services/rag_service.py | KBDetailPage | test_kb_nlq | P0 |
| FR-KBQ-02 | Source citations | TRD §4.2, §6.2 | POST /knowledge-bases/{id}/query | services/rag_service.py | KBDetailPage (sources) | test_source_citations | P0 |
| FR-KBQ-03 | Confidence scoring | TRD §4.3 | POST /knowledge-bases/{id}/query | KBQueryResponse.low_confidence | KBDetailPage (confidence) | test_confidence | P0 |
| FR-KBQ-04 | Follow-up questions | TRD §5.3 | POST /chat + rag_kb_ids | services/chat_service.py | ChatPage + KB | test_rag_chat | P0 |
| FR-KBQ-05 | Export results | PRD §3.6 | GET /chat/{id}/export | services/chat_service.py | ChatPage (export) | manual | P0 |

---

## 9. AI Agent (FR-AGENT)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-AGENT-01 | Goal understanding | TRD §7.2, §7.3 | POST /agents/runs | services/agent_service.py | AgentPage | test_agent_planning | P1 |
| FR-AGENT-02 | Tool selection | TRD §6.7, §8.1 | Background execution | services/agent_service.py | Agent trace | test_tool_selection | P1 |
| FR-AGENT-03 | Tool execution | TRD §6.7 | Background execution | services/tool_service.py | Agent trace | test_tool_execution | P1 |
| FR-AGENT-04 | Result synthesis | TRD §7.3 | Background execution | services/agent_service.py | Agent run result | test_agent_synthesis | P1 |
| FR-AGENT-05 | Max iterations | TRD §6.7, §7.3 | Background execution | services/agent_service.py | Agent run status | test_max_iterations | P1 |
| FR-AGENT-06 | Failure handling | TRD §6.7 | GET /agents/runs/{id} | services/agent_service.py | Agent run (error state) | test_agent_failure | P1 |
| FR-AGENT-07 | Execution trace | TRD §4.1.7, §6.5 | GET /agents/runs/{id} | models/agent.py | Agent trace view | test_agent_trace | P1 |

---

## 10. Tool System (FR-TOOL)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-TOOL-01 | Tool registry | TRD §6.7, §8.1 | N/A (internal) | tools/registry.py | Settings (tool list) | test_tool_registry | P1 |
| FR-TOOL-02 | Permission levels | TRD §8.2 | N/A (enforced in agent) | tools/registry.py | Settings | test_tool_permissions | P1 |
| FR-TOOL-03 | Risk classification | TRD §6.7 | N/A | tools/registry.py | Agent trace (risk badge) | test_risk_levels | P1 |
| FR-TOOL-04 | Input validation | TRD §5.3 | N/A (Pydantic) | tools/*.py (input schemas) | — | test_tool_validation | P1 |
| FR-TOOL-05 | Output capture | TRD §6.8 | GET /agents/runs/{id} | services/sandbox_service.py | Agent trace | test_output_capture | P1 |
| FR-TOOL-06 | Built-in tools | TRD §6.7 | N/A | tools/ directory | — | test_builtin_tools | P1 |

---

## 11. Docker Sandbox (FR-SANDBOX)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-SANDBOX-01 | Container isolation | TRD §6.8, §7.1 | N/A (internal) | services/sandbox_service.py | Agent trace (Sandboxed badge) | test_sandbox_isolation | P1 |
| FR-SANDBOX-02 | Resource limits | TRD §6.4 | N/A | services/sandbox_service.py | Settings | test_resource_limits | P1 |
| FR-SANDBOX-03 | Filesystem restrictions | TRD §6.4, §8.1 | N/A | services/sandbox_service.py | — | test_filesystem_restrict | P1 |
| FR-SANDBOX-04 | Network restrictions | TRD §6.4, §8.1 | N/A | services/sandbox_service.py | — | test_network_restrict | P1 |
| FR-SANDBOX-05 | Container lifecycle / cleanup | TRD §6.8 | N/A | services/sandbox_service.py | — | test_container_cleanup | P1 |
| FR-SANDBOX-06 | Execution logging | TRD §4.1.7 | GET /agents/runs/{id} | models/agent.py (ToolCall) | Agent trace | test_sandbox_logging | P1 |

---

## 12. Human Approval (FR-APPROVAL)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-APPROVAL-01 | Approval triggers | TRD §6.7, §6.9 | N/A (agent internal) | services/approval_service.py | Agent trace (approval banner) | test_approval_trigger | P1 |
| FR-APPROVAL-02 | Approval request UI | TRD §5.7 | GET /approvals/pending | services/approval_service.py | ApprovalsPage | test_approval_ui | P1 |
| FR-APPROVAL-03 | Approval workflow | TRD §5.7, §6.9 | POST /approvals/{id}/approve | services/approval_service.py | ApprovalsPage | test_approval_workflow | P1 |
| FR-APPROVAL-04 | Approver roles | TRD §8.2 | POST /approvals/{id}/approve | dependencies.py (admin check) | — | test_approver_role | P1 |
| FR-APPROVAL-05 | Audit trail | TRD §6.10 | GET /audit/logs | services/audit_service.py | AuditPage | test_approval_audit | P1 |

---

## 13. Audit Logging (FR-AUDIT)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-AUDIT-01 | Immutable logs (append-only) | TRD §6.5, §8.1 | N/A (DB constraint) | services/audit_service.py | — | test_audit_immutability | P0 |
| FR-AUDIT-02 | Event categories | TRD §6.5 | GET /audit/logs | services/audit_service.py | AuditPage (filter) | test_audit_categories | P0 |
| FR-AUDIT-03 | Structured JSON events | TRD §4.1.9 | GET /audit/logs | models/audit.py | AuditPage | test_audit_structure | P0 |
| FR-AUDIT-04 | Log retention | TRD §2.2 | GET /audit/logs | AuditService (retention policy) | Settings | test_retention | P0 |
| FR-AUDIT-05 | Query & export | TRD §5.8 | GET /audit/logs, /export | routers/audit.py | AuditPage | test_audit_query | P0 |
| FR-AUDIT-06 | Audit verification | TRD §6.5, §8.2 | GET /audit/verify | services/audit_service.py | AuditPage (Verify) | test_hash_chain | P0 |

---

## 14. Dashboard (FR-DASH)

| FR ID | Requirement | TRD Ref | API Endpoint | Backend Module | Frontend Page | Test Ref | Status |
|-------|-------------|---------|-------------|---------------|--------------|---------|--------|
| FR-DASH-01 | System health | TRD §5.9 | GET /system/status | services/system_service.py | DashboardPage | test_system_status | P0 |
| FR-DASH-02 | Resource usage | TRD §5.9 | GET /system/resources | services/system_service.py (psutil) | DashboardPage (gauges) | test_resource_metrics | P0 |
| FR-DASH-03 | Model status | TRD §5.9 | GET /models | services/model_service.py | DashboardPage (model panel) | test_model_status | P0 |
| FR-DASH-04 | Activity feed | PRD §3.12 | GET /audit/logs | services/audit_service.py | DashboardPage (feed) | manual | P0 |
| FR-DASH-05 | Audit summary | PRD §3.12 | GET /audit/logs | services/audit_service.py | DashboardPage | manual | P0 |

---

## 15. Non-Functional Requirements Traceability

| NFR ID | Requirement | Implementation Location |
|--------|-------------|------------------------|
| NFR-PERF-01 | API response P95 < 500ms | Async architecture, SQLAlchemy, caching |
| NFR-PERF-02 | Chat token latency | Ollama streaming, SSE |
| NFR-PERF-03 | Document processing < 30s for 50MB | Background tasks, async OCR |
| NFR-PERF-05 | 10 concurrent users | Async FastAPI, WAL SQLite |
| NFR-SEC-01 | Data at rest protection | Docker volumes; optional SQLCipher |
| NFR-SEC-02 | TLS for external comms | Nginx reverse proxy (host-level) |
| NFR-SEC-03 | Secret management | Pydantic BaseSettings, .env |
| NFR-SEC-04 | Input sanitization | Pydantic v2, FileValidator, PromptSanitizer |
| NFR-SEC-05 | Sandbox escape prevention | cap_drop, non-root, network=none |
| NFR-SEC-06 | Audit log integrity | SHA-256 hash chain |
| NFR-USE-01 | Responsive design | Tailwind responsive classes |
| NFR-USE-02 | WCAG 2.1 AA | ARIA attributes, focus management (doc 05) |
| NFR-HW-01–05 | Hardware constraints | CPU-first models, optional GPU |

---

## 16. MVP Feature Coverage Summary

| Feature | PRD ID | Implemented | Tested |
|---------|--------|-------------|--------|
| Local AI Chat | MVP-01 | ☐ | ☐ |
| Model Management | MVP-02 | ☐ | ☐ |
| Document Upload & Processing | MVP-03 | ☐ | ☐ |
| RAG Pipeline | MVP-04 | ☐ | ☐ |
| Knowledge Base Query | MVP-05 | ☐ | ☐ |
| Basic AI Agent | MVP-06 | ☐ | ☐ |
| Tool System | MVP-07 | ☐ | ☐ |
| Docker Sandbox | MVP-08 | ☐ | ☐ |
| Human Approval | MVP-09 | ☐ | ☐ |
| Audit Logging | MVP-10 | ☐ | ☐ |
| Unified Dashboard | MVP-11 | ☐ | ☐ |
| Auth & RBAC | MVP-12 | ☐ | ☐ |

*Checkboxes to be filled during implementation tracking.*

---

## 17. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial Requirements Traceability Matrix |

---

*End of Requirements Traceability*
