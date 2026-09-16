"""
Web tools — Web Search and Web Fetch.

Security invariants:
- web_fetch blocks private/loopback/link-local targets (SSRF guard) and only
  returns text/* responses under a hard size cap.
- Retrieved web content is untrusted data and must never redefine agent policy.
- Search is keyless and uses DuckDuckGo HTML/Lite endpoints with resilient HTML parsing.
"""
from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from pydantic import BaseModel, Field

_MAX_RESULTS = 6
_FETCH_TIMEOUT = 15.0
_MAX_BYTES = 1_000_000
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_UA = "Mozilla/5.0 (compatible; SovereignAIWorkbench/1.0)"


class WebSearchInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=400, description="Search query")


class WebSearchOutput(BaseModel):
    results: list[dict[str, Any]] = []
    engine: str = "duckduckgo"
    error: str | None = None


def _assert_public_host(host: str) -> None:
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


def _clean_text(value: str) -> str:
    value = html_lib.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _normalize_result_url(href: str) -> str | None:
    href = html_lib.unescape(href).strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/") or "uddg" in parse_qs(parsed.query):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            href = unquote(target)
    if href.startswith("/l/"):
        match = re.search(r"[?&]uddg=([^&]+)", href)
        if match:
            href = unquote(match.group(1))
    if not href.startswith(("http://", "https://")):
        return None
    return href[:500]


class _SearchLinkParser(HTMLParser):
    """Parse DDG result links without depending on attribute order/quote style."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href: str | None = None
        self._capture = False
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        classes = attrs_dict.get("class", "").split()
        if "result__a" in classes or "result-link" in classes:
            self._href = attrs_dict.get("href")
            self._capture = bool(self._href)
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._capture:
            return
        href = _normalize_result_url(self._href or "")
        title = _clean_text(" ".join(self._text))
        if href and title:
            self.results.append({"title": title[:200], "url": href})
        self._href = None
        self._capture = False
        self._text = []


def _parse_search_html(body: str) -> list[dict[str, str]]:
    parser = _SearchLinkParser()
    try:
        parser.feed(body)
    except Exception:
        return []
    # Fallback for markup where DDG keeps result links but changes class names.
    if not parser.results:
        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.I | re.S
        ):
            href = _normalize_result_url(match.group(1))
            title = _clean_text(re.sub(r"<[^>]+>", " ", match.group(2)))
            if href and title and len(title) > 2:
                parser.results.append({"title": title[:200], "url": href})
                if len(parser.results) >= _MAX_RESULTS:
                    break
    return parser.results[:_MAX_RESULTS]


async def _search_endpoint(client: httpx.AsyncClient, endpoint: str, query: str) -> tuple[list[dict[str, str]], str | None]:
    try:
        response = await client.get(endpoint, params={"q": query})
        response.raise_for_status()
        results = _parse_search_html(response.text)
        return results, None if results else "No results parsed"
    except httpx.TimeoutException:
        return [], "Search timed out"
    except httpx.HTTPStatusError as exc:
        return [], f"Search HTTP error: {exc.response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return [], f"Search failed: {type(exc).__name__}"


async def web_search_execute(data: WebSearchInput, context: dict) -> dict:
    """Search the public web with resilient DDG HTML parsing and Lite fallback."""
    endpoints = (
        "https://html.duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
    )
    errors: list[str] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"},
        timeout=12.0,
        follow_redirects=True,
    ) as client:
        for endpoint in endpoints:
            results, error = await _search_endpoint(client, endpoint, data.query)
            if results:
                return {"results": results, "engine": "duckduckgo", "error": None}
            if error:
                errors.append(error)

    return {
        "results": [],
        "engine": "duckduckgo",
        "error": "; ".join(errors) or "No search results available",
    }


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
        return {"url": data.url, "status": None, "content": "", "truncated": False, "error": "Only http(s) URLs are allowed"}
    try:
        _assert_public_host(parsed.hostname)
    except ValueError as exc:
        return {"url": data.url, "status": None, "content": "", "truncated": False, "error": f"Blocked: {exc}"}

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA}, timeout=_FETCH_TIMEOUT,
            follow_redirects=True, max_redirects=5,
        ) as client:
            resp = await client.get(data.url)
        ctype = resp.headers.get("content-type", "")
        if ctype and not ctype.split(";")[0].strip().startswith("text/"):
            return {"url": data.url, "status": resp.status_code, "content": "", "truncated": False, "error": f"Unsupported content-type: {ctype.split(';')[0]}"}
        body = resp.content[:_MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
    except httpx.TimeoutException:
        return {"url": data.url, "status": None, "content": "", "truncated": False, "error": "Fetch timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"url": data.url, "status": None, "content": "", "truncated": False, "error": f"Fetch failed: {type(exc).__name__}"}

    text = _WS.sub("\n\n", _TAG_ANY.sub("", _TAG_SCRIPT.sub("", body))).strip()
    truncated = len(text) > data.max_chars
    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "content": text[: data.max_chars],
        "truncated": truncated,
        "error": None,
    }
