"""
Sub-agent data types — shared types for the multi-agent system.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubAgentResult:
    """Result returned by a sub-agent upon completion."""
    agent_id: str
    agent_type: str
    status: str  # completed | failed | cancelled
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    tool_calls_made: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "summary": self.summary,
            "findings": self.findings,
            "artifacts": self.artifacts,
            "files_changed": self.files_changed,
            "recommendations": self.recommendations,
            "verification": self.verification,
            "tool_calls_made": self.tool_calls_made,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class SubAgentSession:
    """A running sub-agent session."""
    id: str
    parent_id: str | None
    task: str
    agent_type: str  # researcher | coder | tester | reviewer | security | data_analyst
    status: str  # running | completed | failed | cancelled
    model: str
    depth: int  # nesting level (0 = main agent)
    result: SubAgentResult | None = None
    started_at: float = 0.0
    completed_at: float | None = None
    todo: list[dict[str, Any]] = field(default_factory=list)
    activity: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "task": self.task,
            "agent_type": self.agent_type,
            "status": self.status,
            "model": self.model,
            "depth": self.depth,
            "result": self.result.to_dict() if self.result else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


# Agent type descriptions for the LLM
AGENT_TYPE_DESCRIPTIONS = {
    "researcher": (
        "Research agent — searches the web, reads documentation, gathers information. "
        "Best for: finding facts, checking documentation, gathering context."
    ),
    "coder": (
        "Coder agent — reads, writes, and edits code files. Runs commands and tests. "
        "Best for: implementing features, fixing bugs, writing scripts."
    ),
    "tester": (
        "Tester agent — runs tests, validates code, checks for regressions. "
        "Best for: verifying implementations, running test suites, checking outputs."
    ),
    "reviewer": (
        "Reviewer agent — reviews code quality, checks for issues, suggests improvements. "
        "Best for: code review, security audit, quality checks."
    ),
    "security": (
        "Security agent — analyzes for vulnerabilities, checks permissions, audits access. "
        "Best for: security analysis, vulnerability scanning, policy checks."
    ),
    "data_analyst": (
        "Data analyst agent — queries databases, analyzes data, generates reports. "
        "Best for: data analysis, report generation, statistical analysis."
    ),
}

# Available tools per agent type
AGENT_TYPE_TOOLS = {
    "researcher": ["web_search", "web_fetch", "search_kb", "search_org_data", "file_read", "file_list"],
    "coder": ["file_read", "file_list", "file_write", "run_command", "run_powershell", "python_exec"],
    "tester": ["file_read", "file_list", "run_command", "run_powershell", "python_exec"],
    "reviewer": ["file_read", "file_list", "run_command"],
    "security": ["file_read", "file_list", "run_command", "web_search", "search_kb"],
    "data_analyst": ["file_read", "file_list", "search_kb", "search_org_data", "calculator", "run_command"],
}
