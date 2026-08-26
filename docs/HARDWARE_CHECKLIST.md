# Model Configuration — VERIFIED 2026-08-24

## Installed Models (Confirmed)

| Model | Role | Status | Size |
|---|---|---|---|
| `qwen3:14b` | **Primary Chat + Agent** | ✅ Installed & Verified | 9.3 GB |
| `nomic-embed-text` | **Embeddings (RAG required)** | ✅ Installed & Verified | 274 MB |

## Notes on qwen3:14b

`qwen3:14b` is a **thinking model** — it generates an internal chain-of-thought before answering.
This produces higher-quality, more reasoned responses but has two implications:

1. **CPU latency:** ~90–230 seconds per response on CPU (no GPU). This is expected behaviour.
2. **Token budget:** The backend sets `max_tokens=2048` to ensure the model has enough budget
   to complete its reasoning AND produce output text.

The model has been verified to produce **grounded RAG answers** citing local components
(Qdrant, nomic-embed-text) without hallucinating cloud services.

## Optional Smaller Chat Model

If hardware performance is a concern (demo on a weak CPU), an optional fallback:

```bash
ollama pull llama3.2:3b        # 2 GB — ~5-15s per response on CPU
```

Then in `.env`:
```
DEFAULT_CHAT_MODEL=llama3.2:3b
```

`llama3.2:3b` is NOT a thinking model and responds much faster. Use it if `qwen3:14b`
is too slow for the demo environment.

---

# Pre-Demo Checklist
## Sovereign AI Workbench — SIH 2026 Prototype

**Version:** 1.0 Release Candidate  
**Date:** 2026-08-24  
**Status:** VERIFIED — Ready for SIH Demonstration

---

## Minimum Requirements (Will Work)

| Component | Minimum | Notes |
|---|---|---|
| **RAM** | 8 GB | Tight — avoid running other heavy apps during demo |
| **CPU** | 4 cores | 2.5 GHz+ recommended |
| **Disk free** | 20 GB | Models + Docker images + demo data |
| **GPU** | Not required | CPU inference works; slower responses |
| **OS** | Windows 10+, macOS 12+, Ubuntu 20.04+ | |
| **Docker** | 24+ (Docker Desktop or Engine) | Must be running before demo |
| **Ollama** | Latest stable | Must be running on host |
| **Internet** | Only for initial setup | Fully offline after model pull |

## Recommended (Comfortable Demo)

| Component | Recommended | Notes |
|---|---|---|
| **RAM** | 16 GB | Allows chat + RAG simultaneously |
| **CPU** | 8 cores, 3.0 GHz+ | Noticeably faster inference |
| **Disk free** | 50 GB | Room for multiple models + large docs |
| **GPU** | NVIDIA 6GB+ VRAM (optional) | Dramatically faster if available |
| **SSD** | Required | HDD will make model loading very slow |

---

## Required Software

```bash
# 1. Docker Desktop (includes Docker Compose v2)
# https://www.docker.com/products/docker-desktop/
docker --version   # Must be 24+
docker compose version  # Must be v2+

# 2. Ollama
# https://ollama.ai
ollama --version

# 3. Git (to clone the repository)
git --version
```

---

## Model Download Requirements

One-time internet download required before the demo.

| Model | Role | Size on Disk | RAM When Loaded |
|---|---|---|---|
| `llama3.2:3b` | Chat (minimum) | ~2.0 GB | ~3 GB |
| `nomic-embed-text` | Embeddings | ~0.5 GB | ~0.5 GB |
| **Total minimum** | | **~2.5 GB** | **~3.5 GB** |

Optional better-quality models (if 16 GB RAM available):

| Model | Role | Size | RAM |
|---|---|---|---|
| `mistral:7b-q4` | Chat (better) | ~4.1 GB | ~5 GB |
| `llava:7b-q4` | Vision (optional) | ~4.5 GB | ~5.5 GB |

```bash
# Pull minimum required models
ollama pull llama3.2:3b       # ~2 GB download
ollama pull nomic-embed-text  # ~0.5 GB download

# Verify
ollama list
```

---

## Docker Image Download Requirements

One-time download (~2–3 GB total):

| Image | Purpose | Size |
|---|---|---|
| `python:3.11-slim` | Backend + sandbox | ~150 MB |
| `nginx:1.27-alpine` | Frontend | ~25 MB |
| `node:20-alpine` | Build stage | ~180 MB |
| `qdrant/qdrant:v1.9.2` | Vector database | ~120 MB |

```bash
# Pre-pull all Docker images (run before demo)
docker compose pull
docker pull python:3.11-slim
```

---

## Pre-Demo Verification Script

Run this 15 minutes before the SIH presentation:

```bash
#!/bin/bash
echo "=== Pre-Demo Verification ==="

# 1. Docker
echo -n "Docker: "
docker info >/dev/null 2>&1 && echo "OK" || echo "FAILED - start Docker Desktop"

# 2. Ollama
echo -n "Ollama: "
ollama list >/dev/null 2>&1 && echo "OK" || echo "FAILED - run: ollama serve"

# 3. Required models
echo -n "llama3.2:3b: "
ollama list | grep -q "llama3.2:3b" && echo "OK" || echo "MISSING - run: ollama pull llama3.2:3b"

echo -n "nomic-embed-text: "
ollama list | grep -q "nomic-embed" && echo "OK" || echo "MISSING - run: ollama pull nomic-embed-text"

# 4. Stack health
echo -n "Stack health: "
curl -sf http://localhost/api/v1/system/health >/dev/null 2>&1 \
  && echo "OK" \
  || echo "NOT RUNNING - run: docker compose up -d"

echo "=== Done ==="
```

---

## Known Performance Characteristics on Low-End Hardware

| Situation | Expected Behaviour |
|---|---|
| **First chat message** | 15–30s delay — Ollama loading model into RAM |
| **Subsequent messages** | 3–15s — model already in RAM |
| **Scanned PDF OCR** | 5–15s per page on CPU |
| **RAG query (retrieval)** | < 1s — Qdrant is very fast |
| **RAG query (with LLM)** | 5–15s — LLM generation on CPU |
| **Docker sandbox startup** | 2–5s — container creation overhead |
| **Qdrant startup** | 5–10s |
| **Full stack startup** | 30–60s |

### Tips for Low-End Machines

1. **Use `llama3.2:3b`** — smaller than mistral, adequate for demo
2. **Close other applications** before starting the demo — free as much RAM as possible  
3. **Warm up Ollama** before the demo by sending one test chat message
4. **Pre-process demo documents** — don't OCR live during a time-pressured demo
5. **Use text PDFs**, not scanned PDFs, to avoid OCR latency
6. **Enable GPU if available** — Ollama detects NVIDIA CUDA automatically, no config needed

---

## Startup Order

```
1. Start Docker Desktop / Docker Engine
2. Start Ollama:  ollama serve
3. Start stack:   docker compose up -d
4. Wait 60s, then verify: curl http://localhost/api/v1/system/health
5. Open browser:  http://localhost
```

---

## Quick Recovery Procedures

### Ollama not responding
```bash
pkill ollama
ollama serve &
# Wait 10s, then verify: ollama list
```

### Stack not starting
```bash
docker compose logs backend   # Check for errors
docker compose down
docker compose up -d
```

### Database corrupted
```bash
docker compose down -v           # WARNING: deletes all data
docker compose up -d
# You will need to re-run first-time setup
```

### Model not loaded (slow first response)
```bash
# Pre-warm by running a test inference
ollama run llama3.2:3b "Hello" --nowordwrap
```
