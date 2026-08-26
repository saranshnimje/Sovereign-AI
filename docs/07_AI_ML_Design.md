# 07 AI/ML Design
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0, 03_System_Architecture.md v1.0

---

## 1. Purpose

This document specifies the design of all AI/ML components in Sovereign AI Workbench, including:
- LLM integration and abstraction layer
- Embedding pipeline
- RAG (Retrieval-Augmented Generation) system
- Document processing and OCR pipeline
- Agent architecture and prompting strategy
- Model configuration and management
- Hardware-aware operation

All AI/ML processing is local and on-premise. No model inference is sent to any external cloud service.

---

## 2. LLM Abstraction Layer

### 2.1 Design Goal

All LLM calls go through a single `LLMClient` class. This ensures:
- The underlying inference engine can be replaced (Ollama → llama.cpp server → vLLM) without modifying service code.
- Consistent error handling and retry logic in one place.
- Model availability checking centralized.
- Telemetry and audit hooks applied uniformly.

### 2.2 LLMClient Interface

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from dataclasses import dataclass

@dataclass
class ChatMessage:
    role: str        # system | user | assistant | tool
    content: str

@dataclass
class ChatResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str    # stop | length | tool_calls

@dataclass
class EmbeddingResponse:
    embeddings: list[list[float]]
    model: str
    tokens: int

class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> ChatResponse | AsyncGenerator[str, None]: ...

    @abstractmethod
    async def embed(
        self,
        model: str,
        texts: list[str],
    ) -> EmbeddingResponse: ...

    @abstractmethod
    async def list_models(self) -> list[dict]: ...

    @abstractmethod
    async def health_check(self, model: str | None = None) -> bool: ...
```

### 2.3 OllamaClient Implementation

```python
import httpx
from config import get_settings

class OllamaClient(LLMClient):
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        )

    async def chat(self, model, messages, stream=False, temperature=0.7,
                   max_tokens=2048, system_prompt=None):
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        if system_prompt:
            payload["system"] = system_prompt

        if stream:
            return self._stream_chat(payload)
        else:
            resp = await self._retry(
                lambda: self.client.post("/api/chat", json=payload)
            )
            data = resp.json()
            return ChatResponse(
                content=data["message"]["content"],
                model=model,
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                finish_reason=data.get("done_reason", "stop"),
            )

    async def _stream_chat(self, payload) -> AsyncGenerator[str, None]:
        async with self.client.stream("POST", "/api/chat", json=payload) as resp:
            async for line in resp.aiter_lines():
                if line:
                    data = json.loads(line)
                    if not data.get("done"):
                        yield data["message"]["content"]

    async def embed(self, model, texts):
        # Ollama /api/embed accepts a list of inputs
        resp = await self._retry(
            lambda: self.client.post("/api/embed", json={"model": model, "input": texts})
        )
        data = resp.json()
        return EmbeddingResponse(
            embeddings=data["embeddings"],
            model=model,
            tokens=data.get("prompt_eval_count", 0),
        )

    async def _retry(self, fn, attempts=3):
        last_exc = None
        for i, delay in enumerate([0, 1, 2]):
            try:
                if delay:
                    await asyncio.sleep(delay)
                resp = await fn()
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
        raise ModelUnavailableError(str(last_exc))
```

---

## 3. Model Management

### 3.1 Model Roles

The system tracks a role assignment for each model. Roles are stored in a `model_roles` configuration (SQLite or env var). Multiple models can exist but only one is "active" per role.

| Role | Purpose | Recommended model |
|------|---------|------------------|
| `chat` | General conversation | `llama3.2:3b` (small) or `mistral:7b-q4` (medium) |
| `embedding` | Vector generation for RAG | `nomic-embed-text` |
| `vision` | Image understanding, VQA | `llava:7b-q4` (optional) |
| `reasoning` | Structured planning (agent) | Same as chat, or `qwen2.5:7b-q4` |

A model can be assigned multiple roles if capable.

### 3.2 Model Availability Check

Before every LLM call, the system checks model availability:

```python
async def ensure_model_available(model_name: str, llm_client: LLMClient):
    try:
        available = await llm_client.health_check(model_name)
        if not available:
            raise ModelUnavailableError(model_name)
    except Exception:
        raise ModelUnavailableError(model_name)
