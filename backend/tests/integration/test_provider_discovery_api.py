"""
Integration tests for provider connection testing and automatic model discovery.

Covers:
- provider creation WITHOUT a manually entered model name (connection-only)
- successful / failed connection tests
- model discovery via the adapter layer
- empty model list, unreachable provider, invalid API key
- multiple providers
- authorization (admin-only writes) and API key non-disclosure
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

from services.llm_client import ModelUnavailableError


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fake_adapter(models=None, healthy=True):
    """Build a mock adapter object mimicking the BaseLLMProvider surface."""
    adapter = MagicMock()
    adapter.health_check = AsyncMock(return_value=(healthy, 12))
    adapter.list_models = AsyncMock(return_value=models or [])
    return adapter


async def _create_connection_only_provider(client: AsyncClient, **kwargs) -> dict:
    """Create a provider with NO model_name — pure connection config."""
    defaults = {
        "name": "My Ollama",
        "provider_type": "ollama",
        "environment": "local",
        "base_url": "http://ollama:11434",
    }
    defaults.update(kwargs)
    resp = await client.post("/api/v1/models/providers/", json=defaults)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def admin_and_viewer_clients(client: AsyncClient):
    """First registered user becomes admin; second becomes viewer."""
    await client.post("/api/v1/auth/register", json={
        "email": "pa@x.com", "username": "prov_admin", "password": "StrongPass123!"})
    ra = await client.post("/api/v1/auth/login", json={
        "email": "pa@x.com", "password": "StrongPass123!"})
    tok_a = ra.json()["access_token"]

    await client.post("/api/v1/auth/register", json={
        "email": "pv@x.com", "username": "prov_viewer", "password": "StrongPass123!"})
    rv = await client.post("/api/v1/auth/login", json={
        "email": "pv@x.com", "password": "StrongPass123!"})
    tok_v = rv.json()["access_token"]

    admin_c = AsyncClient(transport=client._transport, base_url="http://testserver")
    viewer_c = AsyncClient(transport=client._transport, base_url="http://testserver")
    admin_c.headers.update({"Authorization": f"Bearer {tok_a}"})
    viewer_c.headers.update({"Authorization": f"Bearer {tok_v}"})
    yield admin_c, viewer_c
    await admin_c.aclose()
    await viewer_c.aclose()


# ------------------------------------------------------------------
# Provider = connection configuration only
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_provider_without_model_name(auth_client: AsyncClient):
    """Providers store connection info only — model_name must NOT be required."""
    data = await _create_connection_only_provider(auth_client)
    assert data["model_name"] == ""
    assert data["base_url"] == "http://ollama:11434"
    assert data["provider_type"] == "ollama"


@pytest.mark.asyncio
async def test_create_cloud_provider_with_api_key(auth_client: AsyncClient):
    data = await _create_connection_only_provider(
        auth_client,
        name="My Cloud Provider",
        provider_type="openai_compatible",
        environment="cloud",
        base_url="https://provider.example.com/v1",
        api_key="sk-live-secret-987654",
    )
    assert data["has_api_key"] is True
    # SECURITY: raw key must never appear anywhere in the response payload
    assert "sk-live-secret-987654" not in json.dumps(data)


@pytest.mark.asyncio
async def test_create_provider_invalid_type_rejected(auth_client: AsyncClient):
    resp = await auth_client.post("/api/v1/models/providers/", json={
        "name": "Bad", "provider_type": "not_a_type",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_provider_empty_name_rejected(auth_client: AsyncClient):
    resp = await auth_client.post("/api/v1/models/providers/", json={
        "name": "   ", "provider_type": "ollama",
    })
    assert resp.status_code == 422


# ------------------------------------------------------------------
# Test Connection
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_connection_success_reports_model_count(auth_client: AsyncClient):
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter(models=[
        {"name": "llama3.2", "details": {"family": "llama"}},
        {"name": "qwen3:8b", "details": {"family": "qwen2"}},
        {"name": "gemma3"},
        {"name": "mistral"},
        {"name": "nomic-embed-text", "details": {"family": "nomic-bert"}},
    ])
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["models_found"] == 5
    assert body["error"] is None


@pytest.mark.asyncio
async def test_test_connection_unreachable(auth_client: AsyncClient):
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter(healthy=False)
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "unavailable" in body["error"].lower()


@pytest.mark.asyncio
async def test_test_connection_invalid_api_key(auth_client: AsyncClient):
    p = await _create_connection_only_provider(
        auth_client,
        name="Cloud", provider_type="openai_compatible",
        base_url="http://x.example.com/v1",
        api_key="sk-wrong-key-000111222333",
    )
    adapter = MagicMock()
    adapter.health_check = AsyncMock(side_effect=ModelUnavailableError(
        "401 Unauthorized: invalid sk-wrong-key-000111222333"))
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    body = resp.json()
    assert body["success"] is False
    # SECURITY + UX: friendly message; raw key never echoed back
    assert "sk-wrong-key" not in json.dumps(body)
    assert body["error"]


@pytest.mark.asyncio
async def test_test_connection_missing_api_key(auth_client: AsyncClient):
    p = await _create_connection_only_provider(auth_client)
    with patch("services.provider_service.build_provider",
               side_effect=ModelUnavailableError("provider requires an api key")):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    body = resp.json()
    assert body["success"] is False
    assert "api key" in body["error"].lower()


@pytest.mark.asyncio
async def test_test_connection_rejects_fake_key_via_auth_probe(auth_client: AsyncClient):
    """
    Cloud gateways serve /models publicly — a fake key passes basic checks.
    The 1-token verify_auth probe must catch it and fail the test.
    """
    p = await _create_connection_only_provider(
        auth_client, name="OR", provider_type="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-v1-not-a-real-key",
    )
    adapter = _fake_adapter(models=[{"id": "openai/gpt-4.1"}])
    adapter.verify_auth = AsyncMock(return_value=(False, "Authentication failed — invalid API key"))
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    body = resp.json()
    assert body["success"] is False
    assert body["error"] == "Authentication failed — invalid API key"
    assert "sk-or-v1-not-a-real-key" not in json.dumps(body)


@pytest.mark.asyncio
async def test_test_connection_valid_key_passes_probe(auth_client: AsyncClient):
    p = await _create_connection_only_provider(
        auth_client, name="OK", provider_type="openrouter",
        base_url="https://openrouter.ai/api/v1", api_key="sk-or-real",
    )
    adapter = _fake_adapter(models=[{"id": "m"}])
    adapter.verify_auth = AsyncMock(return_value=(True, None))
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    body = resp.json()
    assert body["success"] is True and body["models_found"] == 1


@pytest.mark.asyncio
async def test_test_connection_ollama_skips_auth_probe(auth_client: AsyncClient):
    """No api_key stored → probe not invoked (Ollama needs no key)."""
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter(models=[{"name": "llama3.2:3b"}])
    adapter.verify_auth = AsyncMock()
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/test")
    assert resp.json()["success"] is True
    adapter.verify_auth.assert_not_called()


# ------------------------------------------------------------------
# Model discovery
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_models_from_ollama_adapter(auth_client: AsyncClient):
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter(models=[
        {
            "name": "llama3.2:3b", "size": 2019393189,
            "details": {"family": "llama", "parameter_size": "3.2B",
                        "quantization_level": "Q4_K_M"},
        },
        {"name": "nomic-embed-text:latest", "size": 274302450,
         "details": {"family": "nomic-bert", "parameter_size": "137M"}},
    ])
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/refresh")
    assert resp.status_code == 200
    models = resp.json()
    assert [m["model_id"] for m in models] == ["llama3.2:3b", "nomic-embed-text:latest"]
    llama = models[0]
    # Only fields returned by the provider are populated — nothing fabricated
    assert llama["family"] == "llama"
    assert llama["parameter_size"] == "3.2B"
    assert llama["quantization"] == "Q4_K_M"
    assert llama["size_bytes"] == 2019393189
    # Capability/context fields Ollama's tags API does not report stay unset —
    # nothing is fabricated.
    assert llama["context_length"] is None
    assert "vision" not in llama and "embedding_capable" not in llama

    # Cached catalog endpoint returns the same persisted rows without a live call
    cached = await auth_client.get(f"/api/v1/models/providers/{p['id']}/models")
    assert cached.status_code == 200
    assert [m["model_id"] for m in cached.json()] == ["llama3.2:3b", "nomic-embed-text:latest"]
    # Persisted rows carry enabled=True by default and provider reference
    for row in cached.json():
        assert row["enabled"] is True
        assert row["provider_id"] == p["id"]


@pytest.mark.asyncio
async def test_discover_models_openai_compatible_format(auth_client: AsyncClient):
    """OpenAI-style /v1/models payloads map id→name, owned_by→family."""
    p = await _create_connection_only_provider(
        auth_client, name="vLLM", provider_type="openai_compatible",
        environment="custom", base_url="http://vllm.internal:8000/v1",
    )
    adapter = _fake_adapter(models=[
        {"id": "model-a", "owned_by": "organization"},
        {"id": "model-b", "owned_by": "organization"},
    ])
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/refresh")
    models = resp.json()
    assert sorted(m["model_id"] for m in models) == ["model-a", "model-b"]
    assert models[0]["family"] == "organization"


@pytest.mark.asyncio
async def test_discover_models_empty_list(auth_client: AsyncClient):
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter(models=[])
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/refresh")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_discover_models_provider_unreachable(auth_client: AsyncClient):
    p = await _create_connection_only_provider(auth_client)
    adapter = MagicMock()
    # Discovery verifies reachability first (strict mode) — adapter reports down
    adapter.health_check = AsyncMock(return_value=(False, None))
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/refresh")
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_discover_models_list_error_after_reachable(auth_client: AsyncClient):
    """Reachable but listing blows up → 502 with friendly message."""
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter()
    adapter.health_check = AsyncMock(return_value=(True, 5))
    adapter.list_models = AsyncMock(side_effect=ModelUnavailableError("401 unauthorized bad key"))
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/refresh")
    assert resp.status_code == 502
    assert "api key" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_discover_models_malformed_entries_skipped(auth_client: AsyncClient):
    """Entries without any usable identifier are skipped, never fabricated."""
    p = await _create_connection_only_provider(auth_client)
    adapter = _fake_adapter(models=[
        {"nope": 1},                # skipped
        {"name": "valid-model"},    # kept
        "just-a-string",            # skipped
    ])
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await auth_client.post(f"/api/v1/models/providers/{p['id']}/refresh")
    models = resp.json()
    assert len(models) == 1
    assert models[0]["model_id"] == "valid-model"


@pytest.mark.asyncio
async def test_discover_models_nonexistent_provider_404(auth_client: AsyncClient):
    resp = await auth_client.get(
        "/api/v1/models/providers/00000000-0000-0000-0000-000000000000/models")
    assert resp.status_code == 404


# ------------------------------------------------------------------
# Multiple providers
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_providers_discover_independently(admin_and_viewer_clients):
    admin_c, _ = admin_and_viewer_clients
    ollama = await _create_connection_only_provider(admin_c, name="My Ollama")
    cloud = await _create_connection_only_provider(
        admin_c, name="Company vLLM", provider_type="openai_compatible",
        environment="custom", base_url="http://vllm.local:8000/v1",
    )
    adapters = {
        ollama["id"]: _fake_adapter(models=[{"name": "llama3.2"}, {"name": "qwen3:8b"}]),
        cloud["id"]: _fake_adapter(models=[{"id": "corp-model-x"}]),
    }
    results = {}
    for pid, adapter in adapters.items():
        with patch("services.provider_service.build_provider", return_value=adapter):
            resp = await admin_c.post(f"/api/v1/models/providers/{pid}/refresh")
            assert resp.status_code == 200
            results[pid] = {m["model_id"] for m in resp.json()}

    assert results[ollama["id"]] == {"llama3.2", "qwen3:8b"}
    assert results[cloud["id"]] == {"corp-model-x"}

    # Both providers listed together
    lst = await admin_c.get("/api/v1/models/providers/")
    names = {p["name"] for p in lst.json()}
    assert {"My Ollama", "Company vLLM"} <= names


# ------------------------------------------------------------------
# Authorization & security
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_viewer_cannot_create_provider(admin_and_viewer_clients):
    _, viewer_c = admin_and_viewer_clients
    resp = await viewer_c.post("/api/v1/models/providers/", json={
        "name": "Nope", "provider_type": "ollama",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_update_or_delete_provider(admin_and_viewer_clients):
    admin_c, viewer_c = admin_and_viewer_clients
    p = await _create_connection_only_provider(admin_c)
    r1 = await viewer_c.put(f"/api/v1/models/providers/{p['id']}", json={"name": "Hax"})
    assert r1.status_code == 403
    r2 = await viewer_c.delete(f"/api/v1/models/providers/{p['id']}")
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_test_connection(admin_and_viewer_clients):
    admin_c, viewer_c = admin_and_viewer_clients
    p = await _create_connection_only_provider(admin_c)
    resp = await viewer_c.post(f"/api/v1/models/providers/{p['id']}/test")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_list_refresh_and_read_catalog(admin_and_viewer_clients):
    admin_c, viewer_c = admin_and_viewer_clients
    p = await _create_connection_only_provider(admin_c)
    r1 = await viewer_c.get("/api/v1/models/providers/")
    assert r1.status_code == 200

    adapter = _fake_adapter(models=[{"name": "shared-model"}])
    with patch("services.provider_service.build_provider", return_value=adapter):
        # Refresh is read-only discovery → allowed for any authenticated user
        r2 = await viewer_c.post(f"/api/v1/models/providers/{p['id']}/refresh")
    assert r2.status_code == 200
    assert [m["model_id"] for m in r2.json()] == ["shared-model"]

    # Cached catalog readable by viewer as well
    r3 = await viewer_c.get(f"/api/v1/models/providers/{p['id']}/models")
    assert [m["model_id"] for m in r3.json()] == ["shared-model"]


@pytest.mark.asyncio
async def test_viewer_cannot_enable_disable_model(admin_and_viewer_clients):
    admin_c, viewer_c = admin_and_viewer_clients
    p = await _create_connection_only_provider(admin_c)
    adapter = _fake_adapter(models=[{"name": "toggle-me"}])
    with patch("services.provider_service.build_provider", return_value=adapter):
        await admin_c.post(f"/api/v1/models/providers/{p['id']}/refresh")
    catalog = await admin_c.get(f"/api/v1/models/providers/{p['id']}/models")
    rec = catalog.json()[0]

    # Viewer cannot toggle
    r = await viewer_c.patch(
        f"/api/v1/models/providers/{p['id']}/models/{rec['id']}",
        json={"enabled": False})
    assert r.status_code == 403

    # Admin can toggle
    r = await admin_c.patch(
        f"/api/v1/models/providers/{p['id']}/models/{rec['id']}",
        json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False

    # Disabled model excluded from user-facing enabled list
    from services.provider_service import ProviderService  # noqa: F401
    r = await viewer_c.get("/api/v1/models/providers/")
    prov = next(x for x in r.json() if x["id"] == p["id"])
    assert prov["model_count"] == 0   # available count excludes disabled

    # Re-enable restores it
    r = await admin_c.patch(
        f"/api/v1/models/providers/{p['id']}/models/{rec['id']}",
        json={"enabled": True})
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client: AsyncClient):
    """No Bearer token → 401 on discovery and provider endpoints."""
    r1 = await client.get("/api/v1/models/providers/")
    assert r1.status_code == 401
    r2 = await client.get("/api/v1/models/providers/some-id/models")
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_discovery_response_never_contains_api_key(admin_and_viewer_clients):
    admin_c, viewer_c = admin_and_viewer_clients
    secret = "sk-should-never-leak-42"
    p = await _create_connection_only_provider(
        admin_c, provider_type="openai_compatible", api_key=secret,
        base_url="http://gw.internal/v1",
    )
    adapter = _fake_adapter(models=[{"id": "m1"}])
    with patch("services.provider_service.build_provider", return_value=adapter):
        resp = await viewer_c.get(f"/api/v1/models/providers/{p['id']}/models")
    assert secret not in resp.text
    detail = await viewer_c.get(f"/api/v1/models/providers/{p['id']}")
    assert secret not in detail.text


# ------------------------------------------------------------------
# Role binding stores provider reference (selection architecture reuse)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_role_with_provider_binding(admin_and_viewer_clients):
    admin_c, _ = admin_and_viewer_clients
    p = await _create_connection_only_provider(admin_c, name="RoleSrc")
    resp = await admin_c.put("/api/v1/models/roles", json={
        "role": "chat", "model_name": "llama3.2:3b", "provider_id": p["id"],
    })
    assert resp.status_code == 200
    roles = resp.json()
    assert roles["chat"] == "llama3.2:3b"
    assert roles["chat_provider_id"] == p["id"]

    # Cleanup so the persisted role file does not affect other tests / live runs
    await admin_c.put("/api/v1/models/roles", json={
        "role": "chat", "model_name": "llama3.2:3b", "provider_id": None,
    })


@pytest.mark.asyncio
async def test_set_role_invalid_role_rejected(admin_and_viewer_clients):
    admin_c, _ = admin_and_viewer_clients
    resp = await admin_c.put("/api/v1/models/roles", json={
        "role": "banana", "model_name": "x",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_set_role_requires_admin(admin_and_viewer_clients):
    _, viewer_c = admin_and_viewer_clients
    resp = await viewer_c.put("/api/v1/models/roles", json={
        "role": "chat", "model_name": "x",
    })
    assert resp.status_code == 403


# ==================================================================
# Presets, masked keys, per-user preferences, per-message routing
# ==================================================================

@pytest.mark.asyncio
async def test_presets_include_all_required_providers(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/models/providers/presets")
    assert resp.status_code == 200
    presets = {p["id"]: p for p in resp.json()}
    for pid in ("openrouter", "opencode_zen", "nvidia", "ollama", "openai_compatible"):
        assert pid in presets, f"missing preset: {pid}"
    assert presets["openrouter"]["default_base_url"] == "https://openrouter.ai/api/v1"
    assert presets["opencode_zen"]["default_base_url"] == "https://opencode.ai/zen/v1"
    assert presets["nvidia"]["default_base_url"] == "https://integrate.api.nvidia.com/v1"
    # Ollama needs no API key; cloud presets do
    assert presets["ollama"]["requires_api_key"] is False
    assert presets["openrouter"]["requires_api_key"] is True
    # No model lists inside presets — models come from live discovery only
    for p in presets.values():
        assert "models" not in p


@pytest.mark.asyncio
async def test_create_from_openrouter_preset(auth_client: AsyncClient):
    """Preset creation pre-fills base URL; only the API key is user-provided."""
    resp = await auth_client.post("/api/v1/models/providers/", json={
        "name": "My OpenRouter",
        "provider_type": "openrouter",
        "environment": "cloud",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-v1-abcdef1234567890",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["base_url"] == "https://openrouter.ai/api/v1"
    assert data["has_api_key"] is True
    # SECURITY: masked hint shows at most last 4 chars, never the full key
    assert data["api_key_masked"].endswith("7890")
    assert "sk-or-v1-abcdef" not in data["api_key_masked"]
    assert "sk-or-v1-abcdef1234567890" not in json.dumps(data)


@pytest.mark.asyncio
async def test_masked_key_short_key_safe(auth_client: AsyncClient):
    """Keys shorter than 4 chars produce a mask with no tail leak."""
    resp = await auth_client.post("/api/v1/models/providers/", json={
        "name": "TinyKey", "provider_type": "openai_compatible",
        "base_url": "http://gw.internal/v1", "api_key": "ab",
    })
    assert resp.json()["api_key_masked"] == "••••••••"


@pytest.mark.asyncio
async def test_chat_routes_to_explicit_provider(admin_and_viewer_clients):
    """Per-message provider_id routes chat through that provider's adapter."""
    from services.llm_client import ChatMessage

    admin_c, viewer_c = admin_and_viewer_clients
    p = await _create_connection_only_provider(
        admin_c, name="Routing Ollama", base_url="http://routing-host:11434")

    conv = (await admin_c.post("/api/v1/chat/conversations", json={
        "model_name": "any-model", "title": "Routing test"})).json()

    captured = {}

    class FakeStream:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    async def fake_chat(*, model, messages, stream=False, **kw):
        captured["model"] = model
        captured["messages"] = messages
        return FakeStream()

    adapter = MagicMock()
    adapter.chat = AsyncMock(side_effect=fake_chat)

    with patch("services.llm_client.build_provider", return_value=adapter) as bp:
        r = await admin_c.post(f"/api/v1/chat/conversations/{conv['id']}/messages",
                               json={"content": "hi", "model_name": "llama3.2:3b",
                                     "provider_id": p["id"]})
    assert r.status_code == 200
    # Adapter built from the target provider's connection and used for chat
    kwargs = bp.call_args.kwargs
    assert kwargs.get("base_url") == "http://routing-host:11434"
    assert captured["model"] == "llama3.2:3b"

    # Unknown / disabled providers rejected cleanly
    r = await admin_c.post(f"/api/v1/chat/conversations/{conv['id']}/messages",
                           json={"content": "x", "provider_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_model_preference_per_user_isolated(admin_and_viewer_clients):
    admin_c, viewer_c = admin_and_viewer_clients

    # Admin sets a preference — viewer's is untouched
    r = await admin_c.put("/api/v1/models/preferences",
                          json={"provider_id": None, "model_name": "llama3.2:3b"})
    assert r.status_code == 200 and r.json()["model_name"] == "llama3.2:3b"

    r = await viewer_c.get("/api/v1/models/preferences")
    assert r.json()["model_name"] is None   # isolation

    # Viewer sets their own
    r = await viewer_c.put("/api/v1/models/preferences",
                           json={"provider_id": None, "model_name": "mistral"})
    assert r.json()["model_name"] == "mistral"

    # Admin's unchanged; round-trip restores correctly
    assert (await admin_c.get("/api/v1/models/preferences")).json()["model_name"] == "llama3.2:3b"

    # Empty model_name rejected
    r = await viewer_c.put("/api/v1/models/preferences",
                           json={"provider_id": None, "model_name": "  "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_refresh_preserves_disabled_state_and_marks_removed(admin_and_viewer_clients):
    """Re-refresh keeps manual enable/disable; vanished models → unavailable."""
    admin_c, _ = admin_and_viewer_clients
    p = await _create_connection_only_provider(admin_c)

    adapter_v1 = _fake_adapter(models=[{"name": "keep-me"}, {"name": "disable-me"}])
    with patch("services.provider_service.build_provider", return_value=adapter_v1):
        await admin_c.post(f"/api/v1/models/providers/{p['id']}/refresh")
    catalog = {m["model_id"]: m for m in
               (await admin_c.get(f"/api/v1/models/providers/{p['id']}/models")).json()}

    # Admin disables one model
    r = await admin_c.patch(
        f"/api/v1/models/providers/{p['id']}/models/{catalog['disable-me']['id']}",
        json={"enabled": False})
    assert r.status_code == 200

    # Provider now reports one model gone and one new one
    adapter_v2 = _fake_adapter(models=[{"name": "keep-me"}, {"name": "brand-new"}])
    with patch("services.provider_service.build_provider", return_value=adapter_v2):
        await admin_c.post(f"/api/v1/models/providers/{p['id']}/refresh")

    rows = {m["model_id"]: m for m in
            (await admin_c.get(f"/api/v1/models/providers/{p['id']}/models")).json()}
    assert rows["disable-me"]["enabled"] is False          # preserved across refresh
    assert rows["disable-me"]["status"] == "unavailable"   # removed from provider
    assert rows["keep-me"]["status"] == "available"
    assert rows["brand-new"]["enabled"] is True            # new model starts enabled
