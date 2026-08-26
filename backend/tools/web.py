"""
Web tools — Web Search and Web Fetch.

Security invariants:
- web_fetch blocks private/loopback/link-local targets (SSRF guard) and only
  returns text/* responses under a hard size cap.
- Both tools treat ALL retrieved content as UNTRUSTED DATA. Callers must never
  let tool output redefine agent permissions or instructions.
- No API key required for the default DuckDuckGo HTML backend; an optional
  provider config can be added later without changing the schema.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from pydantic import BaseModel, Field

_MAX_RESULTS = 6
_FETCH_TIMEOUT = 15.0
_MAX_BYTES = 1_000_000  # 1 MB text cap
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_UA = ("Mozilla/5.0 (compatible; SovereignAIWorkbench/1.0; +https://localhost)")


# ------------------------------------------------------------------
# Web Search — keyless DuckDuckGo HTML endpoint
# ------------------------------------------------------------------
class WebSearchInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=400,
                       description="Search query")


class WebSearchOutput(BaseModel):
    results: list[dict[str, Any]] = []
    engine: str = "duckduckgo"
    error: str | None = None


def _assert_public_host(host: str) -> None:
    """Raise ValueError when the host resolves to a non-public address."""
    if host.lower() in _BLOCKED_HOSTS:
        raise ValueError("Blocked host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError("Cannot resolve host") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("Blocked: target resolves to a private address")


async def web_search_execute(data: WebSearchInput, context: dict) -> dict:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(data.query)}"
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA}, timeout=12.0, follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.TimeoutException:
        return {"results": [], "engine": "duckduckgo", "error": "Search timed out"}
    except Exception as exc:  # noqa: BLE001 — user-safe message only
        return {"results": [], "engine": "duckduckgo",
                "error": f"Search failed: {type(exc).__name__}"}

    results: list[dict[str, Any]] = []
    # DDG html result links look like: <a rel="nofollow" class="result__a" href="...">
    for m in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.S,
    ):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        # DDG wraps URLs through a redirect (/l/?uddg=<urlencoded>)
        if href.startswith("//duckduckgo.com/l/") or href.startswith("/l/"):
            mm = re.search(r"uddg=([^&]+)", href)
            if not mm:
                continue
            from urllib.parse import unquote
            href = unquote(mm.group(1))
        if href.startswith("//"):
            href = "https:" + href
        results.append({"title": title[:200], "url": href[:500]})
        if len(results) >= _MAX_RESULTS:
            break

    if not results:
        return {"results": [], "engine": "duckduckgo",
                "error": "No results parsed (page layout may have changed)"}
    return {"results": results, "engine": "duckduckgo", "error": None}


# ------------------------------------------------------------------
# Web Fetch — read one page as plain text
# ------------------------------------------------------------------
class WebFetchInput(BaseModel):
    url: str = Field(..., max_length=1000)
    max_chars: int = Field(8000, ge=200, le=20000)


class WebFetchOutput(BaseModel):
    url: str
    status: int | None = None
    content: str = ""
    truncated: bool = False
    error: str | None = None


_TAG_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG_ANY = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n{3,}")


async def web_fetch_execute(data: WebFetchInput, context: dict) -> dict:
    parsed = urlparse(data.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"url": data.url, "status": None, "content": "",
                "truncated": False, "error": "Only http(s) URLs are allowed"}
    try:
        _assert_public_host(parsed.hostname)
    except ValueError as exc:
        return {"url": data.url, "status": None, "content": "",
                "truncated": False, "error": f"Blocked: {exc}"}

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA}, timeout=_FETCH_TIMEOUT,
            follow_redirects=True, max_redirects=5,
        ) as client:
            resp = await client.get(data.url)
        ctype = resp.headers.get("content-type", "")
        if ctype and not ctype.split(";")[0].strip().startswith("text/"):
            return {"url": data.url, "status": resp.status_code, "content": "",
                    "truncated": False,
                    "error": f"Unsupported content-type: {ctype.split(';')[0]}"}
        body = resp.content[:_MAX_BYTES].decode(resp.encoding or "utf-8",
                                                errors="replace")
    except httpx.TimeoutException:
        return {"url": data.url, "status": None, "content": "",
                "truncated": False, "error": "Fetch timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"url": data.url, "status": None, "content": "",
                "truncated": False, "error": f"Fetch failed: {type(exc).__name__}"}

    text = _WS.sub("\n\n", _TAG_ANY.sub("", _TAG_SCRIPT.sub("", body))).strip()
    truncated = len(text) > data.max_chars
    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "content": text[: data.max_chars],
        "truncated": truncated,
        "error": None,
    }
