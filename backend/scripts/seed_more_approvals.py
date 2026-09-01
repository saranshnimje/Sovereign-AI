"""
Additional approval request sample data.
Run: docker exec sovereignaiworkbench-backend-1 python -m scripts.seed_more_approvals
"""
import json
import sys
import os
import random
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import uuid
from database import AsyncSessionLocal
from models.user import User
from models.agent import AgentRun, ApprovalRequest

from sqlalchemy import select


def utcnow():
    return datetime.now(timezone.utc)


MORE_APPROVALS = [
    {
        "operation": "Modify production schedule for Line 2: swap batch orders",
        "operation_detail_json": json.dumps({"tool_name": "production_planner", "input": {"line": 2, "action": "swap_orders", "order_a": "PO-4521", "order_b": "PO-4538"}}),
        "risk_level": "high", "status": "pending", "expires_hours": 2,
    },
    {
        "operation": "Run predictive maintenance model on compressor unit C-12",
        "operation_detail_json": json.dumps({"tool_name": "python_exec", "input": {"script": "predictive_maintenance.py", "params": {"asset": "C-12", "model": "xgboost_v2"}}}),
        "risk_level": "low", "status": "approved", "decided_hours_ago": 3, "decision_note": "Approved. Predictive models are read-only and safe to run.", "expires_hours": 24,
    },
    {
        "operation": "Export quality inspection data to external vendor portal",
        "operation_detail_json": json.dumps({"tool_name": "data_export", "input": {"destination": "vendor_portal", "dataset": "qc_inspections_aug2025", "format": "csv"}}),
        "risk_level": "critical", "status": "rejected", "decided_hours_ago": 4, "decision_note": "Rejected: Data export to external systems requires management approval and data classification review.", "expires_hours": 24,
    },
    {
        "operation": "Update vendor scoring weights in procurement system",
        "operation_detail_json": json.dumps({"tool_name": "config_update", "input": {"module": "procurement", "setting": "vendor_scoring_weights", "values": {"quality": 0.4, "delivery": 0.3, "price": 0.2, "sustainability": 0.1}}}),
        "risk_level": "medium", "status": "pending", "expires_hours": 6,
    },
    {
        "operation": "Execute batch data cleaning on sensor readings",
        "operation_detail_json": json.dumps({"tool_name": "python_exec", "input": {"script": "batch_data_clean.py", "params": {"source": "sensor_readings", "dedup": True, "fillna": "interpolate"}}}),
        "risk_level": "medium", "status": "approved", "decided_hours_ago": 2, "decision_note": "Approved. Data cleaning script is non-destructive, creates backup before modifying.", "expires_hours": 24,
    },
    {
        "operation": "Send email alert to procurement team about expired contracts",
        "operation_detail_json": json.dumps({"tool_name": "notification_send", "input": {"channel": "email", "recipient": "procurement@company.com", "template": "expired_contracts_alert", "count": 3}}),
        "risk_level": "low", "status": "pending", "expires_hours": 12,
    },
    {
        "operation": "Delete archived audit logs older than 2 years",
        "operation_detail_json": json.dumps({"tool_name": "data_maintenance", "input": {"target": "audit_logs", "filter": {"older_than": "2023-08-01"}, "dry_run": False}}),
        "risk_level": "critical", "status": "pending", "expires_hours": 1,
    },
    {
        "operation": "Modify agent permissions: allow web_search tool for analyst role",
        "operation_detail_json": json.dumps({"tool_name": "config_update", "input": {"module": "agent_permissions", "role": "analyst", "add_tool": "web_search"}}),
        "risk_level": "high", "status": "approved", "decided_hours_ago": 5, "decision_note": "Approved. Web search is read-only and analysts need it for research tasks.", "expires_hours": 24,
    },
    {
        "operation": "Run FFT vibration analysis script with elevated memory limit",
        "operation_detail_json": json.dumps({"tool_name": "python_exec", "input": {"script": "fft_analysis.py", "params": {"memory_limit": "2GB", "time_range": "30d"}}}),
        "risk_level": "medium", "status": "rejected", "decided_hours_ago": 1, "decision_note": "Rejected: Memory limit exceeds sandbox cap (512MB). Use chunked processing instead.", "expires_hours": 24,
    },
    {
        "operation": "Create new knowledge base from uploaded maintenance PDFs",
        "operation_detail_json": json.dumps({"tool_name": "kb_create", "input": {"name": "Compressor Maintenance Archive", "source": "uploaded_files", "file_count": 12, "embedding_model": "nomic-embed-text"}}),
        "risk_level": "low", "status": "approved", "decided_hours_ago": 6, "decision_note": "Approved. New KB creation is a standard operation.", "expires_hours": 24,
    },
    {
        "operation": "Execute network scan script on production subnet",
        "operation_detail_json": json.dumps({"tool_name": "python_exec", "input": {"script": "network_scan.py", "params": {"target": "192.168.1.0/24", "ports": "common"}}}),
        "risk_level": "critical", "status": "rejected", "decided_hours_ago": 7, "decision_note": "Rejected: Network scanning is a restricted operation. Must be performed by IT security team directly.", "expires_hours": 24,
    },
    {
        "operation": "Update Ollama model configuration: increase context window for qwen3:14b",
        "operation_detail_json": json.dumps({"tool_name": "config_update", "input": {"module": "llm_providers", "provider": "ollama", "model": "qwen3:14b", "setting": "num_ctx", "value": 8192}}),
        "risk_level": "medium", "status": "pending", "expires_hours": 4,
    },
    {
        "operation": "Archive completed agent runs older than 90 days",
        "operation_detail_json": json.dumps({"tool_name": "data_maintenance", "input": {"target": "agent_runs", "filter": {"status": "completed", "older_than_days": 90}, "action": "archive"}}),
        "risk_level": "high", "status": "pending", "expires_hours": 3,
    },
    {
        "operation": "Import sensor calibration data from CSV file",
        "operation_detail_json": json.dumps({"tool_name": "data_import", "input": {"source": "calibration_aug2025.csv", "target": "sensor_calibrations", "rows": 450, "overwrite": False}}),
        "risk_level": "low", "status": "approved", "decided_hours_ago": 8, "decision_note": "Approved. Import is append-only and does not overwrite existing records.", "expires_hours": 24,
    },
    {
        "operation": "Execute SQL query against production database",
        "operation_detail_json": json.dumps({"tool_name": "python_exec", "input": {"script": "sql_query.py", "params": {"connection": "production", "query": "SELECT * FROM orders WHERE status='pending'"}}}),
        "risk_level": "critical", "status": "pending", "expires_hours": 1,
    },
]


