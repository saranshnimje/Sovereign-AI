# Agent Architecture Analysis

## Architecture Overview

The Sovereign AI Workbench uses a single canonical autonomous agent loop implemented in `AgentRuntime` (`backend/services/agent/runtime.py`). All other agent-related code is either supporting infrastructure or confirmed dead code.

### Core Agent Loop: `AgentRuntime`

`AgentRuntime` is the **only** production autonomous agent loop. It implements a structured plan → reason → execute → verify cycle:

```
User Message → Create Plan → [Decide → Execute → Observe] → Verify → Respond
                                    ↑                  |
                                    └──────────────────┘
```

**Key methods:**
| Method | Purpose |
|--------|---------|
| `_create_plan()` | LLM generates structured Plan with AcceptanceCriteria |
| `_decide()` | LLM picks next ToolAction from plan steps |
| `_execute_tool()` | Validates input via ToolRegistry, executes handler, enforces retry limits |
| `_replan()` | Re-plan when stuck or plan exhausted |
| `_verify()` | LLM verifier checks all criteria before final answer |
| `_trim_output()` | Compresses large tool outputs before sending to LLM |
| `_extract_artifacts()` | Extracts deliverables from conversation |
| `run()` | Async generator yielding SSE events |

**Safety limits** (from `AgentStateMachine`):
- `MAX_TOOL_CALLS = 30` — global safety cap
- Per-tool retry: max 2 retries on failure
- Max 3 replans before forced completion
- Max 80% context utilization before compression

### State Machine: `AgentStateMachine`

Formal finite state machine (`backend/services/agent_state.py`) with defined transitions:

```
idle → planning → executing → observing → verifying → completed
                  ↑            |    ↑
                  └────────────┘    | (replan)
                                    └───────────────→ replanning → planning
```

Valid transitions enforced:
- `idle → planning` (on run start)
- `planning → executing` (plan created)
- `executing → observing` (tool completed)
- `observing → planning` (observe after execute)
- `observing → verifying` (decide to verify)
- `planning → verifying` (plan complete)
- `verifying → completed` (all criteria met)
- Any active state → `cancelled` (user cancellation)
- Any active state → `failed` (error/circuit breaker)

### Backend Components

**`backend/services/agent/__init__.py`** — Package init, exports `AgentRuntime`

**`backend/services/agent/schemas.py`** — Pydantic schemas for structured LLM output:
- `Plan`, `PlanStep`, `AcceptanceCriteria` — structured planning
- `AgentDecision`, `ToolAction` — reasoning/decisions
- `Observation` — tool execution results
- `VerificationResult`, `VerificationCriteriaResult` — verification
- `parse_llm_json()` — robust JSON extraction from LLM responses

**`backend/services/agent/prompts.py`** — Prompt templates for each LLM role:
- Planner: `PLANNER_SYSTEM/USER`
- Reasoner: `REASONER_SYSTEM/USER`
- Verifier: `VERIFIER_SYSTEM/USER`
- Replanner: `REPLANNER_SYSTEM/USER`
- Context compression: `COMPRESS_PROMPT`

**`backend/services/agent/runtime.py`** — The canonical agent loop (847 lines)

**`backend/routers/chat.py`** — Thin router (~524 lines):
- `send_agent_message` — SSE streaming endpoint
- Creates `AgentRuntime`, calls `runtime.run()`
- Handles DB lookups for conversation/messages
- Heartbeat keepalive for long tool executions

**`backend/services/agent_state.py`** — `AgentStateMachine`, safety limits, transitions

**`backend/services/approval_service.py`** — Human-in-the-loop gate:
- Creates `ApprovalRequest`, sets state to `awaiting_approval`
- `wait_for_decision()` uses `asyncio.Event` for immediate wakeup

**`backend/services/audit_service.py`** — Append-only hash-chained audit log:
- `log(event_type, action, outcome, user_id, resource_type, resource_id, metadata)`

**`backend/services/sandbox_service.py`** — Docker-based Python execution:
- Fresh container per execution, no network, no host filesystem

### Tool System

**`backend/tools/registry.py`** — `ToolRegistry`:
- 17 registered tools with risk levels (low/medium/high/critical)
- RBAC: permission check → risk check → approval gate → validation → execution
- `list_enabled(user_role)` filters tools by role
- `requires_approval(tool)` checks risk level