```

Health check: send a minimal prompt (`"ping"`) with `max_tokens=1` and measure response. If it returns within 5 seconds, the model is available.

### 3.3 Hardware-Aware Model Selection

```python
class ModelSelector:
    def select_chat_model(self, available_ram_gb: float) -> str:
        """Select the best available model given RAM constraints."""
        if available_ram_gb >= 8:
            return self._prefer(["mistral:7b-q4", "llama3.1:8b-q4", "llama3.2:3b"])
        elif available_ram_gb >= 4:
            return self._prefer(["llama3.2:3b", "phi3:mini", "tinyllama:1.1b"])
        else:
            return self._prefer(["tinyllama:1.1b", "phi3:mini"])

    def _prefer(self, models: list[str]) -> str:
        """Return first model that is installed in Ollama."""
        installed = {m["name"] for m in self.installed_models}
        for model in models:
            if model in installed:
                return model
        raise ModelUnavailableError("No suitable model installed")
```

---

## 4. Embedding Pipeline

### 4.1 Design

Embeddings are generated via the Ollama `/api/embed` endpoint using a local embedding model. The default model is `nomic-embed-text` (768-dimensional vectors).

### 4.2 EmbeddingService

```python
class EmbeddingService:
    def __init__(self, llm_client: LLMClient, settings: Settings):
        self.llm = llm_client
        self.batch_size = settings.embedding_batch_size  # default 32

    async def embed_text(self, text: str, model: str) -> list[float]:
        result = await self.llm.embed(model=model, texts=[text])
        return result.embeddings[0]

    async def embed_batch(self, texts: list[str], model: str) -> list[list[float]]:
        """Embed texts in batches to avoid OOM."""
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            result = await self.llm.embed(model=model, texts=batch)
            all_embeddings.extend(result.embeddings)
        return all_embeddings

    async def embed_query(self, query: str, model: str) -> list[float]:
        """Embed a single query (same as embed_text; explicit for clarity)."""
        return await self.embed_text(query, model)
```

### 4.3 Vector Dimension Management

Each knowledge base stores its embedding model at creation time. The Qdrant collection is created with the correct vector size for that model.

```python
MODEL_VECTOR_DIMENSIONS = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "bge-large": 1024,
}

def get_vector_size(model_name: str) -> int:
    # Check known sizes first
    for key, size in MODEL_VECTOR_DIMENSIONS.items():
        if key in model_name.lower():
            return size
    # Default: probe by embedding a test string
    return 768  # safe default for nomic-embed-text
```

---

## 5. Document Processing Pipeline

### 5.1 Text Extraction by MIME Type

```python
class TextExtractor:
    async def extract(self, path: str, mime_type: str) -> tuple[str, int]:
        """Returns (text, page_count)."""
        if mime_type == "application/pdf":
            return await self._extract_pdf(path)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return await self._extract_docx(path)
        elif mime_type in ("text/plain", "text/markdown"):
            return await self._extract_text(path)
        elif mime_type == "text/csv":
            return await self._extract_csv(path)
        elif mime_type in ("image/png", "image/jpeg", "image/webp"):
            return "", 1  # images go to OCR directly
        else:
            raise DocumentProcessingError(f"Unsupported MIME type: {mime_type}")

    async def _extract_pdf(self, path: str) -> tuple[str, int]:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        pages = []
        for page_num, page in enumerate(doc):
            pages.append(f"[Page {page_num + 1}]\n{page.get_text()}")
        doc.close()
        return "\n\n".join(pages), len(doc)

    async def _extract_docx(self, path: str) -> tuple[str, int]:
        from docx import Document
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs), 1

    async def _extract_csv(self, path: str) -> tuple[str, int]:
        import pandas as pd
        df = pd.read_csv(path)
        # Convert to text representation
        return df.to_string(index=False), 1
