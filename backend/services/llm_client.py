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


class ModelUnavailableError(Exception):
    pass


@dataclass
class ChatMessage:
    role: str
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


class BaseLLMProvider(ABC):
    """Abstract base for all LLM provider adapters."""

    @abstractmethod
    async def chat(
        self, model: str, messages: list[ChatMessage], stream: bool = False,
        temperature: float = 0.7, max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> "ChatResponse | AsyncGenerator[str, None]": ...

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResponse:
        raise ModelUnavailableError(f"Provider {self.__class__.__name__} does not support embeddings")

    async def list_models(self) -> list[dict]:
        return []

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        return False, None

    @staticmethod
    def _retry_delays() -> list[float]:
        return [0.0, 1.0, 2.0]

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 500, 502, 503)
        return False

    async def _retry_request(self, fn, attempts: int = 3):
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


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(connect=5.0, read=600.0, write=10.0, pool=5.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat(self, model: str, messages: list[ChatMessage], stream: bool = False, temperature: float = 0.7, max_tokens: int = 2048, system_prompt: str | None = None) -> "ChatResponse | AsyncGenerator[str, None]":
        payload = {"model": model, "messages": [{**{"role": m.role, "content": m.content}, **({"images": m.images} if m.images else {})} for m in messages], "stream": stream, "options": {"temperature": temperature, "num_predict": max_tokens}}
        if system_prompt: payload["system"] = system_prompt
        if stream: return self._stream_chat(payload)
        resp = await self._retry(lambda: self._get_client().post("/api/chat", json=payload))
        data = resp.json(); msg = data.get("message", {}); content = msg.get("content", "")
        if not content and msg.get("thinking"): content = msg.get("thinking", "")[-500:]
        return ChatResponse(content=content, model=model, prompt_tokens=data.get("prompt_eval_count", 0), completion_tokens=data.get("eval_count", 0), total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0), finish_reason=data.get("done_reason", "stop"))

    async def _stream_chat(self, payload: dict) -> AsyncGenerator[str, None]:
        try:
            async with self._get_client().stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            if not data.get("done"):
                                msg = data.get("message", {}); delta = msg.get("content", "") or msg.get("thinking", "")
                                if delta: yield delta
                        except json.JSONDecodeError: continue
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ModelUnavailableError(str(exc)) from exc

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResponse:
        data = (await self._retry(lambda: self._get_client().post("/api/embed", json={"model": model, "input": texts}))).json()
        return EmbeddingResponse(embeddings=data.get("embeddings", []), model=model, tokens=data.get("prompt_eval_count", 0))

    async def list_models(self) -> list[dict]:
        return (await self._retry(lambda: self._get_client().get("/api/tags"))).json().get("models", [])

    async def health_check(self, model: str | None = None) -> tuple[bool, int | None]:
        import time
        try:
            t0 = time.monotonic(); resp = await self._get_client().get("/", timeout=5.0)
            return resp.status_code < 500, int((time.monotonic() - t0) * 1000)
        except Exception: return False, None

    async def _retry(self, fn, attempts: int = 3) -> httpx.Response:
        last_exc: Exception | None = None
        for delay in [0.0, 1.0, 2.0]:
            try:
                if delay: await asyncio.sleep(delay)
                resp = await fn(); resp.raise_for_status(); return resp
            except (httpx.ConnectError, httpx.TimeoutException) as exc: last_exc = exc
            except httpx.HTTPStatusError as exc: raise ModelUnavailableError(str(exc)) from exc
        raise ModelUnavailableError(str(last_exc))


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 600.0, custom_headers: dict[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/"); self._api_key = api_key; self._timeout = timeout; self._custom_headers = custom_headers or {}; self._client: httpx.AsyncClient | None = None
    def _build_headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key: h["Authorization"] = f"Bearer {self._api_key}"
        h.update(self._custom_headers); return h
    def _api_root(self) -> str: return "" if self.base_url.rstrip("/").endswith("/v1") else "/v1"
    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed: self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(connect=10.0, read=self._timeout, write=30.0, pool=5.0))
        return self._client
    def _build_messages(self, messages, system_prompt):
        result = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        result.extend({"role": m.role, "content": m.content} for m in messages); return result
    async def chat(self, model, messages, stream=False, temperature=0.7, max_tokens=2048, system_prompt=None):
        payload = {"model": model, "messages": self._build_messages(messages, system_prompt), "temperature": temperature, "max_tokens": max_tokens, "stream": stream}
        if stream: return self._stream_chat(model, payload)
        try:
            resp = await self._get_client().post(f"{self._api_root()}/chat/completions", json=payload, headers=self._build_headers())
            for attempt in range(3):
                if resp.status_code != 429: break
                await asyncio.sleep(min(float(resp.headers.get("retry-after", 2 ** (attempt + 1))), 30))
                resp = await self._get_client().post(f"{self._api_root()}/chat/completions", json=payload, headers=self._build_headers())
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc: raise ModelUnavailableError(str(exc)) from exc
        except httpx.HTTPStatusError as exc: raise ModelUnavailableError(f"{exc} | Response: {exc.response.text[:500] if exc.response else ''}") from exc
        data = resp.json(); choice = data.get("choices", [{}])[0]; msg = choice.get("message", {}); usage = data.get("usage", {})
        return ChatResponse(content=msg.get("content") or "", model=data.get("model", model), prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0), total_tokens=usage.get("total_tokens", 0), finish_reason=choice.get("finish_reason", "stop"))
    async def _stream_chat(self, model, payload):
        try:
            async with self._get_client().stream("POST", f"{self._api_root()}/chat/completions", json=payload, headers=self._build_headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk=line[6:].strip()
                        if chunk == "[DONE]": break
                        try:
                            delta=json.loads(chunk).get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta: yield delta
                        except json.JSONDecodeError: continue
        except (httpx.ConnectError, httpx.TimeoutException) as exc: raise ModelUnavailableError(str(exc)) from exc
    async def health_check(self, model=None):
        import time
        try:
            t0=time.monotonic(); resp=await self._get_client().get(f"{self._api_root()}/models", headers=self._build_headers(), timeout=5.0); return resp.status_code < 500, int((time.monotonic()-t0)*1000)
        except Exception: return False, None
    async def list_models(self):
        resp=await self._get_client().get(f"{self._api_root()}/models", headers=self._build_headers(), timeout=5.0); resp.raise_for_status(); return resp.json().get("data", [])
    async def verify_auth(self, model=None):
        if not self._api_key or not model: return None, None
        try: resp=await self._get_client().post(f"{self._api_root()}/chat/completions", json={"model":model,"messages":[{"role":"user","content":"hi"}],"max_tokens":1,"stream":False}, headers=self._build_headers(), timeout=45.0)
        except (httpx.ConnectError, httpx.TimeoutException): return False, "Connection timed out during authentication check"
        except Exception: return None, None
        if resp.status_code in (401,403): return False,"Authentication failed — invalid API key"
        if resp.status_code == 402: return False,"API key valid but has insufficient credits"
        if resp.status_code in (200,429) or resp.status_code < 500 and resp.status_code != 404: return True,None
        return None,None


class AnthropicProvider(BaseLLMProvider):
    DEFAULT_BASE_URL="https://api.anthropic.com"; API_VERSION="2023-06-01"; DEFAULT_MAX_TOKENS=2048
    def __init__(self, api_key, base_url=None, timeout=300.0, custom_headers=None): self._api_key=api_key; self._base_url=(base_url or self.DEFAULT_BASE_URL).rstrip("/"); self._timeout=timeout; self._custom_headers=custom_headers or {}; self._client=None
    def _get_client(self):
        if self._client is None or self._client.is_closed: self._client=httpx.AsyncClient(base_url=self._base_url,timeout=httpx.Timeout(connect=10.0,read=self._timeout,write=30.0,pool=5.0))
        return self._client
    def _headers(self): h={"x-api-key":self._api_key,"anthropic-version":self.API_VERSION,"content-type":"application/json"}; h.update(self._custom_headers); return h
    def _api_root(self): return "" if self._base_url.rstrip("/").endswith("/v1") else "/v1"
    async def chat(self,model,messages,stream=False,temperature=0.7,max_tokens=DEFAULT_MAX_TOKENS,system_prompt=None):
        payload={"model":model,"max_tokens":max_tokens,"messages":[{"role":m.role,"content":m.content} for m in messages if m.role!="system"],"temperature":temperature}; system=system_prompt or next((m.content for m in messages if m.role=="system"),None)
        if system: payload["system"]=system
        if stream: return self._stream_chat(model,payload)
        data=(await self._retry_request(lambda:self._get_client().post(f"{self._api_root()}/messages",json=payload,headers=self._headers()))).json(); text=" ".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text"); usage=data.get("usage",{})
        return ChatResponse(content=text,model=data.get("model",model),prompt_tokens=usage.get("input_tokens",0),completion_tokens=usage.get("output_tokens",0),total_tokens=usage.get("input_tokens",0)+usage.get("output_tokens",0),finish_reason=data.get("stop_reason","end_turn"))
    async def _stream_chat(self,model,payload):
        payload["stream"]=True
        try:
            async with self._get_client().stream("POST",f"{self._api_root()}/messages",json=payload,headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            d=json.loads(line[6:]); text=d.get("delta",{}).get("text","") if d.get("type")=="content_block_delta" else ""
                            if text: yield text
                        except json.JSONDecodeError: continue
        except (httpx.ConnectError,httpx.TimeoutException) as exc: raise ModelUnavailableError(str(exc)) from exc
    async def health_check(self,model=None):
        import time
        try:
            t0=time.monotonic(); resp=await self._get_client().get(f"{self._api_root()}/messages",headers=self._headers(),timeout=5.0); return resp.status_code<500,int((time.monotonic()-t0)*1000)
        except Exception:return False,None
    async def verify_auth(self,model=None): return None,None


class GeminiProvider(BaseLLMProvider):
    """Google Gemini REST adapter, including live model discovery."""
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

    def __init__(self, api_key: str, base_url: str | None = None, timeout: float = 300.0, custom_headers: dict[str, str] | None = None) -> None:
        self._api_key=api_key; self._base_url=(base_url or self.DEFAULT_BASE_URL).rstrip("/"); self._timeout=timeout; self._custom_headers=custom_headers or {}; self._client=None

    def _get_client(self):
        if self._client is None or self._client.is_closed: self._client=httpx.AsyncClient(base_url=self._base_url,timeout=httpx.Timeout(connect=10.0,read=self._timeout,write=30.0,pool=5.0),headers=self._custom_headers)
        return self._client

    def _url(self, model: str, stream: bool=False) -> str:
        action="streamGenerateContent" if stream else "generateContent"
        return f"/v1beta/models/{model}:{action}?key={self._api_key}"

    def _build_payload(self,messages,system_prompt,temperature,max_tokens):
        contents=[]
        for m in messages:
            if m.role=="system": continue
            contents.append({"role":"user" if m.role=="user" else "model","parts":[{"text":m.content}]})
        payload={"contents":contents,"generationConfig":{"temperature":temperature,"maxOutputTokens":max_tokens}}
        system=system_prompt or next((m.content for m in messages if m.role=="system"),None)
        if system: payload["systemInstruction"]={"parts":[{"text":system}]}
        return payload

    async def chat(self,model,messages,stream=False,temperature=0.7,max_tokens=2048,system_prompt=None):
        payload=self._build_payload(messages,system_prompt,temperature,max_tokens)
        if stream:return self._stream_chat(model,payload)
        resp=await self._retry_request(lambda:self._get_client().post(self._url(model),json=payload)); data=resp.json(); candidates=data.get("candidates",[{}]); content_parts=candidates[0].get("content",{}).get("parts",[]); usage=data.get("usageMetadata",{})
        return ChatResponse(content=" ".join(p.get("text","") for p in content_parts),model=model,prompt_tokens=usage.get("promptTokenCount",0),completion_tokens=usage.get("candidatesTokenCount",0),total_tokens=usage.get("totalTokenCount",0),finish_reason=candidates[0].get("finishReason","STOP"))

    async def _stream_chat(self,model,payload):
        try:
            async with self._get_client().stream("POST",self._url(model,True),json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if '"text":' in line:
                        try:
                            idx=line.index('"text":'); snippet=line[idx+8:].strip().strip('"').strip(',')
                            if snippet: yield snippet
                        except Exception: continue
        except (httpx.ConnectError,httpx.TimeoutException) as exc: raise ModelUnavailableError(str(exc)) from exc

    async def health_check(self,model=None):
        import time
        try:
            t0=time.monotonic(); resp=await self._get_client().get("/v1beta/models",params={"key":self._api_key,"pageSize":1},timeout=5.0); return resp.status_code<500,int((time.monotonic()-t0)*1000)
        except Exception:return False,None

    async def list_models(self) -> list[dict]:
        """Discover Gemini models that support generateContent, following pagination."""
        models=[]
        next_page_token=None
        while True:
            params={"key":self._api_key,"pageSize":1000}
            if next_page_token: params["pageToken"]=next_page_token
            try:
                resp=await self._get_client().get("/v1beta/models",params=params,timeout=10.0)
                resp.raise_for_status()
            except (httpx.ConnectError,httpx.TimeoutException) as exc:
                raise ModelUnavailableError(str(exc)) from exc
            except httpx.HTTPStatusError as exc:
                body=exc.response.text[:500] if exc.response else ""
                raise ModelUnavailableError(f"Gemini model listing failed: {body}") from exc
            data=resp.json()
            for model in data.get("models",[]):
                if not isinstance(model,dict): continue
                methods=model.get("supportedGenerationMethods") or []
                if "generateContent" not in methods: continue
                name=model.get("name","")
                if name.startswith("models/"): name=name[len("models/"):]
                if not name: continue
                models.append({"id":name,"name":name,"display_name":model.get("displayName") or name,"description":model.get("description","")})
            next_page_token=data.get("nextPageToken")
            if not next_page_token: break
        return models

    async def verify_auth(self,model=None):
        if not self._api_key or not model:return None,None
        try: resp=await self._get_client().post(self._url(model),json=self._build_payload([ChatMessage(role="user",content="hi")],None,0.7,1),timeout=45.0)
        except (httpx.ConnectError,httpx.TimeoutException):return False,"Connection timed out during authentication check"
        except Exception:return None,None
        if resp.status_code in (401,403):return False,"Authentication failed — invalid API key"
        if resp.status_code==429:return True,None
        if resp.status_code==200:return True,None
        if resp.status_code<500 and resp.status_code!=404:return True,None
        return None,None


class CohereProvider(BaseLLMProvider):
    DEFAULT_BASE_URL="https://api.cohere.com/v2"
    def __init__(self,api_key,base_url=None,timeout=300.0,custom_headers=None): self._api_key=api_key; self._base_url=(base_url or self.DEFAULT_BASE_URL).rstrip("/"); self._timeout=timeout; self._custom_headers=custom_headers or {}; self._client=None
    def _get_client(self):
        if self._client is None or self._client.is_closed:self._client=httpx.AsyncClient(base_url=self._base_url,timeout=httpx.Timeout(connect=10.0,read=self._timeout,write=30.0,pool=5.0))
        return self._client
    def _headers(self): h={"Authorization":f"Bearer {self._api_key}","Content-Type":"application/json","Accept":"application/json"}; h.update(self._custom_headers); return h
    async def chat(self,model,messages,stream=False,temperature=0.7,max_tokens=2048,system_prompt=None):
        chat_history=[]; preamble=None
        for m in messages:
            if m.role=="system":preamble=m.content
            elif m.role=="user":chat_history.append({"role":"USER","message":m.content})
            elif m.role=="assistant":chat_history.append({"role":"CHATBOT","message":m.content})
        if system_prompt:preamble=system_prompt
        payload={"model":model,"messages":chat_history,"temperature":temperature,"max_tokens":max_tokens}
        if preamble:payload["preamble"]=preamble
        if stream:return self._stream_chat(model,payload)
        data=(await self._retry_request(lambda:self._get_client().post("/chat",json=payload,headers=self._headers()))).json(); text=data.get("message",{}).get("content",[{"text":""}])[0].get("text",""); usage=data.get("usage",{}).get("tokens",{})
        return ChatResponse(content=text,model=model,prompt_tokens=usage.get("input_tokens",0),completion_tokens=usage.get("output_tokens",0),total_tokens=usage.get("input_tokens",0)+usage.get("output_tokens",0),finish_reason=data.get("stop_reason","END_TURN"))
    async def _stream_chat(self,model,payload): return
    async def health_check(self,model=None):
        import time
        try:t0=time.monotonic();resp=await self._get_client().get("/models",headers=self._headers(),timeout=5.0);return resp.status_code<500,int((time.monotonic()-t0)*1000)
        except Exception:return False,None
    async def list_models(self):
        data=(await self._get_client().get("/models",headers=self._headers(),timeout=5.0));data.raise_for_status();return data.json().get("models") or data.json().get("data",[])
    async def verify_auth(self,model=None):return None,None


def build_provider(provider_type,base_url,api_key,timeout=600.0,custom_headers=None):
    if isinstance(custom_headers,str):
        try: parsed=json.loads(custom_headers); custom_headers=parsed if isinstance(parsed,dict) else None
        except (ValueError,TypeError): custom_headers=None
    from models.provider import PROVIDER_OLLAMA,PROVIDER_OPENAI,PROVIDER_ANTHROPIC,PROVIDER_GEMINI,PROVIDER_OPENAI_COMPATIBLE,PROVIDER_OPENROUTER,PROVIDER_OPENCODE_ZEN,PROVIDER_NVIDIA,PROVIDER_GROQ,PROVIDER_TOGETHER,PROVIDER_DEEPSEEK,PROVIDER_MISTRAL,PROVIDER_COHERE,PROVIDER_PERPLEXITY,PROVIDER_FIREWORKS,PROVIDER_AI21,PROVIDER_CLOUDFLARE,PROVIDER_AZURE_OPENAI,PROVIDER_HUGGINGFACE,PROVIDER_REPLICATE,PROVIDER_bedrock,PROVIDER_OLLAMA_COMPATIBLE
    if provider_type in (PROVIDER_OLLAMA,PROVIDER_OLLAMA_COMPATIBLE): return OllamaProvider(base_url or "http://host.docker.internal:11434")
    if provider_type==PROVIDER_OPENAI:return OpenAICompatibleProvider(base_url or "https://api.openai.com",api_key,timeout,custom_headers)
    if provider_type==PROVIDER_ANTHROPIC:
        if not api_key:raise ModelUnavailableError("Anthropic provider requires an API key")
        return AnthropicProvider(api_key,base_url,timeout,custom_headers)
    if provider_type==PROVIDER_GEMINI:
        if not api_key:raise ModelUnavailableError("Gemini provider requires an API key")
        return GeminiProvider(api_key,base_url,timeout,custom_headers)
    if provider_type==PROVIDER_COHERE:
        if not api_key:raise ModelUnavailableError("Cohere provider requires an API key")
        return CohereProvider(api_key,base_url,timeout,custom_headers)
    urls={PROVIDER_OPENROUTER:"https://openrouter.ai/api/v1",PROVIDER_OPENCODE_ZEN:"https://opencode.ai/zen/v1",PROVIDER_NVIDIA:"https://integrate.api.nvidia.com/v1",PROVIDER_GROQ:"https://api.groq.com/openai/v1",PROVIDER_TOGETHER:"https://api.together.xyz/v1",PROVIDER_DEEPSEEK:"https://api.deepseek.com",PROVIDER_MISTRAL:"https://api.mistral.ai/v1",PROVIDER_PERPLEXITY:"https://api.perplexity.ai",PROVIDER_FIREWORKS:"https://api.fireworks.ai/inference/v1",PROVIDER_AI21:"https://api.ai21.com/studio/v1",PROVIDER_HUGGINGFACE:"https://api-inference.huggingface.co/v1"}
    if provider_type in urls:return OpenAICompatibleProvider(base_url or urls[provider_type],api_key,timeout,custom_headers)
    if provider_type in (PROVIDER_CLOUDFLARE,PROVIDER_AZURE_OPENAI,PROVIDER_REPLICATE,PROVIDER_bedrock,PROVIDER_OPENAI_COMPATIBLE):
        if not base_url:raise ModelUnavailableError("Provider requires a base URL")
        return OpenAICompatibleProvider(base_url,api_key,timeout,custom_headers)
    raise ModelUnavailableError(f"Unknown provider type: {provider_type}")

OllamaClient=OllamaProvider
