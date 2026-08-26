"""Live API audit against the running Sovereign AI Workbench. Prints JSON lines."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from io import BytesIO

import urllib.error
import urllib.request
import ssl

BASE = os.environ.get("AUDIT_BASE", "http://127.0.0.1:8000")
results: list[dict] = []


def rec(**kwargs):
    results.append(kwargs)
    status = kwargs.get("status", "")
    print(f"{status:8} {kwargs.get('method','':5} {kwargs.get('path','')} :: {kwargs.get('note','')[:180]}")


def req(method: str, path: str, *, token=None, json_body=None, data=None, headers=None, timeout=30):
    url = BASE + path
    hdrs = dict(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif data is not None:
        body = data
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            elapsed = int((time.time() - t0) * 1000)
            try:
                parsed = json.loads(raw.decode() or "null")
            except Exception:
                parsed = raw.decode(errors="replace")[:2000]
            return resp.status, dict(resp.headers), parsed, elapsed, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        elapsed = int((time.time() - t0) * 1000)
        try:
            parsed = json.loads(raw.decode() or "null")
        except Exception:
            parsed = raw.decode(errors="replace")[:2000]
        return e.code, dict(e.headers), parsed, elapsed, raw
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        return 0, {}, {"error": str(e)}, elapsed, b""


def expect(name, method, path, code, got, *, note="", extra=None):
    ok = got == code if not isinstance(code, (list, tuple)) else got in code
    rec(
        feature=name,
        method=method,
        path=path,
        expected=code,
        got=got,
        status="PASS" if ok else "FAIL",
        note=note,
        extra=extra or {},
    )
    return ok


def dump_detail(obj, n=400):
    s = json.dumps(obj, default=str) if not isinstance(obj, str) else obj
    return s[:n]


def main():
    stamp = uuid.uuid4().hex[:8]
    pw = "AuditPassw0rd!2026"
    admin_token = None
    viewer_token = None
    analyst_token = None
    viewer_b_token = None
    admin_id = None
    viewer_id = None
    viewer_b_id = None
    conv_a = None
    kb_id = None
    doc_id = None

    # --- health / public ---
    st, _, body, ms, _ = req("GET", "/api/v1/system/health")
    expect("health", "GET", "/api/v1/system/health", 200, st, note=f"{ms}ms {dump_detail(body)}")

    st, _, body, _, _ = req("GET", "/api/v1/auth/setup-status")
    expect("setup-status", "GET", "/api/v1/auth/setup-status", 200, st, note=dump_detail(body))

    st, _, _, _, _ = req("GET", "/api/v1/system/status")
    expect("status-unauth", "GET", "/api/v1/system/status", 401, st)

    st, _, _, _, _ = req("GET", "/api/docs")
    expect("openapi-docs-exposed", "GET", "/api/docs", 200, st, note="Swagger UI publicly reachable")

    # CORS
    st, hdrs, _, _, _ = req(
        "OPTIONS",
        "/api/v1/auth/login",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    acao = hdrs.get("Access-Control-Allow-Origin") or hdrs.get("access-control-allow-origin")
    rec(
        feature="cors-evil-origin",
        method="OPTIONS",
        path="/api/v1/auth/login",
        expected="no reflect",
        got=st,
        status="FAIL" if acao in ("http://evil.example", "*") else "PASS",
        note=f"ACAO={acao} status={st}",
    )

    # --- login documented demo admin ---
    for email, password, label in [
        ("admin@sovereign.local", "SecureAdmin2026!", "demo-admin"),
        ("admin@example.com", "adminadminadmin", "generic"),
    ]:
        st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": email, "password": password})
        if st == 200 and isinstance(body, dict) and body.get("access_token"):
            admin_token = body["access_token"]
            rec(feature="demo-login", method="POST", path="/api/v1/auth/login", expected=200, got=200, status="PASS", note=f"logged in as {label}")
            break
        rec(feature="demo-login", method="POST", path="/api/v1/auth/login", expected=200, got=st, status="FAIL", note=f"{label} {dump_detail(body)}")

    # Register users (viewers after first admin exists)
    users = {}
    for role_hint, uname in [("viewerA", f"vwa_{stamp}"), ("viewerB", f"vwb_{stamp}")]:
        email = f"{uname}@audit.local"
        st, _, body, _, _ = req(
            "POST",
            "/api/v1/auth/register",
            json_body={"email": email, "username": uname, "password": pw},
        )
        expect(
            f"register-{role_hint}",
            "POST",
            "/api/v1/auth/register",
            201,
            st,
            note=dump_detail(body),
        )
        if st == 201:
            users[role_hint] = {"email": email, "username": uname, "id": body.get("id"), "role": body.get("role")}

    # validation cases
    cases = [
        ("dup-email", {"email": users.get("viewerA", {}).get("email", "x@y.com"), "username": f"dup_{stamp}", "password": pw}, 400),
        ("invalid-email", {"email": "not-an-email", "username": f"bad_{stamp}", "password": pw}, [400, 422]),
        ("empty", {"email": "", "username": "", "password": ""}, [400, 422]),
        ("weak-pw", {"email": f"weak_{stamp}@a.com", "username": f"weak_{stamp}", "password": "short"}, [400, 422]),
        ("long-user", {"email": f"long_{stamp}@a.com", "username": "a" * 80, "password": pw}, [400, 422]),
        ("special-user", {"email": f"sp_{stamp}@a.com", "username": "user<script>", "password": pw}, [400, 422]),
        ("sqli-user", {"email": f"sqli_{stamp}@a.com", "username": "admin_or_1", "password": pw}, 201),  # username allowed charset
        ("xss-email", {"email": f"<script>@a.com", "username": f"xss_{stamp}", "password": pw}, [400, 422]),
    ]
    for name, payload, code in cases:
        st, _, body, _, _ = req("POST", "/api/v1/auth/register", json_body=payload)
        expect(f"register-{name}", "POST", "/api/v1/auth/register", code, st, note=dump_detail(body))

    # login viewer
    if "viewerA" in users:
        st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerA"]["email"], "password": pw})
        expect("login-viewerA", "POST", "/api/v1/auth/login", 200, st)
        if st == 200:
            viewer_token = body.get("access_token")
            viewer_id = users["viewerA"]["id"]
            rec(
                feature="token-shape",
                method="POST",
                path="/api/v1/auth/login",
                expected="bearer+ttl",
                got=st,
                status="PASS" if body.get("token_type") == "bearer" and body.get("expires_in") else "FAIL",
                note=dump_detail({k: body.get(k) for k in ("token_type", "expires_in")}),
            )
            # cookie?
            # urllib doesn't expose set-cookie easily from http.client in this wrapper — skip

    if "viewerB" in users:
        st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerB"]["email"], "password": pw})
        expect("login-viewerB", "POST", "/api/v1/auth/login", 200, st)
        if st == 200:
            viewer_b_token = body.get("access_token")
            viewer_b_id = users["viewerB"]["id"]

    st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": "nobody@audit.local", "password": pw})
    expect("login-bad-user", "POST", "/api/v1/auth/login", 401, st, note=dump_detail(body))

    if "viewerA" in users:
        st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerA"]["email"], "password": "WrongPassword!!"})
        expect("login-bad-pw", "POST", "/api/v1/auth/login", 401, st, note=dump_detail(body))
        st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerA"]["email"], "password": ""})
        expect("login-empty-pw", "POST", "/api/v1/auth/login", [400, 401, 422], st)

        # lockout: 8 failures
        codes = []
        for _ in range(8):
            st, _, _, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerA"]["email"], "password": "WrongPassword!!"})
            codes.append(st)
        rec(
            feature="login-lockout",
            method="POST",
            path="/api/v1/auth/login",
            expected="429 after N",
            got=codes[-1],
            status="FAIL" if 429 not in codes and 423 not in codes else "PASS",
            note=f"statuses={codes}",
        )

    if viewer_token:
        st, _, body, _, _ = req("GET", " /api/v1/auth/me".strip(), token=viewer_token)
        expect("me", "GET", "/api/v1/auth/me", 200, st, note=dump_detail(body))
        leaked = False
        if isinstance(body, dict):
            blob = json.dumps(body).lower()
            leaked = "password" in blob and "must_change_password" not in blob.replace("must_change_password", "")
            if "password_hash" in blob or "hashed_password" in blob:
                leaked = True
        rec(feature="me-no-password-hash", method="GET", path="/api/v1/auth/me", expected="no hash", got=st, status="FAIL" if leaked else "PASS", note=dump_detail(body))

        st, _, _, _, _ = req("GET", "/api/v1/auth/users", token=viewer_token)
        expect("viewer-list-users", "GET", "/api/v1/auth/users", 403, st)

        st, _, _, _, _ = req("GET", "/api/v1/system/status", token=viewer_token)
        expect("status-auth", "GET", "/api/v1/system/status", 200, st)

        st, _, body, ms, _ = req("GET", "/api/v1/system/status", token=viewer_token)
        rec(feature="status-payload", method="GET", path="/api/v1/system/status", expected=200, got=st, status="PASS" if st == 200 else "FAIL", note=f"{ms}ms {dump_detail(body, 800)}")

        st, _, body, _, _ = req("GET", "/api/v1/models/", token=viewer_token)
        rec(feature="list-models", method="GET", path="/api/v1/models/", expected=200, got=st, status="PASS" if st == 200 else "FAIL", note=dump_detail(body, 600))

        st, _, _, _, _ = req("PUT", "/api/v1/models/roles", token=viewer_token, json_body={"role": "chat", "model_name": "x"})
        expect("viewer-set-roles", "PUT", "/api/v1/models/roles", 403, st)

        st, _, _, _, _ = req("GET", "/api/v1/settings/", token=viewer_token)
        expect("viewer-settings", "GET", "/api/v1/settings/", 403, st)

        st, _, _, _, _ = req("GET", "/api/v1/audit/logs", token=viewer_token)
        expect("viewer-audit", "GET", "/api/v1/audit/logs", 403, st)

        st, _, _, _, _ = req("GET", "/api/v1/approvals/pending", token=viewer_token)
        expect("viewer-approvals", "GET", "/api/v1/approvals/pending", 403, st)

        st, _, _, _, _ = req("POST", "/api/v1/knowledge-bases/", token=viewer_token, json_body={"name": "kb-viewer"})
        expect("viewer-create-kb", "POST", "/api/v1/knowledge-bases/", 403, st)

        st, _, _, _, _ = req("POST", "/api/v1/agents/runs", token=viewer_token, json_body={"goal": "test"})
        expect("viewer-create-agent", "POST", "/api/v1/agents/runs", 403, st)

        st, _, _, _, _ = req("POST", "/api/v1/models/providers/", token=viewer_token, json_body={"name": "x", "provider_type": "ollama", "model_name": "m"})
        expect("viewer-create-provider", "POST", "/api/v1/models/providers/", 403, st)

        # chat isolation
        st, _, conv, _, _ = req("POST", "/api/v1/chat/conversations", token=viewer_token, json_body={"model_name": "llama3.2:3b", "title": "A-secret"})
        expect("create-conv-A", "POST", "/api/v1/chat/conversations", 201, st, note=dump_detail(conv))
        conv_a = conv.get("id") if isinstance(conv, dict) else None

        if conv_a and viewer_b_token:
            st, _, body, _, _ = req("GET", f"/api/v1/chat/conversations/{conv_a}", token=viewer_b_token)
            expect("idor-chat-get", "GET", f"/api/v1/chat/conversations/{conv_a}", 404, st, note=dump_detail(body))
            st, _, body, _, _ = req("DELETE", f"/api/v1/chat/conversations/{conv_a}", token=viewer_b_token)
            expect("idor-chat-delete", "DELETE", f"/api/v1/chat/conversations/{conv_a}", [403, 404], st, note=dump_detail(body))
            st, _, body, _, _ = req("POST", f"/api/v1/chat/conversations/{conv_a}/messages", token=viewer_b_token, json_body={"content": "hack"})
            expect("idor-chat-msg", "POST", f"/api/v1/chat/conversations/{conv_a}/messages", [403, 404], st, note=dump_detail(body)[:200])

        if conv_a:
            st, _, body, ms, raw = req(
                "POST",
                f"/api/v1/chat/conversations/{conv_a}/messages",
                token=viewer_token,
                json_body={"content": "Say hi in one word"},
                timeout=60,
            )
            rec(
                feature="chat-send",
                method="POST",
                path=f"/api/v1/chat/conversations/{conv_a}/messages",
                expected=200,
                got=st,
                status="PASS" if st == 200 else "FAIL",
                note=f"{ms}ms {dump_detail(body, 500)}",
            )
            st, _, body, _, _ = req("POST", f"/api/v1/chat/conversations/{conv_a}/messages", token=viewer_token, json_body={"content": "   "})
            expect("chat-empty-msg", "POST", "/messages", [400, 422], st, note=dump_detail(body))
            st, _, body, _, _ = req(
                "POST",
                f"/api/v1/chat/conversations/{conv_a}/messages",
                token=viewer_token,
                json_body={"content": "x" * 33000},
            )
            expect("chat-too-long", "POST", "/messages", [400, 422], st, note=dump_detail(body))
            st, _, body, _, _ = req("GET", f"/api/v1/chat/conversations/{conv_a}/export?format=markdown", token=viewer_token)
            expect("chat-export", "GET", "/export", 200, st, note=str(body)[:120])

        st, _, body, _, _ = req("GET", "/api/v1/chat/conversations", token=viewer_token)
        expect("list-conv", "GET", "/api/v1/chat/conversations", 200, st, note=f"n={len(body) if isinstance(body, list) else body}")

        if viewer_b_token:
            st, _, body, _, _ = req("GET", "/api/v1/chat/conversations", token=viewer_b_token)
            titles = [c.get("title") for c in body] if isinstance(body, list) else []
            rec(
                feature="chat-list-isolation",
                method="GET",
                path="/api/v1/chat/conversations",
                expected="no A-secret",
                got=st,
                status="FAIL" if "A-secret" in titles else "PASS",
                note=f"titles={titles}",
            )

    # SQL injection login
    st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": "admin' OR 1=1--@x.com", "password": "x"})
    expect("login-sqli", "POST", "/api/v1/auth/login", [400, 401, 422], st, note=dump_detail(body))

    # Admin flows
    if admin_token:
        st, _, me, _, _ = req("GET", "/api/v1/auth/me", token=admin_token)
        expect("admin-me", "GET", "/api/v1/auth/me", 200, st, note=dump_detail(me))
        admin_id = me.get("id") if isinstance(me, dict) else None

        st, _, body, _, _ = req("GET", "/api/v1/auth/users", token=admin_token)
        expect("admin-list-users", "GET", "/api/v1/auth/users", 200, st, note=f"n={len(body) if isinstance(body, list) else body}")

        if viewer_id:
            st, _, body, _, _ = req(
                "PUT",
                f"/api/v1/auth/users/{viewer_id}",
                token=admin_token,
                json_body={"role": "analyst"},
            )
            expect("promote-analyst", "PUT", f"/api/v1/auth/users/{viewer_id}", 200, st, note=dump_detail(body))
            if st == 200:
                # re-login for new token? role is in JWT? JWT only has sub — role from DB
                analyst_token = viewer_token

            st, _, body, _, _ = req(
                "PUT",
                f"/api/v1/auth/users/{viewer_id}",
                token=admin_token,
                json_body={"is_active": False},
            )
            expect("disable-user", "PUT", f"/api/v1/auth/users/{viewer_id}", 200, st, note=dump_detail(body))
            st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerA"]["email"], "password": pw})
            expect("login-disabled", "POST", "/api/v1/auth/login", 403, st, note=dump_detail(body))
            st, _, body, _, _ = req(
                "PUT",
                f"/api/v1/auth/users/{viewer_id}",
                token=admin_token,
                json_body={"is_active": True, "role": "analyst"},
            )
            expect("enable-user", "PUT", f"/api/v1/auth/users/{viewer_id}", 200, st)
            st, _, body, _, _ = req("POST", "/api/v1/auth/login", json_body={"email": users["viewerA"]["email"], "password": pw})
            if st == 200:
                analyst_token = body.get("access_token")
            expect("login-reenabled", "POST", "/api/v1/auth/login", 200, st)

            st, _, body, _, _ = req("PUT", f"/api/v1/auth/users/{uuid.uuid4()}", token=admin_token, json_body={"role": "viewer"})
            expect("update-bad-id", "PUT", "/api/v1/auth/users/{id}", 404, st, note=dump_detail(body))

        st, _, _, _, _ = req("DELETE", f"/api/v1/auth/users/{viewer_b_id or 'x'}", token=admin_token)
        rec(
            feature="delete-user-endpoint",
            method="DELETE",
            path="/api/v1/auth/users/{id}",
            expected="exists",
            got=st,
            status="FAIL" if st in (404, 405, 0) else "PASS",
            note="User delete endpoint missing or not implemented" if st in (404, 405) else dump_detail(st),
        )

        # providers
        st, _, body, _, _ = req("GET", "/api/v1/models/providers/", token=admin_token)
        rec(feature="list-providers", method="GET", path="/api/v1/models/providers/", expected=200, got=st, status="PASS" if st == 200 else "FAIL", note=dump_detail(body, 800))
        leaked_key = False
        if isinstance(body, list):
            for p in body:
                blob = json.dumps(p).lower()
                if "api_key" in blob and "has_api_key" not in blob.replace("has_api_key", ""):
                    leaked_key = True
                if p.get("api_key"):
                    leaked_key = True
        rec(feature="provider-key-not-listed", method="GET", path="/api/v1/models/providers/", expected="no api_key", got=st, status="FAIL" if leaked_key else "PASS")

        secret = "sk-live-AUDIT-DO-NOT-LEAK-999"
        st, _, body, _, _ = req(
            "POST",
            "/api/v1/models/providers/",
            token=admin_token,
            json_body={
                "name": f"ssrf-probe-{stamp}",
                "provider_type": "openai_compatible",
                "environment": "custom",
                "base_url": "http://127.0.0.1:9",
                "model_name": "probe",
                "api_key": secret,
            },
        )
        expect("create-custom-provider", "POST", "/api/v1/models/providers/", 201, st, note=dump_detail(body))
        pid = body.get("id") if isinstance(body, dict) else None
        if isinstance(body, dict) and (body.get("api_key") == secret or secret in json.dumps(body)):
            rec(feature="provider-create-leaks-key", method="POST", path="/providers", expected="no key", got=201, status="FAIL", note="api_key echoed")
        else:
            rec(feature="provider-create-leaks-key", method="POST", path="/providers", expected="no key", got=st, status="PASS", note="key not in create response")

        if pid:
            st, _, body, _, _ = req("GET", f"/api/v1/models/providers/{pid}", token=admin_token)
            expect("get-provider", "GET", f"/api/v1/models/providers/{pid}", 200, st, note=dump_detail(body))
            if secret in json.dumps(body):
                rec(feature="provider-get-leaks-key", method="GET", path="/providers/id", expected="no key", got=st, status="FAIL")
            else:
                rec(feature="provider-get-leaks-key", method="GET", path="/providers/id", expected="no key", got=st, status="PASS")

            st, _, body, ms, _ = req("POST", f"/api/v1/models/providers/{pid}/test", token=admin_token, timeout=20)
            rec(
                feature="provider-ssrf-test",
                method="POST",
                path=f"/api/v1/models/providers/{pid}/test",
                expected="blocked or fail closed",
                got=st,
                status="FAIL" if st == 200 and isinstance(body, dict) and body.get("success") else ("PASS" if st in (200, 400, 422, 502, 504) else "FAIL"),
                note=f"{ms}ms {dump_detail(body)} — custom base_url to 127.0.0.1 accepted (SSRF surface)",
            )

            st, _, body, _, _ = req("PUT", f"/api/v1/models/providers/{pid}", token=admin_token, json_body={"enabled": False})
            expect("update-provider", "PUT", f"/providers/{pid}", 200, st, note=dump_detail(body))
            st, _, _, _, _ = req("DELETE", f"/api/v1/models/providers/{pid}", token=admin_token)
            expect("delete-provider", "DELETE", f"/providers/{pid}", [200, 204], st)

        # metadata SSRF candidate
        st, _, body, _, _ = req(
            "POST",
            "/api/v1/models/providers/",
            token=admin_token,
            json_body={
                "name": f"file-url-{stamp}",
                "provider_type": "openai_compatible",
                "environment": "custom",
                "base_url": "file:///etc/passwd",
                "model_name": "x",
            },
        )
        rec(
            feature="provider-file-url",
            method="POST",
            path="/providers",
            expected="reject",
            got=st,
            status="FAIL" if st in (200, 201) else "PASS",
            note=dump_detail(body),
        )
        if st in (200, 201) and isinstance(body, dict) and body.get("id"):
            req("DELETE", f"/api/v1/models/providers/{body['id']}", token=admin_token)

        st, _, body, _, _ = req("GET", "/api/v1/settings/", token=admin_token)
        expect("get-settings", "GET", "/api/v1/settings/", 200, st, note=dump_detail(body, 500))
        st, _, body, _, _ = req("GET", "/api/v1/settings/summary", token=admin_token)
        expect("dashboard-summary", "GET", "/api/v1/settings/summary", 200, st, note=dump_detail(body, 500))
        st, _, body, _, _ = req("GET", "/api/v1/audit/logs", token=admin_token)
        expect("audit-logs", "GET", "/api/v1/audit/logs", 200, st, note=dump_detail(body, 300))
        st, _, body, _, _ = req("GET", "/api/v1/audit/verify", token=admin_token)
        expect("audit-verify", "GET", "/api/v1/audit/verify", 200, st, note=dump_detail(body, 300))

        # KB as admin
        st, _, kb, _, _ = req("POST", "/api/v1/knowledge-bases/", token=admin_token, json_body={"name": f"kb-admin-{stamp}", "description": "audit"})
        expect("create-kb-admin", "POST", "/api/v1/knowledge-bases/", 201, st, note=dump_detail(kb))
        kb_id = kb.get("id") if isinstance(kb, dict) else None

        if kb_id:
            # upload txt
            boundary = "----AuditBoundary"
            filename = "../../etc/passwd.txt"
            content = b"The secret project codeword is BLUEBANANA for retrieval testing.\n"
            body_bytes = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"kb_id\"\r\n\r\n{kb_id}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: text/plain\r\n\r\n"
            ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
            st, _, doc, _, _ = req(
                "POST",
                "/api/v1/documents/upload",
                token=admin_token,
                data=body_bytes,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            rec(
                feature="upload-txt-traversal-name",
                method="POST",
                path="/api/v1/documents/upload",
                expected=202,
                got=st,
                status="PASS" if st in (200, 201, 202) else "FAIL",
                note=dump_detail(doc),
            )
            doc_id = doc.get("id") if isinstance(doc, dict) else None
            if viewer_b_token and doc_id:
                st, _, body, _, _ = req("GET", f"/api/v1/documents/{doc_id}", token=viewer_b_token)
                rec(
                    feature="idor-document-get",
                    method="GET",
                    path=f"/api/v1/documents/{doc_id}",
                    expected="403/404",
                    got=st,
                    status="FAIL" if st == 200 else "PASS",
                    note=dump_detail(body),
                )
                st, _, body, _, _ = req("GET", "/api/v1/documents/", token=viewer_b_token)
                rec(
                    feature="idor-document-list",
                    method="GET",
                    path="/api/v1/documents/",
                    expected="isolated",
                    got=st,
                    status="FAIL" if st == 200 and isinstance(body, list) and any(d.get("id") == doc_id for d in body) else ("PASS" if st in (200, 403) else "FAIL"),
                    note=dump_detail(body, 400),
                )
                st, _, body, _, _ = req("GET", f"/api/v1/knowledge-bases/{kb_id}", token=viewer_b_token)
                rec(
                    feature="idor-kb-get",
                    method="GET",
                    path=f"/api/v1/knowledge-bases/{kb_id}",
                    expected="403/404",
                    got=st,
                    status="FAIL" if st == 200 else "PASS",
                    note=dump_detail(body),
                )
                st, _, body, _, _ = req("GET", "/api/v1/knowledge-bases/", token=viewer_b_token)
                rec(
                    feature="idor-kb-list",
                    method="GET",
                    path="/api/v1/knowledge-bases/",
                    expected="isolated",
                    got=st,
                    status="FAIL" if st == 200 and isinstance(body, list) and any(k.get("id") == kb_id for k in body) else "PASS",
                    note=f"n={len(body) if isinstance(body, list) else body}",
                )

            # empty file
            boundary = "----AuditBoundary2"
            body_bytes = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"kb_id\"\r\n\r\n{kb_id}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"empty.txt\"\r\nContent-Type: text/plain\r\n\r\n"
            ).encode() + f"\r\n--{boundary}--\r\n".encode()
            st, _, body, _, _ = req(
                "POST",
                "/api/v1/documents/upload",
                token=admin_token,
                data=body_bytes,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            expect("upload-empty", "POST", "/documents/upload", [400, 422], st, note=dump_detail(body))

            # exe
            boundary = "----AuditBoundary3"
            body_bytes = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"kb_id\"\r\n\r\n{kb_id}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"evil.exe\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            ).encode() + b"MZ" + b"\x00" * 20 + f"\r\n--{boundary}--\r\n".encode()
            st, _, body, _, _ = req(
                "POST",
                "/api/v1/documents/upload",
                token=admin_token,
                data=body_bytes,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            expect("upload-exe", "POST", "/documents/upload", [400, 415, 422], st, note=dump_detail(body))

            # wait processing
            if doc_id:
                last = None
                for _ in range(12):
                    time.sleep(2)
                    st, _, last, _, _ = req("GET", f"/api/v1/documents/{doc_id}", token=admin_token)
                    if isinstance(last, dict) and last.get("status") in ("ready", "indexed", "completed", "failed", "error"):
                        break
                rec(
                    feature="doc-processing",
                    method="GET",
                    path=f"/api/v1/documents/{doc_id}",
                    expected="ready",
                    got=st,
                    status="PASS" if isinstance(last, dict) and last.get("status") in ("ready", "indexed", "completed") else "FAIL",
                    note=dump_detail(last),
                )
                st, _, body, ms, _ = req(
                    "POST",
                    f"/api/v1/knowledge-bases/{kb_id}/query",
                    token=admin_token,
                    json_body={"query": "What is the secret project codeword?", "top_k": 5},
                    timeout=90,
                )
                rec(
                    feature="rag-query",
                    method="POST",
                    path=f"/knowledge-bases/{kb_id}/query",
                    expected=200,
                    got=st,
                    status="PASS" if st == 200 else "FAIL",
                    note=f"{ms}ms {dump_detail(body, 700)}",
                )

            if viewer_b_token:
                st, _, body, _, _ = req(
                    "POST",
                    f"/api/v1/knowledge-bases/{kb_id}/query",
                    token=viewer_b_token,
                    json_body={"query": "What is the secret project codeword?"},
                    timeout=60,
                )
                rec(
                    feature="idor-kb-query",
                    method="POST",
                    path=f"/knowledge-bases/{kb_id}/query",
                    expected="403/404",
                    got=st,
                    status="FAIL" if st == 200 else "PASS",
                    note=dump_detail(body, 400),
                )

        if analyst_token:
            st, _, kb2, _, _ = req("POST", "/api/v1/knowledge-bases/", token=analyst_token, json_body={"name": f"kb-analyst-{stamp}"})
            expect("analyst-create-kb", "POST", "/api/v1/knowledge-bases/", 201, st, note=dump_detail(kb2))
            st, _, run, _, _ = req("POST", "/api/v1/agents/runs", token=analyst_token, json_body={"goal": "Calculate 2+2 using tools if needed"})
            rec(
                feature="agent-create",
                method="POST",
                path="/api/v1/agents/runs",
                expected=202,
                got=st,
                status="PASS" if st in (200, 201, 202) else "FAIL",
                note=dump_detail(run),
            )
            run_id = run.get("id") if isinstance(run, dict) else None
            st, _, tools, _, _ = req("GET", "/api/v1/agents/tools", token=analyst_token)
            rec(feature="agent-tools", method="GET", path="/api/v1/agents/tools", expected=200, got=st, status="PASS" if st == 200 else "FAIL", note=dump_detail(tools, 500))
            if run_id and viewer_b_token:
                st, _, body, _, _ = req("GET", f"/api/v1/agents/runs/{run_id}", token=viewer_b_token)
                rec(
                    feature="idor-agent-get",
                    method="GET",
                    path=f"/agents/runs/{run_id}",
                    expected="403/404",
                    got=st,
                    status="FAIL" if st == 200 else "PASS",
                    note=dump_detail(body),
                )

        st, _, _, _, _ = req("POST", "/api/v1/auth/logout", token=admin_token)
        expect("logout", "POST", "/api/v1/auth/logout", [200, 204], st)
        st, _, _, _, _ = req("GET", "/api/v1/auth/me", token=admin_token)
        rec(
            feature="logout-invalidates-access",
            method="GET",
            path="/api/v1/auth/me",
            expected=401,
            got=st,
            status="FAIL" if st == 200 else "PASS",
            note="access JWT still valid after logout (stateless JWT) " if st == 200 else "",
        )

    # unauthenticated sweep of write endpoints
    for method, path, body in [
        ("GET", "/api/v1/auth/me", None),
        ("GET", "/api/v1/chat/conversations", None),
        ("POST", "/api/v1/chat/conversations", {"model_name": "x"}),
        ("GET", "/api/v1/models/", None),
        ("GET", "/api/v1/knowledge-bases/", None),
        ("POST", "/api/v1/knowledge-bases/", {"name": "x"}),
        ("GET", "/api/v1/documents/", None),
        ("GET", "/api/v1/agents/runs", None),
        ("GET", "/api/v1/agents/tools", None),
        ("GET", "/api/v1/models/providers/", None),
        ("GET", "/api/v1/audit/logs", None),
        ("GET", "/api/v1/settings/", None),
        ("GET", "/api/v1/system/resources", None),
        ("GET", "/api/v1/system/activity", None),
    ]:
        st, _, _, _, _ = req(method, path, json_body=body)
        expect(f"unauth-{method}-{path}", method, path, 401, st)

    # frontend
    st, _, body, ms, raw = req("GET", "/")  # this hits backend :8000 not frontend
    rec(feature="backend-root", method="GET", path="/", expected="docs or 404", got=st, status="PASS", note=f"{ms}ms")

    out = {
        "pass": sum(1 for r in results if r["status"] == "PASS"),
        "fail": sum(1 for r in results if r["status"] == "FAIL"),
        "total": len(results),
        "results": results,
    }
    path = os.path.join(os.path.dirname(__file__), "_live_audit_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nSUMMARY", out["pass"], "pass", out["fail"], "fail", "of", out["total"])
    print("WROTE", path)


if __name__ == "__main__":
    main()
