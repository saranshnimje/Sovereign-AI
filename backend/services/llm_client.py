"""
LLM abstraction layer.

Hierarchy:
  BaseLLMProvider (protocol/ABC)
    ├── OllamaProvider          — local Ollama server (default, existing behaviour)
    ├── OpenAICompatibleProvider — any endpoint implementing the OpenAI chat completions spec
    ├── AnthropicProvider        — Anthropic Messages API (Claude)
    ├── GeminiProvider           — Google Gemini API (via generateContent)
    ├── CohereProvider           — Cohere Chat API (Command R+, Command R)
    └── (new adapters can be added here)

All providers implement the same interface: chat(), list_models(), health_check().
The OllamaClient name is kept as an alias for backward compatibility.
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)


# ── Shared data classes ────────────────────────────────────────

class ModelUnavailableError(Exception):
    pass


@dataclass
class ChatMessage:
    role: str          # system | user | assistant | tool
    content: str
    images: list[str] | None = None


@dataclass
class ChatResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"


@dataclass
class EmbeddingResponse:
    embeddings: list[list[float]]
    model: str
    tokens: int = 0


# ── Base provider interface ────────────────────────────────────

class BaseLLMProvider(ABC):
    """Abstract base for all LLM provider adapters."""

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]":
        ...

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResponse:
        raise ModelUnavailableError(
            f"Provider {self.__class__.__name__} does not support embeddings"
        )

    async def list_models(self) -> list[dict]:
        return []

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        return False, None

    @staticmethod
    def _retry_delays() -> list[float]:
        return [0.0, 1.0, 2.0]

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Return True for transient errors safe to retry."""
        if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 500, 502, 503)
        return False

    async def _retry_request(self, fn, attempts: int = 3):
        """Execute fn() with retries on transient errors. Returns httpx.Response."""
        last_exc: Exception | None = None
        for delay in [0.0, 1.0, 2.0][:attempts]:
            try:
                if delay:
                    await asyncio.sleep(delay)
                resp = await fn()
                resp.raise_for_status()
                return resp
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable(exc):
                    break
        if isinstance(last_exc, httpx.HTTPStatusError):
            body = ""
            try:
                body = last_exc.response.text[:500]
            except Exception:
                pass
            raise ModelUnavailableError(f"{last_exc} | Response: {body}") from last_exc
        raise ModelUnavailableError(str(last_exc)) from last_exc


# ── Ollama Provider ────────────────────────────────────────────

