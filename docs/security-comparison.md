# Security Comparison — Reference Project vs My Project

> Every finding verified in source. Severity: CRITICAL / HIGH / MEDIUM / LOW / INFO.
> Format: SEVERITY · FILE · LOCATION · PROBLEM · ATTACK SCENARIO · CORRECT FIX.

## 1. Reference Project Findings

| Sev | File:Line | Problem | Attack / Failure Scenario | Correct Fix |
|---|---|---|---|---|
| CRITICAL | app/api/demo.py:12–36,189–190 | Unauthenticated `POST /api/demo/seed` creates ADMIN with password echoed in response | Anyone on LAN mints admin: `admin@sovereign.local / AdminSovereign2026!` | Remove endpoint; seed via CLI only; never return secrets |
| CRITICAL | app/api/auth.py:32–35 | Register with existing email returns valid JWT for that account **without verifying password** | Account takeover of any known email (e.g., the seeded admin) | 409 Conflict on duplicate email |
| CRITICAL | app/api/auth.py:16,41 | Registration accepts client-chosen role incl. ADMIN | Self-promotion to ADMIN at signup | Fixed roles; first-user-admin bootstrap; admin-managed roles |
| CRITICAL | app/main.py:31–37 | CORS `allow_origins=["*"]` + `allow_credentials=True` | Any origin can make credentialed requests | Explicit origin allowlist |
| CRITICAL | app/main.py:77 | `/files` StaticFiles mount serves all uploads unauthenticated | Anonymous download of CONFIDENTIAL manuals/telemetry | Auth-gated download endpoint with ownership checks |
| CRITICAL | core/config.py:42 + .env.example:44 | Hardcoded JWT secret shipped in repo | Forge ADMIN tokens for any default deployment | Env-only secret; fail-fast if default detected in prod |
| HIGH | app/api/auth.py:87–99 | Failed login for demo emails auto-creates account with attacker's password | Backdoor account creation via login form | Never create users during login |
| HIGH | api/inspection.py:21–23; api/data_analysis.py:21–23 | `os.path.join(STORAGE_PATH, file.filename)` with raw client filename | `..\..\sovereign_workbench.db` overwrites DB or arbitrary files | uuid + sanitize + basename (as my project already does) |
| HIGH | api/models_mgr.py:74 | RBAC check called, return value ignored | VIEWER reconfigures model settings | Dependency that raises 403 |
| HIGH | api/audit.py:10–22 | Audit trail readable by any authenticated user | VIEWER exfiltrates full activity history incl. IPs | Admin-only scope |
| HIGH | api/chat.py:29–32,157–179 | Conversation read/write without ownership check (IDOR) | Read other users' transcripts; write into their threads | owner_id filter on every access |
| MEDIUM | api/documents.py:134–147 | Any user deletes any document | Sabotage / evidence destruction across departments | owner-or-admin gate |
| MEDIUM | api/documents.py:121+ | `/chunks` exposes full indexed text cross-department | Confidential content leak via chunk API | department/owner filtering |
| MEDIUM | api/health.py, ai.py, main.py root | Public endpoints disclose config, models, Firebase project | Reconnaissance | Require auth; minimal disclosure |
| MEDIUM | security_mgr.py:26–32; dashboard floors | Fabricated security posture (`score 98.5`, `0 unauthorized attempts`) | False assurance to operators/security reviewers | Report measured values only |
| LOW/MED | services/document_service.py:12–37 | No upload size limits; extension-only validation | Disk exhaustion; polyglot files | Size cap + magic-byte validation (mine has both) |
| INFO | core/security.py:40–49 | Deactivated users keep valid tokens up to 8 h | Revocation gap | Check is_active during validation (mine does) |
| INFO | docker-compose.yml:9; .env.example:7–13 | Postgres creds and Firebase web config committed | Default-credential logins | Secrets out of VCS |

**Clean axes (credit where due):** ORM-parameterized queries throughout — no SQL injection found;
no os.system/subprocess/eval/pickle/yaml.load usage; no `verify=False`.

## 2. My Project Findings

