"""
Tool Registry — the ONLY gateway between LLM proposals and execution.

Security invariant (NON-NEGOTIABLE):
  LLM proposes an action → registry validates name/schema/permission/risk
  → approval gate if High/Critical → execution via controlled handler
  → audit logged

The LLM NEVER executes anything directly.
No shell=True, no exec(), no eval(), no os.system().
Every tool call must flow through ToolRegistry.execute().
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Risk levels — determines approval requirement
RISK_LOW      = "low"
RISK_MEDIUM   = "medium"
RISK_HIGH     = "high"
RISK_CRITICAL = "critical"

# Roles that may invoke tools
ROLE_VIEWER  = "viewer"
ROLE_ANALYST = "analyst"
ROLE_ADMIN   = "admin"

_ROLE_RANK = {ROLE_VIEWER: 0, ROLE_ANALYST: 1, ROLE_ADMIN: 2}


@dataclass
class ToolDefinition:
    name: str
    description: str          # shown verbatim to the LLM
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    risk_level: str            # low | medium | high | critical
    required_role: str         # minimum role allowed to invoke
    requires_sandbox: bool     # True → execution goes through SandboxService
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    category: str = "utilities"          # UI grouping
    version: str = "1.0.0"
    # Explicit permission identifiers — surfaced in API/UI, enforced by policy:
    permissions: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)  # operator-settable keys
    # Async handler: (validated_input, context) -> dict
    # context carries workspace_path, rag_service, etc.
    handler: Callable[..., Awaitable[dict]] | None = None


class ToolRegistry:
    """
    Central registry.  All tool invocations must go through .execute().
    Callers MUST:
      1. Call .get(name) → ToolDefinition
      2. Call .check_permission(tool, user_role)
      3. Consult .requires_approval(tool) → send for human review if True
      4. Call .validate_input(tool, raw_input) → validated Pydantic model
      5. Call .execute(tool, validated_input, context) → result dict
    This sequence is enforced by AgentService.  No shortcutting allowed.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' already registered")
        self._tools[definition.name] = definition
        logger.debug("Registered tool: %s (risk=%s)", definition.name, definition.risk_level)

    def get(self, name: str) -> ToolDefinition | None:
        t = self._tools.get(name)
        return t if (t and t.enabled) else None

    def get_definition_any_state(self, name: str) -> ToolDefinition | None:
        """Return definition even when disabled — for management endpoints."""
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_enabled(self, user_role: str | None = None) -> list[ToolDefinition]:
        tools = [t for t in self._tools.values() if t.enabled]
        if user_role:
            tools = [t for t in tools if self._role_ok(t.required_role, user_role)]
        return tools

    def check_permission(self, tool: ToolDefinition, user_role: str) -> None:
        """Raises PermissionError if user_role is insufficient."""
        if not self._role_ok(tool.required_role, user_role):
            raise PermissionError(
                f"Tool '{tool.name}' requires role '{tool.required_role}', "
                f"caller has '{user_role}'"
            )

    def requires_approval(
        self, tool: ToolDefinition, approval_threshold: str = RISK_HIGH
    ) -> bool:
        """
        Return True when the tool's risk level is >= approval_threshold.
        Default threshold = HIGH (High and Critical require human approval).
        LOW and MEDIUM are auto-approved.
        """
        order = [RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL]
        tool_idx = order.index(tool.risk_level) if tool.risk_level in order else 0
        thresh_idx = order.index(approval_threshold) if approval_threshold in order else 2
        return tool_idx >= thresh_idx

    def validate_input(
        self, tool: ToolDefinition, raw_input: dict
    ) -> BaseModel:
        """
        Validate and coerce raw LLM-supplied input through the tool's Pydantic schema.
        Raises pydantic.ValidationError on failure.
        IMPORTANT: validated output is what gets executed — not the raw LLM text.
        """
        return tool.input_schema.model_validate(raw_input)

    async def execute(
        self,
        tool: ToolDefinition,
        validated_input: BaseModel,
        context: dict,
    ) -> dict:
        """
        Execute the tool handler with the VALIDATED (not raw) input.
        The handler must be an async function (validated_input, context) → dict.
        """
        if tool.handler is None:
            raise RuntimeError(f"Tool '{tool.name}' has no handler registered")
        result = await tool.handler(validated_input, context)
        return result

    def get_tool_list_for_prompt(
        self, allowed_names: list[str] | None = None, user_role: str = ROLE_ANALYST
    ) -> str:
        """
        Format enabled tools for injection into the LLM system prompt.
        Only shows tools the user's role can actually invoke.
        Includes required fields so the LLM knows which parameters are mandatory.
        """
        tools = self.list_enabled(user_role)
        if allowed_names:
            tools = [t for t in tools if t.name in allowed_names]

        lines: list[str] = []
        for t in tools:
            try:
                schema = t.input_schema.model_json_schema()
                required_set = set(schema.get("required", []))
                props = {}
                for k, v in schema.get("properties", {}).items():
                    type_str = v.get("type", v.get("anyOf", "any"))
                    if k in required_set:
                        props[k] = f"{type_str} (required)"
                    else:
                        props[k] = type_str
            except Exception:
                props = {}
            lines.append(
                f"- {t.name}: {t.description} "
                f"Input schema: {json.dumps(props)}. "
                f"Risk: {t.risk_level.upper()}."
            )
        return "\n".join(lines)

    @staticmethod
    def _role_ok(required: str, actual: str) -> bool:
        return _ROLE_RANK.get(actual, 0) >= _ROLE_RANK.get(required, 0)


