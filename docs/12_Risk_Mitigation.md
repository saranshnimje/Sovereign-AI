# 12 Risk & Mitigation
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 09_Implementation_Plan.md v1.0

---

## 1. Risk Overview

This document catalogs known technical, operational, and project risks for the Sovereign AI Workbench SIH 2026 prototype. Each risk is assessed for likelihood and impact, and mitigations are specified.

Risk scores: **Likelihood** (1=Low, 3=High) × **Impact** (1=Low, 3=High) = **Score** (1–9)

---

## 2. Technical Risks

### 2.1 AI/ML Component Risks

| ID | Risk | L | I | Score | Mitigation | Residual |
|----|------|---|---|-------|-----------|---------|
| R-AI-01 | LLM returns unparseable JSON in agent mode | 3 | 2 | 6 | Implement robust JSON extraction (regex fallback); retry with "please respond in JSON" hint; fail step gracefully | Medium |
| R-AI-02 | Ollama unresponsive during demo | 2 | 3 | 6 | Pre-warm model before demo; health check on dashboard; restart script ready | Medium |
| R-AI-03 | LLM quality too poor for demo on small model | 2 | 2 | 4 | Test all demo flows with llama3.2:3b beforehand; have mistral:7b-q4 as fallback if hardware allows | Low |
| R-AI-04 | PaddleOCR install fails on target machine | 2 | 2 | 4 | Use pre-built Docker image with all deps; test Docker build on clean machine | Low |
| R-AI-05 | Embedding model not available → RAG fails | 2 | 3 | 6 | Setup script enforces `ollama pull nomic-embed-text`; clear error message if missing | Low |
| R-AI-06 | Prompt injection in uploaded document content | 1 | 3 | 3 | Pattern detection + structural separation in prompts; all tool calls still validated server-side | Low |
| R-AI-07 | Agent enters reasoning loop before hitting max iterations | 2 | 2 | 4 | Hard iteration limit (default 10); SSE stream shows live progress so user can cancel | Low |

### 2.2 Infrastructure Risks

| ID | Risk | L | I | Score | Mitigation | Residual |
|----|------|---|---|-------|-----------|---------|
| R-INF-01 | Docker socket permission denied (Linux sandbox) | 2 | 2 | 4 | Document Linux-specific setup (docker group membership); sandboxed tools disabled gracefully if unavailable | Low |
| R-INF-02 | `host.docker.internal` not resolvable on Linux | 2 | 3 | 6 | Document `extra_hosts: host-gateway` workaround; `OLLAMA_URL` env var override | Low |
| R-INF-03 | Port conflicts (6333, 8000, 80) | 1 | 2 | 2 | Document required ports; provide `docker-compose.override.yml` example for port changes | Very Low |
| R-INF-04 | Disk space exhaustion during demo | 1 | 3 | 3 | Pre-check disk space in setup script (50 GB minimum); monitor via dashboard | Low |
| R-INF-05 | SQLite WAL file corruption | 1 | 3 | 3 | WAL mode; backup script; SQLite is robust for single-writer workloads | Very Low |
| R-INF-06 | Qdrant data corruption | 1 | 2 | 2 | Qdrant has built-in WAL; backup script; re-indexing recovers data from uploaded files | Very Low |

### 2.3 Security Risks

| ID | Risk | L | I | Score | Mitigation | Residual |
|----|------|---|---|-------|-----------|---------|
| R-SEC-01 | Sandbox container escape | 1 | 3 | 3 | Drop all capabilities; non-root user; network=none; seccomp default; no socket in sandbox | Low |
| R-SEC-02 | JWT secret exposed in git | 1 | 3 | 3 | `.env` in `.gitignore`; setup script generates unique key; `.env.example` has placeholder only | Very Low |
| R-SEC-03 | Agent performs destructive action without approval | 1 | 3 | 3 | Risk-level approval gates enforced in `AgentService`; approval required for high/critical tools | Low |
| R-SEC-04 | Weak password allows unauthorized access | 1 | 2 | 2 | Minimum 12 chars; bcrypt; common password blocklist | Very Low |

