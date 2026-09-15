"""Seed safe, human-readable SIH demo content and artifacts."""
from __future__ import annotations
import asyncio, hashlib, os, sys, uuid
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User
from models.knowledge_base import KnowledgeBase, Document
from models.artifact import Artifact

KBS = {
"Sovereign AI Workbench Product Guide": """# Sovereign AI Workbench v2.0\n\nAgentic AI workbench for RAG, tools, model routing, approvals, auditability and artifact generation.\n\n## Workflow\nUNDERSTAND -> ROUTE -> PLAN -> REASON -> EXECUTE -> OBSERVE -> VERIFY\n\n## Stack\nVercel frontend, Render FastAPI backend, Neon PostgreSQL, Qdrant Cloud and OpenAI-compatible model providers. Ollama is for local development.\n\n## Safety\nThe UI exposes safe execution summaries such as planning, tools, observations and verification, not private chain-of-thought.\n""",
"AI Agent Architecture": """# AI Agent Architecture\n\n1. UNDERSTAND - interpret the goal.\n2. ROUTE - select model/provider and capabilities.\n3. PLAN - create ordered actions.\n4. REASON - choose the next safe action.\n5. EXECUTE - call approved tools.\n6. OBSERVE - capture results.\n7. VERIFY - validate the result and deliverables.\n\nAgent runs have stable run IDs and persisted lifecycle events. High-risk actions can pause for human approval. Knowledge Base documents are extracted, chunked, embedded and indexed for RAG retrieval.\n""",
"SIH Project Problem Statement": """# SIH 2026 Project Summary\n\nSovereign AI Workbench combines conversational AI, RAG, multi-step agents, tools, human approval, persistent execution history and generated deliverables.\n\n## Innovation\nChat -> Knowledge -> Agent -> Tools -> Artifact, with run-level observability and verification.\n\n## Demo\nAsk a question, retrieve from a KB, use a tool, run a multi-step task and generate an artifact.\n""",
"Leave Application Policy": """# Leave Application Policy\n\nA leave request should include employee name, requested dates, a concise reason and a request for approval.\n\n## Health-related leave\nState that leave is requested for health reasons without unnecessarily disclosing sensitive medical details. Provide supporting documentation only through the approved HR process when required.\n\n## Professional format\nUse a clear subject, respectful greeting, requested dates, brief reason, expected return date when known and a polite approval request.\n""",
}
ARTIFACTS = {
"SIH_Project_Summary.md": "# Sovereign AI Workbench v2.0\n\nCloud-deployed agentic AI combining Chat, Knowledge, Agents, Tools and Artifacts.\n\nStack: Vercel + Render + Neon + Qdrant Cloud.\n",
"AI_Architecture.md": KBS["AI Agent Architecture"],
"Knowledge_Base_Summary.md": "# Knowledge Base Demo\n\nFour curated KBs demonstrate product documentation, agent architecture, SIH context and leave-policy RAG.\n",
"Agent_Test_Report.json": '{"project":"Sovereign AI Workbench v2.0","checks":["Knowledge retrieval","Tool calling","Agent timeline","Artifact listing","Human approval"]}\n',
"Model_Comparison.csv": "model,provider,use_case\nopenrouter/free,OpenRouter,general agent demo\nlocal-ollama,Ollama,local development\n",
}

async def seed():
    from config import get_settings
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        admin = (await db.execute(select(User).where(User.role == "admin").limit(1))).scalar_one_or_none()
        if not admin:
            print("No admin user found"); return
        for name, content in KBS.items():
            kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.owner_id == admin.id, KnowledgeBase.name == name))).scalar_one_or_none()
            if not kb:
                kb = KnowledgeBase(id=str(uuid.uuid4()), owner_id=admin.id, name=name, description=f"SIH demo knowledge base: {name}", embedding_model="nomic-embed-text", qdrant_collection=f"kb_{uuid.uuid4().hex[:8]}", doc_count=0, chunk_count=0)
                db.add(kb); await db.flush()
            exists = (await db.execute(select(Document).where(Document.kb_id == kb.id, Document.original_name == name.replace(" ", "_").lower()+".md"))).scalar_one_or_none()
            if not exists:
                filename = name.replace(" ", "_").lower()+".md"
                path = Path(settings.data_dir)/"uploads"/f"{uuid.uuid4()}_{filename}"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
                chunks = max(1, len(content)//900)
                db.add(Document(id=str(uuid.uuid4()), kb_id=kb.id, uploader_id=admin.id, filename=path.name, original_name=filename, mime_type="text/markdown", size_bytes=len(content.encode()), storage_path=str(path), status="indexed", chunk_count=chunks))
                kb.doc_count = (kb.doc_count or 0)+1; kb.chunk_count = (kb.chunk_count or 0)+chunks
        root = Path(settings.data_dir)/"artifacts"/admin.id; root.mkdir(parents=True, exist_ok=True)
        for filename, content in ARTIFACTS.items():
            exists = (await db.execute(select(Artifact).where(Artifact.user_id == admin.id, Artifact.filename == filename))).scalar_one_or_none()
            if exists: continue
            raw = content.encode(); ext=Path(filename).suffix or ".bin"; key=f"{uuid.uuid4()}{ext}"; (root/key).write_bytes(raw)
            mime="text/csv" if ext==".csv" else "application/json" if ext==".json" else "text/markdown"
            db.add(Artifact(id=str(uuid.uuid4()), user_id=admin.id, filename=filename, relative_path=os.path.join(admin.id,key), mime_type=mime, size_bytes=len(raw), storage_key=key, checksum=hashlib.sha256(raw).hexdigest()))
        await db.commit(); print("SIH demo data seeded")

if __name__ == "__main__": asyncio.run(seed())
