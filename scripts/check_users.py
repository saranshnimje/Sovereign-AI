#!/usr/bin/env python3
"""Check which test accounts exist in the live stack."""
import requests

BASE = "http://localhost/api/v1"
W = "------------------------------------------------------------------------"

candidates = [
    # From validate_stack.py (most recent run)
    ("validate@sovereign.example.com", "Validator2026Pass"),
    # From rag_validation.py
    ("rag_test@sovereign.example.com", "RagTestPass2026"),
    ("ragadmin@sovereign.example.com", "RagAdmin2026Pass"),
    # From validate_stack.py RBAC section
    ("rbac_viewer@test.example.com", "RbacViewer2026Pass"),
    # From test_phase4_api.py / test_phase5_api.py
    ("admin@demo.local", "SovereignDemo2026!"),
    # conftest.py test admin
    ("admin@test.com", "StrongPassword123!"),
    # Phase 5 validation scripts
    ("sec_admin@x.com", "StrongPass123!"),
]

print(W)
print("  Live User Account Check")
print(W)

found_admin = None

for email, pwd in candidates:
    try:
        r = requests.post(
            BASE + "/auth/login",
            json={"email": email, "password": pwd},
            timeout=5,
        )
        if r.status_code == 200:
            token = r.json().get("access_token", "")
            me = requests.get(
                BASE + "/auth/me",
                headers={"Authorization": "Bearer " + token},
                timeout=5,
            )
            u = me.json()
            role = u.get("role", "?")
            username = u.get("username", "?")
            active = u.get("is_active", "?")
            status = "ACTIVE" if active else "DISABLED"
            print(f"  FOUND  [{status}]  email={email}")
            print(f"         username={username}  role={role}")
            print(f"         password={pwd}")
            print()
            if role == "admin" and active and not found_admin:
                found_admin = (email, pwd, username, role)
        else:
            print(f"  not found  {email}  (HTTP {r.status_code})")
    except Exception as e:
        print(f"  error  {email}  {e}")

print(W)
if found_admin:
    email, pwd, username, role = found_admin
    print(f"\n  RECOMMENDED ADMIN FOR FRONTEND TESTING:")
    print(f"  Email:    {email}")
    print(f"  Password: {pwd}")
    print(f"  Username: {username}")
    print(f"  Role:     {role}")
    print(f"  URL:      http://localhost")
else:
    print("\n  NO USABLE ADMIN FOUND — see instructions below")
    print("  Run the create_admin.py script to create a fresh admin.")
print(W)
