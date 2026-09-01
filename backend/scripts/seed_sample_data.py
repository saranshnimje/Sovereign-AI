"""
Seed script for sample knowledge bases, agent runs, and approval requests.
Run: docker exec sovereignaiworkbench-backend-1 python -m scripts.seed_sample_data
"""
import json
import sys
import os
import random
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import uuid
from database import AsyncSessionLocal, engine, Base
from models.user import User
from models.knowledge_base import KnowledgeBase, Document
from models.agent import AgentRun, ToolCall, ApprovalRequest


def utcnow():
    return datetime.now(timezone.utc)


SAMPLE_KNOWLEDGE_BASES = [
    {
        "name": "Industrial Safety Manual",
        "description": "Comprehensive safety protocols and procedures for manufacturing environments, including PPE guidelines, emergency response, and hazard identification.",
        "embedding_model": "nomic-embed-text",
        "documents": [
            {"original_name": "safety_handbook_2024.pdf", "mime_type": "application/pdf", "size_bytes": 2450000, "status": "indexed", "page_count": 84, "chunk_count": 312},
            {"original_name": "ppe_guidelines.pdf", "mime_type": "application/pdf", "size_bytes": 890000, "status": "indexed", "page_count": 28, "chunk_count": 96},
            {"original_name": "emergency_response_plan.docx", "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size_bytes": 156000, "status": "indexed", "page_count": 12, "chunk_count": 45},
            {"original_name": "incident_reporting_template.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size_bytes": 67000, "status": "indexed", "page_count": 3, "chunk_count": 8},
        ],
    },
    {
        "name": "Machine Maintenance Records",
        "description": "Historical maintenance logs, preventive maintenance schedules, and equipment calibration records for all production machinery.",
        "embedding_model": "nomic-embed-text",
        "documents": [
            {"original_name": "maintenance_log_Q1_2025.csv", "mime_type": "text/csv", "size_bytes": 340000, "status": "indexed", "page_count": None, "chunk_count": 156},
            {"original_name": "maintenance_log_Q2_2025.csv", "mime_type": "text/csv", "size_bytes": 420000, "status": "indexed", "page_count": None, "chunk_count": 189},
            {"original_name": "calibration_records_2024.pdf", "mime_type": "application/pdf", "size_bytes": 1200000, "status": "indexed", "page_count": 42, "chunk_count": 168},
            {"original_name": "preventive_maintenance_schedule.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size_bytes": 98000, "status": "indexed", "page_count": 6, "chunk_count": 24},
            {"original_name": "equipment_downtime_report_2025.pdf", "mime_type": "application/pdf", "size_bytes": 780000, "status": "processing", "page_count": None, "chunk_count": 0},
        ],
    },
    {
        "name": "Quality Control Standards",
        "description": "ISO 9001:2015 quality management documentation, inspection checklists, defect classification, and SPC guidelines.",
        "embedding_model": "nomic-embed-text",
        "documents": [
            {"original_name": "iso9001_manual.pdf", "mime_type": "application/pdf", "size_bytes": 3200000, "status": "indexed", "page_count": 120, "chunk_count": 480},
            {"original_name": "inspection_checklist_CNC.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size_bytes": 45000, "status": "indexed", "page_count": 2, "chunk_count": 12},
            {"original_name": "defect_classification_guide.pdf", "mime_type": "application/pdf", "size_bytes": 560000, "status": "indexed", "page_count": 18, "chunk_count": 72},
            {"original_name": "spc_control_charts_template.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size_bytes": 120000, "status": "failed", "page_count": None, "chunk_count": 0, "error_message": "Unsupported chart format in embedded objects"},
        ],
    },
    {
        "name": "Employee Training Materials",
        "description": "Onboarding documentation, training videos transcripts, certification requirements, and skill assessment frameworks.",
        "embedding_model": "nomic-embed-text",
        "documents": [
            {"original_name": "onboarding_guide_2025.pdf", "mime_type": "application/pdf", "size_bytes": 980000, "status": "indexed", "page_count": 36, "chunk_count": 144},
            {"original_name": "safety_training_transcript.txt", "mime_type": "text/plain", "size_bytes": 45000, "status": "indexed", "page_count": None, "chunk_count": 89},
            {"original_name": "certification_requirements.docx", "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size_bytes": 230000, "status": "indexed", "page_count": 8, "chunk_count": 32},
        ],
    },
    {
        "name": "Supply Chain & Vendor Directory",
        "description": "Vendor contracts, supplier performance metrics, lead time analysis, and procurement policies.",
        "embedding_model": "nomic-embed-text",
        "documents": [
            {"original_name": "vendor_directory_2025.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size_bytes": 280000, "status": "indexed", "page_count": 4, "chunk_count": 18},
            {"original_name": "procurement_policy.pdf", "mime_type": "application/pdf", "size_bytes": 670000, "status": "indexed", "page_count": 22, "chunk_count": 88},
            {"original_name": "supplier_scorecard_Q2.csv", "mime_type": "text/csv", "size_bytes": 56000, "status": "pending", "page_count": None, "chunk_count": 0},
        ],
    },
]