class OllamaProvider(BaseLLMProvider):
    """
    Async HTTP client for Ollama.
    Implements: chat (stream + non-stream), embed, list_models, health_check.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=5.0, read=600.0, write=10.0, pool=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]":
        payload: dict = {
            "model": model,
            "messages": [
                {**{"role": m.role, "content": m.content},
                 **({"images": m.images} if m.images else {})}
                for m in messages
            ],
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system_prompt:
            payload["system"] = system_prompt

        if stream:
            return self._stream_chat(payload)

        resp = await self._retry(lambda: self._get_client().post("/api/chat", json=payload))
        data = resp.json()
        msg = data.get("message", {})
        content = msg.get("content", "")
        if not content and msg.get("thinking"):
            content = msg.get("thinking", "")[-500:]
        return ChatResponse(
            content=content,
            model=model,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            finish_reason=data.get("done_reason", "stop"),
        )

    async def _stream_chat(self, payload: dict) -> AsyncGenerator[str, None]:
        client = self._get_client()
        try:
            async with client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            if not data.get("done"):
                                msg = data.get("message", {})
                                delta = msg.get("content", "")
                                if not delta and msg.get("thinking"):
                                    delta = msg["thinking"]
                                if delta:
                                    yield delta
                        except json.JSONDecodeError:
                            continue
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResponse:
        payload = {"model": model, "input": texts}
        resp = await self._retry(lambda: self._get_client().post("/api/embed", json=payload))
        data = resp.json()
        return EmbeddingResponse(
            embeddings=data.get("embeddings", []),
            model=model,
            tokens=data.get("prompt_eval_count", 0),
        )

    async def list_models(self) -> list[dict]:
        resp = await self._retry(lambda: self._get_client().get("/api/tags"))
        return resp.json().get("models", [])

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        import time
        try:
            t0 = time.monotonic()
            resp = await self._get_client().get("/", timeout=5.0)
            latency = int((time.monotonic() - t0) * 1000)
            return resp.status_code < 500, latency
        except Exception:
            return False, None

    async def _retry(self, fn, attempts: int = 3) -> httpx.Response:
        last_exc: Exception | None = None
        for delay in [0.0, 1.0, 2.0]:
            try:
                if delay:
                    await asyncio.sleep(delay)
                resp = await fn()
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
            except httpx.HTTPStatusError as exc:
                raise ModelUnavailableError(str(exc)) from exc
        raise ModelUnavailableError(str(last_exc))


# ── OpenAI-Compatible Provider ─────────────────────────────────

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    Adapter for any OpenAI-compatible chat completions endpoint.
    Covers: OpenAI, vLLM, LM Studio, LocalAI, Groq, Together, DeepSeek,
    Mistral, Fireworks, Perplexity, AI21, NVIDIA, OpenRouter, HuggingFace,
    and any service that implements POST /v1/chat/completions.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 600.0,
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._custom_headers = custom_headers or {}
        self._client: httpx.AsyncClient | None = None

    def _build_headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        h.update(self._custom_headers)
        logger.debug("OpenAICompatible _build_headers: keys=%s custom=%s", list(h.keys()), list(self._custom_headers.keys()))
        return h

    def _api_root(self) -> str:
        return "" if self.base_url.rstrip("/").endswith("/v1") else "/v1"

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=30.0, pool=5.0),
            )
        return self._client

    def _build_messages(
        self,
        messages: list[ChatMessage],
        system_prompt: str | None,
    ) -> list[dict]:
        result: list[dict] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        result.extend({"role": m.role, "content": m.content} for m in messages)
        return result

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]":
        payload = {
            "model": model,
            "messages": self._build_messages(messages, system_prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if stream:
            return self._stream_chat(model, payload)

        try:
            resp = await self._get_client().post(
                f"{self._api_root()}/chat/completions",
                json=payload,
                headers=self._build_headers(),
            )
            for attempt in range(3):
                if resp.status_code != 429:
                    break
                retry_after = float(resp.headers.get("retry-after", 2 ** (attempt + 1)))
                import asyncio as _aio
                await _aio.sleep(min(retry_after, 30))
                resp = await self._get_client().post(
                    f"{self._api_root()}/chat/completions",
                    json=payload,
                    headers=self._build_headers(),
                )
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            body = ""
            if exc.response is not None:
                try:
                    body = exc.response.text[:500]
                except Exception:
                    pass
            raise ModelUnavailableError(f"{exc} | Response: {body}") from exc

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})
        return ChatResponse(
            content=msg.get("content") or "",
            model=data.get("model", model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def _stream_chat(self, model: str, payload: dict) -> AsyncGenerator[str, None]:
        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                f"{self._api_root()}/chat/completions",
                json=payload,
                headers=self._build_headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            delta = (
                                data.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response else ""
            raise ModelUnavailableError(
                f"HTTP {exc.response.status_code} during streaming | Response: {body}"
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        import time
        try:
            t0 = time.monotonic()
            resp = await self._get_client().get(
                f"{self._api_root()}/models",
                headers=self._build_headers(),
                timeout=5.0,
            )
            latency = int((time.monotonic() - t0) * 1000)
            return resp.status_code < 500, latency
        except Exception:
            return False, None

    async def list_models(self) -> list[dict]:
        resp = await self._get_client().get(
            f"{self._api_root()}/models", headers=self._build_headers(), timeout=5.0
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def verify_auth(self, model: str | None = None) -> tuple[bool | None, str | None]:
        if not self._api_key or not model:
            return None, None
        try:
            resp = await self._get_client().post(
                f"{self._api_root()}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                headers=self._build_headers(),
                timeout=45.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return False, "Connection timed out during authentication check"
        except Exception:
            return None, None

        code = resp.status_code
        if code in (401, 403):
            return False, "Authentication failed — invalid API key"
        if code == 402:
            return False, "API key valid but has insufficient credits"
        if code == 429:
            return True, None
        if code == 200:
            return True, None
        if code < 500 and code != 404:
            return True, None
        return None, None


# ── Anthropic Provider ─────────────────────────────────────────

class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Messages API adapter (pure httpx, no SDK).
    Docs: https://docs.anthropic.com/en/api/messages

    Accepts optional base_url for proxies/enterprise endpoints.
    """

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    API_VERSION = "2023-06-01"
    DEFAULT_MAX_TOKENS = 2048

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 300.0,
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._custom_headers = custom_headers or {}
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=30.0, pool=5.0),
            )
        return self._client

    def _headers(self) -> dict:
        h = {
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        h.update(self._custom_headers)
        return h

    def _api_root(self) -> str:
        return "" if self._base_url.rstrip("/").endswith("/v1") else "/v1"

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]":
        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages
                         if m.role != "system"],
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        elif any(m.role == "system" for m in messages):
            payload["system"] = next(m.content for m in messages if m.role == "system")

        if stream:
            return self._stream_chat(model, payload)

        resp = await self._retry_request(
            lambda: self._get_client().post(
                f"{self._api_root()}/messages", json=payload, headers=self._headers()
            )
        )

        data = resp.json()
        content_blocks = data.get("content", [])
        text = " ".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
        usage = data.get("usage", {})
        return ChatResponse(
            content=text,
            model=data.get("model", model),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            finish_reason=data.get("stop_reason", "end_turn"),
        )

    async def _stream_chat(self, model: str, payload: dict) -> AsyncGenerator[str, None]:
        payload["stream"] = True
        client = self._get_client()
        try:
            async with client.stream(
                "POST", f"{self._api_root()}/messages", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "content_block_delta":
                                delta = data.get("delta", {}).get("text", "")
                                if delta:
                                    yield delta
                        except json.JSONDecodeError:
                            continue
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        import time
        try:
            t0 = time.monotonic()
            resp = await self._get_client().get(
                f"{self._api_root()}/messages",
                headers=self._headers(),
                timeout=5.0,
            )
            latency = int((time.monotonic() - t0) * 1000)
            # Anthropic returns 405 Method Not Allowed on GET /messages — that means reachable
            return resp.status_code < 500, latency
        except Exception:
            return False, None

    async def verify_auth(self, model: str | None = None) -> tuple[bool | None, str | None]:
        """Verify API key with a minimal chat probe."""
        if not self._api_key or not model:
            return None, None
        try:
            resp = await self._get_client().post(
                f"{self._api_root()}/messages",
                json={
                    "model": model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                headers=self._headers(),
                timeout=45.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return False, "Connection timed out during authentication check"
        except Exception:
            return None, None

        code = resp.status_code
        if code in (401, 403):
            return False, "Authentication failed — invalid API key"
        if code == 429:
            return True, None
        if code == 200:
            return True, None
        if code < 500 and code != 404:
            return True, None
        return None, None


# ── Gemini Provider ────────────────────────────────────────────

class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini API adapter (pure httpx, no SDK).
    Uses the generateContent REST endpoint.
    Accepts optional base_url for proxies/enterprise endpoints.
    """

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 300.0,
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._custom_headers = custom_headers or {}
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=30.0, pool=5.0),
            )
        return self._client

    def _url(self, model: str, stream: bool = False) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        return f"/v1beta/models/{model}:{action}?key={self._api_key}"

    def _build_payload(
        self,
        messages: list[ChatMessage],
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        contents = []
        for m in messages:
            if m.role == "system":
                continue
            role = "user" if m.role == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        system = system_prompt or next(
            (m.content for m in messages if m.role == "system"), None
        )
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        return payload

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]":
        payload = self._build_payload(messages, system_prompt, temperature, max_tokens)

        if stream:
            return self._stream_chat(model, payload)

        resp = await self._retry_request(
            lambda: self._get_client().post(self._url(model), json=payload)
        )

        data = resp.json()
        candidates = data.get("candidates", [{}])
        content_parts = candidates[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in content_parts)
        usage = data.get("usageMetadata", {})
        return ChatResponse(
            content=text,
            model=model,
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            total_tokens=usage.get("totalTokenCount", 0),
            finish_reason=candidates[0].get("finishReason", "STOP"),
        )

    async def _stream_chat(self, model: str, payload: dict) -> AsyncGenerator[str, None]:
        client = self._get_client()
        try:
            async with client.stream(
                "POST", self._url(model, stream=True), json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith('"text"'):
                        try:
                            text = json.loads("{" + line + "}")["text"]
                            if text:
                                yield text
                        except Exception:
                            continue
                    elif '"text":' in line:
                        try:
                            idx = line.index('"text":')
                            snippet = line[idx + 8:].strip().strip('"').strip(",")
                            if snippet:
                                yield snippet
                        except Exception:
                            continue
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        import time
        try:
            t0 = time.monotonic()
            resp = await self._get_client().get(
                f"/v1beta/models?key={self._api_key}", timeout=5.0
            )
            latency = int((time.monotonic() - t0) * 1000)
            return resp.status_code < 500, latency
        except Exception:
            return False, None

    async def verify_auth(self, model: str | None = None) -> tuple[bool | None, str | None]:
        if not self._api_key or not model:
            return None, None
        try:
            resp = await self._get_client().post(
                self._url(model),
                json=self._build_payload(
                    [ChatMessage(role="user", content="hi")], None, 0.7, 1
                ),
                timeout=45.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return False, "Connection timed out during authentication check"
        except Exception:
            return None, None

        code = resp.status_code
        if code in (401, 403):
            return False, "Authentication failed — invalid API key"
        if code == 429:
            return True, None
        if code == 200:
            return True, None
        if code < 500 and code != 404:
            return True, None
        return None, None


# ── Cohere Provider ────────────────────────────────────────────

class CohereProvider(BaseLLMProvider):
    """
    Cohere Chat API adapter (pure httpx, no SDK).
    Docs: https://docs.cohere.com/reference/chat
    """

    DEFAULT_BASE_URL = "https://api.cohere.com/v2"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 300.0,
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._custom_headers = custom_headers or {}
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=30.0, pool=5.0),
            )
        return self._client

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        h.update(self._custom_headers)
        return h

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]":
        # Cohere v2 uses a different message format
        chat_history = []
        preamble = None
        for m in messages:
            if m.role == "system":
                preamble = m.content
            elif m.role == "user":
                chat_history.append({"role": "USER", "message": m.content})
            elif m.role == "assistant":
                chat_history.append({"role": "CHATBOT", "message": m.content})

        if system_prompt:
            preamble = system_prompt

        payload: dict = {
            "model": model,
            "messages": chat_history,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if preamble:
            payload["preamble"] = preamble

        if stream:
            return self._stream_chat(model, payload)

        resp = await self._retry_request(
            lambda: self._get_client().post(
                "/chat", json=payload, headers=self._headers()
            )
        )

        data = resp.json()
        text = data.get("message", {}).get("content", [{"text": ""}])[0].get("text", "")
        usage = data.get("usage", {})
        return ChatResponse(
            content=text,
            model=model,
            prompt_tokens=usage.get("tokens", {}).get("input_tokens", 0),
            completion_tokens=usage.get("tokens", {}).get("output_tokens", 0),
            total_tokens=usage.get("tokens", {}).get("input_tokens", 0) + usage.get("tokens", {}).get("output_tokens", 0),
            finish_reason=data.get("stop_reason", "END_TURN"),
        )

    async def _stream_chat(self, model: str, payload: dict) -> AsyncGenerator[str, None]:
        payload["stream"] = True
        client = self._get_client()
        try:
            async with client.stream(
                "POST", "/chat", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            delta_type = data.get("type")
                            if delta_type == "content-delta":
                                text = data.get("delta", {}).get("message", {}).get("content", {}).get("text", "")
                                if text:
                                    yield text
                        except json.JSONDecodeError:
                            continue
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        import time
        try:
            t0 = time.monotonic()
            resp = await self._get_client().get(
                "/models", headers=self._headers(), timeout=5.0
            )
            latency = int((time.monotonic() - t0) * 1000)
            return resp.status_code < 500, latency
        except Exception:
            return False, None

    async def list_models(self) -> list[dict]:
        resp = await self._get_client().get(
            "/models", headers=self._headers(), timeout=5.0
        )
        resp.raise_for_status()
        data = resp.json()
        # Cohere v2 returns {"models": [...]} or {"data": [...]}
        models = data.get("models") or data.get("data", [])
        return [{"id": m.get("id", m.get("name", "")), **m} if isinstance(m, dict) else {"id": m} for m in models]

    async def verify_auth(self, model: str | None = None) -> tuple[bool | None, str | None]:
        if not self._api_key or not model:
            return None, None
        try:
            resp = await self._get_client().post(
                "/chat",
                json={"model": model, "messages": [{"role": "USER", "message": "hi"}], "max_tokens": 1},
                headers=self._headers(),
                timeout=45.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return False, "Connection timed out during authentication check"
        except Exception:
            return None, None

        code = resp.status_code
        if code in (401, 403):
            return False, "Authentication failed — invalid API key"
        if code == 429:
            return True, None
        if code == 200:
            return True, None
        if code < 500 and code != 404:
            return True, None
        return None, None


# ── Factory ────────────────────────────────────────────────────

def build_provider(
    provider_type: str,
    base_url: str | None,
    api_key: str | None,
    timeout: float = 600.0,
    custom_headers: dict[str, str] | str | None = None,
) -> BaseLLMProvider:
    """
    Factory: create the correct provider instance from stored config.
    Used by the dependency injection layer to build request-time clients.
    """
    # Parse JSON string from DB if needed
    if isinstance(custom_headers, str):
        try:
            import json as _json
            parsed = _json.loads(custom_headers)
            custom_headers = parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            custom_headers = None
    from models.provider import (
        PROVIDER_OLLAMA, PROVIDER_OPENAI, PROVIDER_ANTHROPIC,
        PROVIDER_GEMINI, PROVIDER_OPENAI_COMPATIBLE,
        PROVIDER_OPENROUTER, PROVIDER_OPENCODE_ZEN, PROVIDER_NVIDIA,
        PROVIDER_GROQ, PROVIDER_TOGETHER, PROVIDER_DEEPSEEK,
        PROVIDER_MISTRAL, PROVIDER_COHERE, PROVIDER_PERPLEXITY,
        PROVIDER_FIREWORKS, PROVIDER_AI21, PROVIDER_CLOUDFLARE,
        PROVIDER_AZURE_OPENAI, PROVIDER_HUGGINGFACE, PROVIDER_REPLICATE,
        PROVIDER_bedrock, PROVIDER_OLLAMA_COMPATIBLE,
    )

    if provider_type == PROVIDER_OLLAMA:
        url = base_url or "http://host.docker.internal:11434"
        return OllamaProvider(url)

    if provider_type == PROVIDER_OLLAMA_COMPATIBLE:
        url = base_url or "http://host.docker.internal:11434"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_OPENAI:
        url = base_url or "https://api.openai.com"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_ANTHROPIC:
        if not api_key:
            raise ModelUnavailableError("Anthropic provider requires an API key")
        return AnthropicProvider(api_key, base_url=base_url, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_GEMINI:
        if not api_key:
            raise ModelUnavailableError("Gemini provider requires an API key")
        return GeminiProvider(api_key, base_url=base_url, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_COHERE:
        if not api_key:
            raise ModelUnavailableError("Cohere provider requires an API key")
        return CohereProvider(api_key, base_url=base_url, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_OPENROUTER:
        url = base_url or "https://openrouter.ai/api/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_OPENCODE_ZEN:
        url = base_url or "https://opencode.ai/zen/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_NVIDIA:
        url = base_url or "https://integrate.api.nvidia.com/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_GROQ:
        url = base_url or "https://api.groq.com/openai/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_TOGETHER:
        url = base_url or "https://api.together.xyz/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_DEEPSEEK:
        url = base_url or "https://api.deepseek.com"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_MISTRAL:
        url = base_url or "https://api.mistral.ai/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_PERPLEXITY:
        url = base_url or "https://api.perplexity.ai"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_FIREWORKS:
        url = base_url or "https://api.fireworks.ai/inference/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_AI21:
        url = base_url or "https://api.ai21.com/studio/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_CLOUDFLARE:
        if not base_url:
            raise ModelUnavailableError("Cloudflare Workers AI requires a base URL (include your account ID)")
        return OpenAICompatibleProvider(base_url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_AZURE_OPENAI:
        if not base_url:
            raise ModelUnavailableError("Azure OpenAI requires a base URL (your Azure endpoint)")
        return OpenAICompatibleProvider(base_url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_HUGGINGFACE:
        url = base_url or "https://api-inference.huggingface.co/v1"
        return OpenAICompatibleProvider(url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_REPLICATE:
        if not base_url:
            raise ModelUnavailableError("Replicate requires a base URL")
        return OpenAICompatibleProvider(base_url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_bedrock:
        if not base_url:
            raise ModelUnavailableError("AWS Bedrock requires a base URL (your regional endpoint)")
        return OpenAICompatibleProvider(base_url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    if provider_type == PROVIDER_OPENAI_COMPATIBLE:
        if not base_url:
            raise ModelUnavailableError("OpenAI-compatible provider requires a base URL")
        return OpenAICompatibleProvider(base_url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)

    raise ModelUnavailableError(f"Unknown provider type: {provider_type}")


# ── Backward-compatibility alias ───────────────────────────────
OllamaClient = OllamaProvider
