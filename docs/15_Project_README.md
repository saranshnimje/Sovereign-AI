# 15 README
## Sovereign AI Workbench

**Version:** 1.0
**Classification:** Internal - SIH 2026 Prototype

---

# Sovereign AI Workbench

**AI capabilities without giving your data away.**

Sovereign AI Workbench is a privacy-first, on-premise AI platform for organizations that need to use modern AI without sending sensitive data to external cloud services. Everything runs locally — models, documents, embeddings, and AI reasoning all stay within your infrastructure.

---

## What It Does

| Capability | Description |
|-----------|-------------|
| 💬 **Local AI Chat** | Chat with locally running LLMs via Ollama. Streaming responses. No cloud. |
| 📄 **Document Processing** | Upload PDFs, DOCX, images, CSVs. OCR for scanned documents. |
| 🧠 **Knowledge Base RAG** | Index documents into a local vector database. Ask questions, get answers with source citations. |
| 🤖 **AI Agents** | Agents that plan, select tools, execute tasks, and synthesize results. |
| 🔧 **Controlled Tools** | File operations, Python execution, knowledge base search — all with permission levels. |
| 🐳 **Docker Sandbox** | Untrusted code runs in isolated containers with CPU/memory/network limits. |
| ✅ **Human Approval** | High-risk operations (file deletion, system modification) require explicit admin approval. |
| 📋 **Audit Logging** | Tamper-evident, hash-chained log of all AI actions, tool calls, and approvals. |
| 🔒 **RBAC** | Role-based access control (Admin / Analyst / Viewer) on all endpoints. |

---

## Quick Start

### Prerequisites

