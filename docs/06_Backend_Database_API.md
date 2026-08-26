# 06 Backend, Database & API
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0, 03_System_Architecture.md v1.0

---

## 1. Purpose

This document provides complete backend implementation specifications including:
- FastAPI application structure and configuration
- SQLAlchemy ORM models (full implementation detail)
- Pydantic schemas for every API endpoint
- Complete API endpoint specifications with request/response contracts
- Service layer implementation patterns
- Error handling conventions
- Database migration strategy

---

## 2. FastAPI Application Bootstrap

### 2.1 Application Factory (`main.py`)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import init_db
from middleware import (
    RequestIDMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from routers import (
    auth, chat, models, documents, knowledge_bases,
    agents, tools, approvals, audit, system
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    await init_db()          # create tables if not exists
    yield
    # Shutdown (cleanup if needed)

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Sovereign AI Workbench API",
        version="1.0.0",
        docs_url="/api/docs",          # disable in production
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Middleware (applied in reverse order of listing)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Routers
    prefix = "/api/v1"
    app.include_router(auth.router,            prefix=f"{prefix}/auth")
    app.include_router(chat.router,            prefix=f"{prefix}/chat")
    app.include_router(models.router,          prefix=f"{prefix}/models")
    app.include_router(documents.router,       prefix=f"{prefix}/documents")
    app.include_router(knowledge_bases.router, prefix=f"{prefix}/knowledge-bases")
    app.include_router(agents.router,          prefix=f"{prefix}/agents")
    app.include_router(tools.router,           prefix=f"{prefix}/tools")
    app.include_router(approvals.router,       prefix=f"{prefix}/approvals")
    app.include_router(audit.router,           prefix=f"{prefix}/audit")
    app.include_router(system.router,          prefix=f"{prefix}/system")

    return app

app = create_app()
```

### 2.2 Settings (`config.py`)

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Core
    secret_key: str
    database_url: str = "sqlite+aiosqlite:////app/data/sqlite/sovereign.db"
    qdrant_url: str = "http://qdrant:6333"
    ollama_url: str = "http://host.docker.internal:11434"
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"

    # Auth
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_min: int = 60
    jwt_refresh_ttl_days: int = 7

    # Uploads
    max_upload_size_mb: int = 50
    upload_dir: str = "/app/data/uploads"
    allowed_mime_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/webp",
    ]

    # RAG
    default_embedding_model: str = "nomic-embed-text"
    default_chunk_size: int = 512
    default_chunk_overlap: int = 50
    default_top_k: int = 5
    default_score_threshold: float = 0.6
    embedding_batch_size: int = 32

    # Agent
    default_max_iterations: int = 10
    default_approval_risk_level: str = "high"
    approval_timeout_minutes: int = 5

    # Sandbox
    sandbox_image: str = "python:3.11-slim"
    sandbox_timeout_s: int = 30
    sandbox_mem_limit_mb: int = 256
    sandbox_cpu_quota: int = 50000
    sandbox_workspace: str = "/app/data/sandbox_workspace"

    # Audit
    audit_retention_days: int = 365

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## 3. Database Layer

### 3.1 Async Engine Setup (`database.py`)

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},  # SQLite
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def init_db():
    """Create all tables on startup. Alembic handles migrations in production."""
    # Enable WAL mode for SQLite concurrency
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await Base.metadata.create_all(conn)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

### 3.2 ORM Models

#### `models/base.py`
```python
import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database import Base

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

def generate_uuid() -> str:
    return str(uuid.uuid4())
```

#### `models/user.py`
```python
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, generate_uuid

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="user")
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(back_populates="owner")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

#### `models/conversation.py`
```python
class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="truncate")

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user|assistant|system|tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
```

#### `models/knowledge_base.py`
```python
class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    qdrant_collection: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner: Mapped["User"] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    kb_id: Mapped[str] = mapped_column(
        String, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    uploader_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)       # stored name (UUID prefix)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)  # user's original filename
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
```

#### `models/agent.py`
```python
class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    plan_json: Mapped[str | None] = mapped_column("plan", Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    user: Mapped["User"] = relationship(back_populates="agent_runs")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="agent_run"
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    agent_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_json: Mapped[str] = mapped_column("input_data", Text, nullable=False)
    output_json: Mapped[str | None] = mapped_column("output_data", Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sandbox_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    agent_run: Mapped["AgentRun"] = relationship(back_populates="tool_calls")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    agent_run_id: Mapped[str | None] = mapped_column(String, ForeignKey("agent_runs.id"), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String, ForeignKey("tool_calls.id"), nullable=True)
    requester_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_detail_json: Mapped[str] = mapped_column("operation_detail", Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    agent_run: Mapped["AgentRun"] = relationship(back_populates="approval_requests")
```

#### `models/audit.py`
```python
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    sequence_num: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
```

---

## 4. Pydantic Schemas

### 4.1 Auth Schemas (`schemas/auth.py`)

```python
from pydantic import BaseModel, EmailStr, field_validator
import re

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", v):
            raise ValueError("Username must be 3-50 chars: letters, numbers, underscores only")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

### 4.2 Chat Schemas (`schemas/chat.py`)

```python
class ConversationCreate(BaseModel):
    model_name: str
    title: str | None = None
    system_prompt: str | None = None


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    model_name: str
    system_prompt: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    content: str
    model_name: str | None = None       # override conversation model
    rag_kb_ids: list[str] | None = None # knowledge bases to include

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message content cannot be empty")
        if len(v) > 32000:
            raise ValueError("Message too long (max 32000 chars)")
        return v


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    token_count: int | None
    created_at: datetime
    metadata: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse] = []
