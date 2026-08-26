# 11 Deployment & DevOps
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 02_TRD.md v1.0, 03_System_Architecture.md v1.0

---

## 1. Deployment Overview

Sovereign AI Workbench deploys as a self-contained Docker Compose stack on a single host. This is the only officially supported deployment mode for the SIH 2026 prototype.

**Deployment target:** A single on-premise machine (laptop, workstation, or server) controlled by the organization.

**What is required on the host:**
- Docker Engine 24+
- Docker Compose v2 (included with Docker Desktop)
- Ollama (running on host, not in Docker)
- At minimum 8 GB RAM, 4 CPU cores, 50 GB free disk

**What the Docker Compose stack provides:**
- FastAPI backend (with SQLite, file storage)
- React frontend (served by nginx)
- Qdrant vector database

---

## 2. Repository Structure

```
sovereign-ai-workbench/
├── docker-compose.yml          # Production-ready compose file
├── docker-compose.dev.yml      # Override for local development
├── .env.example                # Environment variable template
├── .gitignore
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt        # Pinned Python dependencies
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   ├── services/
│   ├── tools/
│   └── utils/
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── nginx.conf              # Production nginx config
│   └── src/
│
├── scripts/
│   ├── setup.sh                # First-time setup script
│   ├── pull_models.sh          # Pull required Ollama models
│   └── backup.sh               # Backup data volumes
│
└── docs/
    └── *.md
```

---

## 3. Docker Compose Configuration

### 3.1 `docker-compose.yml`

```yaml
version: "3.9"

services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    image: sovereign-ai-frontend:1.0
    ports:
      - "80:80"
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - sovereign_network
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    image: sovereign-ai-backend:1.0
    ports:
      - "8000:8000"
    depends_on:
      qdrant:
        condition: service_healthy
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////app/data/sqlite/sovereign.db
      - QDRANT_URL=http://qdrant:6333
      - OLLAMA_URL=http://host.docker.internal:11434
      - FRONTEND_ORIGIN=http://localhost
      - LOG_LEVEL=INFO
      - SECRET_KEY=${SECRET_KEY}
      - MAX_UPLOAD_SIZE_MB=${MAX_UPLOAD_SIZE_MB:-50}
      - SANDBOX_IMAGE=${SANDBOX_IMAGE:-python:3.11-slim}
      - SANDBOX_TIMEOUT_S=${SANDBOX_TIMEOUT_S:-30}
      - SANDBOX_MEM_LIMIT_MB=${SANDBOX_MEM_LIMIT_MB:-256}
    volumes:
      - backend_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/system/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s
    networks:
      - sovereign_network
    restart: unless-stopped
    user: "1000:1000"

  qdrant:
    image: qdrant/qdrant:v1.9.2
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 20s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - sovereign_network
    restart: unless-stopped

volumes:
  backend_data:
    driver: local
  qdrant_data:
    driver: local

networks:
  sovereign_network:
    driver: bridge
    internal: false   # backend needs host.docker.internal for Ollama
```

### 3.2 `docker-compose.dev.yml` (Development Override)

```yaml
# Usage: docker compose -f docker-compose.yml -f docker-compose.dev.yml up
version: "3.9"

services:
  frontend:
    build:
      target: development
    command: ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src:ro
    environment:
      - VITE_API_URL=http://localhost:8000

  backend:
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    environment:
      - LOG_LEVEL=DEBUG
      - FRONTEND_ORIGIN=http://localhost:5173
    volumes:
      - ./backend:/app/backend:ro  # hot reload source
      - backend_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
```

---

## 4. Dockerfiles

### 4.1 Backend Dockerfile

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim AS base

# Install system dependencies for PaddleOCR and PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r sovereign && useradd -r -g sovereign -u 1000 sovereign

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=sovereign:sovereign . .

# Create required directories with correct ownership
RUN mkdir -p /app/data/sqlite /app/data/uploads /app/data/sandbox_workspace \
    && chown -R sovereign:sovereign /app/data

USER sovereign

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### 4.2 Frontend Dockerfile

```dockerfile
# frontend/Dockerfile
# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --frozen-lockfile

COPY . .
RUN npm run build

# Development stage
FROM node:20-alpine AS development
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# Production stage
FROM nginx:1.27-alpine AS production

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### 4.3 Frontend nginx Configuration

```nginx
# frontend/nginx.conf
server {
    listen 80;
    server_name localhost;

    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Serve React SPA: all routes to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API calls to backend
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # SSE support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
    }

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/javascript application/json;
}
```

---

## 5. Environment Configuration

### 5.1 `.env.example`

```bash
# ==============================================================
# Sovereign AI Workbench - Environment Configuration
# Copy this file to .env and fill in your values.
# NEVER commit .env to version control.
# ==============================================================