SAMPLE_AGENT_RUNS = [
    {
        "goal": "Analyze bearing vibration data from Line 3 and compare against historical failure patterns",
        "status": "completed",
        "model_name": "qwen3:14b",
        "step_count": 5,
        "iteration_count": 5,
        "result": "Analysis complete. Bearing temperature on Line 3 is 12% above baseline. Vibration amplitude shows periodic spikes at 2.3kHz, consistent with inner race defect pattern. Recommend inspection within 48 hours.",
        "plan_json": json.dumps([
            {"step": 1, "tool": "knowledge_search", "description": "Search KB for bearing failure patterns"},
            {"step": 2, "tool": "data_query", "description": "Query Line 3 sensor data for last 7 days"},
            {"step": 3, "tool": "python_exec", "description": "Run FFT analysis on vibration data"},
            {"step": 4, "tool": "knowledge_search", "description": "Search for similar historical incidents"},
            {"step": 5, "tool": "report_generator", "description": "Compile analysis report"},
        ]),
        "tool_calls": [
            {"tool_name": "knowledge_search", "step_number": 1, "status": "success", "duration_ms": 1200, "input_data": json.dumps({"query": "bearing failure vibration patterns", "kb_ids": []}), "output_data": json.dumps({"results": 3, "top_score": 0.89})},
            {"tool_name": "data_query", "step_number": 2, "status": "success", "duration_ms": 3400, "input_data": json.dumps({"source": "line_3_sensors", "metrics": ["temperature", "vibration", "rpm"], "time_range": "7d"}), "output_data": json.dumps({"rows": 10080, "anomalies_detected": 12})},
            {"tool_name": "python_exec", "step_number": 3, "status": "success", "duration_ms": 8900, "sandbox_used": True, "input_data": json.dumps({"script": "fft_analysis.py", "params": {"sampling_rate": 1000}}), "output_data": json.dumps({"dominant_frequency": 2300, "amplitude_ratio": 1.12})},
            {"tool_name": "knowledge_search", "step_number": 4, "status": "success", "duration_ms": 980, "input_data": json.dumps({"query": "inner race defect 2.3kHz", "kb_ids": []}), "output_data": json.dumps({"results": 2, "top_score": 0.94})},
            {"tool_name": "report_generator", "step_number": 5, "status": "success", "duration_ms": 2100, "input_data": json.dumps({"format": "markdown", "sections": ["summary", "findings", "recommendation"]}), "output_data": json.dumps({"report_id": "rpt_8f3k2"})},
        ],
        "created_hours_ago": 2,
    },
    {
        "goal": "Generate weekly production summary report for all manufacturing lines",
        "status": "completed",
        "model_name": "qwen3:14b",
        "step_count": 4,
        "iteration_count": 4,
        "result": "Weekly report generated. Total output: 12,450 units (98.2% target). Line 1: 102% efficiency. Line 2: 97% efficiency. Line 3: 94% efficiency (downtime due to bearing issue). Overall OEE: 87.3%.",
        "plan_json": json.dumps([
            {"step": 1, "tool": "data_query", "description": "Fetch production metrics for all lines"},
            {"step": 2, "tool": "data_query", "description": "Fetch downtime and OEE data"},
            {"step": 3, "tool": "python_exec", "description": "Calculate summary statistics"},
            {"step": 4, "tool": "report_generator", "description": "Generate formatted report"},
        ]),
        "tool_calls": [
            {"tool_name": "data_query", "step_number": 1, "status": "success", "duration_ms": 4200, "input_data": json.dumps({"source": "production_lines", "metrics": ["output", "efficiency", "target"], "time_range": "7d"}), "output_data": json.dumps({"lines": 3, "total_output": 12450})},
            {"tool_name": "data_query", "step_number": 2, "status": "success", "duration_ms": 3800, "input_data": json.dumps({"source": "oee_data", "metrics": ["availability", "performance", "quality"], "time_range": "7d"}), "output_data": json.dumps({"avg_oee": 87.3})},
            {"tool_name": "python_exec", "step_number": 3, "status": "success", "duration_ms": 1500, "sandbox_used": False, "input_data": json.dumps({"script": "summary_stats.py"}), "output_data": json.dumps({"mean": 97.7, "std": 4.1})},
            {"tool_name": "report_generator", "step_number": 4, "status": "success", "duration_ms": 2800, "input_data": json.dumps({"format": "pdf", "template": "weekly_production"}), "output_data": json.dumps({"report_id": "rpt_9g4m1"})},
        ],
        "created_hours_ago": 5,
    },
    {
        "goal": "Investigate root cause of increased defect rate on CNC machining center MC-07",
        "status": "running",
        "model_name": "qwen3:14b",
        "step_count": 3,
        "iteration_count": 3,
        "result": None,
        "plan_json": json.dumps([
            {"step": 1, "tool": "knowledge_search", "description": "Search for MC-07 maintenance history"},
            {"step": 2, "tool": "data_query", "description": "Query defect rate data for MC-07"},
            {"step": 3, "tool": "python_exec", "description": "Run correlation analysis"},
            {"step": 4, "tool": "knowledge_search", "description": "Search for similar defect patterns"},
            {"step": 5, "tool": "report_generator", "description": "Generate investigation report"},
        ]),
        "tool_calls": [
            {"tool_name": "knowledge_search", "step_number": 1, "status": "success", "duration_ms": 1100, "input_data": json.dumps({"query": "MC-07 maintenance spindle replacement", "kb_ids": []}), "output_data": json.dumps({"results": 4, "top_score": 0.82})},
            {"tool_name": "data_query", "step_number": 2, "status": "success", "duration_ms": 2900, "input_data": json.dumps({"source": "defect_logs", "filter": {"machine": "MC-07"}, "time_range": "30d"}), "output_data": json.dumps({"defect_rate": 4.2, "baseline": 1.8})},
            {"tool_name": "python_exec", "step_number": 3, "status": "success", "duration_ms": 6700, "sandbox_used": True, "input_data": json.dumps({"script": "correlation_analysis.py", "params": {"variables": ["spindle_hours", "tool_wear", "ambient_temp"]}}), "output_data": json.dumps({"top_correlation": {"variable": "spindle_hours", "r_value": 0.87}})},
        ],
        "created_hours_ago": 1,
    },
    {
        "goal": "Draft incident report for the hydraulic press safety sensor malfunction on August 28",
        "status": "awaiting_approval",
        "model_name": "qwen3:14b",
        "step_count": 3,
        "iteration_count": 3,
        "result": None,
        "plan_json": json.dumps([
            {"step": 1, "tool": "knowledge_search", "description": "Search for hydraulic press safety protocols"},
            {"step": 2, "tool": "python_exec", "description": "Draft incident report from structured data"},
            {"step": 3, "tool": "file_write", "description": "Save draft report for review"},
            {"step": 4, "tool": "notification_send", "description": "Notify safety officer of pending report"},
        ]),
        "tool_calls": [
            {"tool_name": "knowledge_search", "step_number": 1, "status": "success", "duration_ms": 890, "input_data": json.dumps({"query": "hydraulic press safety sensor malfunction procedure", "kb_ids": []}), "output_data": json.dumps({"results": 5, "top_score": 0.91})},
            {"tool_name": "python_exec", "step_number": 2, "status": "success", "duration_ms": 4500, "sandbox_used": False, "input_data": json.dumps({"script": "draft_incident.py", "params": {"incident_date": "2025-08-28", "equipment": "hydraulic_press_02"}}), "output_data": json.dumps({"draft_id": "draft_k8m2", "sections": 6})},
            {"tool_name": "file_write", "step_number": 3, "status": "success", "duration_ms": 340, "input_data": json.dumps({"path": "/drafts/incident_2025_08_28.md", "content": "draft_k8m2"}), "output_data": json.dumps({"bytes_written": 4560})},
        ],
        "created_hours_ago": 0.5,
    },
    {
        "goal": "Optimize inventory reorder points based on lead time variability and demand forecasting",
        "status": "failed",
        "model_name": "qwen3:14b",
        "step_count": 2,
        "iteration_count": 3,
        "error_message": "Data source 'inventory_forecast' is not available. Required provider 'demand_planner' is not configured.",
        "result": None,
        "plan_json": json.dumps([
            {"step": 1, "tool": "data_query", "description": "Fetch current inventory levels"},
            {"step": 2, "tool": "data_query", "description": "Fetch demand forecast data"},
            {"step": 3, "tool": "python_exec", "description": "Calculate optimal reorder points"},
        ]),
        "tool_calls": [
            {"tool_name": "data_query", "step_number": 1, "status": "success", "duration_ms": 2100, "input_data": json.dumps({"source": "inventory_db", "metrics": ["stock_level", "reorder_point", "lead_time"]}), "output_data": json.dumps({"skus": 234})},
            {"tool_name": "data_query", "step_number": 2, "status": "failed", "duration_ms": 500, "input_data": json.dumps({"source": "inventory_forecast", "metrics": ["forecast", "confidence_interval"]}), "output_data": None, "exit_code": 1},
            {"tool_name": "data_query", "step_number": 3, "status": "failed", "duration_ms": 500, "input_data": json.dumps({"source": "inventory_forecast"}), "output_data": None, "exit_code": 1},
        ],
        "created_hours_ago": 8,
    },
    {
        "goal": "Summarize all open safety incidents and their resolution status for the monthly safety review meeting",
        "status": "completed",
        "model_name": "qwen3:14b",
        "step_count": 3,
        "iteration_count": 3,
        "result": "Summary complete. 7 open incidents: 2 critical (hydraulic press sensor, confined space ventilation), 3 medium (slippery floor zone B, expired fire extinguisher, guard rail damage), 2 low (broken light fixture, missing warning sign). Average resolution time for closed incidents this month: 3.2 days.",
        "plan_json": json.dumps([
            {"step": 1, "tool": "knowledge_search", "description": "Search incident database"},
            {"step": 2, "tool": "python_exec", "description": "Aggregate and categorize incidents"},
            {"step": 3, "tool": "report_generator", "description": "Generate summary report"},
        ]),
        "tool_calls": [
            {"tool_name": "knowledge_search", "step_number": 1, "status": "success", "duration_ms": 1800, "input_data": json.dumps({"query": "open safety incidents status", "kb_ids": []}), "output_data": json.dumps({"total_incidents": 12, "open": 7, "closed": 5})},
            {"tool_name": "python_exec", "step_number": 2, "status": "success", "duration_ms": 2200, "sandbox_used": False, "input_data": json.dumps({"script": "aggregate_incidents.py"}), "output_data": json.dumps({"by_severity": {"critical": 2, "medium": 3, "low": 2}})},
            {"tool_name": "report_generator", "step_number": 3, "status": "success", "duration_ms": 1600, "input_data": json.dumps({"format": "markdown", "template": "safety_summary"}), "output_data": json.dumps({"report_id": "rpt_2h7n"})},
        ],
        "created_hours_ago": 24,
    },
]