async def seed():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.role == "admin").limit(1))
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            print("No admin user found.")
            return
        user_id = admin_user.id

        result = await session.execute(select(AgentRun.id).limit(10))
        run_ids = [row[0] for row in result.all()]

        print(f"Adding {len(MORE_APPROVALS)} approval requests...")
        for i, data in enumerate(MORE_APPROVALS):
            created_at = utcnow() - timedelta(hours=random.randint(1, 12))
            decided_by = user_id if data["status"] in ("approved", "rejected") else None
            decided_at = (utcnow() - timedelta(hours=data.get("decided_hours_ago", 1))) if decided_by else None

            approval = ApprovalRequest(
                id=str(uuid.uuid4()),
                agent_run_id=run_ids[i % len(run_ids)] if run_ids else None,
                tool_call_id=None,
                requester_id=user_id,
                operation=data["operation"],
                operation_detail_json=data["operation_detail_json"],
                risk_level=data["risk_level"],
                status=data["status"],
                decided_by=decided_by,
                decided_at=decided_at,
                decision_note=data.get("decision_note"),
                expires_at=created_at + timedelta(hours=data["expires_hours"]),
            )
            approval.created_at = created_at
            session.add(approval)

            icon = {"pending": "⏳", "approved": "✓", "rejected": "✗"}[data["status"]]
            print(f"  {icon} {data['operation'][:60]}... [{data['risk_level']}]")

        await session.commit()
        print(f"\n✓ {len(MORE_APPROVALS)} approval requests added!")


if __name__ == "__main__":
    asyncio.run(seed())