---

## 3. Implementation Risks

| ID | Risk | L | I | Score | Mitigation |
|----|------|---|---|-------|-----------|
| R-IMP-01 | 4-week timeline too aggressive for all features | 3 | 2 | 6 | Phase ordering prioritizes demo path; P1 features first; P2 features can be partial |
| R-IMP-02 | Frontend integration takes longer than estimated | 2 | 2 | 4 | Use React Query + simple API client; avoid custom state management complexity |
| R-IMP-03 | OCR processing too slow on demo hardware | 2 | 2 | 4 | Pre-process demo documents before event; show progress indicator; document expected times |
| R-IMP-04 | Agent tool JSON parsing fails in edge cases | 2 | 2 | 4 | Extensive testing with llama3.2:3b; build fallback JSON extraction |
| R-IMP-05 | First LLM response takes >30 seconds (cold start) | 3 | 1 | 3 | Send warmup request at startup; loading state in UI; document behavior |
| R-IMP-06 | PaddleOCR model download required at container build | 1 | 2 | 2 | Include PaddleOCR in Docker image; models downloaded at build time |

---

## 4. Demonstration Risks

| ID | Risk | L | I | Score | Mitigation |
|----|------|---|---|-------|-----------|
| R-DEMO-01 | Hardware at demo venue is weaker than expected | 2 | 3 | 6 | Bring own pre-configured laptop; test on minimum spec hardware beforehand |
| R-DEMO-02 | Demo venue has no internet (model pull fails) | 2 | 2 | 4 | All models pre-pulled; system fully offline-capable; pre-pull during setup |
| R-DEMO-03 | Demo crashes during live evaluation | 1 | 3 | 3 | Full end-to-end dry run day before; backup laptop pre-configured; rollback plan |
| R-DEMO-04 | LLM answer quality poor during demo | 2 | 2 | 4 | Prepare specific demo questions with known good answers; use medium model if hardware allows |
| R-DEMO-05 | Evaluators ask about features not yet built | 2 | 2 | 4 | Document future scope clearly; demonstrate architecture and design as differentiation |

---

## 5. Risk Register Summary

| Priority | Risks | Action |
|----------|-------|--------|
| **Critical (score 6+)** | R-AI-01, R-AI-02, R-AI-05, R-INF-02, R-IMP-01, R-DEMO-01 | Address in implementation; test before demo |
| **Medium (score 3–5)** | R-AI-03, R-AI-04, R-AI-07, R-INF-01, R-IMP-02–06, R-DEMO-02 | Mitigate during implementation |
| **Low (score 1–2)** | All others | Accept; monitor |

---

## 6. Contingency Plans

### 6.1 If Ollama is unresponsive during demo
1. Open terminal; check `ollama list` and `ollama ps`
2. Restart: `pkill ollama && ollama serve &`
3. Dashboard will turn green when reconnected (30s poll)
4. Fall back to showing architecture and audit log features while waiting

### 6.2 If agent produces bad JSON repeatedly
1. Show the raw LLM response in the trace (educational value)
2. Try with a larger/better model (mistral:7b-q4 if available)
3. Demonstrate with a simpler goal that uses fewer tool calls

### 6.3 If Docker sandbox is unavailable
1. Non-sandboxed tools (file_read, search_kb, calculator) still work
2. Agent can still complete goals that don't require Python execution
3. Explain that sandboxed execution requires Docker socket; show the architecture

### 6.4 If the demo laptop is unavailable
1. Secondary laptop with identical setup pre-configured
2. Docker volumes backed up nightly with `scripts/backup.sh`
3. All documentation covers the architecture fully (SIH evaluation includes docs)

---

## 7. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial Risk & Mitigation document |

---

*End of Risk & Mitigation*