```

### 5.2 OCR Service (PaddleOCR)

```python
class OCRService:
    _instance = None  # singleton; PaddleOCR takes ~30s to initialize

    def get_ocr(self):
        if self._instance is None:
            from paddleocr import PaddleOCR
            self._instance = PaddleOCR(
                use_gpu=False,
                use_angle_cls=True,
                lang="en",
                show_log=False,
            )
        return self._instance

    async def process(self, path: str, mime_type: str) -> str:
        """Run OCR and return text string."""
        import asyncio
        # OCR is blocking; run in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run_ocr, path, mime_type)

    def _run_ocr(self, path: str, mime_type: str) -> str:
        if mime_type == "application/pdf":
            return self._ocr_pdf(path)
        else:
            return self._ocr_image(path)

    def _ocr_image(self, path: str) -> str:
        ocr = self.get_ocr()
        result = ocr.ocr(path, cls=True)
        lines = []
        if result and result[0]:
            for item in result[0]:
                text, confidence = item[1][0], item[1][1]
                if confidence >= 0.7:
                    lines.append(text)
                else:
                    lines.append(f"[LOW_CONF:{confidence:.2f}] {text}")
        return "\n".join(lines)

    def _ocr_pdf(self, path: str) -> str:
        import fitz
        doc = fitz.open(path)
        all_text = []
        for page_num, page in enumerate(doc):
            # Render page to image
            mat = fitz.Matrix(2, 2)  # 2x zoom for better OCR
            pix = page.get_pixmap(matrix=mat)
            img_path = f"/tmp/ocr_page_{page_num}.png"
            pix.save(img_path)
            page_text = self._ocr_image(img_path)
            all_text.append(f"[OCR:page_{page_num + 1}]\n{page_text}")
        doc.close()
        return "\n\n".join(all_text)
```

### 5.3 Text Chunking

```python
class TextChunker:
    @dataclass
    class Chunk:
        content: str
        chunk_index: int
        page_number: int | None
        token_count: int

    def chunk(
        self,
        text: str,
        chunk_size: int = 512,
        overlap: int = 50,
    ) -> list[Chunk]:
        """
        RecursiveCharacterTextSplitter logic:
        Split by paragraphs first, then sentences, then characters.
        Produces chunks of approximately chunk_size tokens with overlap.
        """
        separators = ["\n\n", "\n", ". ", " ", ""]
        chunks = self._recursive_split(text, separators, chunk_size, overlap)
        return [
            self.Chunk(
                content=c,
                chunk_index=i,
                page_number=self._extract_page_number(c),
                token_count=self._estimate_tokens(c),
            )
            for i, c in enumerate(chunks) if c.strip()
        ]

    def _estimate_tokens(self, text: str) -> int:
        # Approximation: 1 token ≈ 4 chars for English text
        return len(text) // 4

    def _extract_page_number(self, text: str) -> int | None:
        import re
        match = re.search(r'\[Page (\d+)\]', text)
        return int(match.group(1)) if match else None
```

---

## 6. RAG System Design

### 6.1 Architecture

```
Query
  │
  ▼ embed_query(query, embedding_model)
Query Vector
  │
  ▼ qdrant.search(collection, query_vector, top_k, score_threshold)
Retrieved Points (with payload)
  │
  ▼ construct_context(chunks, token_budget)
Context String (with citation markers)
  │
  ▼ llm.chat([system, context_message, user_query])
Generated Answer
  │
  ▼ format_response(answer, sources)
