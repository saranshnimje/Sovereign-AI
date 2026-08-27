# Settings Wiring Audit — P1.5

## Overview

Two settings layers exist in the application:

1. **`config.Settings`** (env-based) — loaded once at startup via `get_settings()`, cached by `@lru_cache`. Source: `.env` file. Immutable at runtime.
2. **`SystemSettings`** (JSON-based) — loaded dynamically via `load_settings()` from `system_settings.json`. Mutable at runtime via admin API (`PUT /settings/`).

## Wiring Status

### LIVE Settings (take effect on next request)

| Setting | Schema Field | Service | How |
|---|---|---|---|
| Chunk size | `default_chunk_size` | `document_service.py` | `load_settings().default_chunk_size` |
| Chunk overlap | `default_chunk_overlap` | `document_service.py` | `load_settings().default_chunk_overlap` |
| Top-k results | `default_top_k` | `chat.py` router | `load_settings().default_top_k` |
| Score threshold | `default_score_threshold` | `chat.py` router | `load_settings().default_score_threshold` |
| Upload size limit | `max_upload_size_mb` | `document_service.py` | `load_settings().max_upload_size_mb` |
| Approval timeout | `approval_timeout_minutes` | `approval_service.py` | `load_settings().approval_timeout_minutes` |
| Sandbox timeout | `sandbox_timeout_s` | `sandbox_service.py` | `load_settings().sandbox_timeout_s` |
| Sandbox memory | `sandbox_mem_limit_mb` | `sandbox_service.py` | `load_settings().sandbox_mem_limit_mb` |
| Sandbox CPU | `sandbox_cpu_quota` | `sandbox_service.py` | `load_settings().sandbox_cpu_quota` |

### STATIC Settings (apply to new items only)

| Setting | Schema Field | Notes |
|---|---|---|
| Max iterations | `default_max_iterations` | Schema-level default in `schemas/agent.py`. Existing agent runs keep their value. |

### ENV-Only Settings (not in SystemSettings)

| Setting | Config Field | Notes |
|---|---|---|
| Embedding model | `default_embedding_model` | Changing requires reindexing all KBs. Env-only. |
| Sandbox image | `sandbox_image` | Docker image name. Env-only. |
| Ollama URL | `ollama_url` | External service endpoint. Env-only. |
| Qdrant URL | `qdrant_url` | External service endpoint. Env-only. |
| JWT secrets | `secret_key`, `jwt_*` | Security-sensitive. Env-only. |
| Rate limiting | `rate_limit_*` | Per-process. Env-only. |
| Data directory | `data_dir` | Structural. Env-only. |

## Frontend Badges

The SettingsPage shows:
- **LIVE** badge (green) — setting takes effect on next request
- **STATIC** badge (yellow) — setting applies to new items only

## Sovereignty Section

The SettingsPage includes a Sovereignty Status section showing:
- Active providers (enabled/disabled status)
- Model role assignments (chat, embedding, vision)
