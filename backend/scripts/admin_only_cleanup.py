"""
Admin-only cleanup for local prototype DB (SQLite).

- Resets the admin user's password to the configured demo password
  (admin12345678) so the demo credential actually verifies.
- Deletes every non-admin user and ALL their dependent rows, in FK
  dependency order (PRAGMA foreign_keys=ON is enforced by the app).

Run inside the backend container:  python scripts/admin_only_cleanup.py
"""
import asyncio

from passlib.context import CryptContext
from sqlalchemy import bindparam, select, text

from database import AsyncSessionLocal
from models.user import User

ADMIN_EMAIL = "admin@admin.com"
ADMIN_DEMO_PASSWORD = "admin12345678"

pwd_ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12, deprecated="auto")


async def main() -> None:
    async with AsyncSessionLocal() as session:
        # ---- 1. Identify admin ----
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if not admin:
            print(f"ERROR: no user with email {ADMIN_EMAIL} found — aborting.")
            return
        if admin.role != "admin":
            print(f"ERROR: {ADMIN_EMAIL} is role='{admin.role}', not admin — aborting.")
            return
        print(f"Admin found: {admin.email} (username={admin.username}, role={admin.role}, id={admin.id})")

        # ---- 2. Reset admin password ----
        admin.password_hash = pwd_ctx.hash(ADMIN_DEMO_PASSWORD)
        print(f"Password reset for {admin.email} -> configured demo password (bcrypt rounds=12).")

        # ---- 3. Collect non-admin users ----
        result = await session.execute(select(User).where(User.role != "admin"))
        to_delete = list(result.scalars().all())
        print(f"\nNon-admin users to delete: {len(to_delete)}")
        for u in to_delete:
            print(f"  - {u.email} (role={u.role}, id={u.id})")

        if to_delete:
            ids = [u.id for u in to_delete]

            async def run(sql: str, **params) -> int:
                stmt = text(sql)
                # ':ids' appears many times and is an expanding IN list
                stmt = stmt.bindparams(bindparam("ids", expanding=True))
                for k, v in params.items():
                    stmt = stmt.bindparams(bindparam(k, value=v))
                res = await session.execute(stmt, {"ids": ids, **params})
                return res.rowcount if res.rowcount is not None else -1

            # approval_requests: references agent_runs/tool_calls/users
            n = await run(
                "DELETE FROM approval_requests WHERE agent_run_id IN "
                "(SELECT id FROM agent_runs WHERE user_id IN :ids) "
                "OR requester_id IN :ids OR decided_by IN :ids"
            )
            print(f"  approval_requests: deleted {n}")

            n = await run(
                "DELETE FROM agent_events WHERE run_id IN "
                "(SELECT id FROM agent_runs WHERE user_id IN :ids)"
            )
            print(f"  agent_events: deleted {n}")

            n = await run(
                "DELETE FROM tool_calls WHERE agent_run_id IN "
                "(SELECT id FROM agent_runs WHERE user_id IN :ids)"
            )
            print(f"  tool_calls: deleted {n}")

            n = await run("DELETE FROM agent_runs WHERE user_id IN :ids")
            print(f"  agent_runs: deleted {n}")

            n = await run(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE user_id IN :ids)"
            )
            print(f"  messages: deleted {n}")

            n = await run("DELETE FROM conversations WHERE user_id IN :ids")
            print(f"  conversations: deleted {n}")

            n = await run("DELETE FROM inspection_images WHERE owner_id IN :ids")
            print(f"  inspection_images: deleted {n}")

            n = await run("DELETE FROM incidents WHERE owner_id IN :ids")
            print(f"  incidents: deleted {n}")

            n = await run("DELETE FROM sensor_analyses WHERE owner_id IN :ids")
            print(f"  sensor_analyses: deleted {n}")

            # documents reference knowledge_bases (CASCADE) + users.uploader_id (NO ondelete)
            n = await run(
                "DELETE FROM documents WHERE kb_id IN "
                "(SELECT id FROM knowledge_bases WHERE owner_id IN :ids) "
                "OR uploader_id IN :ids"
            )
            print(f"  documents: deleted {n}")

            n = await run("DELETE FROM knowledge_bases WHERE owner_id IN :ids")
            print(f"  knowledge_bases: deleted {n}")

            n = await run(
                "DELETE FROM data_sources WHERE org_id IN "
                "(SELECT id FROM organizations WHERE owner_id IN :ids)"
            )
            print(f"  data_sources: deleted {n}")

            n = await run("DELETE FROM organizations WHERE owner_id IN :ids")
            print(f"  organizations: deleted {n}")

            n = await run("DELETE FROM audit_logs WHERE user_id IN :ids")
            print(f"  audit_logs: deleted {n}")

            n = await run("DELETE FROM user_model_prefs WHERE user_id IN :ids")
            print(f"  user_model_prefs: deleted {n}")

            n = await run("DELETE FROM refresh_tokens WHERE user_id IN :ids")
            print(f"  refresh_tokens: deleted {n}")

            # ---------- 5. Delete the users themselves ----------
            n = await run("DELETE FROM users WHERE id IN :ids")
            print(f"  users: deleted {n}")

        await session.commit()

        # ---- 6. Verify final state ----
        result = await session.execute(select(User).order_by(User.created_at))
        remaining = list(result.scalars().all())
        print("\n===== FINAL USERS =====")
        for u in remaining:
            print(f"  {u.email}  (username={u.username}, role={u.role}, is_active={u.is_active})")
        print(f"TOTAL: {len(remaining)}")

        ok = pwd_ctx.verify(ADMIN_DEMO_PASSWORD, admin.password_hash)
        print(f"Admin demo password verifies against stored hash: {ok}")

        print("\n===== CHILD ROWS REMAINING FOR ADMIN =====")
        for table, col in [
            ("conversations", "user_id"),
            ("agent_runs", "user_id"),
            ("knowledge_bases", "owner_id"),
            ("organizations", "owner_id"),
            ("sensor_analyses", "owner_id"),
            ("incidents", "owner_id"),
        ]:
            cnt = (await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :aid").bindparams(bindparam("aid", value=admin.id))
            )).scalar_one()
            print(f"  {table}: {cnt}")


if __name__ == "__main__":
    asyncio.run(main())