Final Response with Citations
```

### 6.2 RAGService Implementation

```python
class RAGService:
    def __init__(self, llm: LLMClient, qdrant: QdrantClient,
                 embedding: EmbeddingService, db: AsyncSession):
        self.llm = llm
        self.qdrant = qdrant
        self.embedding = embedding
        self.db = db

    async def query(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.6,
        generate_answer: bool = True,
        model_name: str | None = None,
    ) -> KBQueryResponse:
        kb = await self._get_kb(kb_id)

        # 1. Embed query
        t0 = time.monotonic()
        query_vector = await self.embedding.embed_query(query, kb.embedding_model)
        embed_ms = int((time.monotonic() - t0) * 1000)

        # 2. Vector search
        t1 = time.monotonic()
        results = await self.qdrant.search(
            collection_name=kb.qdrant_collection,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        retrieval_ms = int((time.monotonic() - t1) * 1000)

        sources = [
            KBQuerySource(
                chunk_id=str(r.id),
                doc_id=r.payload["doc_id"],
                filename=r.payload["filename"],
                page_number=r.payload.get("page_number"),
                content=r.payload["content"],
                score=r.score,
            )
            for r in results
        ]

        if not sources:
            return KBQueryResponse(
                answer=None,
                sources=[],
                query_embedding_ms=embed_ms,
                retrieval_ms=retrieval_ms,
                generation_ms=None,
                low_confidence=True,
            )

        # 3. Generate answer
        gen_ms = None
        answer = None
        if generate_answer:
            t2 = time.monotonic()
            answer = await self._generate_answer(query, sources, model_name)
            gen_ms = int((time.monotonic() - t2) * 1000)

        return KBQueryResponse(
            answer=answer,
            sources=sources,
            query_embedding_ms=embed_ms,
            retrieval_ms=retrieval_ms,
            generation_ms=gen_ms,
            low_confidence=max(s.score for s in sources) < 0.75 if sources else True,
        )

    async def _generate_answer(
        self, query: str, sources: list[KBQuerySource], model: str | None
    ) -> str:
        context_parts = []
        for i, src in enumerate(sources, 1):
            context_parts.append(
                f"[Source {i}: {src.filename}"
                f"{f', Page {src.page_number}' if src.page_number else ''}]\n"
                f"{src.content}"
            )
        context = "\n\n---\n\n".join(context_parts)

        system_prompt = (
            "You are a helpful assistant answering questions based strictly on the "
            "provided context. If the answer is not in the context, say so clearly. "
            "Always cite sources using [Source N] notation."
        )

        messages = [
            ChatMessage(role="user", content=f"Context:\n{context}\n\nQuestion: {query}")
        ]

        response = await self.llm.chat(
            model=model or await self._get_active_chat_model(),
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.1,  # low temperature for factual answers
            max_tokens=1024,
            stream=False,
        )
        return response.content
```

### 6.3 Context Window Management

```python
def build_context(
    sources: list[KBQuerySource],
    max_tokens: int,
    query_tokens: int,
    system_tokens: int = 200,
) -> list[KBQuerySource]:
    """Select sources that fit within the token budget."""
    available = max_tokens - query_tokens - system_tokens - 200  # 200 buffer
    selected = []
    used = 0
    for src in sorted(sources, key=lambda s: s.score, reverse=True):
        est_tokens = len(src.content) // 4
        if used + est_tokens <= available:
            selected.append(src)
            used += est_tokens
        else:
            break
    return selected
```

---

## 7. Agent Architecture

### 7.1 Design Principles

- The LLM is an **untrusted reasoner**, not a trusted executor.
- All tool calls proposed by the LLM are validated, permission-checked, and executed through the controlled `ToolService`.
- The LLM never receives raw system credentials, file paths outside the workspace, or other users' data.
- Prompt injection from document content is mitigated by wrapping document content in clear delimiters.

### 7.2 Agent Prompting Strategy

The agent uses a **structured JSON function-calling** style prompt. Since Ollama models may not have native function-calling, the system uses a constrained output prompt:

**System prompt template:**
```
You are an AI agent operating within Sovereign AI Workbench.
You have access to the following tools:

{tool_list}

RULES:
1. Always respond with a JSON object in one of these formats:
   PLANNING: {"type": "plan", "steps": [{"step": 1, "description": "...", "tool": "..."}]}
   TOOL CALL: {"type": "tool_call", "tool": "TOOL_NAME", "input": {...}, "reasoning": "..."}
   COMPLETE: {"type": "complete", "result": "final answer here"}
2. Only use tools from the list above.
3. Tool inputs must match the schema exactly.
4. Never include sensitive data (credentials, secrets) in reasoning.
5. If a tool call fails, explain what you observed and try an alternative.
6. Maximum iterations: {max_iterations}

Current iteration: {current_iteration}
Previous steps: {step_summary}
```

**Tool list format (injected into system prompt):**
```
- file_read: Read a file's contents. Input: {"path": "string (relative to /workspace)"}.
  Risk: LOW. Output: {"content": "string"}.
- python_exec: Execute Python code in a sandbox. Input: {"code": "string"}.
  Risk: HIGH (requires approval if not pre-approved). Output: {"stdout": "string", "exit_code": int}.
...
```

### 7.3 Agent Execution Loop

```python
class AgentService:
    async def execute_run(self, run_id: str):
        run = await self._get_run(run_id)
        await self._set_status(run_id, "running")

        step_history = []
        iteration = 0

        try:
            # Initial planning
            plan = await self._plan(run.goal, run.model_name)
            await self._save_plan(run_id, plan)

            while iteration < run.max_iterations:
                iteration += 1

                # Ask LLM for next action
                llm_response = await self.llm.chat(
                    model=run.model_name or self.settings.active_chat_model,
                    messages=self._build_messages(run.goal, step_history),
                    system_prompt=self._build_system_prompt(run),
                    temperature=0.0,  # deterministic for agent
                    stream=False,
                )

                # Parse LLM JSON response
                action = self._parse_action(llm_response.content)

                if action["type"] == "complete":
                    await self._complete_run(run_id, action["result"])
                    return

                elif action["type"] == "tool_call":
                    result = await self._execute_tool(
                        run_id, iteration, action, run
                    )
                    step_history.append({
                        "iteration": iteration,
                        "tool": action["tool"],
                        "input": action["input"],
                        "result": result,
                        "reasoning": action.get("reasoning"),
                    })

                else:
                    # Unexpected output — log and continue
                    step_history.append({
                        "iteration": iteration,
                        "error": f"Unexpected LLM output: {action}"
                    })

            # Max iterations reached
            partial = self._synthesize_partial(step_history)
            await self._fail_run(run_id, "max_iterations_exceeded", partial_result=partial)

        except Exception as e:
            await self._fail_run(run_id, str(e))

    async def _execute_tool(self, run_id, iteration, action, run):
        tool_name = action["tool"]
        tool_input = action["input"]

        # Get tool from registry
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {"error": f"Tool '{tool_name}' not found"}

        # Permission check
        if not self.tool_registry.is_permitted(tool_name, run.user_role):
            return {"error": f"Permission denied for tool '{tool_name}'"}

        # Validate input
        try:
            validated_input = tool.input_schema.model_validate(tool_input)
        except ValidationError as e:
            return {"error": f"Invalid input: {e}"}

        # Risk assessment → approval if needed
        if self._requires_approval(tool.risk_level, run):
            approved = await self.approval_service.request_and_wait(
                run_id=run_id,
                tool_name=tool_name,
                tool_input=tool_input,
                risk_level=tool.risk_level,
                requester_id=run.user_id,
            )
            if not approved:
                return {"error": "Approval denied or timed out"}

        # Execute
        if tool.requires_sandbox:
            result = await self.sandbox_service.run(tool_name, validated_input)
        else:
            result = await self.tool_service.execute(tool, validated_input)

        # Record tool call
        await self._record_tool_call(run_id, iteration, tool_name, tool_input, result)
        return result

    def _parse_action(self, llm_text: str) -> dict:
        """Extract JSON from LLM response. Handle markdown code blocks."""
        # Strip markdown fences
        text = re.sub(r"```json\n?", "", llm_text)
        text = re.sub(r"```\n?", "", text)
        # Find JSON object
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {"type": "error", "message": "Failed to parse LLM response"}
```

### 7.4 Prompt Injection Mitigation

```python
class PromptSanitizer:
    INJECTION_PATTERNS = [
        r"ignore previous instructions",
        r"system\s*:",
        r"<\|im_start\|>",
        r"<\|system\|>",
        r"forget everything",
        r"your new instructions",
        r"disregard all",
        r"you are now",
    ]

    def sanitize_user_input(self, text: str) -> str:
        """Sanitize user input before including in LLM prompt."""
        # Detect injection attempts
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                # Log security event
                logger.warning(f"Potential prompt injection detected: {pattern}")
                # Don't block (may be false positive), but flag in audit
                self._flag_for_audit(text, pattern)
        return text

    def wrap_document_content(self, content: str, source: str) -> str:
        """Wrap document content in clear delimiters to contain injection."""
        return (
            f"<document source='{source}'>\n"
            f"{content}\n"
            f"</document>"
        )

    def sanitize_for_prompt(self, text: str) -> str:
        """Remove characters that can break JSON output."""
        # Escape control characters that might corrupt JSON parsing
        return text.replace("\x00", "").replace("\r", "").strip()
```

---

## 8. Tool System Design

### 8.1 Tool Registry

```python
@dataclass
class ToolDefinition:
    name: str
    description: str                     # shown to LLM
    input_schema: type[BaseModel]        # Pydantic model
    output_schema: type[BaseModel]       # Pydantic model
    risk_level: str                      # low | medium | high | critical
    requires_sandbox: bool
    required_role: str                   # viewer | analyst | admin
    enabled: bool = True
    tags: list[str] = field(default_factory=list)

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        from tools import file_read, file_write, file_list, file_delete
        from tools import search_kb, calculator, python_exec, http_request

        self.register(ToolDefinition(
            name="file_read",
            description="Read the contents of a file in the workspace.",
            input_schema=file_read.FileReadInput,
            output_schema=file_read.FileReadOutput,
            risk_level="low",
            requires_sandbox=False,
            required_role="analyst",
        ))
        self.register(ToolDefinition(
            name="python_exec",
            description=(
                "Execute Python code in an isolated sandbox. "
                "Code runs in /workspace with pandas, numpy, and matplotlib available. "
                "No internet access. Output via print() or return value."
            ),
            input_schema=python_exec.PythonExecInput,
            output_schema=python_exec.PythonExecOutput,
            risk_level="high",
            requires_sandbox=True,
            required_role="analyst",
        ))
        self.register(ToolDefinition(
            name="http_request",
            description="Make an HTTP request to an external URL (requires admin approval).",
            input_schema=http_request.HTTPRequestInput,
            output_schema=http_request.HTTPRequestOutput,
            risk_level="critical",
            requires_sandbox=True,
            required_role="admin",
            enabled=False,  # disabled by default
        ))
        # ... other tools

    def get_tool_list_for_prompt(self, allowed: list[str] | None = None) -> str:
        """Format tool list for LLM system prompt."""
        tools = [t for t in self._tools.values() if t.enabled]
        if allowed:
            tools = [t for t in tools if t.name in allowed]
        lines = []
        for tool in tools:
            schema = {
                k: v.get("type", "any")
                for k, v in tool.input_schema.model_json_schema()
                .get("properties", {}).items()
            }
            lines.append(
                f"- {tool.name}: {tool.description} "
                f"Input: {json.dumps(schema)}. Risk: {tool.risk_level.upper()}."
            )
        return "\n".join(lines)
```

### 8.2 Built-in Tool Implementations

**`tools/file_read.py`:**
```python
class FileReadInput(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def safe_path(cls, v: str) -> str:
        # Prevent path traversal
        p = Path(v)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("Path must be relative and within workspace")
        return str(p)

class FileReadOutput(BaseModel):
    content: str
    size_bytes: int
    path: str

async def execute(input: FileReadInput, workspace: str) -> FileReadOutput:
    full_path = Path(workspace) / input.path
    if not full_path.exists():
        raise ToolExecutionError(f"File not found: {input.path}")
    content = full_path.read_text(encoding="utf-8", errors="replace")
    return FileReadOutput(content=content, size_bytes=len(content), path=input.path)
```

**`tools/python_exec.py`:**
```python
class PythonExecInput(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if len(v) > 50000:
            raise ValueError("Code too long (max 50000 chars)")
        return v

class PythonExecOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool

# Execution is delegated to SandboxService.run("python_exec", input)
```

**`tools/search_kb.py`:**
```python
class SearchKBInput(BaseModel):
    kb_id: str
    query: str
    top_k: int = 3

class SearchKBOutput(BaseModel):
    results: list[dict]  # [{content, filename, score}]
    found: bool

async def execute(input: SearchKBInput, rag_service: RAGService) -> SearchKBOutput:
    response = await rag_service.query(
        kb_id=input.kb_id,
        query=input.query,
        top_k=input.top_k,
        generate_answer=False,  # retrieval only in tool context
    )
    return SearchKBOutput(
        results=[{"content": s.content, "filename": s.filename, "score": s.score}
                 for s in response.sources],
        found=len(response.sources) > 0,
    )
```

---

## 9. Sandbox Service Design

### 9.1 Sandbox Execution Flow

```python
class SandboxService:
    def __init__(self, settings: Settings):
        self.settings = settings
        try:
            import docker
            self.docker = docker.from_env()
            self.available = True
        except Exception:
            logger.warning("Docker not available; sandboxed tools disabled")
            self.available = False

    async def run(
        self,
        tool_name: str,
        tool_input: BaseModel,
        workspace_path: str | None = None,
    ) -> dict:
        if not self.available:
            raise SandboxError("Docker sandbox not available")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_sync,
            tool_name,
            tool_input,
            workspace_path,
        )

    def _run_sync(self, tool_name, tool_input, workspace_path) -> dict:
        import docker

        # Prepare workspace
        ws = workspace_path or self._create_workspace()
        command = self._build_command(tool_name, tool_input)

        container = None
        t_start = time.monotonic()
        try:
            container = self.docker.containers.run(
                image=self.settings.sandbox_image,
                command=command,
                detach=True,
                remove=False,
                # Resource limits
                mem_limit=f"{self.settings.sandbox_mem_limit_mb}m",
                cpu_period=100000,
                cpu_quota=self.settings.sandbox_cpu_quota,
                pids_limit=50,
                # Security
                network_mode="none",
                read_only=True,
                user="1000:1000",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                # Workspace
                volumes={ws: {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
            )

            # Wait with timeout
            try:
                exit_data = container.wait(timeout=self.settings.sandbox_timeout_s)
                timed_out = False
            except Exception:
                container.kill()
                timed_out = True
                exit_data = {"StatusCode": -1}

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            duration_ms = int((time.monotonic() - t_start) * 1000)

            return {
                "stdout": stdout[:10000],  # cap output size
                "stderr": stderr[:2000],
                "exit_code": exit_data.get("StatusCode", -1),
                "timed_out": timed_out,
                "duration_ms": duration_ms,
                "container_id": container.id[:12],
            }

        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            self._cleanup_workspace(ws)

    def _build_command(self, tool_name, tool_input) -> list[str]:
        if tool_name == "python_exec":
            # Write code to file; execute
            code = tool_input.code
            return ["python", "-c", code]
        raise SandboxError(f"Unknown sandboxed tool: {tool_name}")
```

---

## 10. Vision and OCR Integration

### 10.1 Vision Model (Optional)

If a vision model (e.g. `llava:7b-q4`) is installed and designated as the active vision model, it can be used to:
- Describe images in documents
- Answer questions about image content
- Assist OCR for complex layouts

```python
async def analyze_image(
    image_path: str,
    question: str = "Describe this image in detail",
    model: str = "llava:7b-q4"
) -> str:
    import base64
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    # Ollama vision API
    resp = await llm_client.http_client.post("/api/generate", json={
        "model": model,
        "prompt": question,
        "images": [image_b64],
        "stream": False,
    })
    return resp.json()["response"]
```

Vision model integration is **optional** in MVP; system gracefully falls back to PaddleOCR-only when no vision model is available.

---

## 11. AI Component Failure Modes and Mitigations

| Component | Failure Mode | Mitigation |
|-----------|-------------|------------|
| Ollama | Offline / model not loaded | Health check before use; 503 response; dashboard alert |
| Embedding model | Not installed | Refuse KB creation; clear error message |
| PaddleOCR | Import error (missing native libs) | Document status = "indexed_without_ocr"; log warning |
| Agent LLM | Returns unparseable JSON | Retry 2× with hint; fail step with explanation |
| Agent LLM | Proposes non-existent tool | Tool not found error returned to agent; agent adapts |
| Qdrant | Collection not found | Return empty results; suggest re-indexing |
| Sandbox | Docker unavailable | Disable sandboxed tools; non-sandboxed tools still work |
| Long OCR | CPU-bound, slow | Background async processing; user sees progress indicator |

---

## 12. Recommended Model Configurations

### 12.1 Minimum Hardware (8 GB RAM)

| Role | Model | Size on disk | RAM when loaded |
|------|-------|-------------|----------------|
| Chat | `llama3.2:3b` | ~2 GB | ~3 GB |
| Embedding | `nomic-embed-text` | ~0.5 GB | ~0.5 GB |
| Vision | Not recommended at 8 GB | — | — |

### 12.2 Recommended Hardware (16 GB RAM)

| Role | Model | Size on disk | RAM when loaded |
|------|-------|-------------|----------------|
| Chat | `mistral:7b-q4` | ~4.1 GB | ~5 GB |
| Embedding | `nomic-embed-text` | ~0.5 GB | ~0.5 GB |
| Vision | `llava:7b-q4` | ~4.5 GB | ~5.5 GB |

**Note:** Only load one large model at a time on 16 GB RAM. Chat and vision models should not be loaded simultaneously unless 24+ GB available.

### 12.3 Optimal Demo Configuration (SIH)

Use `llama3.2:3b` for both chat and agent tasks. It runs well on CPU. Keep the demo focused on functionality over answer quality.

---

## 13. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial AI/ML Design document |

---

*End of AI/ML Design*