| Sev | Location | Problem | Scenario | Fix |
|---|---|---|---|---|
| HIGH | docker-compose.dev.yml (docker.sock mount) | API container holds Docker socket ⇒ any RCE = host root-equivalent | LLM-driven code escapes sandbox logic bug → socket abuse → host compromise | Socket-proxy (read-only, least-priv) or sidecar executor service; never expose socket to API process long-term |
| HIGH | config.py secret_key default `"change-me-in-production-use-32-random-bytes"` | Weak-secret deployments possible | Token forgery if deployed unchanged | Fail-fast startup guard when default + ENVIRONMENT=production |
| HIGH | global (no rate limiting) | Brute force / resource exhaustion | Password spraying on /auth/login | slowapi-style limiter on auth + chat + upload; lockout after N failures |
| MED | document_service / knowledge_base delete/get paths | Ownership checks inconsistent (role-only in places) | Analyst deletes/deletes-across-KBs they don't own | Enforce owner_id-or-admin on every document/KB mutation & read-detail |
| MED | BackgroundTasks ingestion session lifetime (FastAPI ≥0.106 semantics) | Possible closed-session errors mid-ingest | Uploads stuck `processing` intermittently | Inject session inside the background task itself |
| MED | audit sequence allocation race | Concurrent writes may reuse seq → chain verify false-negative | Two simultaneous events | Retry-on-conflict or DB sequence/unique constraint |
| MED | audit immutability convention-only | Direct DB edit breaks chain silently until verify | Insider tamper discovered late | SQLite trigger/Postgres rule rejecting UPDATE/DELETE on audit_logs |
| MED | web tools DNS-TOCTOU in SSRF guard | Re-resolution allows private-IP pivot | crafted redirect/DNS rebinding | Pin resolved IP per request; block re-resolves |
| LOW | qdrant sync client on event loop | Latency stalls under load | Slow searches block loop | Async client or threadpool wrapper |
| LOW | StaticPool single SQLite connection | Throughput ceiling; approval polling holds session ≤5 min | UI freezes under concurrency | Short-lived sessions in approval poll; consider WAL + pool |
| LOW | embedding model switch w/o version stamping | Silent retrieval breakage (dimension mismatch) | KB becomes unqueryable after model change | Stamp vectors+KB with embedding model id; refuse mismatch; reindex command |
| LOW | frontend export links rely on cookie auth via window.open | Export auth depends on deployment topology | Exports 401 behind some proxies | Signed short-lived download URLs from API |
| LOW | missing eslint config / favicon 404 | hygiene | — | add config + public/favicon |

**Strong (verified):** origin-allowlisted CORS with explicit methods/headers · security headers ·
request-ID tracing + structured error envelopes · bcrypt + JWT with DB-backed is_active verification ·
refresh-token rotation/revocation with hashed storage · httpOnly refresh cookie, memory-only access
token · first-admin bootstrap · require_role gates · uuid+magic-byte upload validation with size caps ·
sandbox (fresh container, UID 1000, cap_drop ALL, no network, read-only fs, pids/mem/CPU caps,
timeout, auto-remove) · registry risk/permission gating + human approval for high-risk tools ·
hash-chained append-only audit with verify/export and trusted IP extraction.

## 3. Head-to-Head Scorecard

| Axis | Reference | Mine |
|---|---|---|
| Auth backdoors | **4 independent ones** | none found |
| CORS | wildcard+credentials | allowlist |
| File serving | anonymous static mount | authenticated APIs (add download endpoint) |
| Secret management | hardcoded-in-repo | env-based (add fail-fast) |
| Tenancy isolation | none | partial → P0 hardening |
| Tool execution | unsandboxed direct calls | hardened Docker sandbox + approval gates |
| Audit integrity | none, world-readable | hash chain + verify + export (harden race/immutability) |
| Honest metrics | fabricated everywhere | measured values only |
| Injection defenses | good design in dead code | live delimiters/escaping/grounded prompts |
| Rate limiting | none | none (**both need it**) |

**Conclusion:** my project needs hardening at five concrete points (socket isolation, secret fail-fast,
rate limiting, ownership consistency, background sessions). The reference project needs a rebuild;
none of its auth/session/file patterns should be ported.
