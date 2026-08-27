"""
Integration security tests — P0.2 ownership / IDOR enforcement.

Policy under test: knowledge bases are private (owner + admin). Any other
user receives 404 (identical to "missing") on every KB-scoped operation:
get, delete, query, document get/delete, upload into it, and agent runs
referencing it.
"""
import pytest
from unittest.mock import patch
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str, username: str) -> dict:
    """Register a user, promote to analyst via admin, login; return headers."""
    await client.post("/api/v1/auth/register", json={
        "email": email, "username": username, "password": "StrongPass123!"
    })
    return {"email": email, "password": "StrongPass123!", "username": username}


@pytest.mark.asyncio
async def test_kb_documents_isolated_between_users(client: AsyncClient):
    # ---- admin (first user) ----
    await client.post("/api/v1/auth/register", json={
        "email": "root@test.com", "username": "rootuser", "password": "StrongPass123!"
    })
    r = await client.post("/api/v1/auth/login", json={
        "email": "root@test.com", "password": "StrongPass123!"})
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # ---- second user → promoted to analyst ----
    creds = await _register_and_login(client, "eve@test.com", "evesuser")
    r = await client.post("/api/v1/auth/login", json=creds)
    eve_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    users = (await client.get("/api/v1/auth/users", headers=admin_headers)).json()
    eve_id = next(u["id"] for u in users if u["email"] == "eve@test.com")
    upd = await client.put(f"/api/v1/auth/users/{eve_id}", json={"role": "analyst"},
                           headers=admin_headers)
    assert upd.status_code == 200

    # ---- admin creates a KB and uploads a document ----
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb_resp = await client.post("/api/v1/knowledge-bases/",
                                    json={"name": "SecretKB"}, headers=admin_headers)
    kb_id = kb_resp.json()["id"]

    up = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("secret.txt", b"top secret bearing data", "text/plain")},
        data={"kb_id": kb_id, "run_ocr": "false"},
        headers=admin_headers,
    )
    assert up.status_code == 202
    doc_id = up.json()["id"]

    # ---- Eve must receive 404 (not 403) everywhere ----
    assert (await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=eve_headers)).status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=eve_headers)).status_code == 404
    q = await client.post(f"/api/v1/knowledge-bases/{kb_id}/query",
                          json={"query": "bearing?", "generate_answer": False},
                          headers=eve_headers)
    assert q.status_code == 404
    d = await client.delete(f"/api/v1/documents/{doc_id}", headers=eve_headers)
    assert d.status_code == 404
    u = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("intrude.txt", b"x", "text/plain")},
        data={"kb_id": kb_id}, headers=eve_headers,
    )
    assert u.status_code == 404
    kbdel = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=eve_headers)
    assert kbdel.status_code == 404

    # ---- Eve cannot enumerate: her lists contain nothing of the admin's ----
    kb_list = (await client.get("/api/v1/knowledge-bases/", headers=eve_headers)).json()
    assert all(kb["id"] != kb_id for kb in kb_list)
    doc_list = (await client.get("/api/v1/documents/", headers=eve_headers)).json()
    assert all(d["id"] != doc_id for d in doc_list)

    # ---- Admin retains full access ----
    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=admin_headers)).status_code == 200

    # ---- Owner-equivalent access: Eve creates her own KB and sees only hers ----
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_y"):
        own = await client.post("/api/v1/knowledge-bases/", json={"name": "EveKB"},
                                headers=eve_headers)
    assert own.status_code == 201
    own_list = (await client.get("/api/v1/knowledge-bases/", headers=eve_headers)).json()
    assert [kb["id"] for kb in own_list] == [own.json()["id"]]


@pytest.mark.asyncio
async def test_owner_can_manage_own_kb_but_not_others(client: AsyncClient):
    """Analyst A vs Analyst B — write access is owner-only too."""
    await client.post("/api/v1/auth/register", json={
        "email": "admin3@test.com", "username": "admin3", "password": "StrongPass123!"})
    r = await client.post("/api/v1/auth/login", json={
        "email": "admin3@test.com", "password": "StrongPass123!"})
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    users = (await client.get("/api/v1/auth/users", headers=admin_headers)).json()
    admin_id = next(u["id"] for u in users if u["email"] == "admin3@test.com")

    async def _mk_analyst(email, username):
        await client.post("/api/v1/auth/register", json={
            "email": email, "username": username, "password": "StrongPass123!"})
        lr = await client.post("/api/v1/auth/login", json={
            "email": email, "password": "StrongPass123!"})
        h = {"Authorization": f"Bearer {lr.json()['access_token']}"}
        uid = next(u["id"] for u in users if u["email"] == email) if any(
            u["email"] == email for u in users) else None
        if uid is None:
            ulist = (await client.get("/api/v1/auth/users", headers=admin_headers)).json()
            uid = next(u["id"] for u in ulist if u["email"] == email)
        await client.put(f"/api/v1/auth/users/{uid}", json={"role": "analyst"},
                         headers=admin_headers)
        return h

    a_headers = await _mk_analyst("alice@test.com", "aliceu")
    b_headers = await _mk_analyst("bob@test.com", "bobu")

    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_a"):
        kb_a = (await client.post("/api/v1/knowledge-bases/", json={"name": "A-KB"},
                                  headers=a_headers)).json()

    # B cannot read or write A's KB
    assert (await client.get(f"/api/v1/knowledge-bases/{kb_a['id']}", headers=b_headers)).status_code == 404
    assert (await client.post(
        "/api/v1/documents/upload",
        files={"file": ("x.txt", b"x", "text/plain")},
        data={"kb_id": kb_a["id"]}, headers=b_headers,
    )).status_code == 404

    # A can upload into their own KB without being admin
    ok = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("mine.txt", b"mine", "text/plain")},
        data={"kb_id": kb_a["id"], "run_ocr": "false"}, headers=a_headers,
    )
    assert ok.status_code == 202


@pytest.mark.asyncio
async def test_agent_run_with_foreign_kb_rejected(client: AsyncClient):
    """create_run validates every requested kb_id against tenancy."""
    from unittest.mock import AsyncMock

    await client.post("/api/v1/auth/register", json={
        "email": "admin4@test.com", "username": "admin4", "password": "StrongPass123!"})
    r = await client.post("/api/v1/auth/login", json={
        "email": "admin4@test.com", "password": "StrongPass123!"})
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_z"):
        kb = (await client.post("/api/v1/knowledge-bases/", json={"name": "AdminKB"},
                                headers=admin_headers)).json()

    # Second user (viewer default is fine — run creation requires analyst;
    # expect 404 from KB check first regardless of ordering by using analyst)
    await client.post("/api/v1/auth/register", json={
        "email": "mallory@test.com", "username": "mallory", "password": "StrongPass123!"})
    lr = await client.post("/api/v1/auth/login", json={
        "email": "mallory@test.com", "password": "StrongPass123!"})
    m_headers = {"Authorization": f"Bearer {lr.json()['access_token']}"}
    ulist = (await client.get("/api/v1/auth/users", headers=admin_headers)).json()
    mid = next(u["id"] for u in ulist if u["email"] == "mallory@test.com")
    await client.put(f"/api/v1/auth/users/{mid}", json={"role": "analyst"},
                     headers=admin_headers)

    resp = await client.post("/api/v1/agents/runs", json={
        "goal": "search the secret kb",
        "kb_ids": [kb["id"]],
    }, headers=m_headers)
    assert resp.status_code == 404