**`backend/tools/terminal.py`** — Hardened terminal tools:
- Workspace restriction: `working_dir` must resolve within workspace
- Dangerous command blocklist (case-insensitive): `rm -rf /`, `format`, `shutdown`, PowerShell `Remove-Item -Recurse`
- Path traversal detection: `../`, `..\\`, `/etc/passwd`, `C:\Windows\System32`
- Both `execute_command` and `execute_powershell` enforce all checks

**`backend/tools/subagent_tool.py`** — Sub-agent tool handlers:
- Depth limit (3), concurrency limit (5), role-based access control
- All sub-agent actions audit-logged

### Data Models

**`backend/models/agent.py`**:
- `AgentRun` — tracks agent execution with state, metrics, retry counts
- `ToolCall` — individual tool invocations with timing, status, retry info
- `ApprovalRequest` — human approval for high-risk tools
- `AgentEvent` — persistent event stream (sequence, type, payload JSON)

### Database & Migrations

**`backend/database.py`** — Async SQLAlchemy with `get_db` dependency
**`backend/alembic/versions/f1a2b3c4d5e6_add_agent_events.py`** — AgentEvent table migration

### Frontend Components

**`frontend/src/pages/ChatPage.tsx`** — SSE event handling:
- Events: `token`, `evidence`, `tool_call`, `tool_started`, `tool_result`, `tool_error`, `plan`, `error`, `done`, `heartbeat`
- SSE keepalive via `_run_with_heartbeat()`

**`frontend/src/components/chat/ToolCallCard.tsx`**:
- Displays tool calls with status icons, expandable details
- States: pending, running, success, error, denied, approval_required

### Security Controls

| Control | Implementation |
|---------|---------------|
| Authentication | JWT via `get_current_user` dependency |
| Authorization | RBAC in `ToolRegistry.list_enabled()` |
| Terminal workspace restriction | `_is_path_within_workspace()` |
| Dangerous command blocking | `_is_dangerous_command()` (case-insensitive) |
| Path traversal detection | `_contains_traversal()` |
| Tool approval gate | `ApprovalService.wait_for_decision()` |
| Sandbox execution | Docker containers, no network/filesystem |
| Audit logging | `AuditService.log()` on every write |
| Sub-agent depth limit | 3 levels max |
| Context compression | `_trim_output()` at 80% utilization |

### SSE Events

| Event | Payload | Description |
|-------|---------|-------------|
| `plan` | model, task, tools, acceptance_criteria | Structured plan created |
| `tool_call` | call_id, tool, input_summary, reasoning | LLM selected a tool |
| `tool_started` | call_id, tool | Execution began |
| `tool_result` | call_id, status, result_summary, duration_ms | Execution completed |
| `tool_error` | call_id, tool, error | Execution failed |
| `token` | text | Incremental text token |
| `evidence` | type, content, source | Evidence extracted |
| `observation` | facts, evidence_ids | Post-execution observation |
| `verification` | passed, criteria | Verification result |
| `done` | token_count, activity, tool_calls | Stream complete |
| `error` | message | Error occurred |
| `heartbeat` | timestamp | Keepalive during long operations |

### Test Coverage

| Test File | Count | Coverage |
|-----------|-------|----------|
| `test_agent_runtime.py` | 13 | Runtime guarantees (plan, verify, compress, abort) |
| `test_tool_calling.py` | 35 | Full agent loop integration (plan→verify, retries, replan, max limits) |
| `test_terminal_security.py` | 21 | Workspace restriction, dangerous commands, path traversal |
| `test_chat_security.py` | 18 | Auth, tenant isolation, citation, provider failures |
| `test_persistent_cancellation.py` | 14 | Cancel from all states, persistence, runtime events |
| `test_agent_event_persistence.py` | 13 | Model, DB persistence, replay, metadata |
| `test_subagent_security.py` | 16 | Depth/concurrency/RBAC/audit |
| `test_verification_authority.py` | 13 | Verifier controls completion, false-completion prevention |
| `test_retry_classification.py` | 14 | Retry limits, failure types, tool call limits |
| `test_dead_code_removal.py` | 11 | AgentService dead code, AgentRuntime canonical |
| `test_context_compression.py` | 13 | Compression, provider failures, memory |
| `test_tool_registry.py` | 20 | Tool registration, RBAC, risk levels, validation |
| `test_sandbox_service.py` | 7 | Docker security, cleanup, isolation |
| `test_agent_api.py` | 8 | Agent endpoint integration |
| `test_phase5_api.py` | 14 | Agent API integration |
| **Total** | **220** | |