SAMPLE_APPROVAL_REQUESTS = [
    {
        "operation": "Execute Python script in sandbox: correlation_analysis.py",
        "operation_detail_json": json.dumps({
            "tool_name": "python_exec",
            "input": {"script": "correlation_analysis.py", "params": {"variables": ["spindle_hours", "tool_wear", "ambient_temp"]}},
        }),
        "risk_level": "medium",
        "status": "pending",
        "expires_hours": 4,
    },
    {
        "operation": "Write file to shared directory: /drafts/incident_2025_08_28.md",
        "operation_detail_json": json.dumps({
            "tool_name": "file_write",
            "input": {"path": "/drafts/incident_2025_08_28.md", "content_preview": "INCIDENT REPORT: Hydraulic Press Safety Sensor Malfunction..."},
        }),
        "risk_level": "high",
        "status": "pending",
        "expires_hours": 3,
    },
    {
        "operation": "Send notification to safety officer group",
        "operation_detail_json": json.dumps({
            "tool_name": "notification_send",
            "input": {"recipient": "safety_officers", "message": "New incident report draft pending review"},
        }),
        "risk_level": "low",
        "status": "approved",
        "decided_hours_ago": 1,
        "decision_note": "Approved. Safety team should be notified promptly.",
        "expires_hours": 24,
    },
    {
        "operation": "Execute Python script in sandbox: external_api_call.py",
        "operation_detail_json": json.dumps({
            "tool_name": "python_exec",
            "input": {"script": "external_api_call.py", "params": {"endpoint": "https://api.vendor.com/inventory"}},
        }),
        "risk_level": "critical",
        "status": "rejected",
        "decided_hours_ago": 2,
        "decision_note": "Rejected: External API calls must be pre-approved by IT security. Use internal data sources only.",
        "expires_hours": 24,
    },
    {
        "operation": "Delete knowledge base document: legacy_safety_data.pdf",
        "operation_detail_json": json.dumps({
            "tool_name": "kb_delete_document",
            "input": {"kb_name": "Industrial Safety Manual", "document": "legacy_safety_data.pdf"},
        }),
        "risk_level": "high",
        "status": "pending",
        "expires_hours": 2,
    },
    {
        "operation": "Execute Python script in sandbox: data_export.py with PII fields",
        "operation_detail_json": json.dumps({
            "tool_name": "python_exec",
            "input": {"script": "data_export.py", "params": {"fields": ["employee_id", "name", "email", "salary"]}},
        }),
        "risk_level": "critical",
        "status": "pending",
        "expires_hours": 1,
    },
]