- [Docker Desktop 24+](https://www.docker.com/products/docker-desktop/) or Docker Engine + Compose v2
- [Ollama](https://ollama.ai) installed and running on the host
- 8 GB RAM minimum (16 GB recommended)
- 50 GB free disk space

### 1. Pull Required Models (one-time, requires internet)

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 2. Clone and Set Up

```bash
git clone <repo-url>
cd sovereign-ai-workbench
bash scripts/setup.sh
```

This will:
- Generate a `.env` file with a random `SECRET_KEY`
- Pull the Docker sandbox base image
- Verify Ollama is reachable

### 3. Start the Stack

```bash
docker compose up --build -d
```

Wait ~60 seconds for all services to start. Check health:

```bash
curl http://localhost/api/v1/system/health
# {"status": "ok"}
```

### 4. Open in Browser

Navigate to **http://localhost**

The first time you run the system, a setup wizard will guide you through creating the admin account and configuring the default models.

---

## Architecture Overview

```
Browser
  └── React Frontend (nginx)
        └── FastAPI Backend
              ├── SQLite (local volume)
              ├── Qdrant (vector database, local container)
              ├── Ollama (LLM inference, runs on host)
              └── Docker Engine (sandbox containers)
```

All components run locally. No data leaves your machine during AI processing.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, Tailwind CSS |
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Database | SQLite (via SQLAlchemy async) |
| Vector DB | Qdrant |
| LLM Inference | Ollama |
| OCR | PaddleOCR |
| Sandbox | Docker SDK |
| Auth | JWT (HS256), bcrypt |
| Deployment | Docker Compose |

---

## Project Structure

```
sovereign-ai-workbench/
├── backend/           FastAPI application
├── frontend/          React application
├── scripts/           Setup, backup, model pull utilities
├── docs/              Full documentation (15 documents)
│   ├── 01_PRD.md
│   ├── 02_TRD.md
│   ├── 03_System_Architecture.md
│   ├── 04_App_User_Flow.md
│   ├── 05_UI_UX_Specification.md
│   ├── 06_Backend_Database_API.md
│   ├── 07_AI_ML_Design.md
│   ├── 08_Security_Privacy.md
│   ├── 09_Implementation_Plan.md
│   ├── 10_Testing_QA_Plan.md
│   ├── 11_Deployment_DevOps.md
│   ├── 12_Risk_Mitigation.md
│   ├── 13_Requirements_Traceability.md
│   ├── 14_User_Guide.md
│   └── 15_README.md
├── docker-compose.yml
├── docker-compose.dev.yml
└── .env.example
```

---

## Environment Variables

Copy `.env.example` to `.env` and set:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | **Yes** | JWT signing secret (min 32 chars). Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `OLLAMA_URL` | No | Ollama endpoint. Default: `http://host.docker.internal:11434` |
| `MAX_UPLOAD_SIZE_MB` | No | Max file upload. Default: `50` |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING`. Default: `INFO` |

See `.env.example` for the full list.

---

## Development

```bash
# Hot-reload dev mode
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# API docs available at
open http://localhost:8000/api/docs

# Run backend tests
cd backend && pytest tests/ -v

# Run static security analysis
bandit -r backend/ -ll
```

---

## Recommended Models

| Role | Model | RAM | Command |
|------|-------|-----|---------|
| Chat (minimum) | `llama3.2:3b` | ~3 GB | `ollama pull llama3.2:3b` |
| Chat (better) | `mistral:7b-q4` | ~5 GB | `ollama pull mistral:7b-q4` |
| Embedding | `nomic-embed-text` | ~0.5 GB | `ollama pull nomic-embed-text` |
| Vision (optional) | `llava:7b-q4` | ~5 GB | `ollama pull llava:7b-q4` |

---

## Security

- All AI processing is on-premise — no cloud API calls for core functionality
- JWT authentication with refresh token rotation
- Role-based access control (Admin / Analyst / Viewer)
- Docker sandbox with dropped capabilities, no network, non-root user
- Tamper-evident audit log with SHA-256 hash chain
- All tool calls validated by Pydantic before execution
- High-risk operations require explicit human approval
- See [docs/08_Security_Privacy.md](08_Security_Privacy.md) for the full security model

---

## Documentation

| Document | Description |
|----------|-------------|
| [01 PRD](01_PRD.md) | Product requirements, user stories, acceptance criteria |
| [02 TRD](02_TRD.md) | Technical requirements, API specs, data models |
| [03 System Architecture](03_System_Architecture.md) | Component diagrams, data flows, service design |
| [04 App/User Flow](04_App_User_Flow.md) | User journeys and state transitions |
| [05 UI/UX Specification](05_UI_UX_Specification.md) | Design system, component library, accessibility |
| [06 Backend/Database/API](06_Backend_Database_API.md) | Full API reference, ORM models, service patterns |
| [07 AI/ML Design](07_AI_ML_Design.md) | LLM integration, RAG pipeline, agent architecture |
| [08 Security & Privacy](08_Security_Privacy.md) | Threat model, security controls, privacy design |
| [09 Implementation Plan](09_Implementation_Plan.md) | Phased delivery plan, task breakdown |
| [10 Testing & QA](10_Testing_QA_Plan.md) | Unit tests, integration tests, acceptance criteria |
| [11 Deployment & DevOps](11_Deployment_DevOps.md) | Docker Compose, Dockerfiles, backup, troubleshooting |
| [12 Risk & Mitigation](12_Risk_Mitigation.md) | Risk register, contingency plans |
| [13 Requirements Traceability](13_Requirements_Traceability.md) | Requirements → implementation → test mapping |
| [14 User Guide](14_User_Guide.md) | End-user documentation |
| [15 README](15_README.md) | This document |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Ollama not reachable | Ensure Ollama is running: `ollama serve` |
| Backend won't start | Check `.env` has `SECRET_KEY` set |
| Models not listed | Check `OLLAMA_URL` in `.env`; test with `curl http://localhost:11434/api/tags` |
| Docker sandbox fails | Ensure Docker socket is accessible; check Docker is running |
| Slow LLM responses | CPU inference is slow; first request loads model (~10-30s) |
| Port conflicts | Change ports in `docker-compose.yml` |

Full troubleshooting guide: [docs/11_Deployment_DevOps.md](11_Deployment_DevOps.md)

---

## Future Scope

These features are architecturally planned but out of scope for the SIH prototype:

- PostgreSQL migration (swap `DATABASE_URL` env var)
- Multi-agent orchestration
- Kubernetes deployment
- Model fine-tuning pipeline
- Federated knowledge bases
- LDAP/SAML user authentication
- Plugin marketplace for custom tools

---

## License

Internal project — SIH 2026 Prototype. All rights reserved by the developing team.

---

## Contact

For deployment support or questions, contact the system administrator.

---

*Sovereign AI Workbench — Privacy-first AI for organizations that need control.*
