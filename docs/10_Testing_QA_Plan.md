# 10 Testing & QA Plan
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0, 09_Implementation_Plan.md v1.0

---

## 1. Testing Philosophy

Testing for the SIH prototype focuses on:
1. **Correctness** of critical paths (auth, document processing, RAG, agent tool execution).
2. **Security** of input validation, auth enforcement, and sandbox behavior.
3. **Stability** under demo conditions — no crashes during a 15-minute demonstration.
4. **Acceptance criteria verification** from the PRD.

The test suite is realistic for a small team with a 4-week timeline. Coverage targets are set for critical components; UI acceptance testing is prioritized over exhaustive unit coverage.

---

## 2. Test Types and Scope

| Test Type | Tools | Scope |
|-----------|-------|-------|
| Unit tests | pytest + pytest-asyncio | Services, utilities, hash chain, chunking, validation |
| Integration tests | pytest + TestClient | API endpoints with real DB (in-memory SQLite) |
| E2E acceptance tests | Manual checklist (or Playwright if time allows) | Key user flows per PRD acceptance criteria |
| Security tests | Manual + bandit (SAST) | Auth bypass, injection, path traversal |
| Performance tests | Manual + locust (optional) | Response time targets from NFRs |
| Regression tests | Automated (run before demo) | Core features must not break |

---

## 3. Backend Unit Tests

### 3.1 Test Setup

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database import Base

