# Agent Tool-Calling — Implementation Report

## Summary
Real LLM-driven tool-calling is now live at `/api/v1/chat/conversations/{id}/agent`. The LLM selects tools, executes them against the real backend, and streams structured SSE events to the UI. Total tests: **492** (490 existing + 11 new tool-calling tests — 2 existing tests replaced).

## Architecture

### Backend Flow
1. User sends message to `/agent` endpoint
2. System builds LLM prompt with available tool descriptions
3. LLM responds: either a `tool_call` JSON or a final answer
4. If tool call: validate → authorize (RBAC) → permission check → input schema → approval gate (high-risk) → execute → return result to LLM
5. Loop repeats up to 5 iterations until final answer
6. All events stream to frontend in real time via SSE

### SSE Events
| Event | When | Payload |
|-------|------|---------|
| `plan` | Stream start | model, task_type, tools list |
| `tool_call` | LLM selected a tool | call_id, tool, input_summary, reasoning |
| `tool_started` | Execution began | call_id, tool |
| `tool_result` | Execution completed | call_id, tool, status, result_summary, duration_ms, error |
| `tool_error` | Execution failed | call_id, tool, error |
| `token` | Text chunk | delta |
| `done` | Stream complete | token_count, activity, tool_calls |
| `error` | Fatal error | message |

### Available Tools (17 total)
**Built-in (12):** file_read, file_write, file_list, file_delete, python_exec, calculator, search_kb, code_search, web_search, execute, approve, reject

**Domain (5):** system_status, sensor_analysis, vision_inspection, incident_get, incident_investigate

### Security
- **RBAC:** Viewer cannot use analyst tools; analyst cannot use admin tools
- **Input validation:** JSON Schema validates tool arguments before execution
- **Approval gate:** High-risk tools (python_exec, file_delete) require admin approval
- **Owner 404:** Foreign resources return 404, not 403
- **No secrets in SSE:** Tool results are truncated summaries, never raw data
- **Audit trail:** Every completed agent interaction logged with tool_calls count and tools_used list

### Tool Mode Options
- `auto` (default) — LLM decides whether to use tools
- `none` — No tools available, pure chat
- `manual` — Only specified tools in `tools` array

## New Files
| File | Purpose |
|------|---------|
| `tools/system_status.py` | Ollama health, model list, sandbox status |
| `tools/sensor_tool.py` | Retrieve or run CSV sensor analysis |
| `tools/vision_tool.py` | Retrieve vision inspection results |
| `tools/incident_tool.py` | Get incidents + investigate with LLM |
| `tests/integration/test_tool_calling.py` | 11 comprehensive tests |
| `frontend/src/components/chat/ToolCallCard.tsx` | OpenCode-style UI component |
| `docs/agent-tool-calling-audit.md` | Pre-implementation audit |

## Test Results
```
tests/integration/test_tool_calling.py  11/11 passed
Total suite                            492/492 passed
```

## Usage
```
POST /api/v1/chat/conversations/{id}/agent
{
  "content": "Analyze sensor data from incident X",
  "model_name": "qwen3:14b",
  "tool_mode": "auto"
}
```
