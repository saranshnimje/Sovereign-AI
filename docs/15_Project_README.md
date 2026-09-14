# Sovereign AI Workbench v2.0

**SIH 2026 — current project README**

Sovereign AI Workbench is an agentic AI workbench with multi-provider LLM support, conversation memory, per-message agent execution timelines, tools/plugins, web search, Knowledge Bases, Qdrant retrieval, approvals, artifacts, and production deployment support.

## Current deployment

| Layer | Development | Production |
|---|---|---|
| Frontend | Vite/React | Vercel |
| Backend | FastAPI | Render |
| Relational DB | PostgreSQL/Neon-compatible configuration | Neon PostgreSQL |
| Vector DB | Qdrant Docker container | Qdrant Cloud |
| LLM | Configured local/cloud providers | Cloud/free providers; local Ollama is optional and not a production dependency |

**Qdrant is intentionally preserved in both environments.** Local Docker Qdrant uses persistent storage; production uses Qdrant Cloud with `QDRANT_URL` and `QDRANT_API_KEY`.

## v2.0 agent architecture

```text
User message
    │
    ├── Conversation history (bounded, same conversation only)
    │
    ├── AgentRun (one run per user message)
    │       └── AgentEvent sequence
    │
    └── AgentRuntime
          ├── understand
          ├── plan
          ├── decide
          ├── tool/plugin execution
          ├── observe
          ├── verify
          ├── ask_user / resume
          └── final response
```

### Per-message timeline invariant

Every agent-mode user message creates its own `AgentRun`. The frontend groups persisted/live events by `run_id`; events from different runs must never be merged into one lifecycle timeline.

```text
Conversation
├── User message A → AgentRun A → Timeline A
├── User message B → AgentRun B → Timeline B
└── User message C → AgentRun C → Timeline C
```

Each timeline is persisted in the `agent_events` table and survives page refresh.

## Conversation memory

The agent receives bounded recent history from the current conversation. History is never intentionally shared between conversations or users. The runtime also receives the current user goal separately so the current turn remains unambiguous.

## LLM/provider routing

The workbench supports OpenAI-compatible and other provider adapters. The selected provider/model is sent from the chat UI and resolved server-side. Provider health tracking and failover are used for transient provider failures such as rate limits and 5xx responses.

### Important operational rule

A successful provider health check does **not** guarantee that a particular model can generate a response. A production smoke test must exercise an actual `/chat/completions` request/stream, not only `/models` or a health endpoint.

Free/cloud providers may return `429` during load. The application should surface the provider failure clearly and use an eligible fallback instead of silently returning a fabricated generic answer.

## Agent responses

Agent mode emits lifecycle SSE events including:

- `agent_started`
- `understanding_started` / `understanding_completed`
- `plan_created` / `plan_updated`
- `decision`
- `tool_call` / `tool_result` / `tool_timeout` / `tool_error`
- `observation`
- `verification_started` / `verification_passed` / `verification_failed`
- `ask_user`
- `final_response`
- `done` / `error` / `cancelled`

The final response is persisted before the terminal `done` event so a successful stream cannot disappear from the conversation UI after streaming ends.

## Interactive ASK_USER

The agent can pause a run when it needs user input. The frontend shows selectable options plus custom text input. The answer is submitted against the same `run_id`, allowing the run to resume without creating an unrelated execution timeline.

## Tools, plugins and web search

The central tool registry validates tool names, permissions, schemas, risk levels and execution. High-risk operations can require approval. Web search currently uses a keyless DuckDuckGo HTML search path with SSRF/public-host protections and response limits; no search API key is required for that implementation.

## Files and artifacts

Agent file tools use an isolated run workspace. Generated artifacts are tracked in PostgreSQL/Neon metadata and exposed through the Data UI with preview/download support for supported formats.

**Production caveat:** Render's local filesystem is ephemeral. Durable user-visible artifact storage should use persistent object storage before treating generated files as permanently retained production data.

## Knowledge Bases and Qdrant

```text
Upload
  → extract
  → clean
  → chunk
  → embed
  → Qdrant upsert
  → semantic retrieval
  → grounded answer + citations
```

Local development keeps Qdrant in Docker. Production uses Qdrant Cloud. Tenant/ownership authorization is enforced by the application; defense-in-depth payload filters should also be used for production hardening.

## Authentication demo

The login UI supports a demo-credential fill action. It fills the form and does **not** auto-submit.

For production, demo credentials should be disabled or supplied through deployment configuration rather than hardcoded application code.

## Local development

```bash
docker compose up --build -d
```

For hot reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Local Qdrant is exposed on port `6333` and persists through the Compose Qdrant volume.

## Verification checklist

Before calling a deployment healthy, test all of the following against the real deployed services:

1. Login and token refresh.
2. Two consecutive agent messages in one conversation.
3. Verify each message has a distinct `AgentRun` and timeline.
4. Verify the second message can use relevant first-turn memory.
5. Verify the selected provider actually receives a chat request and returns tokens.
6. Force/observe a provider `429` and verify fallback/error handling.
7. Verify ASK_USER pause and same-run resume.
8. Verify tool/plugin execution and approval gates.
9. Verify web search.
10. Create a file, open it from Data, preview it and download it.
11. Upload a Knowledge Base document, verify Qdrant indexing and retrieval, then preview the document.
12. Refresh the browser and verify timelines, messages and persisted state remain correct.

## Known production limitations

- Render filesystem is ephemeral for locally stored artifacts.
- Free cloud providers can rate-limit or become temporarily unavailable.
- HTML scraping based web search can change if the upstream search page changes.
- Qdrant tenant isolation should be reinforced with payload filters in addition to API authorization.
- Demo credentials should be moved to deployment configuration for production.

## Documentation

The repository also contains detailed PRD, architecture, security, testing, deployment, user-guide and AI/ML documents under `docs/`.

---

**Sovereign AI Workbench v2.0 — agentic, provider-aware, Qdrant-backed, and deployment-focused.**