# ---- REQUIRED ----
# JWT signing secret. Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-secret-key-here-minimum-32-characters

# ---- OPTIONAL (defaults shown) ----

# Ollama endpoint (use host.docker.internal on Mac/Windows; 172.17.0.1 on Linux)
OLLAMA_URL=http://host.docker.internal:11434

# Qdrant endpoint (default uses Docker service name)
QDRANT_URL=http://qdrant:6333

# Max file upload size in MB
MAX_UPLOAD_SIZE_MB=50

# Docker image for code execution sandbox
SANDBOX_IMAGE=python:3.11-slim

# Sandbox execution limits
SANDBOX_TIMEOUT_S=30
SANDBOX_MEM_LIMIT_MB=256

# Log level: DEBUG | INFO | WARNING | ERROR
LOG_LEVEL=INFO

# Audit log retention in days
AUDIT_RETENTION_DAYS=365
```

### 5.2 Generating `SECRET_KEY`

```bash
python -c "import secrets; print(secrets.token_hex(32))"
# Example output: 8f3a2b...  (64-char hex = 32 bytes)
```

---

## 6. Setup and Installation Guide

### 6.1 `scripts/setup.sh`

```bash
#!/bin/bash
# setup.sh — First-time setup for Sovereign AI Workbench

set -e

echo "=== Sovereign AI Workbench Setup ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker is required but not installed."; exit 1; }
command -v ollama >/dev/null 2>&1 || { echo "Ollama is required but not installed."; exit 1; }

# Generate .env if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/your-secret-key-here-minimum-32-characters/$SECRET_KEY/" .env
    echo "✓ Generated .env with new SECRET_KEY"
else
    echo "✓ .env already exists (skipping)"
fi

# Pull sandbox base image
echo "Pulling sandbox Docker image..."
docker pull python:3.11-slim
echo "✓ Sandbox image ready"

# Pull recommended Ollama models
echo "Pulling Ollama models (this may take a while)..."
ollama pull llama3.2:3b
ollama pull nomic-embed-text
echo "✓ Models ready"

echo ""
echo "=== Setup Complete ==="
echo "Run: docker compose up --build"
echo "Then open: http://localhost"
```

### 6.2 `scripts/pull_models.sh`

```bash
#!/bin/bash
# Pull additional recommended models

echo "Pulling medium chat model..."
ollama pull mistral:7b-q4

echo "Pulling vision model (optional, requires ~5GB)..."
ollama pull llava:7b-q4

echo "Done. Available models:"
ollama list
```

---

## 7. Starting and Stopping

### 7.1 First Start (Production)

```bash
# 1. Clone/copy the project
git clone <repo-url> sovereign-ai-workbench
cd sovereign-ai-workbench

# 2. Run setup
bash scripts/setup.sh

# 3. Start Ollama on host (must be running before compose up)
ollama serve &   # or start as a system service

# 4. Start the stack
docker compose up --build -d

# 5. Follow logs
docker compose logs -f

# 6. Check health
curl http://localhost/api/v1/system/health
# Expected: {"status": "ok"}

# 7. Open in browser
open http://localhost  # or http://localhost on Linux
```

### 7.2 Development Start

```bash
# Start with hot reload
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Frontend dev server: http://localhost:5173
# Backend API: http://localhost:8000
# API docs: http://localhost:8000/api/docs
```

### 7.3 Stopping and Cleanup

```bash
# Stop (preserves data volumes)
docker compose down

# Stop and remove data volumes (DESTRUCTIVE — deletes all AI data)
docker compose down -v

# Remove built images (forces rebuild next time)
docker compose down --rmi local
```

---

## 8. Data Backup

### 8.1 `scripts/backup.sh`

```bash
#!/bin/bash
# Backup all persistent data volumes

BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up SQLite database..."
docker run --rm \
    -v sovereign-ai-workbench_backend_data:/data \
    -v "$(pwd)/$BACKUP_DIR":/backup \
    alpine \
    tar czf /backup/backend_data.tar.gz /data

echo "Backing up Qdrant data..."
docker run --rm \
    -v sovereign-ai-workbench_qdrant_data:/data \
    -v "$(pwd)/$BACKUP_DIR":/backup \
    alpine \
    tar czf /backup/qdrant_data.tar.gz /data