@pytest_asyncio.fixture
async def db():
    """In-memory SQLite for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession)
    async with async_session() as session:
        yield session
    await engine.dispose()

@pytest.fixture
def mock_llm_client():
    """Mock LLMClient that returns predetermined responses."""
    from unittest.mock import AsyncMock, MagicMock
    client = AsyncMock()
    client.health_check.return_value = True
    client.list_models.return_value = [{"name": "llama3.2:3b", "size": 2048}]
    return client

@pytest.fixture
def mock_qdrant_client():
    from unittest.mock import AsyncMock
    client = AsyncMock()
    client.search.return_value = []
    return client
```

### 3.2 Auth Service Tests

```python
# tests/unit/test_auth_service.py

async def test_register_success(db):
    service = AuthService(db, get_settings())
    user = await service.register(RegisterRequest(
        email="test@example.com",
        username="testuser",
        password="StrongPassword123!"
    ))
    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.role == "viewer"
    assert "StrongPassword" not in user.password_hash  # bcrypt hash

async def test_register_duplicate_email(db):
    service = AuthService(db, get_settings())
    data = RegisterRequest(email="dupe@example.com", username="u1", password="StrongPass123!")
    await service.register(data)
    with pytest.raises(HTTPException) as exc:
        await service.register(RegisterRequest(email="dupe@example.com", username="u2", password="StrongPass123!"))
    assert exc.value.status_code == 400

async def test_login_wrong_password(db):
    service = AuthService(db, get_settings())
    await service.register(RegisterRequest(email="u@e.com", username="u", password="StrongPass123!"))
    with pytest.raises(HTTPException) as exc:
        await service.login(LoginRequest(email="u@e.com", password="WrongPassword!"), ip="127.0.0.1")
    assert exc.value.status_code == 401

async def test_verify_token_valid(db):
    service = AuthService(db, get_settings())
    user = await service.register(RegisterRequest(email="v@e.com", username="v", password="StrongPass123!"))
    token, _ = await service.login(LoginRequest(email="v@e.com", password="StrongPass123!"), ip="127.0.0.1")
    verified = await service.verify_token(token)
    assert verified.id == user.id

async def test_weak_password_rejected(db):
    service = AuthService(db, get_settings())
    with pytest.raises(Exception):  # ValidationError or HTTPException
        await service.register(RegisterRequest(email="x@e.com", username="x", password="short"))
```

### 3.3 Audit Log Hash Chain Tests

```python
# tests/unit/test_audit_hash_chain.py

async def test_hash_chain_integrity(db):
    audit = AuditService(db)
    # Insert 10 entries
    for i in range(10):
        await audit.log(
            event_type="auth",
            action=f"test.action.{i}",
            outcome="success",
            user_id=None,
        )
    # Verify chain
    result = await audit.verify_chain()
    assert result.verified is True
    assert result.entries_checked == 10

async def test_hash_chain_detects_tampering(db):
    audit = AuditService(db)
    await audit.log("auth", "test.login", "success", user_id=None)
    await audit.log("auth", "test.logout", "success", user_id=None)

    # Simulate tampering: change outcome of first entry
    # (In production this is prevented; here we test detection)
    await db.execute(text("UPDATE audit_logs SET outcome='failure' WHERE sequence_num=1"))
    await db.commit()

    result = await audit.verify_chain()
    assert result.verified is False
    assert result.first_error_at_sequence == 1

async def test_genesis_entry_prev_hash():
    """First entry must have prev_hash = 'GENESIS'."""
    from utils.hash_chain import compute_hash, GENESIS_HASH
    entry_hash = compute_hash(1, "timestamp", None, "auth.login", "success", GENESIS_HASH)
    assert len(entry_hash) == 64  # SHA-256 hex
```

### 3.4 Text Chunker Tests

```python
# tests/unit/test_chunker.py

def test_basic_chunking():
    chunker = TextChunker()
    text = "word " * 2000  # ~10000 chars
    chunks = chunker.chunk(text, chunk_size=512, overlap=50)
    assert len(chunks) > 1
    # Each chunk under size limit
    for chunk in chunks:
        assert chunk.token_count <= 600  # some tolerance

def test_overlap():
    chunker = TextChunker()
    text = "sentence one. " * 100
    chunks = chunker.chunk(text, chunk_size=100, overlap=20)
    if len(chunks) >= 2:
        # Overlap: end of chunk N should appear in start of chunk N+1
        end_of_first = chunks[0].content[-80:]
        start_of_second = chunks[1].content[:80:]
        # Some text should be shared
        assert any(word in start_of_second for word in end_of_first.split()[-5:])

def test_empty_text():
    chunker = TextChunker()
    chunks = chunker.chunk("", chunk_size=512)
    assert len(chunks) == 0

def test_single_paragraph():
    chunker = TextChunker()
    text = "This is a short paragraph."
    chunks = chunker.chunk(text, chunk_size=512)
    assert len(chunks) == 1
    assert chunks[0].content == text
```

### 3.5 File Validator Tests

```python
# tests/unit/test_file_validator.py

def test_valid_pdf():
    validator = FileValidator()
    # Use actual PDF magic bytes
    pdf_header = b"%PDF-1.4 test content"
    with patch("magic.from_buffer", return_value="application/pdf"):
        name, mime = validator.validate("report.pdf", pdf_header, "application/pdf")
    assert mime == "application/pdf"

def test_oversized_file_rejected():
    validator = FileValidator()
    large_content = b"x" * (51 * 1024 * 1024)  # 51 MB
    with pytest.raises(ValueError, match="exceeds maximum size"):
        validator.validate("file.pdf", large_content, "application/pdf")

def test_path_traversal_in_filename():
    validator = FileValidator()
    safe_content = b"%PDF-1.4"
    with patch("magic.from_buffer", return_value="application/pdf"):
        name, _ = validator.validate("../../etc/passwd", safe_content, "application/pdf")
    # Filename sanitized to just the base name
    assert "/" not in name
    assert "\\" not in name

def test_disallowed_mime_type():
    validator = FileValidator()
    with patch("magic.from_buffer", return_value="application/x-executable"):
        with pytest.raises(ValueError, match="not allowed"):
            validator.validate("malware.exe", b"MZ", "application/octet-stream")
```

### 3.6 Tool Registry Tests

```python
# tests/unit/test_tool_registry.py

def test_all_tools_have_schemas():
    registry = ToolRegistry()
    for name, tool in registry._tools.items():
        assert tool.input_schema is not None, f"{name} missing input schema"
        assert tool.risk_level in ["low", "medium", "high", "critical"]

def test_http_tool_disabled_by_default():
    registry = ToolRegistry()
    http_tool = registry._tools.get("http_request")
    assert http_tool is not None
    assert http_tool.enabled is False

def test_path_traversal_in_file_read():
    from tools.file_read import FileReadInput
    with pytest.raises(ValueError):
        FileReadInput(path="../../etc/passwd")

def test_tool_list_for_prompt_excludes_disabled():
    registry = ToolRegistry()
    prompt = registry.get_tool_list_for_prompt()
    assert "http_request" not in prompt  # disabled by default

def test_tool_permission_check():
    registry = ToolRegistry()
    assert registry.is_permitted("file_read", "analyst")
    assert registry.is_permitted("file_read", "admin")
    assert not registry.is_permitted("file_read", "viewer")
```

---

## 4. Backend Integration Tests

### 4.1 API Integration Test Setup

```python
# tests/integration/conftest.py
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db, Base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

@pytest_asyncio.fixture
async def test_app():
    # Create in-memory DB for integration tests
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession)

    async def override_get_db():
        async with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()
    await test_engine.dispose()

@pytest_asyncio.fixture
async def client(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def auth_client(client):
    """Client with a logged-in analyst user."""
    # Register + login
    await client.post("/api/v1/auth/register", json={
        "email": "test@test.com", "username": "testuser", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "test@test.com", "password": "StrongPass123!"
    })
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
```

### 4.2 Auth Flow Integration Tests

```python
# tests/integration/test_auth.py

async def test_register_and_login(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "new@test.com", "username": "newuser", "password": "SecurePass123!"
    })
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@test.com"

    resp = await client.post("/api/v1/auth/login", json={
        "email": "new@test.com", "password": "SecurePass123!"
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()

async def test_protected_endpoint_requires_auth(client):
    resp = await client.get("/api/v1/chat/conversations")
    assert resp.status_code == 403 or resp.status_code == 401

async def test_viewer_cannot_upload_document(auth_client):
    # auth_client has viewer role by default
    resp = await auth_client.post("/api/v1/documents/upload",
        files={"file": ("test.txt", b"test content", "text/plain")},
        data={"kb_id": "some-id", "run_ocr": "false"}
    )
    assert resp.status_code == 403

async def test_get_current_user(auth_client):
    resp = await auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@test.com"
```

### 4.3 Document Processing Integration Tests

```python
# tests/integration/test_documents.py (with mocked Ollama and Qdrant)

async def test_document_upload_creates_pending_record(analyst_client):
    txt_content = b"This is a test document with content."
    resp = await analyst_client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.txt", txt_content, "text/plain")},
        data={"kb_id": test_kb_id, "run_ocr": "false"},
    )
    assert resp.status_code == 202
    doc = resp.json()
    assert doc["status"] == "pending"
    assert doc["original_name"] == "test.txt"

async def test_document_status_polling(analyst_client):
    # Upload and wait for processing (with mocked services)
    doc_id = (await upload_test_document(analyst_client))["id"]
    # Poll up to 10 times
    for _ in range(10):
        await asyncio.sleep(0.5)
        resp = await analyst_client.get(f"/api/v1/documents/{doc_id}")
        if resp.json()["status"] in ("indexed", "failed"):
            break
    assert resp.json()["status"] == "indexed"
```

### 4.4 Knowledge Base Query Integration Tests

```python
async def test_kb_query_returns_sources(analyst_client, seeded_kb):
    resp = await analyst_client.post(
        f"/api/v1/knowledge-bases/{seeded_kb}/query",
        json={"query": "test query", "top_k": 3, "generate_answer": False}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert "answer" in data  # may be None if generate_answer=False

async def test_kb_query_empty_result_no_crash(analyst_client, empty_kb):
    resp = await analyst_client.post(
        f"/api/v1/knowledge-bases/{empty_kb}/query",
        json={"query": "irrelevant query", "top_k": 5}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sources"] == []
    assert data["low_confidence"] is True
```

---

## 5. Security Tests

### 5.1 Authentication Security Tests

| Test | Expected Result |
|------|----------------|
| Login with wrong password | 401 |
| Login with non-existent email | 401 |
| Access protected endpoint without token | 401 |
| Access protected endpoint with expired token | 401 |
| Access admin endpoint with analyst token | 403 |
| Use refresh token as access token | 401 |
| Request 6 login attempts with wrong password | 5th returns 401, 6th returns 429 |

### 5.2 Input Validation Security Tests

| Test | Expected Result |
|------|----------------|
| Upload file with path traversal in filename | Filename sanitized; no traversal |
| Upload `.exe` file disguised as PDF | 422 (MIME mismatch detected) |
| Upload file > 50 MB | 413 or 422 |
| File read tool with `../../etc/passwd` | ValidationError; 422 |
| SQL injection in query param | 422 (Pydantic validation) |
| KB query with 10,000 character query | 422 (max 2000 chars) |

### 5.3 Agent Security Tests

| Test | Expected Result |
|------|----------------|
| Agent proposes `file_delete` | Approval request created; execution blocked pending approval |
| Agent proposes `http_request` | Tool not available (disabled); returned as error |
| Agent proposes non-existent tool | Error returned; agent continues |
| Document with injection text uploaded | OCR processes text; injection pattern logged in audit; no tool called |
| Agent run exceeds max iterations | Run terminated with partial result |

### 5.4 SAST (Static Analysis)

```bash
# Run bandit static security analysis
bandit -r backend/ -ll -f json -o security_report.json

# Key checks:
# B105: hardcoded password (must be 0 findings)
# B106: hardcoded password in function argument (must be 0)
# B108: probable insecure /tmp usage (review)
# B201: flask debug mode — not applicable
# B301: pickle (must be 0 findings)
# B324: md5 or sha1 for security purposes (must be 0)
```

---

## 6. Performance Tests

### 6.1 API Response Time Targets

Test with a tool like `locust` or manual timing with `curl` against a local Docker Compose deployment.

| Endpoint | Target P95 |
|----------|-----------|
| `GET /api/v1/system/health` | < 50ms |
| `GET /api/v1/auth/me` | < 100ms |
| `POST /api/v1/auth/login` | < 400ms (bcrypt ≈ 250ms) |
| `GET /api/v1/chat/conversations` | < 200ms |
| `POST /api/v1/knowledge-bases/{id}/query` (no LLM) | < 500ms |
| `GET /api/v1/audit/logs` (50 rows) | < 300ms |

### 6.2 Resource Usage Targets

On minimum hardware (8 GB RAM, 4 CPU cores):
- At rest (no active requests): < 2 GB RAM
- During chat with `llama3.2:3b`: < 6 GB RAM total
- During document processing: < 3 GB RAM (excluding model)
- CPU at rest: < 5%
- CPU during LLM generation: 70-100% (expected; single-threaded inference)

---

## 7. Manual Acceptance Test Checklist

This checklist directly maps to PRD §9 Acceptance Criteria.

### AC-01: Cold Start
- [ ] Run `docker compose up` on a clean machine
- [ ] All services healthy within 60 seconds
- [ ] Dashboard shows green health indicators

### AC-02: User Registration and Login
- [ ] Register new user (email, username, password)
- [ ] Login with correct credentials → dashboard loads
- [ ] Login with wrong password → error shown
- [ ] Session persists on page refresh

### AC-03: Chat with Streaming
- [ ] Select a model from dropdown
- [ ] Send a message
- [ ] Response streams token-by-token
- [ ] "Processing locally" indicator visible
- [ ] Conversation saved in history

### AC-04: Document Upload and Processing
- [ ] Upload a PDF document
- [ ] Processing steps visible: extraction → OCR → chunking → embedding → indexed
- [ ] Document status shows "Indexed" when complete
- [ ] Upload an image → OCR runs

### AC-05: Knowledge Base Query with Citations
- [ ] Create knowledge base
- [ ] Upload documents
- [ ] Ask a question
- [ ] Answer received with source citations
- [ ] Citations show filename and page number

### AC-06: Agent with File Analysis
- [ ] Create a CSV file in workspace
- [ ] Start agent with goal: "analyze the CSV and summarize"
- [ ] Agent uses `file_read` tool
- [ ] Agent uses `python_exec` tool (in sandbox)
- [ ] Final result returned

### AC-07: Approval Workflow
- [ ] Start agent that will attempt `file_delete`
- [ ] Approval request appears in Approvals page
- [ ] Approve the request
- [ ] Agent execution continues
- [ ] Approval event appears in audit log

### AC-08: Audit Log
- [ ] All actions from AC-02 through AC-07 appear in audit log
- [ ] Each event has timestamp, user, action, outcome
- [ ] Audit integrity check returns ✓ verified
- [ ] Audit log export (CSV) downloads correctly

### AC-09: Minimum Hardware
- [ ] All above tests pass on machine with 8 GB RAM and 4 CPU cores
- [ ] System Dashboard shows RAM usage < 6 GB during demo
- [ ] No OOM kills or crashes

### AC-10: Offline Operation
- [ ] Disconnect internet
- [ ] All features still work (chat, RAG, agent, document upload)
- [ ] Dashboard shows all services green

---

## 8. Test Execution Commands

```bash
# Run all unit tests
cd backend
pytest tests/unit/ -v --tb=short

# Run with coverage
pytest tests/unit/ --cov=services --cov=tools --cov=utils --cov-report=term-missing

# Run integration tests (requires Docker Compose running)
pytest tests/integration/ -v --tb=short

# Run security static analysis
bandit -r backend/ -ll

# Run a specific test file
pytest tests/unit/test_auth_service.py -v

# Run tests matching a pattern
pytest -k "test_hash_chain" -v
```

---

## 9. Known Test Limitations

| Limitation | Impact | Notes |
|------------|--------|-------|
| PaddleOCR not tested in unit tests | OCR logic tested manually | PaddleOCR requires heavy deps; mock in unit tests |
| LLM responses not deterministic | Agent tests use mocked LLMClient | Integration tests with real Ollama run manually |
| Sandbox tests require Docker | Unit tests mock Docker SDK | Integration sandbox tests run in full Docker Compose |
| Full RAG pipeline not unit tested | Integration test covers it | Qdrant and Ollama mocked in unit tests |

---

## 10. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial Testing & QA Plan |

---

*End of Testing & QA Plan*