```

### 4.3 Document Schemas (`schemas/document.py`)

```python
class ProcessingStep(BaseModel):
    step: str
    status: str     # pending | running | done | failed | skipped
    duration_ms: int | None = None
    detail: str | None = None


class DocumentResponse(BaseModel):
    id: str
    kb_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    status: str
    page_count: int | None
    chunk_count: int
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentStatusResponse(DocumentResponse):
    processing_steps: list[ProcessingStep] = []
```

### 4.4 Knowledge Base Schemas (`schemas/knowledge_base.py`)

```python
class KBCreate(BaseModel):
    name: str
    description: str | None = None
    embedding_model: str | None = None  # uses default if None


class KBResponse(BaseModel):
    id: str
    name: str
    description: str | None
    embedding_model: str
    doc_count: int
    chunk_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KBQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    score_threshold: float = 0.6
    include_sources: bool = True
    generate_answer: bool = True
    model_name: str | None = None

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty")
        if len(v) > 2000:
            raise ValueError("Query too long (max 2000 chars)")
        return v

    @field_validator("top_k")
    @classmethod
    def valid_top_k(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("top_k must be between 1 and 20")
        return v


class KBQuerySource(BaseModel):
    chunk_id: str
    doc_id: str
    filename: str
    page_number: int | None
    content: str
    score: float


class KBQueryResponse(BaseModel):
    answer: str | None
    sources: list[KBQuerySource]
    query_embedding_ms: int
    retrieval_ms: int
    generation_ms: int | None
    low_confidence: bool = False
```

### 4.5 Agent Schemas (`schemas/agent.py`)

```python
class AgentRunCreate(BaseModel):
    goal: str
    model_name: str | None = None
    allowed_tools: list[str] | None = None
    kb_ids: list[str] | None = None
    max_iterations: int = 10

    @field_validator("goal")
    @classmethod
    def goal_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Agent goal cannot be empty")
        if len(v) > 5000:
            raise ValueError("Goal too long (max 5000 chars)")
        return v

    @field_validator("max_iterations")
    @classmethod
    def valid_iterations(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("max_iterations must be 1-20")
        return v


class AgentRunResponse(BaseModel):
    id: str
    goal: str
    status: str
    step_count: int
    iteration_count: int
    result: str | None
    error_message: str | None
    model_name: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolCallResponse(BaseModel):
    id: str
    step_number: int
    tool_name: str
    input_data: dict
    output_data: dict | None
    status: str
    duration_ms: int | None
    sandbox_used: bool
    created_at: datetime


class AgentRunDetail(AgentRunResponse):
    plan: list[dict] | None = None
    tool_calls: list[ToolCallResponse] = []
```

### 4.6 Approval Schemas (`schemas/approval.py`)

```python
class ApprovalResponse(BaseModel):
    id: str
    operation: str
    risk_level: str
    status: str
    requester_id: str
    operation_detail: dict
    agent_run_id: str | None
    expires_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalDecision(BaseModel):
    note: str | None = None


class ApprovalReject(BaseModel):
    note: str  # required for rejection
```

### 4.7 Audit Schemas (`schemas/audit.py`)

```python
class AuditLogResponse(BaseModel):
    id: str
    sequence_num: int
    timestamp: datetime
    user_id: str | None
    event_type: str
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    ip_address: str | None
    metadata: dict | None

    model_config = ConfigDict(from_attributes=True)


class AuditLogFilter(BaseModel):
    event_type: str | None = None
    user_id: str | None = None
    outcome: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = 50
    offset: int = 0

    @field_validator("limit")
    @classmethod
    def valid_limit(cls, v: int) -> int:
        return min(v, 500)


class AuditVerifyResponse(BaseModel):
    verified: bool
    entries_checked: int
    first_error_at_sequence: int | None = None
    message: str
```

---

## 5. Service Layer Patterns

### 5.1 AuthService

```python
class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.pwd_context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12)

    async def register(self, data: RegisterRequest) -> User:
        # Check for existing email/username
        existing = await self.db.execute(
            select(User).where(
                (User.email == data.email) | (User.username == data.username)
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Email or username already registered")

        # Check password against common password list
        if data.password.lower() in COMMON_PASSWORDS:
            raise HTTPException(400, "Password too common")

        user = User(
            email=data.email,
            username=data.username,
            password_hash=self.pwd_context.hash(data.password),
            role="viewer",  # default role; admin promotes
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def login(self, data: LoginRequest, ip: str) -> tuple[str, str]:
        user = await self._get_user_by_email(data.email)
        if not user or not self.pwd_context.verify(data.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        if not user.is_active:
            raise HTTPException(403, "Account is disabled")

        user.last_login = datetime.utcnow()
        access_token = self._create_access_token(user.id)
        refresh_token = await self._create_refresh_token(user.id)
        return access_token, refresh_token

    def _create_access_token(self, user_id: str) -> str:
        expire = datetime.utcnow() + timedelta(minutes=self.settings.jwt_access_ttl_min)
        return jwt.encode(
            {"sub": user_id, "exp": expire, "type": "access"},
            self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

    async def verify_token(self, token: str) -> User:
        try:
            payload = jwt.decode(
                token, self.settings.secret_key,
                algorithms=[self.settings.jwt_algorithm]
            )
        except JWTError:
            raise HTTPException(401, "Invalid token")
        if payload.get("type") != "access":
            raise HTTPException(401, "Wrong token type")
        user = await self._get_user_by_id(payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(401, "User not found or inactive")
        return user
```

### 5.2 DocumentService (Processing Pipeline)

```python
class DocumentService:
    PROCESSING_STEPS = [
        "validation", "extraction", "ocr", "cleaning", "chunking",
        "embedding", "indexing"
    ]

    async def process_document(self, doc_id: str):
        doc = await self._get_document(doc_id)
        await self._update_status(doc_id, "processing")

        try:
            # Step 1: Extract text
            await self._update_step(doc_id, "extraction", "running")
            text, page_count = await self._extract_text(doc)
            await self._update_step(doc_id, "extraction", "done")

            # Step 2: OCR (if needed)
            if doc.mime_type in ("image/png", "image/jpeg") or \
               (doc.mime_type == "application/pdf" and not text.strip()):
                await self._update_step(doc_id, "ocr", "running")
                ocr_text = await self.ocr_service.process(doc.storage_path, doc.mime_type)
                text = text + "\n" + ocr_text if text else ocr_text
                await self._update_step(doc_id, "ocr", "done")
            else:
                await self._update_step(doc_id, "ocr", "skipped")

            # Step 3: Clean
            await self._update_step(doc_id, "cleaning", "running")
            text = self._clean_text(text)
            await self._update_step(doc_id, "cleaning", "done")

            # Step 4: Chunk
            await self._update_step(doc_id, "chunking", "running")
            kb = await self._get_kb(doc.kb_id)
            chunks = self.chunker.chunk(text, chunk_size=512, overlap=50)
            await self._update_step(doc_id, "chunking", "done")

            # Step 5: Embed
            await self._update_step(doc_id, "embedding", "running")
            embeddings = await self.embedding_service.embed_batch(
                [c.content for c in chunks],
                model=kb.embedding_model,
            )
            await self._update_step(doc_id, "embedding", "done")

            # Step 6: Index to Qdrant
            await self._update_step(doc_id, "indexing", "running")
            points = [
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embeddings[i],
                    payload={
                        "doc_id": doc_id,
                        "kb_id": doc.kb_id,
                        "chunk_index": i,
                        "content": chunks[i].content,
                        "page_number": chunks[i].page_number,
                        "filename": doc.original_name,
                        "created_at": datetime.utcnow().isoformat(),
                    }
                )
                for i, _ in enumerate(chunks)
            ]
            await self.qdrant_client.upsert(
                collection_name=kb.qdrant_collection,
                points=points,
            )
            await self._update_step(doc_id, "indexing", "done")

            # Finalize
            await self._update_status(doc_id, "indexed", page_count=page_count, chunk_count=len(chunks))
            await self._update_kb_counts(doc.kb_id, doc_delta=1, chunk_delta=len(chunks))
            await self.audit_service.log("document", "document.indexed", "success",
                                         resource_id=doc_id, metadata={"chunks": len(chunks)})

        except Exception as e:
            await self._update_status(doc_id, "failed", error=str(e))
            await self.audit_service.log("document", "document.processing.failed", "failure",
                                         resource_id=doc_id, metadata={"error": str(e)})
            raise
```

---

## 6. API Endpoint Reference

### 6.1 Authentication Endpoints

**POST `/api/v1/auth/register`**
- Request: `RegisterRequest`
- Response 201: `UserResponse`
- Response 400: duplicate email/username or weak password
- No auth required

**POST `/api/v1/auth/login`**
- Request: `LoginRequest`
- Response 200: `TokenResponse`
- Sets `refresh_token` httpOnly cookie
- Response 401: invalid credentials
- Response 429: rate limited
- No auth required

**POST `/api/v1/auth/refresh`**
- Request: reads httpOnly cookie
- Response 200: `TokenResponse` (new access + refresh tokens)
- Response 401: expired or revoked refresh token
- Auth: httpOnly cookie

**POST `/api/v1/auth/logout`**
- Response 200: `{"message": "Logged out"}`
- Revokes refresh token; clears cookie
- Auth: Bearer

**GET `/api/v1/auth/me`**
- Response 200: `UserResponse`
- Auth: Bearer

---

### 6.2 Chat Endpoints

**GET `/api/v1/chat/conversations`**
- Query params: `limit=20`, `offset=0`
- Response 200: `list[ConversationResponse]`
- Auth: Bearer (own conversations only)

**POST `/api/v1/chat/conversations`**
- Request: `ConversationCreate`
- Response 201: `ConversationResponse`

**GET `/api/v1/chat/conversations/{id}`**
- Response 200: `ConversationDetail` (includes messages)
- Response 404: not found

**DELETE `/api/v1/chat/conversations/{id}`**
- Response 204: no content
- Deletes conversation and all messages

**POST `/api/v1/chat/conversations/{id}/messages`** ← SSE stream
- Request: `MessageCreate`
- Response: `text/event-stream` (SSE events defined in TRD §5.3)
- User message saved first; assistant message saved after stream completes

**GET `/api/v1/chat/conversations/{id}/export`**
- Query: `format=json|markdown`
- Response: file download

---

### 6.3 Model Endpoints

**GET `/api/v1/models`**
- Response 200: `list[ModelInfo]`
- Calls Ollama `/api/tags`; merges with DB role assignments

**GET `/api/v1/models/{model_name}`**
- Response 200: `ModelInfo`
- URL-encodes model names with colons (e.g. `llama3.2:3b` → path param handling)

**POST `/api/v1/models/pull`** [Admin]
- Request: `{"model_name": "mistral:7b-q4"}`
- Response 202: `{"job_id": "...", "model_name": "..."}`

**GET `/api/v1/models/pull/{model_name}/status`** [Admin] ← SSE
- Streams pull progress from Ollama

**PUT `/api/v1/models/roles`** [Admin]
- Request: `{"role": "chat", "model_name": "llama3.2:3b"}`
- Response 200: updated role mapping

**GET `/api/v1/models/health/{model_name}`**
- Sends test prompt; returns latency and status

---

### 6.4 Document Endpoints

**POST `/api/v1/documents/upload`** [Analyst+]
- Content-Type: `multipart/form-data`
- Fields: `file` (binary), `kb_id` (str), `run_ocr` (bool, default true)
- Response 202: `DocumentResponse` with status=pending

**GET `/api/v1/documents`**
- Query: `kb_id` (required or optional), `status`, `limit`, `offset`
- Response 200: `list[DocumentResponse]`

**GET `/api/v1/documents/{id}`**
- Response 200: `DocumentStatusResponse` (includes processing steps)

**DELETE `/api/v1/documents/{id}`** [Analyst+]
- Deletes file, Qdrant vectors, and DB record
- Response 204

---

### 6.5 Knowledge Base Endpoints

**POST `/api/v1/knowledge-bases`** [Analyst+]
- Request: `KBCreate`
- Response 201: `KBResponse`

**GET `/api/v1/knowledge-bases`**
- Response 200: `list[KBResponse]`

**GET `/api/v1/knowledge-bases/{id}`**
- Response 200: `KBResponse`

**DELETE `/api/v1/knowledge-bases/{id}`** [Admin]
- Deletes Qdrant collection, all documents, DB record
- Response 204

**POST `/api/v1/knowledge-bases/{id}/query`**
- Request: `KBQueryRequest`
- Response 200: `KBQueryResponse`

**POST `/api/v1/knowledge-bases/{id}/reindex`** [Admin]
- Clears Qdrant collection; re-processes all documents
- Response 202: `{"job_id": "...", "doc_count": N}`

---

### 6.6 Agent Endpoints

**POST `/api/v1/agents/runs`** [Analyst+]
- Request: `AgentRunCreate`
- Response 202: `AgentRunResponse`

**GET `/api/v1/agents/runs`**
- Query: `status`, `limit=20`, `offset=0`
- Response 200: `list[AgentRunResponse]`

**GET `/api/v1/agents/runs/{id}`**
- Response 200: `AgentRunDetail` (includes plan + tool calls)

**GET `/api/v1/agents/runs/{id}/stream`** ← SSE
- Streams agent execution events

**POST `/api/v1/agents/runs/{id}/cancel`** [Analyst+, own run or Admin]
- Response 200: `AgentRunResponse` with status=cancelled

---

### 6.7 Approval Endpoints

**GET `/api/v1/approvals/pending`** [Admin]
- Response 200: `list[ApprovalResponse]`

**GET `/api/v1/approvals/{id}`** [Admin]
- Response 200: `ApprovalResponse`

**POST `/api/v1/approvals/{id}/approve`** [Admin]
- Request: `ApprovalDecision` (note optional)
- Response 200: `ApprovalResponse`

**POST `/api/v1/approvals/{id}/reject`** [Admin]
- Request: `ApprovalReject` (note required)
- Response 200: `ApprovalResponse`

---

### 6.8 Audit Endpoints

**GET `/api/v1/audit/logs`** [Admin]
- Query: `event_type`, `user_id`, `outcome`, `start_date`, `end_date`, `limit`, `offset`
- Response 200: `{"items": list[AuditLogResponse], "total": int}`

**GET `/api/v1/audit/logs/{id}`** [Admin]
- Response 200: `AuditLogResponse` with full metadata

**GET `/api/v1/audit/export`** [Admin]
- Query: same filters as logs + `format=csv|json`
- Response: file download

**GET `/api/v1/audit/verify`** [Admin]
- Response 200: `AuditVerifyResponse`

---

### 6.9 System Endpoints

**GET `/api/v1/system/health`**
- No auth required
- Response 200: `{"status": "ok"}` if critical services up
- Response 503: if critical services down

**GET `/api/v1/system/status`**
- Auth: Bearer
- Response 200: `SystemStatus`
- Cached 5 seconds

**GET `/api/v1/system/resources`**
- Auth: Bearer
- Response 200: `ResourceMetrics`

---

## 7. Error Handling

### 7.1 Global Exception Handler

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = request.state.request_id
    logger.exception(f"Unhandled error [{trace_id}]: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "trace_id": trace_id,
        }}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {
            "code": exc.detail if isinstance(exc.detail, str) else "http_error",
            "message": exc.detail,
            "trace_id": getattr(request.state, "request_id", None),
        }}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {
            "code": "validation_error",
            "message": "Input validation failed",
            "details": exc.errors(),
            "trace_id": getattr(request.state, "request_id", None),
        }}
    )
```

### 7.2 Custom Exception Hierarchy

```python
class SovereignException(Exception):
    def __init__(self, message: str, code: str, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code

class ModelUnavailableError(SovereignException):
    def __init__(self, model: str):
        super().__init__(f"Model '{model}' is unavailable", "model_unavailable", 503)

class DocumentProcessingError(SovereignException):
    def __init__(self, reason: str):
        super().__init__(reason, "document_processing_error", 422)

class SandboxError(SovereignException):
    def __init__(self, reason: str):
        super().__init__(reason, "sandbox_error", 500)

class ApprovalTimeoutError(SovereignException):
    def __init__(self):
        super().__init__("Approval request timed out", "approval_timeout", 408)

class PermissionDeniedError(SovereignException):
    def __init__(self, action: str):
        super().__init__(f"Permission denied: {action}", "permission_denied", 403)
```

---

## 8. Database Migration Strategy

### 8.1 Alembic Setup

```
backend/
└── alembic/
    ├── env.py
    ├── script.py.mako
    └── versions/
        └── 001_initial_schema.py
```

`env.py` imports `Base` from `database.py` for autogenerate support.

### 8.2 Migration Commands

```bash
# Generate migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

### 8.3 PostgreSQL Migration Path

1. Set `DATABASE_URL=postgresql+asyncpg://user:pass@host/db`
2. Ensure asyncpg installed: `pip install asyncpg`
3. Run `alembic upgrade head`
4. No application code changes required

---

## 9. Dependency Injection Helpers (`dependencies.py`)

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    auth_service = AuthService(db, settings)
    return await auth_service.verify_token(credentials.credentials)


def require_role(*roles: str):
    async def _check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Requires one of roles: {roles}")
        return user
    return _check_role


# Convenience shortcuts
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_role("admin"))
AnalystRequired = Depends(require_role("analyst", "admin"))
```

---

## 10. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial Backend/Database/API document |

---

*End of Backend, Database & API*
