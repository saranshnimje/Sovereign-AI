"""
Integration tests: Tools management, Plugin manifests, agent planning,
permission enforcement and security invariants.
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def admin_viewer(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "email": "ta@x.com", "username": "tool_admin", "password": "StrongPass123!"})
    ra = await client.post("/api/v1/auth/login", json={
        "email": "ta@x.com", "password": "StrongPass123!"})
    await client.post("/api/v1/auth/register", json={
        "email": "tv@x.com", "username": "tool_viewer", "password": "StrongPass123!"})
    rv = await client.post("/api/v1/auth/login", json={
        "email": "tv@x.com", "password": "StrongPass123!"})
    a = AsyncClient(transport=client._transport, base_url="http://testserver")
    v = AsyncClient(transport=client._transport, base_url="http://testserver")
    a.headers.update({"Authorization": f"Bearer {ra.json()['access_token']}"})
    v.headers.update({"Authorization": f"Bearer {rv.json()['access_token']}"})
    yield a, v
    await a.aclose(); await v.aclose()


# ------------------------------------------------------------------
# Tools listing / metadata
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_list_has_metadata(admin_viewer):
    a, _ = admin_viewer
    r = await a.get("/api/v1/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert {"web_search", "web_fetch", "calculator", "time_now",
            "search_kb", "file_read", "tool_discovery",
            "model_select"} <= names
    ws = next(t for t in r.json() if t["name"] == "web_search")
    assert ws["category"] == "web"
    assert ws["permissions"] == ["internet_access"]
    assert ws["provided_by"] == "web-research"


@pytest.mark.asyncio
async def test_dangerous_plugin_disabled_by_default(admin_viewer):
    """Advanced Workspace (file_write/delete, python_exec) is OFF by default."""
    a, _ = admin_viewer
    plugins = {p["id"]: p for p in (await a.get("/api/v1/plugins")).json()}
    assert plugins["advanced-workspace"]["enabled"] is False
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    for t in ("file_write", "file_delete", "python_exec"):
        assert tools[t]["enabled"] is False, t
    # Safe defaults ON
    assert tools["calculator"]["enabled"] is True
    assert tools["web_search"]["enabled"] is True


# ------------------------------------------------------------------
# Enable / disable + RBAC
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disable_enable_tool_roundtrip(admin_viewer):
    a, _ = admin_viewer
    r = await a.post("/api/v1/tools/calculator/disable")
    assert r.status_code == 200
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    assert tools["calculator"]["enabled"] is False
    r = await a.post("/api/v1/tools/calculator/enable")
    assert (await a.get("/api/v1/tools")).json() is not None
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    assert tools["calculator"]["enabled"] is True


@pytest.mark.asyncio
async def test_viewer_cannot_toggle_tool(admin_viewer):
    _, v = admin_viewer
    r = await v.post("/api/v1/tools/calculator/disable")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_cannot_list_tools(client: AsyncClient):
    r = await client.get("/api/v1/tools")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unknown_tool_404(admin_viewer):
    a, _ = admin_viewer
    r = await a.post("/api/v1/tools/nope-tool/disable")
    assert r.status_code == 404


# ------------------------------------------------------------------
# Plugin ↔ tool relationship
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabling_plugin_disables_its_tools(admin_viewer):
    a, _ = admin_viewer
    r = await a.post("/api/v1/plugins/web-research/disable")
    assert r.status_code == 200
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    assert tools["web_search"]["enabled"] is False
    assert tools["web_fetch"]["enabled"] is False
    assert tools["calculator"]["enabled"] is True   # untouched plugin

    # plugin test reflects it
    r = (await a.post("/api/v1/plugins/web-research/test")).json()
    assert r["success"] is False and "disabled" in (r.get("note") or "")

    # re-enable restores both tools
    await a.post("/api/v1/plugins/web-research/enable")
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    assert tools["web_search"]["enabled"] is True
    assert tools["web_fetch"]["enabled"] is True

    # enabling advanced-workspace exposes its dangerous tools to admins
    await a.post("/api/v1/plugins/advanced-workspace/enable")
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    assert tools["python_exec"]["enabled"] is True
    await a.post("/api/v1/plugins/advanced-workspace/disable")   # restore safe state
    tools = {t["name"]: t for t in (await a.get("/api/v1/tools")).json()}
    assert tools["python_exec"]["enabled"] is False


@pytest.mark.asyncio
async def test_viewer_cannot_toggle_plugin(admin_viewer):
    _, v = admin_viewer
    r = await v.post("/api/v1/plugins/core-utilities/disable")
    assert r.status_code == 403


# ------------------------------------------------------------------
# Configuration + secret masking
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_config_secret_masked(admin_viewer):
    a, _ = admin_viewer
    r = await a.put("/api/v1/tools/web_search/config",
                    json={"config": {"provider": "duckduckgo"}})
    assert r.status_code == 200 and r.json()["config"]["provider"] == "duckduckgo"

    detail = next(t for t in (await a.get("/api/v1/tools")).json()
                  if t["name"] == "web_search")
    assert detail["config"]["provider"] == "duckduckgo"


@pytest.mark.asyncio
async def test_config_unknown_key_rejected(admin_viewer):
    a, _ = admin_viewer
    r = await a.put("/api/v1/tools/calculator/config",
                    json={"config": {"api_key": "sk-x"}})   # no config_keys allowed
    assert r.status_code == 200
    body = r.json()
    assert body["config"] == {}   # filtered out — calculator accepts nothing


# ------------------------------------------------------------------
# Tool TEST endpoint (real execution of canned probes)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calculator_probe_executes(admin_viewer):
    a, _ = admin_viewer
    r = (await a.post("/api/v1/tools/calculator/test")).json()
    assert r["success"] is True
    assert str(r["result"].get("result", "")) in ("42", "42.0")


@pytest.mark.asyncio
async def test_disabled_tool_test_conflict(admin_viewer):
    a, _ = admin_viewer
    await a.post("/api/v1/tools/time_now/disable")
    r = await a.post("/api/v1/tools/time_now/test")
    assert r.status_code == 409
    await a.post("/api/v1/tools/time_now/enable")


# ------------------------------------------------------------------
# Agent planner
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_math_task(admin_viewer):
    a, _ = admin_viewer
    r = (await a.post("/api/v1/agents/plan",
                      json={"goal": "Calculate 125 * 384"})).json()
    assert r["task_type"] in ("fast", "reasoning")
    assert "calculator" in r["tools"]
    assert "core-utilities" in r["plugins"]
    assert "web_search" not in r["tools"]


@pytest.mark.asyncio
async def test_plan_web_task_recommends_research(admin_viewer):
    a, _ = admin_viewer
    r = (await a.post("/api/v1/agents/plan", json={
        "goal": "Search the internet for the latest AI news"})).json()
    assert "web_search" in r["tools"] and "web_fetch" in r["tools"]
    assert "web-research" in r["plugins"]


@pytest.mark.asyncio
async def test_plan_document_task(admin_viewer):
    a, _ = admin_viewer
    r = (await a.post("/api/v1/agents/plan", json={
        "goal": "Summarize my uploaded document about quarterly results"})).json()
    assert "search_kb" in r["tools"] or "file_read" in r["tools"]
    assert "document-tools" in r["plugins"]


@pytest.mark.asyncio
async def test_plan_respects_availability(admin_viewer):
    """Disabling a plugin removes its tools from plans."""
    a, _ = admin_viewer
    await a.post("/api/v1/plugins/web-research/disable")
    r = (await a.post("/api/v1/agents/plan", json={
        "goal": "Search the web for latest news"})).json()
    assert "web_search" not in r["tools"]
    await a.post("/api/v1/plugins/web-research/enable")


@pytest.mark.asyncio
async def test_plan_requires_auth_and_goal(client: AsyncClient, admin_viewer):
    a, _ = admin_viewer
    r = await client.post("/api/v1/agents/plan", json={"goal": "x"})
    assert r.status_code == 401
    r = await a.post("/api/v1/agents/plan", json={"goal": "   "})
    assert r.status_code == 422


# ------------------------------------------------------------------
# Capabilities endpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capabilities_shape(admin_viewer):
    a, _ = admin_viewer
    r = await a.get("/api/v1/agents/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["models"], list)
    tool_names = {t["name"] for t in body["tools"]}
    assert "calculator" in tool_names and "python_exec" not in tool_names
    plugin_ids = {p["id"] for p in body["plugins"]}
    assert "advanced-workspace" not in plugin_ids


# ------------------------------------------------------------------
# Prompt-injection safety net: registry refuses disabled/unknown tools even
# if an LLM proposes them.
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_refuses_disabled_tool_proposal(admin_viewer):
    from tools.registry import get_registry
    reg = get_registry()
    await admin_viewer[0].post("/api/v1/plugins/core-utilities/disable")
    try:
        # LLM could propose calculator; registry must return None while disabled
        assert reg.get("calculator") is None
    finally:
        await admin_viewer[0].post("/api/v1/plugins/core-utilities/enable")