async def seed():
    async with AsyncSessionLocal() as session:
        # Get the first admin user
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.role == "admin").limit(1))
        admin_user = result.scalar_one_or_none()

        if not admin_user:
            print("No admin user found. Please run the app first to create an admin account.")
            return

        user_id = admin_user.id
        print(f"Using admin user: {admin_user.email} (id={user_id})")

        # ── Knowledge Bases ──────────────────────────────────────
        print("\n--- Seeding Knowledge Bases ---")
        kb_ids = []
        for kb_data in SAMPLE_KNOWLEDGE_BASES:
            kb_id = str(uuid.uuid4())
            collection_name = f"kb_{kb_id[:8]}"
            kb = KnowledgeBase(
                id=kb_id,
                owner_id=user_id,
                name=kb_data["name"],
                description=kb_data["description"],
                embedding_model=kb_data["embedding_model"],
                qdrant_collection=collection_name,
                doc_count=0,
                chunk_count=0,
            )
            session.add(kb)
            kb_ids.append(kb_id)

            total_chunks = 0
            for doc_data in kb_data["documents"]:
                doc_id = str(uuid.uuid4())
                doc = Document(
                    id=doc_id,
                    kb_id=kb_id,
                    uploader_id=user_id,
                    filename=f"{doc_id}_{doc_data['original_name']}",
                    original_name=doc_data["original_name"],
                    mime_type=doc_data["mime_type"],
                    size_bytes=doc_data["size_bytes"],
                    storage_path=f"/app/data/uploads/{doc_id}_{doc_data['original_name']}",
                    status=doc_data["status"],
                    page_count=doc_data.get("page_count"),
                    chunk_count=doc_data.get("chunk_count", 0),
                    error_message=doc_data.get("error_message"),
                )
                session.add(doc)
                total_chunks += doc_data.get("chunk_count", 0)

            kb.doc_count = len(kb_data["documents"])
            kb.chunk_count = total_chunks
            print(f"  + KB: {kb_data['name']} ({kb.doc_count} docs, {total_chunks} chunks)")

        await session.commit()
        print(f"  Total: {len(SAMPLE_KNOWLEDGE_BASES)} knowledge bases created")

        # ── Agent Runs ───────────────────────────────────────────
        print("\n--- Seeding Agent Runs ---")
        agent_run_ids = []
        for run_data in SAMPLE_AGENT_RUNS:
            run_id = str(uuid.uuid4())
            created_at = utcnow() - timedelta(hours=run_data.get("created_hours_ago", 1))

            agent_run = AgentRun(
                id=run_id,
                user_id=user_id,
                goal=run_data["goal"],
                status=run_data["status"],
                model_name=run_data["model_name"],
                step_count=run_data["step_count"],
                iteration_count=run_data["iteration_count"],
                result=run_data.get("result"),
                error_message=run_data.get("error_message"),
                plan_json=run_data.get("plan_json"),
                max_iterations=10,
            )
            agent_run.created_at = created_at
            session.add(agent_run)
            agent_run_ids.append(run_id)

            for tc_data in run_data.get("tool_calls", []):
                tc_id = str(uuid.uuid4())
                tc = ToolCall(
                    id=tc_id,
                    agent_run_id=run_id,
                    step_number=tc_data["step_number"],
                    tool_name=tc_data["tool_name"],
                    input_json=tc_data["input_data"],
                    output_json=tc_data.get("output_data"),
                    status=tc_data["status"],
                    exit_code=tc_data.get("exit_code"),
                    duration_ms=tc_data.get("duration_ms"),
                    sandbox_used=tc_data.get("sandbox_used", False),
                )
                tc.created_at = created_at + timedelta(seconds=tc_data.get("duration_ms", 0) / 1000)
                session.add(tc)

            status_icon = {"completed": "✓", "running": "↻", "awaiting_approval": "⏳", "failed": "✗"}.get(run_data["status"], "?")
            print(f"  {status_icon} Agent Run: {run_data['goal'][:60]}... [{run_data['status']}]")

        await session.commit()
        print(f"  Total: {len(SAMPLE_AGENT_RUNS)} agent runs created")

        # ── Approval Requests ────────────────────────────────────
        print("\n--- Seeding Approval Requests ---")
        # Pair approval requests with agent runs where possible
        paired_runs = [agent_run_ids[2], agent_run_ids[3], agent_run_ids[0], agent_run_ids[4], agent_run_ids[0], agent_run_ids[4]]

        for i, approval_data in enumerate(SAMPLE_APPROVAL_REQUESTS):
            approval_id = str(uuid.uuid4())
            created_at = utcnow() - timedelta(hours=random.randint(1, 6))

            decided_by = None
            decided_at = None
            decision_note = approval_data.get("decision_note")

            if approval_data["status"] in ("approved", "rejected"):
                decided_by = user_id
                decided_at = utcnow() - timedelta(hours=approval_data.get("decided_hours_ago", 1))

            expires_at = created_at + timedelta(hours=approval_data.get("expires_hours", 24))

            approval = ApprovalRequest(
                id=approval_id,
                agent_run_id=paired_runs[i] if i < len(paired_runs) else None,
                tool_call_id=None,
                requester_id=user_id,
                operation=approval_data["operation"],
                operation_detail_json=approval_data["operation_detail_json"],
                risk_level=approval_data["risk_level"],
                status=approval_data["status"],
                decided_by=decided_by,
                decided_at=decided_at,
                decision_note=decision_note,
                expires_at=expires_at,
            )
            approval.created_at = created_at
            session.add(approval)

            status_icon = {"pending": "⏳", "approved": "✓", "rejected": "✗"}.get(approval_data["status"], "?")
            print(f"  {status_icon} Approval: {approval_data['operation'][:55]}... [{approval_data['risk_level']}]")

        await session.commit()
        print(f"  Total: {len(SAMPLE_APPROVAL_REQUESTS)} approval requests created")

        print("\n✓ Sample data seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed())
