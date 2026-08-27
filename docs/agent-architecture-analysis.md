# Agent Architecture Analysis

## Current Architecture

### Backend Components

**`backend/routers/chat.py`** — Main agent endpoint (`send_agent_message`)
- Linear loop: `for _iteration in range(MAX_TOOL_CALLS + 1)` (MAX=5)
- States are implicit: determined by position in loop
- No formal state machine
- No structured planning
- No observation/reasoning step
- No verification before final answer

**`backend/tools/registry.py`** — ToolRegistry singleton
- 17 registered tools
- Security: permission check → risk check → approval gate → validation → execution
- `list_enabled(user_role)` filters by RBAC
- `requires_approval(tool)` checks risk level
- `validate_input(tool, raw_input)` Pydantic validation
- `execute(tool, validated_input, context)` runs handler

**`backend/services/llm_client.py`** — LLM provider abstraction
- BaseLLMProvider → OllamaProvider, OpenAIProvider, AnthropicProvider, GeminiProvider
- `chat(model, messages, stream, temperature, max_tokens)` → ChatResponse
- No streaming in agent loop (stream=False always)

**`backend/services/approval_service.py`** — Human-in-the-loop gate
- Creates ApprovalRequest, sets agent run to `awaiting_approval`
- `wait_for_decision()` uses asyncio.Event for immediate wakeup
- Approve/reject with audit logging

**`backend/services/audit_service.py`** — Append-only hash-chained log
- Every write goes through this service
- Chain integrity verification

**`backend/services/sandbox_service.py`** — Docker-based Python execution
- Fresh container per execution
- No network, no host filesystem

### Frontend Components

**`frontend/src/components/chat/ToolCallCard.tsx`**
- Displays tool calls with status icons
- Expandable/collapsible per call
- Shows input_summary, result_summary, duration, error, reasoning
- States: pending, running, success, error, denied, approval_required

**`frontend/src/pages/ChatPage.tsx`**
- SSE event handling: token, evidence, tool_call, tool_started, tool_result, tool_error, plan, error, done
- Agent mode toggle (tool_mode: auto/none/manual)
- Manual tool selection
- AbortController for cancellation
- ToolCallCard integration

### Current SSE Events
```
plan         — model + task info + available tools
tool_call    — LLM selected a tool (call_id, tool, input_summary, reasoning)
tool_started — execution began
tool_result  — completed (status, result_summary, duration_ms)
tool_error   — execution failed
token        — incremental text token
done         — stream complete (token_count, activity, tool_calls)
error        — error occurred
```

### Current Limitations

1. **No formal state machine** — states are implicit in loop position
2. **No structured planning** — LLM decides tool sequence ad-hoc
3. **No observation step** — tool results fed directly back to LLM
4. **No reasoning step** — LLM reasons implicitly between tool calls
5. **No verification** — no check that task actually completed
6. **No dynamic replanning** — fixed loop, no replan based on observations
7. **No evidence tracking** — tool results not structured as evidence
8. **No goal tracking** — no explicit goal/plan sent to frontend
9. **No step progress** — frontend shows tool calls but not plan steps
10. **No cancellation** — AbortController stops rendering, not backend loop
11. **No context compaction** — full history sent every iteration
12. **No sovereignty status** — no indication of local vs cloud
13. **Limited audit** — only final completion logged, not per-step

### Extension Points

1. **Agent state machine** — new file `services/agent_state.py`
2. **Planning** — new method in agent loop, new SSE events
3. **Observation** — structured extraction after tool execution
4. **Reasoning** — LLM call with observation context
5. **Verification** — post-execution check before final answer
6. **SSE events** — add agent_state, plan_step, observation, verification, evidence
7. **Frontend** — upgrade ToolCallCard to AgentActivityPanel
8. **Cancellation** — propagate AbortController to backend via asyncio.CancelledError
9. **Audit** — emit per-step audit events
10. **Context management** — summarize old tool results

## Implementation Plan

### Phase 2: Agent State Machine
- Create `services/agent_state.py` with explicit states
- Every transition is explicit and auditable
- States: IDLE, UNDERSTANDING, PLANNING, EXECUTING, OBSERVING, REASONING, VERIFYING, WAITING_APPROVAL, COMPLETED, FAILED, CANCELLED

### Phase 3: Planning
- LLM generates structured plan before execution
- Plan steps have id, description, status
- Plan events streamed to frontend

### Phase 4-5: Tool Selection & Execution
- Existing registry used (no changes)
- Backend remains authority
- New SSE events for state transitions

### Phase 6: Observation
- After each tool execution, create structured observation
- Facts extracted from tool results
- Evidence IDs tracked

### Phase 7: Reason → Replan
- After observing, LLM decides: complete, need another tool, need clarification, retry, failed
- Dynamic replanning based on observations

### Phase 8: Verification
- Before finalizing, verify task completion
- Check evidence grounding
- Emit verification events

### Phase 9: Safety Limits
- MAX_ITERATIONS = 10
- MAX_TOOL_CALLS = 8
- MAX_EXECUTION_TIME = 300s
- MAX_PLAN_STEPS = 10
- MAX_RETRIES = 2

### Phase 10: Approval
- Integrate with existing ApprovalService
- WAITING_APPROVAL state
- approval_required SSE event

### Phase 11: UI
- Upgrade ToolCallCard to AgentActivityPanel
- Show goal, plan progress, activity, observations, evidence, verification
- Expandable/collapsible sections

### Phase 12: Cancellation
- AbortController → backend asyncio.CancelledError
- Emit cancelled event
- Persist correct state

### Phase 13: Memory/Context
- Summarize old tool results
- Keep only necessary context

### Phase 14: Sovereignty
- Show sovereignty status in plan event
- "Local AI provider unavailable" when Ollama down

### Phase 15: Audit
- Per-step audit events using existing AuditService

### Phase 16: Testing
- 24 test cases covering all scenarios

### Phase 17: Real E2E
- SIH scenario: "Investigate why Bearing B-204 is overheating"
