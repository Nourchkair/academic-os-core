"""Credential-free web search for the assistant runtime.

Uses DuckDuckGo's HTML endpoint so a student does not need another API key.
Results are treated as untrusted external text: the runtime passes titles,
URLs, and snippets to the model, and the model must cite them rather than
following any instruction inside them.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html import unescape
from typing import Any, Callable

ENDPOINT = "https://html.duckduckgo.com/html/"
USER_AGENT = "AcademiaOS/1.0 (academic study assistant)"
MAX_RESULTS = 8
MAX_BODY_BYTES = 2 * 1024 * 1024

_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_SNIPPET = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


class WebSearchError(ValueError):
    """The search could not be completed safely."""


def _clean(value: str) -> str:
    return unescape(_TAGS.sub("", value)).strip()


def _target(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parts = urllib.parse.urlsplit(url)
    if parts.hostname and parts.hostname.endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        query = urllib.parse.parse_qs(parts.query)
        target = (query.get("uddg") or [""])[0]
        if target:
            return target
    return url


def parse_results(body: str, limit: int = 5) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    links = list(_RESULT.finditer(body))
    snippets = [_clean(match.group(1)) for match in _SNIPPET.finditer(body)]
    for index, match in enumerate(links[:max(1, min(limit, MAX_RESULTS))]):
        url = _target(unescape(match.group(1)))
        title = _clean(match.group(2))
        if not title or not url.startswith("http"):
            continue
        results.append({
            "title": title,
            "url": url,
            "snippet": snippets[index][:400] if index < len(snippets) else "",
        })
    return results


def _fetch(url: str, timeout: float, opener: Callable[..., Any]) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with opener(request, timeout=timeout) as response:
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise WebSearchError("the search response was too large")
    return body.decode("utf-8", errors="replace")


def search(query: str, limit: int = 5, *, timeout: float = 12.0, opener: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip():
        raise WebSearchError("a search query is required")
    if len(query) > 400:
        raise WebSearchError("the search query is too long")
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'q': query.strip()})}"
    try:
        body = _fetch(url, timeout, opener or urllib.request.urlopen)
    except WebSearchError:
        raise
    except Exception as exc:  # network errors, HTTP errors, TLS
        raise WebSearchError(f"the web search could not be reached: {exc}") from exc
    results = parse_results(body, limit)
    if not results:
        raise WebSearchError("no web results were returned")
    return results