echo "Backup complete: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
```

### 8.2 Restore

```bash
# Stop the stack
docker compose down

# Restore backend data
docker run --rm \
    -v sovereign-ai-workbench_backend_data:/data \
    -v "$(pwd)/backups/YYYYMMDD_HHMMSS":/backup \
    alpine \
    tar xzf /backup/backend_data.tar.gz -C /

# Restart
docker compose up -d
```

---

## 9. Database Migrations

### 9.1 Running Migrations

```bash
# Run inside the backend container
docker compose exec backend alembic upgrade head

# Check current migration version
docker compose exec backend alembic current

# Generate new migration (after model changes)
docker compose exec backend alembic revision --autogenerate -m "description"
```

### 9.2 Migration at Startup

The `init_db()` function in `database.py` creates tables if they don't exist (development convenience). For production, Alembic is the authoritative migration tool. The compose file can be extended to run migrations before starting the API:

```dockerfile
# In Dockerfile CMD, add a migration step
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
```

---

## 10. Ollama Configuration

### 10.1 Ollama on Linux (System Service)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start as system service
sudo systemctl start ollama
sudo systemctl enable ollama  # start on boot

# Verify
curl http://localhost:11434/api/tags
```

### 10.2 Ollama Host Access from Docker

**Mac / Windows (Docker Desktop):**
`http://host.docker.internal:11434` — works out of the box.

**Linux:**
`host.docker.internal` is not automatically available. Add to `docker-compose.yml`:
```yaml
backend:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```
Or set `OLLAMA_URL=http://172.17.0.1:11434` (Docker bridge IP).

### 10.3 GPU Support (Optional)

If the host has an NVIDIA GPU:
```bash
# Install NVIDIA Container Toolkit
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

# Ollama detects GPU automatically when started on host with CUDA drivers
# No backend code changes needed — Ollama handles GPU inference transparently
```

---

## 11. Monitoring and Logs

### 11.1 Viewing Logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f backend
docker compose logs -f qdrant

# Last N lines
docker compose logs --tail=100 backend
```

### 11.2 Log Format

Backend produces structured JSON logs to stdout:
```json
{"timestamp": "2026-08-23T10:30:00Z", "level": "INFO", "logger": "sovereign.chat", "message": "Chat message sent", "user_id": "...", "duration_ms": 1200}
```

Parsed by Docker's logging driver. For production log aggregation, configure Docker's syslog or json-file driver.

### 11.3 Health Check Endpoints

| Endpoint | Auth | Returns |
|----------|------|---------|
| `GET /api/v1/system/health` | None | `{"status": "ok"}` or 503 |
| `GET /api/v1/system/status` | Bearer | Full service status |
| `GET /api/v1/system/resources` | Bearer | CPU/RAM/disk metrics |
| `GET http://qdrant:6333/healthz` | None | `{"title": "qdrant - ok"}` |

---

## 12. Troubleshooting Guide

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Connection refused` to Ollama | Ollama not running on host | `ollama serve` or check service status |
| Backend container keeps restarting | Missing `.env` or bad `SECRET_KEY` | Check `docker compose logs backend` |
| `Permission denied` on Docker socket | Backend user (1000) not in docker group | Run backend as root (dev only) or use socket group |
| Qdrant fails to start | Port 6333 already in use | Stop conflicting service; change port in compose |
| PaddleOCR import error | Missing native libs | Rebuild backend Docker image with `--no-cache` |
| `CORS policy blocked` | Frontend origin mismatch | Set `FRONTEND_ORIGIN` env var correctly |
| Agent sandbox times out | Code too complex / infinite loop | Increase `SANDBOX_TIMEOUT_S`; check code |
| Models not listed | Ollama not reachable | Check `OLLAMA_URL` and Ollama service status |
| Slow first LLM response | Model not loaded in RAM | Normal; Ollama loads on first request (~10-30s) |

---

## 13. Future Deployment Considerations

| Upgrade | What changes |
|---------|-------------|
| PostgreSQL | Change `DATABASE_URL`; run `alembic upgrade head` |
| TLS/HTTPS | Add nginx reverse proxy with SSL certificate in front of stack |
| Kubernetes | Extract to Deployment + StatefulSet + PVC; add Ingress |
| Multiple API replicas | Requires PostgreSQL (SQLite not shareable); add load balancer |
| External log aggregation | Change Docker log driver to syslog or Loki |

---

## 14. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial Deployment & DevOps document |

---

*End of Deployment & DevOps*
