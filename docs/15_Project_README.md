# Sovereign AI Workbench v2.0

**Production-ready AI workbench with agentic execution, multi-provider LLM routing, RAG, human-in-the-loop approvals, persistent per-message agent timelines, and cloud/local deployment modes.**

## Download

### Git clone

```bash
git clone https://github.com/saranshnimje/Sovereign-AI.git
cd Sovereign-AI
```

### GitHub ZIP

1. Open https://github.com/saranshnimje/Sovereign-AI
2. Click **Code** → **Download ZIP**.
3. Extract the ZIP archive.
4. Open a terminal in the extracted `Sovereign-AI` directory.

Git clone is recommended for development because it makes future updates easy. ZIP download is suitable when Git is not installed.

## Production

| Component | Production |
|---|---|
| Frontend | https://sovereign-ai-workbench-2026.vercel.app/ |
| Backend | https://sovereign-ai-backend-ciy8.onrender.com |
| Database | Neon PostgreSQL |
| Vector DB | Qdrant Cloud |
| LLM | Configured cloud providers with failover |

## Docker installation

### Prerequisites

- Docker Desktop 24+ on Windows/macOS, or Docker Engine + Compose v2 on Linux
- 8 GB RAM minimum; 16 GB recommended for local LLM workloads
- 20 GB+ free disk space, plus model storage if using Ollama

### Setup

Download/clone the repository, then configure the environment:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Set a strong `SECRET_KEY` and configure provider/database/Qdrant settings as needed. Do not commit `.env`.

Start the application:

```bash
docker compose up --build -d
```

For hot-reload development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Health check:

```bash
curl http://localhost/api/v1/system/health
```

Open:

```text
http://localhost
```

Stop:

```bash
docker compose down
```

Do not use `docker compose down -v` unless you intentionally want to remove Docker-managed persistent volumes and their data.

## Non-Docker installation

Non-Docker mode runs the FastAPI backend and React/Vite frontend directly on the host.

### Prerequisites

- Python 3.11+
- Node.js 18+ (Node 20 LTS recommended)
- npm
- Qdrant local service or Qdrant Cloud
- Ollama only if local/self-hosted LLM inference is desired

### Backend

Windows PowerShell:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Linux/macOS:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend health endpoint:

```text
http://localhost:8000/api/v1/system/health
```

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite normally serves at:

```text
http://localhost:5173
```

Configure `VITE_API_URL` to point to the local backend, for example:

```text
VITE_API_URL=http://localhost:8000
```

Production frontend build:

```bash
npm run build
npm run preview
```

### Tests

Backend:

```bash
cd backend
pytest tests/ -v
```

Frontend:

```bash
cd frontend
npm run build
npm run lint
```

## Local Ollama

Ollama is optional and intended for local/self-hosted development. It is not a silent production fallback.

Install Ollama from https://ollama.com/ and pull models such as:

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

When using Docker Desktop, the backend can normally reach host Ollama through `http://host.docker.internal:11434`. Configure `OLLAMA_URL` if your environment uses another endpoint.

For production, configure cloud LLM providers instead of relying on local Ollama.

## Architecture

```text
                         ┌─────────────────────┐
                         │     User Browser     │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ React/Vite Frontend │
                         └──────────┬──────────┘
                                    │ REST + SSE
                         ┌──────────▼──────────┐
                         │    FastAPI Backend  │
                         └───┬──────┬──────┬───┘
                             │      │      │
                           DB     Qdrant   LLM providers
                         Neon/     Cloud    / Ollama local
                         SQLite
```

Production uses Vercel → Render → Neon + Qdrant Cloud + configured cloud LLM providers. Local Docker development can use SQLite, Docker Qdrant, and Ollama.

## Agent runtime

`UNDERSTAND → ROUTE → PLAN → REASON → EXECUTE → OBSERVE → VERIFY`

Each user message gets its own server-generated `run_id` and its own Agent Timeline. A conversation can therefore contain:

```text
User: hii
  Agent Timeline
    Agent started
    Response ready
    Completed
  Assistant response

User: who are you
  Agent Timeline
    Agent started
    Response ready
    Completed
  Assistant response
```

