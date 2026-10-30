"""Tavily web search, used to ground worker B's part of a task in current
web facts. The HTTP call uses httpx (already pulled in by the OpenAI SDK
dependency): an earlier stdlib-urllib version had its response stream
truncated by a proxy in deployment, so the transport was swapped and a
single retry added; the request and response shapes are unchanged.
If no TAVILY_API_KEY is configured, ProofCrew never constructs this
client, worker B runs ungrounded, and the receipts say so."""
from __future__ import annotations

import httpx

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyClient:
    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                resp = httpx.post(
                    TAVILY_SEARCH_URL, json=payload, timeout=self._timeout
                )
                resp.raise_for_status()
                return resp.json().get("results", [])
            except httpx.TransportError as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]


def format_results(results: list[dict]) -> str:
    lines = []
    for r in results:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip()
        lines.append(f"- {title} ({url})\n  {content}")
    return "\n".join(lines)
