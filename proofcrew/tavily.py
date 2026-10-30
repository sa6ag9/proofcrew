"""Tavily web search, called with only the standard library so the runtime
footprint stays tiny. Used to ground worker B's part of a task in current
web facts. If no TAVILY_API_KEY is configured, ProofCrew never constructs
this client, worker B runs ungrounded, and the receipts say so."""
from __future__ import annotations

import json
import urllib.request

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyClient:
    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        body = json.dumps(
            {
                "api_key": self._api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            TAVILY_SEARCH_URL,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", [])


def format_results(results: list[dict]) -> str:
    lines = []
    for r in results:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip()
        lines.append(f"- {title} ({url})\n  {content}")
    return "\n".join(lines)