Timeline events are isolated by `run_id`. Assistant messages are persisted once, and the lifecycle guarantees `final_response` before `done` on terminal paths.

## LLM routing and failover

- Simple requests and greetings are routed through the configured LLM.
- Provider health tracking and failover are supported.
- OpenAI-compatible 429/5xx streaming failures are handled explicitly.
- Production does not silently fall back to local Ollama when cloud providers are unavailable.
- Ollama remains available for local/self-hosted development.

## RAG / Knowledge Base

- Document ingestion and chunking
- Embeddings and similarity search
- Qdrant-backed knowledge bases
- Production Qdrant Cloud support
- Local Docker Qdrant support
- Source/citation retrieval

## Security

- JWT authentication and refresh-token rotation
- RBAC for protected resources and tools
- Central tool registry with risk/permission checks
- Human approval for high-risk operations
- Docker sandboxing for untrusted code
- SSRF and path-traversal protections
- Pydantic validation
- Persistent audit logging

## Environment variables

Copy `.env.example` to `.env` and configure values for your environment.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | JWT signing secret |
| `DATABASE_URL` | Application database connection |
| `QDRANT_URL` | Qdrant endpoint |
| `QDRANT_API_KEY` | Qdrant Cloud API key when required |
| `OLLAMA_URL` | Local Ollama endpoint |
| `VITE_API_URL` | Frontend API base URL for non-Docker development |
| `MAX_UPLOAD_SIZE_MB` | Maximum upload size |
| `LOG_LEVEL` | Application logging level |

Never commit API keys, passwords, JWT secrets, or `.env` files.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| Backend | Python 3.11, FastAPI, Pydantic, Uvicorn |
| Database | Neon PostgreSQL production; SQLite local |
| Vector DB | Qdrant Cloud production; Qdrant Docker/local development |
| LLM | Cloud/OpenAI-compatible providers; Ollama local |
| Streaming | Server-Sent Events (SSE) |
| Containers | Docker / Docker Compose |
| Testing | pytest + pytest-asyncio + TypeScript/Vite checks |

## Project structure

```text
Sovereign-AI/
├── backend/              FastAPI backend
├── frontend/             React/Vite frontend
├── docs/                 Project documentation
├── scripts/              Utility/setup scripts
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
└── README.md
```

## Documentation

- `README.md` — current project overview, architecture, installation and release information
- `docs/01_PRD.md` — product requirements
- `docs/02_TRD.md` — technical requirements
- `docs/03_System_Architecture.md` — system architecture
- `docs/04_App_User_Flow.md` — user flows
- `docs/05_UI_UX_Specification.md` — UI/UX specification
- `docs/06_Backend_Database_API.md` — backend/database/API documentation
- `docs/07_AI_ML_Design.md` — AI/ML design
- `docs/08_Security_Privacy.md` — security and privacy
- `docs/09_Implementation_Plan.md` — implementation plan
- `docs/10_Testing_QA_Plan.md` — testing and QA
- `docs/11_Deployment_DevOps.md` — deployment and DevOps
- `docs/12_Risk_Mitigation.md` — risk mitigation
- `docs/13_Requirements_Traceability.md` — requirements traceability
- `docs/14_User_Guide.md` — user guide
- `docs/15_Project_README.md` — this project README

## Current verification

The latest application fix is commit `fc1a854` on `main`.

- 787 backend tests passed in the latest repository verification.
- Frontend TypeScript compilation and Vite build passed.
- Production frontend canonical URL: `https://sovereign-ai-workbench-2026.vercel.app/`.
- Production backend: `https://sovereign-ai-backend-ciy8.onrender.com`.
- Neon production schema is present and ready.
- Production Qdrant configuration uses Qdrant Cloud.
- Cloud LLM routing/failover is configured; no silent production Ollama fallback.

Historical duplicate assistant-message records created before `fc1a854` may remain in the database. The current code prevents new duplicate persistence; historical data is not automatically deleted.

## License

Internal project — SIH 2026 Prototype. All rights reserved by the developing team.

---

*Sovereign AI Workbench — privacy-first AI with control over deployment, data and model providers.*