# Module-level singleton — imported everywhere
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_builtin_tools(_registry)
    return _registry


def _register_builtin_tools(reg: ToolRegistry) -> None:
    """Register all built-in tools.  Import handlers here (not at module top)."""
    from tools import file_read, file_list, file_write, file_delete
    from tools import search_kb, calculator, python_exec
    from tools import web, meta_tools
    from tools import system_status, sensor_tool, vision_tool, incident_tool
    from tools import org_search
    from tools import terminal
    from tools import subagent_tool

    reg.register(ToolDefinition(
        name="file_read",
        description=(
            "Read the text contents of a file inside the agent workspace. "
            "Path must be relative (e.g. 'report.csv'). No directory traversal."
        ),
        input_schema=file_read.FileReadInput,
        output_schema=file_read.FileReadOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=file_read.execute,
        tags=["file"],
        category="files",
        permissions=["workspace_filesystem_read"],
    ))

    reg.register(ToolDefinition(
        name="file_list",
        description="List files in the agent workspace directory.",
        input_schema=file_list.FileListInput,
        output_schema=file_list.FileListOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=file_list.execute,
        tags=["file"],
        category="files",
        permissions=["workspace_filesystem_read"],
    ))

    reg.register(ToolDefinition(
        name="file_write",
        description=(
            "Write text content to a file in the agent workspace. "
            "Creates the file if it does not exist. Path must be relative."
        ),
        input_schema=file_write.FileWriteInput,
        output_schema=file_write.FileWriteOutput,
        risk_level=RISK_MEDIUM,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=file_write.execute,
        tags=["file"],
        category="files",
        permissions=["workspace_filesystem_write"],
    ))

    reg.register(ToolDefinition(
        name="file_delete",
        description=(
            "Permanently delete a file from the agent workspace. "
            "This action is IRREVERSIBLE. Path must be relative."
        ),
        input_schema=file_delete.FileDeleteInput,
        output_schema=file_delete.FileDeleteOutput,
        risk_level=RISK_HIGH,
        required_role=ROLE_ADMIN,
        requires_sandbox=False,
        handler=file_delete.execute,
        tags=["file", "destructive"],
        category="files",
        permissions=["workspace_filesystem_write"],
    ))

    reg.register(ToolDefinition(
        name="search_kb",
        description=(
            "Search a knowledge base for relevant information. "
            "Returns matching text chunks with relevance scores."
        ),
        input_schema=search_kb.SearchKBInput,
        output_schema=search_kb.SearchKBOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=search_kb.execute,
        tags=["knowledge", "rag"],
        category="knowledge",
        version="1.1.0",
        permissions=["knowledge_base_read"],
    ))

    reg.register(ToolDefinition(
        name="calculator",
        description=(
            "Evaluate a safe mathematical expression. "
            "Supports +, -, *, /, **, %, parentheses, and basic math functions."
        ),
        input_schema=calculator.CalculatorInput,
        output_schema=calculator.CalculatorOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_VIEWER,
        requires_sandbox=False,
        handler=calculator.execute,
        tags=["compute"],
        category="utilities",
        permissions=[],           # no special permission needed
    ))

    reg.register(ToolDefinition(
        name="time_now",
        description=(
            "Get the current date and time (UTC or with a minute offset). "
            "Useful for 'today', 'now', deadline arithmetic."
        ),
        input_schema=meta_tools.TimeNowInput,
        output_schema=meta_tools.TimeNowOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_VIEWER,
        requires_sandbox=False,
        handler=meta_tools.time_now_execute,
        tags=["utilities"],
        category="utilities",
        permissions=[],
    ))

    reg.register(ToolDefinition(
        name="web_search",
        description=(
            "Search the public internet for current information. "
            "Returns a list of result titles and URLs."
        ),
        input_schema=web.WebSearchInput,
        output_schema=web.WebSearchOutput,
        risk_level=RISK_MEDIUM,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=web.web_search_execute,
        tags=["web"],
        category="web",
        version="1.0.0",
        permissions=["internet_access"],
        config_keys=["provider"],          # default: duckduckgo (keyless)
    ))

    reg.register(ToolDefinition(
        name="web_fetch",
        description=(
            "Fetch a web page by URL and return its readable text content. "
            "Only public http(s) pages; private network addresses are blocked."
        ),
        input_schema=web.WebFetchInput,
        output_schema=web.WebFetchOutput,
        risk_level=RISK_MEDIUM,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=web.web_fetch_execute,
        tags=["web"],
        category="web",
        version="1.0.0",
        permissions=["internet_access"],
    ))

    reg.register(ToolDefinition(
        name="tool_discovery",
        description=(
            "Discover which tools are currently available to you. "
            "Call this before guessing a tool exists."
        ),
        input_schema=meta_tools.ToolDiscoveryInput,
        output_schema=meta_tools.ToolDiscoveryOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_VIEWER,
        requires_sandbox=False,
        handler=meta_tools.tool_discovery_execute,
        tags=["agent"],
        category="agent",
        version="1.0.0",
        permissions=[],
    ))

    reg.register(ToolDefinition(
        name="model_select",
        description=(
            "List available LLM models from connected providers, optionally "
            "filtered by task type (reasoning/coding/fast/embedding). "
            "Read-only; helps pick the right model for a task."
        ),
        input_schema=meta_tools.ModelSelectInput,
        output_schema=meta_tools.ModelSelectOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_VIEWER,
        requires_sandbox=False,
        handler=meta_tools.model_select_execute,
        tags=["agent", "models"],
        category="agent",
        version="1.0.0",
        permissions=[],
    ))

    reg.register(ToolDefinition(
        name="python_exec",
        description=(
            "Execute Python code in an ISOLATED Docker sandbox. "
            "The sandbox has NO network access, NO host filesystem access. "
            "pandas, numpy are available. Output via print(). "
            "WARNING: This tool requires administrator approval."
        ),
        input_schema=python_exec.PythonExecInput,
        output_schema=python_exec.PythonExecOutput,
        risk_level=RISK_HIGH,
        required_role=ROLE_ADMIN,
        requires_sandbox=True,
        handler=python_exec.execute,
        tags=["compute", "sandbox"],
        category="advanced",
        permissions=["sandboxed_code_execution"],
    ))

    # ---- Domain tools (Sovereign AI Workbench specific) ----

    reg.register(ToolDefinition(
        name="system_status",
        description=(
            "Check the status of local AI services: Ollama availability, "
            "installed models, and sandbox status. Read-only."
        ),
        input_schema=system_status.SystemStatusInput,
        output_schema=system_status.SystemStatusOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_VIEWER,
        requires_sandbox=False,
        handler=system_status.execute,
        tags=["system", "status"],
        category="system",
        version="1.0.0",
        permissions=[],
    ))

    reg.register(ToolDefinition(
        name="sensor_analysis",
        description=(
            "Analyze sensor data (CSV) for anomalies, risk assessment, "
            "and trend detection. Use an existing analysis_id to retrieve "
            "results, or provide csv_data to run a new analysis."
        ),
        input_schema=sensor_tool.SensorAnalysisInput,
        output_schema=sensor_tool.SensorAnalysisOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=sensor_tool.execute,
        tags=["sensor", "analysis"],
        category="domain",
        version="1.0.0",
        permissions=["sensor_data_read"],
    ))

    reg.register(ToolDefinition(
        name="vision_inspection",
        description=(
            "Retrieve vision inspection results for an image or incident. "
            "Returns findings, severity, and confidence when available."
        ),
        input_schema=vision_tool.VisionInspectionInput,
        output_schema=vision_tool.VisionInspectionOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=vision_tool.execute,
        tags=["vision", "inspection"],
        category="domain",
        version="1.0.0",
        permissions=["vision_data_read"],
    ))

    reg.register(ToolDefinition(
        name="incident_get",
        description=(
            "Get details of an incident by ID. Returns title, machine, "
            "asset tag, risk level, and status. Only accessible to the "
            "incident owner or admins."
        ),
        input_schema=incident_tool.IncidentGetInput,
        output_schema=incident_tool.IncidentGetOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=incident_tool.execute_get,
        tags=["incident"],
        category="domain",
        version="1.0.0",
        permissions=["incident_read"],
    ))

    reg.register(ToolDefinition(
        name="incident_investigate",
        description=(
            "Run an evidence-grounded investigation on an incident. "
            "Collects sensor data, document references, and vision findings "
            "to produce a grounded risk assessment."
        ),
        input_schema=incident_tool.IncidentInvestigateInput,
        output_schema=incident_tool.IncidentInvestigateOutput,
        risk_level=RISK_MEDIUM,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=incident_tool.execute_investigate,
        tags=["incident", "investigation"],
        category="domain",
        version="1.0.0",
        permissions=["incident_read"],
    ))

    reg.register(ToolDefinition(
        name="search_org_data",
        description=(
            "Search organization data: company profiles, employee details, "
            "departments, contacts, infrastructure, and financials. "
            "Use this when the user asks about a specific organization, "
            "its employees, departments, or any company-related information."
        ),
        input_schema=org_search.OrgSearchInput,
        output_schema=org_search.OrgSearchOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=org_search.execute,
        tags=["organization", "data", "search"],
        category="domain",
        version="1.0.0",
        permissions=[],
    ))

    # ---- Terminal tools ----

    reg.register(ToolDefinition(
        name="run_command",
        description=(
            "Execute a shell command (cmd/bash) on the host system. "
            "Returns stdout, stderr, and exit code. "
            "Timeout enforced (default 30s, max 120s). "
            "WARNING: This tool requires administrator approval."
        ),
        input_schema=terminal.RunCommandInput,
        output_schema=terminal.RunCommandOutput,
        risk_level=RISK_HIGH,
        required_role=ROLE_ADMIN,
        requires_sandbox=False,
        handler=terminal.execute_command,
        tags=["terminal", "shell", "command"],
        category="terminal",
        version="1.0.0",
        permissions=["terminal_execution"],
    ))

    reg.register(ToolDefinition(
        name="run_powershell",
        description=(
            "Execute a PowerShell script or command on the host system. "
            "Returns stdout, stderr, and exit code. "
            "Useful for Windows system administration, file operations, and automation. "
            "Timeout enforced (default 30s, max 120s). "
            "WARNING: This tool requires administrator approval."
        ),
        input_schema=terminal.RunPowerShellInput,
        output_schema=terminal.RunPowerShellOutput,
        risk_level=RISK_HIGH,
        required_role=ROLE_ADMIN,
        requires_sandbox=False,
        handler=terminal.execute_powershell,
        tags=["terminal", "powershell", "command"],
        category="terminal",
        version="1.0.0",
        permissions=["terminal_execution"],
    ))

    # ---- Sub-agent tools ----

    reg.register(ToolDefinition(
        name="spawn_subagent",
        description=(
            "Spawn a specialized sub-agent to work on an independent task in parallel. "
            "Sub-agents run with their own context and tool set. "
            "Agent types: researcher, coder, tester, reviewer, security, data_analyst."
        ),
        input_schema=subagent_tool.SpawnSubagentInput,
        output_schema=subagent_tool.SpawnSubagentOutput,
        risk_level=RISK_MEDIUM,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=subagent_tool.execute_spawn,
        tags=["agent", "subagent"],
        category="agent",
        version="1.0.0",
        permissions=["subagent_spawn"],
    ))

    reg.register(ToolDefinition(
        name="get_subagent_result",
        description=(
            "Wait for a sub-agent to complete and retrieve its result. "
            "Returns findings, artifacts, and summary."
        ),
        input_schema=subagent_tool.GetSubagentResultInput,
        output_schema=subagent_tool.GetSubagentResultOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=subagent_tool.execute_get_result,
        tags=["agent", "subagent"],
        category="agent",
        version="1.0.0",
        permissions=["subagent_read"],
    ))

    reg.register(ToolDefinition(
        name="list_subagents",
        description="List all active and completed sub-agents for the current session.",
        input_schema=subagent_tool.ListSubagentsInput,
        output_schema=subagent_tool.ListSubagentsOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_VIEWER,
        requires_sandbox=False,
        handler=subagent_tool.execute_list,
        tags=["agent", "subagent"],
        category="agent",
        version="1.0.0",
        permissions=["subagent_read"],
    ))

    reg.register(ToolDefinition(
        name="cancel_subagent",
        description="Cancel a running sub-agent.",
        input_schema=subagent_tool.CancelSubagentInput,
        output_schema=subagent_tool.CancelSubagentOutput,
        risk_level=RISK_LOW,
        required_role=ROLE_ANALYST,
        requires_sandbox=False,
        handler=subagent_tool.execute_cancel,
        tags=["agent", "subagent"],
        category="agent",
        version="1.0.0",
        permissions=["subagent_cancel"],
    ))
