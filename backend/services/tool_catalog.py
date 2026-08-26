"""
Tool & Plugin catalog service.

- Plugins are CODE-DEFINED manifests bundling existing registered tools.
  No arbitrary plugin code is ever executed.
- A disabled plugin disables all tools it provides.
- Per-tool enable/disable + JSON config are persisted in tool_settings /
  plugin_settings and overlaid onto the registry singleton at request time.
- Secret-looking config values (key/token/secret/password) are returned MASKED.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.tool_settings import ToolSetting, PluginSetting
from tools.registry import get_registry, ROLE_VIEWER

logger = logging.getLogger(__name__)

_SECRET_KEY_RE = re.compile(r"(key|token|secret|password)", re.I)

# ---------------------------------------------------------------------------
# Plugin manifests — code-defined, validated shape. Tools MUST already exist
# in the registry; a manifest referencing an unknown tool fails validation.
# ---------------------------------------------------------------------------
PLUGIN_MANIFESTS: list[dict[str, Any]] = [
    {
        "id": "core-utilities",
        "name": "Core Utilities",
        "version": "1.0.0",
        "description": "Calculator, date/time, agent self-discovery helpers.",
        "author": "Sovereign AI Workbench",
        "tools": ["calculator", "time_now", "tool_discovery", "model_select"],
        "permissions": [],
        "default_enabled": True,
    },
    {
        "id": "web-research",
        "name": "Web Research",
        "version": "1.0.0",
        "description": "Internet search plus page fetching for up-to-date answers.",
        "author": "Sovereign AI Workbench",
        "tools": ["web_search", "web_fetch"],
        "permissions": ["internet_access"],
        "default_enabled": True,
    },
    {
        "id": "document-tools",
        "name": "Document Assistant",
        "version": "1.0.0",
        "description": "Read workspace files and search knowledge bases (RAG).",
        "author": "Sovereign AI Workbench",
        "tools": ["file_read", "file_list", "search_kb"],
        "permissions": ["workspace_filesystem_read", "knowledge_base_read"],
        "default_enabled": True,
    },
    {
        # Dangerous by design → DISABLED by default. Enabling requires admin.
        "id": "advanced-workspace",
        "name": "Advanced Workspace",
        "version": "1.0.0",
        "description": (
            "File write/delete and sandboxed Python execution. "
            "High-risk: disabled until explicitly enabled by an administrator."
        ),
        "author": "Sovereign AI Workbench",
        "tools": ["file_write", "file_delete", "python_exec"],
        "permissions": ["workspace_filesystem_write", "sandboxed_code_execution"],
        "default_enabled": False,
    },
]


def _validate_manifests() -> None:
    reg = get_registry()
    for m in PLUGIN_MANIFESTS:
        for t in m["tools"]:
            if reg.get(t) is None:
                raise RuntimeError(
                    f"Plugin '{m['id']}' references unknown tool '{t}'")


def _mask(value: str) -> str:
    return ("••••" + value[-4:]) if len(value) >= 4 else "••••"


def _masked_config(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return {}
    out = {}
    for k, v in config.items():
        out[k] = _mask(str(v)) if (_SECRET_KEY_RE.search(k) and v) else v
    return out


class ToolCatalogService:
    """Overlay DB state onto the registry; expose catalog views."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -- internal ---------------------------------------------------------
    async def _plugin_states(self) -> dict[str, bool]:
        res = await self.db.execute(select(PluginSetting))
        states = {r.id: r.enabled for r in res.scalars().all()}
        # Seed defaults lazily
        missing = [m for m in PLUGIN_MANIFESTS if m["id"] not in states]
        for m in missing:
            row = PluginSetting(id=m["id"], enabled=m["default_enabled"])
            self.db.add(row)
            states[m["id"]] = m["default_enabled"]
        if missing:
            await self.db.flush()
        return states

    async def _tool_states(self) -> dict[str, ToolSetting]:
        res = await self.db.execute(select(ToolSetting))
        return {r.name: r for r in res.scalars().all()}

    def _plugin_for(self, tool_name: str) -> dict | None:
        for m in PLUGIN_MANIFESTS:
            if tool_name in m["tools"]:
                return m
        return None

    # -- public -----------------------------------------------------------
    async def sync(self) -> dict[str, bool]:
        """Apply DB overrides onto the registry singleton. Cheap; call per request."""
        plugin_states = await self._plugin_states()
        tool_rows = await self._tool_states()
        reg = get_registry()
        for t in reg.list_all():
            provided_by = self._plugin_for(t.name)
            plugin_ok = (provided_by is None) or \
                plugin_states.get(provided_by["id"], False)
            override = tool_rows.get(t.name)
            t.enabled = plugin_ok and (override.enabled if override else True)
        return plugin_states

    async def list_tools(self) -> list[dict]:
        await self.sync()
        reg = get_registry()
        tool_rows = await self._tool_states()
        plugin_states = await self._plugin_states()
        out = []
        for t in reg.list_all():
            provided = self._plugin_for(t.name)
            out.append({
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "version": t.version,
                "risk_level": t.risk_level,
                "required_role": t.required_role,
                "permissions": t.permissions,
                "tags": t.tags,
                "enabled": t.enabled,
                "available": t.enabled,
                "requires_sandbox": t.requires_sandbox,
                "config": _masked_config(
                    json.loads(tool_rows[t.name].config_json)
                    if tool_rows.get(t.name) and tool_rows[t.name].config_json else {}
                ) if True else {},
                "config_keys": t.config_keys,
                "provided_by": provided["id"] if provided else None,
                "input_schema": t.input_schema.model_json_schema().get("properties", {}),
            })
        _ = plugin_states
        return out

    async def set_tool_enabled(self, name: str, enabled: bool) -> dict:
        reg = get_registry()
        if reg.get_definition_any_state(name) is None:
            raise KeyError(name)
        row = await self.db.get(ToolSetting, name)
        if row is None:
            row = ToolSetting(name=name); self.db.add(row)
        row.enabled = enabled
        await self.db.flush()
        await self.sync()
        return {"name": name, "enabled": enabled}

    async def set_tool_config(self, name: str, config: dict) -> dict:
        reg = get_registry()
        d = reg.get_definition_any_state(name)
        if d is None:
            raise KeyError(name)
        allowed = set(d.config_keys or [])
        # Tools with no declared config_keys accept no configuration at all
        clean = {k: v for k, v in config.items() if k in allowed}
        row = await self.db.get(ToolSetting, name)
        if row is None:
            row = ToolSetting(name=name); self.db.add(row)
        row.config_json = json.dumps(clean)
        await self.db.flush()
        return {"name": name, "config": _masked_config(clean)}

    async def list_plugins(self) -> list[dict]:
        plugin_states = await self._plugin_states()
        reg = get_registry()
        out = []
        for m in PLUGIN_MANIFESTS:
            enabled = plugin_states.get(m["id"], False)
            tools = []
            for tn in m["tools"]:
                d = reg.get_definition_any_state(tn)
                tools.append({"name": tn, "enabled": bool(d and d.enabled)})
            out.append({**{k: v for k, v in m.items() if k != "default_enabled"},
                        "enabled": enabled, "tools_detail": tools})
        return out

    async def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> dict:
        manifest = next((m for m in PLUGIN_MANIFESTS if m["id"] == plugin_id), None)
        if manifest is None:
            raise KeyError(plugin_id)
        row = await self.db.get(PluginSetting, plugin_id)
        if row is None:
            row = PluginSetting(id=plugin_id); self.db.add(row)
        row.enabled = enabled
        await self.db.flush()
        await self.sync()
        return {"id": plugin_id, "enabled": enabled}

    # -- planner ------------------------------------------------------------
    async def plan_task(self, goal: str, user_role: str = ROLE_VIEWER) -> dict:
        """
        Heuristic task classification + model/tool/plugin recommendation.
        Deterministic rules first (cheap, testable); no capability invention.
        """
        g = goal.lower()
        task_type = "reasoning"
        recommended: list[str] = []

        mathish = any(k in g for k in ("calculate", "compute", "what is ",
                                       "+", "×", "*", "/")) and \
            any(ch.isdigit() for ch in g)
        webish = any(k in g for k in ("search", "latest", "news", "internet",
                                      "current", "today's", "online"))
        docish = any(k in g for k in ("document", "pdf", "uploaded",
                                      "knowledge base", "my file", "kb"))

        if mathish and not webish and not docish:
            task_type = "fast"; recommended.append("calculator")
            if "time" in g or "now" in g or "today" in g:
                recommended.append("time_now")
        elif docish:
            task_type = "reasoning"
            recommended += ["file_read", "search_kb"]
            if "write" in g or "report" in g or "create" in g:
                recommended.append("file_write")
        elif webish:
            task_type = "reasoning"
            recommended += ["web_search", "web_fetch"]

        # Keep only tools actually available to this role right now
        await self.sync()
        reg = get_registry()
        available = {t.name for t in reg.list_enabled(user_role=user_role)}
        tools_final = [t for t in recommended if t in available]
        plugins_used = sorted({self._plugin_for(t)["id"]
                               for t in tools_final if self._plugin_for(t)})

        # Model suggestion from discovered catalog (metadata-driven only)
        model = await self._suggest_model(task_type)
        return {"task_type": task_type, "model": model,
                "tools": tools_final, "plugins": plugins_used}

    async def _suggest_model(self, task_type: str) -> dict | None:
        try:
            from tools.meta_tools import ModelSelectInput, model_select_execute
            res = await model_select_execute(
                ModelSelectInput(task_type=task_type or None, limit=1), {})
            cands = res.get("candidates") or []
            return ({**cands[0], "auto": True} if cands else None)
        except Exception:
            return None


async def ensure_seeded(db: AsyncSession) -> None:
    """Validate manifests once; plugin defaults are seeded lazily by sync()."""
    _validate_manifests()
