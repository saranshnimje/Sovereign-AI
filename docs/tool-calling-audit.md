# Tool-Calling Audit — Sovereign AI Workbench

**Date:** 2026-08-26
**Status:** Phase 0 Complete

## Existing Tool Inventory

| Tool | Exists | Registered | Executable | Real | AuthZ | Audited | UI Status |
|------|--------|------------|------------|------|-------|---------|-----------|
| file_read | YES | YES | YES | REAL | role+workspace | YES | basic activity |
| file_list | YES | YES | YES | REAL | role+workspace | YES | basic activity |
| file_write | YES | YES | YES | REAL | role+workspace | YES | basic activity |
| file_delete | YES | YES | YES | REAL | role+workspace+approval | YES | basic activity |
| search_kb | YES | YES | YES | REAL | role+KB ownership | YES | basic activity |
| calculator | YES | YES | YES | REAL | role | YES | basic activity |
| time_now | YES | YES | YES | REAL | role | YES | basic activity |
| web_search | YES | YES | YES | REAL | role+SSRF guard | YES | basic activity |
| web_fetch | YES | YES | YES | REAL | role+SSRF guard | YES | basic activity |
| tool_discovery | YES | YES | YES | REAL | role | YES | basic activity |
| model_select | YES | YES | YES | REAL | role | YES | basic activity |
| python_exec | YES | YES | YES | REAL | role+sandbox+approval | YES | basic activity |
| system_status | NO | NO | NO | - | - | - | - |
| sensor_analysis | NO | NO | NO | - | - | - | - |
| vision_inspection | NO | NO | NO | - | - | - | - |
| incident_get | NO | NO | NO | - | - | - | - |
| incident_investigate | NO | NO | NO | - | - | - | - |

## Architecture Assessment

### What Already Exists
1. **ToolRegistry** — full security gateway with permission, validation, execution, approval
2. **AgentService** — complete LLM tool loop (separate from chat)
3. **Chat `/agent` endpoint** — heuristic planner + tool execution + SSE streaming
4. **Frontend** — handles `tool`, `plan`, `token`, `done` SSE events; basic activity list
5. **12 registered tools** — all real, all executable, all audited

### What's Missing
1. **Domain tools** — no sensor/vision/incident tools in registry
2. **LLM-driven tool selection** — `/agent` uses heuristic planner, not LLM reasoning
3. **Rich tool UI** — basic list, no ToolCallCard with expandable details
4. **Rich SSE events** — tool events lack duration_ms, input_summary, result_summary
5. **Chat integration** — tool calling only in separate `/agent` endpoint, not in main chat

### Key Decision
Enhance the existing `/agent` endpoint rather than create a new system. The infrastructure is solid — we add domain tools, upgrade the planner to LLM-driven, enrich SSE events, and build a proper UI.
