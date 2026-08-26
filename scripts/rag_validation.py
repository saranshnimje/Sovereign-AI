#!/usr/bin/env python3
"""
Full end-to-end RAG validation script.
Tests: upload → extract → chunk → embed (nomic-embed-text) → Qdrant → retrieve → qwen3:14b answer

Run: python scripts/rag_validation.py
Requires: requests, docker stack running, both models pulled
"""
import sys
import time
import json

try:
    import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

BASE = "http://localhost/api/v1"
RESULTS = []
TIMINGS = {}

def log(msg):
    print(msg)

def check(label, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((status, label, detail))
    icon = "OK" if passed else "XX"
    print(f"  {icon}  {status:4}  {label}  {('[' + detail + ']') if detail else ''}")
    return passed

def post(path, body=None, headers=None, files=None, data=None, timeout=60):
    try:
        r = requests.post(f"{BASE}{path}", json=body, headers=headers or {},
                         files=files, data=data, timeout=timeout)
        return r
    except Exception as e:
        class Fake:
            status_code = 0
            text = str(e)
            def json(self): return {}
        return Fake()

def get(path, headers=None, timeout=30):
    try:
        r = requests.get(f"{BASE}{path}", headers=headers or {}, timeout=timeout)
        return r
    except Exception as e:
        class Fake:
            status_code = 0
            text = str(e)
            def json(self): return {}
        return Fake()

def put(path, body, headers=None, timeout=30):
    try:
        r = requests.put(f"{BASE}{path}", json=body, headers=headers or {}, timeout=timeout)
        return r
    except Exception as e:
        class Fake:
            status_code = 0
            text = str(e)
            def json(self): return {}
        return Fake()

print("\n" + "="*62)
print("  Sovereign AI Workbench — Full RAG Validation")
print("  Chat model: qwen3:14b  |  Embedding: nomic-embed-text")
print("="*62)

# ── 0. Ollama connectivity ─────────────────────────────────────
print("\n[0] Ollama & Model Verification")
try:
    r = requests.get("http://localhost:11434/api/tags", timeout=5)
    if r.status_code == 200:
        models = [m["name"] for m in r.json().get("models", [])]
        check("Ollama reachable", True, f"{len(models)} models")
        has_qwen = any("qwen3" in m for m in models)
        has_nomic = any("nomic-embed" in m for m in models)
        check("qwen3:14b installed", has_qwen, str([m for m in models if "qwen" in m]))
        check("nomic-embed-text installed", has_nomic,
              str([m for m in models if "nomic" in m]))
        if not has_nomic:
            print("\n  CRITICAL: nomic-embed-text not installed.")
            print("  Run: ollama pull nomic-embed-text")
            sys.exit(1)
    else:
        check("Ollama reachable", False, f"HTTP {r.status_code}")
except Exception as e:
    # Ollama runs on host, not accessible from validation script port 11434 directly
    # in some Docker setups — continue anyway, backend will access via host.docker.internal
    check("Ollama direct (host:11434)", False,
          f"Not directly reachable from host: {str(e)[:60]} — OK, backend uses host.docker.internal")

# ── 1. Auth ────────────────────────────────────────────────────
print("\n[1] Authentication")
# Try existing admin accounts in priority order
admin_credentials = [
    ("validate@sovereign.example.com", "Validator2026Pass"),
    ("admin@demo.local", "SovereignDemo2026!"),
]
r_login = None
for email, pwd in admin_credentials:
    r_try = post("/auth/login", {"email": email, "password": pwd})
    if r_try.status_code == 200:
        r_login = r_try
        break

# If no existing admin works, register as first user (gets admin)
if r_login is None or r_login.status_code != 200:
    post("/auth/register", {
        "email": "ragadmin@sovereign.example.com",
        "username": "ragadmin",
        "password": "RagAdmin2026Pass"
    })
    r_login = post("/auth/login", {
        "email": "ragadmin@sovereign.example.com",
        "password": "RagAdmin2026Pass"
    })

check("Login", r_login.status_code == 200, f"HTTP {r_login.status_code}")
token = r_login.json().get("access_token") if r_login.status_code == 200 else None
if not token:
    print("  CRITICAL: Cannot authenticate — cannot continue")
    sys.exit(1)

auth = {"Authorization": f"Bearer {token}"}
check("Auth token received", bool(token), f"len={len(token)}")

# ── 2. Set model roles ─────────────────────────────────────────
print("\n[2] Model Role Configuration")
r_chat = put("/models/roles", {"role": "chat", "model_name": "qwen3:14b"}, auth)
check("Set chat role = qwen3:14b", r_chat.status_code == 200,
      f"HTTP {r_chat.status_code}")

r_embed = put("/models/roles", {"role": "embedding", "model_name": "nomic-embed-text"}, auth)
check("Set embedding role = nomic-embed-text", r_embed.status_code == 200,
      f"HTTP {r_embed.status_code}")

r_roles = get("/models/roles", auth)
if r_roles.status_code == 200:
    roles = r_roles.json()
    check("Chat role confirmed = qwen3:14b",
          "qwen3" in str(roles.get("chat", "")),
          f"chat={roles.get('chat')}")
    check("Embedding role confirmed = nomic-embed-text",
          "nomic" in str(roles.get("embedding", "")),
          f"embedding={roles.get('embedding')}")

# ── 3. Create Knowledge Base ───────────────────────────────────
print("\n[3] Knowledge Base Setup")
r_kb = post("/knowledge-bases/", {
    "name": "RAG Test KB",
    "description": "Validation knowledge base for RAG testing",
    "embedding_model": "nomic-embed-text"
}, auth)
check("Create KB with nomic-embed-text", r_kb.status_code == 201,
      f"HTTP {r_kb.status_code}")
kb_id = r_kb.json().get("id") if r_kb.status_code == 201 else None
if not kb_id:
    print("  CRITICAL: Cannot create KB")
    sys.exit(1)
check("KB has embedding_model set",
      r_kb.json().get("embedding_model") == "nomic-embed-text",
      r_kb.json().get("embedding_model"))

# ── 4. Upload Document ─────────────────────────────────────────
print("\n[4] Document Upload")
doc_content = """Sovereign AI Workbench Technical Overview

Sovereign AI Workbench is a privacy-first, locally deployed AI platform designed for
organisations that cannot send sensitive data to external cloud providers.

Key Components:
- Ollama: Handles all local LLM inference using open-weight models such as Qwen3 and Llama.
  No API calls leave the organisation network during inference.
- Qdrant: A local vector database that stores document embeddings for retrieval-augmented generation.
  All vectors are stored on-premise.
- nomic-embed-text: A lightweight local embedding model that converts document text into
  768-dimensional vectors for semantic search without requiring cloud API calls.
- SQLite: Application metadata, user accounts, audit logs, and conversation history are
  stored in a local SQLite database using WAL mode for concurrent access.
- FastAPI: The Python backend exposes a RESTful API for all frontend operations.
- React/Vite: The frontend is a single-page application served by nginx.

Security Features:
- JWT authentication with bcrypt password hashing
- Role-based access control (Admin, Analyst, Viewer)
- Human approval gates for high-risk AI agent operations
- Tamper-evident SHA-256 hash-chained audit logs
- Docker sandbox for isolated Python code execution
- Tool registry with permission enforcement

RAG Pipeline:
The system supports retrieval-augmented generation: documents are uploaded, chunked into
512-token segments, embedded using nomic-embed-text, stored in Qdrant, and retrieved
at query time using cosine similarity. The retrieved context is then passed to the
local LLM (e.g. qwen3:14b) along with the user question to produce a grounded answer.

Deployment:
The complete stack runs as a Docker Compose application on a single machine.
No internet connectivity is required after initial model downloads.
"""

files = {"file": ("sovereign_overview.txt", doc_content.encode("utf-8"), "text/plain")}
data = {"kb_id": kb_id, "run_ocr": "false"}
t_upload = time.monotonic()
r_up = requests.post(f"{BASE}/documents/upload", files=files, data=data,
                     headers=auth, timeout=30)
upload_ms = int((time.monotonic() - t_upload) * 1000)
check("Document upload", r_up.status_code == 202,
      f"HTTP {r_up.status_code} ({upload_ms}ms)")
doc_id = r_up.json().get("id") if r_up.status_code == 202 else None
check("Document ID returned", bool(doc_id), str(doc_id)[:16] if doc_id else "missing")
check("Initial status = pending", r_up.json().get("status") == "pending",
      r_up.json().get("status"))

# ── 5. Document Processing Pipeline ───────────────────────────
print("\n[5] Document Processing (extract → clean → chunk → embed → index)")
print("  (Waiting up to 90s for full pipeline including embedding...)")
final_status = "pending"
final_doc = {}
steps_snapshot = []

for attempt in range(18):  # 18 × 5s = 90s max
    time.sleep(5)
    r_ds = get(f"/documents/{doc_id}", auth)
    if r_ds.status_code == 200:
        final_doc = r_ds.json()
        final_status = final_doc.get("status", "unknown")
        steps_snapshot = final_doc.get("processing_steps", [])
        if final_status in ("indexed", "failed"):
            break
    print(f"  ... status={final_status} (attempt {attempt+1}/18)")

TIMINGS["document_processing_s"] = (attempt + 1) * 5

# Verify each processing step
step_map = {s["step"]: s["status"] for s in steps_snapshot}
print(f"  Processing steps: {step_map}")

check("Text extraction step", step_map.get("extraction") == "done",
      f"extraction={step_map.get('extraction')}")
check("Cleaning step", step_map.get("cleaning") in ("done", "skipped"),
      f"cleaning={step_map.get('cleaning')}")
check("Chunking step", step_map.get("chunking") == "done",
      f"chunking={step_map.get('chunking')}")
check("Embedding step (nomic-embed-text)", step_map.get("embedding") == "done",
      f"embedding={step_map.get('embedding')}")
check("Qdrant indexing step", step_map.get("indexing") == "done",
      f"indexing={step_map.get('indexing')}")
check("Final status = indexed", final_status == "indexed",
      f"status={final_status} chunks={final_doc.get('chunk_count',0)}")

if final_status != "indexed":
    print(f"\n  ERROR: {final_doc.get('error_message','unknown error')}")
    if "embedding" not in str(final_doc.get("error_message", "")):
        print("  CRITICAL: Pipeline failed for unexpected reason")
else:
    chunk_count = final_doc.get("chunk_count", 0)
    check("Chunks stored in Qdrant", chunk_count > 0, f"chunks={chunk_count}")
    print(f"  Document indexed: {chunk_count} chunks stored in Qdrant")

# ── 6. RAG Query — Retrieval Only ─────────────────────────────
print("\n[6] Qdrant Retrieval (semantic search without LLM)")
t_ret = time.monotonic()
r_ret = post(f"/knowledge-bases/{kb_id}/query", {
    "query": "What embedding model does Sovereign AI Workbench use?",
    "top_k": 3,
    "generate_answer": False,
    "score_threshold": 0.1
}, auth, timeout=30)
retrieval_ms = int((time.monotonic() - t_ret) * 1000)
TIMINGS["retrieval_ms"] = retrieval_ms

check("Retrieval query", r_ret.status_code == 200, f"HTTP {r_ret.status_code}")
if r_ret.status_code == 200:
    ret_data = r_ret.json()
    sources = ret_data.get("sources", [])
    check("Sources returned", len(sources) > 0,
          f"count={len(sources)} in {retrieval_ms}ms")
    if sources:
        top = sources[0]
        check("Top source has filename", bool(top.get("filename")), top.get("filename",""))
        check("Top source has score", top.get("score", 0) > 0,
              f"score={top.get('score',0):.4f}")
        check("Top source has content", len(top.get("content","")) > 10,
              f"len={len(top.get('content',''))}")
        # Verify the retrieved content is actually relevant
        content_lower = top.get("content", "").lower()
        relevant = any(kw in content_lower for kw in
                      ["nomic", "embed", "vector", "768", "semantic"])
        check("Retrieved content is semantically relevant",
              relevant, top.get("content","")[:80])
    print(f"  Retrieval: {len(sources)} sources, top score={sources[0].get('score',0):.4f}, "
          f"{retrieval_ms}ms")

# ── 7. RAG Query — Full (with qwen3:14b generation) ───────────
print("\n[7] Full RAG: Retrieval + qwen3:14b Generation")
print("  (qwen3:14b generation may take 30-120s on CPU — please wait...)")
t_rag = time.monotonic()
r_rag = post(f"/knowledge-bases/{kb_id}/query", {
    "query": "What components does Sovereign AI Workbench use for local vector storage and embeddings?",
    "top_k": 3,
    "generate_answer": True,
    "score_threshold": 0.1,
    "model_name": "qwen3:14b"
}, auth, timeout=600)   # 10 min — qwen3:14b needs ~100s on CPU
rag_total_ms = int((time.monotonic() - t_rag) * 1000)
TIMINGS["rag_total_ms"] = rag_total_ms

check("RAG query with generation", r_rag.status_code == 200,
      f"HTTP {r_rag.status_code} ({rag_total_ms}ms)")
rag_answer = None
if r_rag.status_code == 200:
    rag = r_rag.json()
    rag_answer = rag.get("answer")
    rag_sources = rag.get("sources", [])
    gen_ms = rag.get("generation_ms")
    TIMINGS["generation_ms"] = gen_ms

    check("Answer generated", bool(rag_answer),
          f"len={len(rag_answer) if rag_answer else 0}")
    check("Sources included", len(rag_sources) > 0, f"count={len(rag_sources)}")

    if rag_answer:
        # Verify answer is grounded — should mention Qdrant or nomic or vectors
        ans_lower = rag_answer.lower()
        grounded = any(kw in ans_lower for kw in
                      ["qdrant", "nomic", "vector", "embed", "local", "768", "sqlite"])
        check("Answer mentions local components (grounded)",
              grounded, rag_answer[:120])
        check("Answer does not hallucinate cloud services",
              "openai" not in ans_lower and "azure" not in ans_lower,
              "no cloud refs")

    print(f"\n  === ANSWER FROM qwen3:14b ===")
    print(f"  {(rag_answer or 'No answer generated')[:400]}")
    print(f"  ===========================")
    print(f"  embed={rag.get('query_embedding_ms')}ms | "
          f"retrieve={rag.get('retrieval_ms')}ms | "
          f"generate={gen_ms}ms | total={rag_total_ms}ms")

# ── 8. Chat with qwen3:14b ─────────────────────────────────────
print("\n[8] Direct Chat with qwen3:14b")
r_conv = post("/chat/conversations", {"model_name": "qwen3:14b"}, auth)
check("Create conversation", r_conv.status_code == 201, f"HTTP {r_conv.status_code}")
conv_id = r_conv.json().get("id") if r_conv.status_code == 201 else None

if conv_id:
    t_chat = time.monotonic()
    try:
        chat_resp = requests.post(
            f"{BASE}/chat/conversations/{conv_id}/messages",
            json={"content": "In one sentence, what is 2 plus 2?",
                  "model_name": "qwen3:14b"},
            headers=auth,
            stream=True,
            timeout=600   # 10 min — qwen3:14b needs ~100s first token on CPU
        )
        check("Chat SSE stream", chat_resp.status_code == 200,
              f"HTTP {chat_resp.status_code}")
        tokens_received = 0
        full_response = ""
        for line in chat_resp.iter_lines(decode_unicode=True):
            if line.startswith("data:"):
                try:
                    d = json.loads(line[5:])
                    if "delta" in d:
                        full_response += d["delta"]
                        tokens_received += 1
                    elif d.get("finish_reason"):
                        break
                except Exception:
                    pass
        chat_ms = int((time.monotonic() - t_chat) * 1000)
        TIMINGS["chat_first_response_ms"] = chat_ms
        check("Chat response received", tokens_received > 0,
              f"tokens={tokens_received} in {chat_ms}ms")
        check("Chat answer contains number",
              "4" in full_response or "four" in full_response.lower(),
              full_response[:60])
        print(f"  Chat response: '{full_response[:100]}' ({chat_ms}ms)")
    except Exception as e:
        check("Chat streaming", False, str(e)[:80])

# ── 9. Error Handling Verification ────────────────────────────
print("\n[9] Graceful Error Handling")

# Bad model in KB query
r_bad_model = post(f"/knowledge-bases/{kb_id}/query", {
    "query": "test",
    "generate_answer": True,
    "model_name": "nonexistent-model-xyz"
}, auth, timeout=30)
check("Bad model returns graceful error (not 500)",
      r_bad_model.status_code in (200, 503, 422),
      f"HTTP {r_bad_model.status_code}")

# Invalid document type
if kb_id:
    bad_files = {"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")}
    bad_data = {"kb_id": kb_id, "run_ocr": "false"}
    r_bad_up = requests.post(f"{BASE}/documents/upload", files=bad_files,
                             data=bad_data, headers=auth, timeout=10)
    check("Invalid file type rejected", r_bad_up.status_code == 422,
          f"HTTP {r_bad_up.status_code}")

# Empty file rejected
empty_files = {"file": ("empty.txt", b"", "text/plain")}
empty_data = {"kb_id": kb_id, "run_ocr": "false"}
r_empty = requests.post(f"{BASE}/documents/upload", files=empty_files,
                        data=empty_data, headers=auth, timeout=10)
check("Empty file rejected", r_empty.status_code == 422, f"HTTP {r_empty.status_code}")

# ── 10. Summary ────────────────────────────────────────────────
print("\n" + "="*62)
passed = sum(1 for s,_,_ in RESULTS if s == "PASS")
failed = sum(1 for s,_,_ in RESULTS if s == "FAIL")
print(f"  RAG VALIDATION: {passed} PASS  |  {failed} FAIL  |  {len(RESULTS)} TOTAL")
print("="*62)

print("\n  Performance timings (observed, not benchmarked):")
for k, v in TIMINGS.items():
    if v is not None:
        unit = "ms" if "ms" in k else "s"
        print(f"    {k}: {v}{unit}")

if failed > 0:
    print("\n  FAILED:")
    for s, l, d in RESULTS:
        if s == "FAIL":
            print(f"    XX {l}  [{d}]")
    sys.exit(1)
else:
    print("\n  All RAG checks passed.")
    sys.exit(0)
