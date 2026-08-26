"""
Integration tests for LLM Provider CRUD and security.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from models.base import generate_uuid


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _create_provider(auth_client: AsyncClient, **kwargs) -> dict:
    defaults = {
        "name": "Test Ollama",
        "provider_type": "ollama",
        "environment": "local",
        "base_url": "http://host.docker.internal:11434",
        "model_name": "qwen3:14b",
        "enabled": True,
    }
    defaults.update(kwargs)
    resp = await auth_client.post("/api/v1/models/providers/", json=defaults)
    return resp


# ------------------------------------------------------------------
# Provider CRUD
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_providers_returns_empty_then_one(auth_client: AsyncClient):
    # Seed from startup may add default Ollama provider
    resp = await auth_client.get("/api/v1/models/providers/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_provider_ollama(auth_client: AsyncClient):
    resp = await _create_provider(auth_client, name="My Ollama")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Ollama"
    assert data["provider_type"] == "ollama"
    assert data["model_name"] == "qwen3:14b"
    assert data["enabled"] is True
    # SECURITY: api_key must NEVER appear in response
    assert "api_key" not in data
    assert "has_api_key" in data
    assert data["has_api_key"] is False   # no key was provided


@pytest.mark.asyncio
async def test_create_provider_with_api_key_never_returned(auth_client: AsyncClient):
    """API key must be stored but never returned in any response."""
    resp = await _create_provider(
        auth_client,
        name="OpenAI Prod",
        provider_type="openai",
        environment="cloud",
        base_url="https://api.openai.com",
        model_name="gpt-4o",
        api_key="sk-super-secret-key-abc123",  # should never appear in response
    )
    assert resp.status_code == 201
    data = resp.json()
    # SECURITY: the actual key must never be returned
    assert "api_key" not in data
    assert data["has_api_key"] is True
    # Also check GET does not return key
    pid = data["id"]
    get_resp = await auth_client.get(f"/api/v1/models/providers/{pid}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert "api_key" not in get_data
    assert "sk-super-secret" not in json.dumps(get_data)
    assert get_data["has_api_key"] is True


@pytest.mark.asyncio
async def test_api_key_never_in_list_response(auth_client: AsyncClient):
    """List response must never contain any api_key values."""
    await _create_provider(auth_client, name="Anthropic", provider_type="anthropic",
                           environment="cloud", model_name="claude-3-5-sonnet-20241022",
                           api_key="sk-ant-secret-key")
    resp = await auth_client.get("/api/v1/models/providers/")
    assert resp.status_code == 200
    raw = resp.text
    assert "sk-ant-secret-key" not in raw
    assert '"api_key"' not in raw


@pytest.mark.asyncio
async def test_get_provider(auth_client: AsyncClient):
    create = await _create_provider(auth_client, name="GetTest")
    pid = create.json()["id"]
    resp = await auth_client.get(f"/api/v1/models/providers/{pid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


@pytest.mark.asyncio
async def test_get_nonexistent_provider_404(auth_client: AsyncClient):
    resp = await auth_client.get(f"/api/v1/models/providers/{generate_uuid()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_provider(auth_client: AsyncClient):
    create = await _create_provider(auth_client, name="ToUpdate", model_name="qwen3:14b")
    assert create.status_code == 201
    pid = create.json()["id"]
    resp = await auth_client.put(f"/api/v1/models/providers/{pid}", json={
        "name": "Updated Name",
        "model_name": "qwen3:7b",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    assert data["model_name"] == "qwen3:7b"
    # SECURITY: api_key must not appear
    assert "api_key" not in data


@pytest.mark.asyncio
async def test_delete_provider(auth_client: AsyncClient):
    create = await _create_provider(auth_client, name="ToDelete")
    pid = create.json()["id"]
    del_resp = await auth_client.delete(f"/api/v1/models/providers/{pid}")
    assert del_resp.status_code == 204
    get_resp = await auth_client.get(f"/api/v1/models/providers/{pid}")
    assert get_resp.status_code == 404


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_provider_invalid_type(auth_client: AsyncClient):
    resp = await _create_provider(auth_client, provider_type="invalid_provider_xyz")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_provider_empty_model_name(auth_client: AsyncClient):
    """
    UPDATED CONTRACT: a provider stores connection configuration only.
    An empty model_name is valid — models are auto-discovered from the
    provider via GET /providers/{id}/models instead of being typed manually.
    """
    resp = await _create_provider(auth_client, model_name="")
    assert resp.status_code == 201
    data = resp.json()
    assert data["model_name"] == ""
    assert data["base_url"]  # the meaningful part of the config is preserved


@pytest.mark.asyncio
async def test_create_openai_compatible_provider(auth_client: AsyncClient):
    resp = await _create_provider(
        auth_client,
        name="Local vLLM",
        provider_type="openai_compatible",
        environment="custom",
        base_url="http://host.docker.internal:8000/v1",
        model_name="mistral-7b",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider_type"] == "openai_compatible"
    assert data["environment"] == "custom"


# ------------------------------------------------------------------
# RBAC
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_provider_requires_admin(client: AsyncClient):
    # First user → admin; second → viewer
    await client.post("/api/v1/auth/register", json={
        "email": "prov_admin@test.com", "username": "prov_admin", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "prov_viewer@test.com", "username": "prov_viewer", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "prov_viewer@test.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.post("/api/v1/models/providers/", json={
        "name": "Bad", "provider_type": "ollama", "model_name": "x"
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_provider_requires_admin(client: AsyncClient):
    from models.base import generate_uuid
    # Register admin + viewer
    await client.post("/api/v1/auth/register", json={
        "email": "del_adm@test.com", "username": "del_adm", "password": "StrongPass123!"
    })
    adm_login = await client.post("/api/v1/auth/login", json={
        "email": "del_adm@test.com", "password": "StrongPass123!"
    })
    adm_token = adm_login.json()["access_token"]
    adm_headers = {"Authorization": f"Bearer {adm_token}"}
    # Admin creates a provider
    create = await client.post("/api/v1/models/providers/", json={
        "name": "DelTest", "provider_type": "ollama", "model_name": "x"
    }, headers=adm_headers)
    pid = create.json()["id"]

    # Viewer tries to delete
    await client.post("/api/v1/auth/register", json={
        "email": "del_viewer@test.com", "username": "del_viewer", "password": "StrongPass123!"
    })
    viewer_login = await client.post("/api/v1/auth/login", json={
        "email": "del_viewer@test.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {viewer_login.json()['access_token']}"
    resp = await client.delete(f"/api/v1/models/providers/{pid}")
    assert resp.status_code == 403


# ------------------------------------------------------------------
# Provider connection test
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_test_returns_result(auth_client: AsyncClient):
    """Test endpoint returns success/fail — never the api_key."""
    create = await _create_provider(auth_client, name="TestConn", api_key="secret-key-xyz")
    pid = create.json()["id"]

    with patch("services.provider_service.build_provider") as mock_build:
        mock_provider = MagicMock()
        mock_provider.health_check = AsyncMock(return_value=(True, 42))
        mock_build.return_value = mock_provider

        resp = await auth_client.post(f"/api/v1/models/providers/{pid}/test")

    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert "error" not in data or data["error"] is None or "secret-key-xyz" not in str(data["error"])
    # SECURITY: api_key must never appear in test result
    assert "secret-key-xyz" not in resp.text
    assert "api_key" not in resp.text


@pytest.mark.asyncio
async def test_connection_test_unavailable_provider(auth_client: AsyncClient):
    """Graceful failure when provider is unreachable."""
    create = await _create_provider(
        auth_client, name="Unreachable",
        base_url="http://localhost:9999"
    )
    pid = create.json()["id"]

    from services.llm_client import ModelUnavailableError
    with patch("services.provider_service.build_provider") as mock_build:
        mock_provider = MagicMock()
        mock_provider.health_check = AsyncMock(
            side_effect=ModelUnavailableError("connection refused")
        )
        mock_build.return_value = mock_provider

        resp = await auth_client.post(f"/api/v1/models/providers/{pid}/test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"] is not None


# ------------------------------------------------------------------
# Provider seeding
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_ollama_provider_seeded(auth_client: AsyncClient, db):
    """
    On startup, the lifespan seeds a default Ollama provider.
    In the test environment the lifespan uses AsyncSessionLocal (real DB),
    but tests use an in-memory DB — so we seed it manually here and verify
    the seed logic is idempotent (won't create duplicates).
    """
    from services.provider_service import ProviderService

    svc = ProviderService(db)
    # Seed first time
    await svc.seed_default_ollama("http://host.docker.internal:11434")
    await db.flush()

    providers = await svc.list_providers()
    ollama_providers = [p for p in providers if p.provider_type == "ollama"]
    assert len(ollama_providers) >= 1, "Default Ollama provider not seeded"

    # Seed again — must be idempotent (no duplicate)
    await svc.seed_default_ollama("http://host.docker.internal:11434")
    await db.flush()
    providers2 = await svc.list_providers()
    ollama_providers2 = [p for p in providers2 if p.provider_type == "ollama"]
    assert len(ollama_providers2) == len(ollama_providers), "Seeding must be idempotent"


# ------------------------------------------------------------------
# build_provider factory
# ------------------------------------------------------------------

def test_build_provider_ollama():
    from services.llm_client import build_provider, OllamaProvider
    p = build_provider("ollama", "http://localhost:11434", None)
    assert isinstance(p, OllamaProvider)


def test_build_provider_openai_compatible():
    from services.llm_client import build_provider, OpenAICompatibleProvider
    p = build_provider("openai_compatible", "http://localhost:8000/v1", "mykey")
    assert isinstance(p, OpenAICompatibleProvider)
    assert p._api_key == "mykey"


def test_build_provider_openai():
    from services.llm_client import build_provider, OpenAICompatibleProvider
    p = build_provider("openai", None, "sk-test")
    assert isinstance(p, OpenAICompatibleProvider)


def test_build_provider_anthropic():
    from services.llm_client import build_provider, AnthropicProvider
    p = build_provider("anthropic", None, "sk-ant-test")
    assert isinstance(p, AnthropicProvider)


def test_build_provider_gemini():
    from services.llm_client import build_provider, GeminiProvider
    p = build_provider("gemini", None, "AIza-test")
    assert isinstance(p, GeminiProvider)


def test_build_provider_unknown_raises():
    from services.llm_client import build_provider, ModelUnavailableError
    import pytest
    with pytest.raises(ModelUnavailableError):
        build_provider("unknown_xyz", None, None)


def test_openai_compatible_no_auth_header_when_no_key():
    from services.llm_client import OpenAICompatibleProvider
    p = OpenAICompatibleProvider("http://localhost:8000/v1", api_key=None)
    headers = p._build_headers()
    assert "Authorization" not in headers


def test_openai_compatible_auth_header_with_key():
    from services.llm_client import OpenAICompatibleProvider
    p = OpenAICompatibleProvider("http://localhost:8000/v1", api_key="sk-test")
    headers = p._build_headers()
    assert headers["Authorization"] == "Bearer sk-test"
