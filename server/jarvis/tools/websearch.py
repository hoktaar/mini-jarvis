"""Websuche über Cloud-Anbieter (Brave Search, Tavily) – Alternative zum lokalen SearXNG.

Die Ergebnisse sind fremde Inhalte (taint) und das Tool ist im Privatmodus gesperrt.
"""

from __future__ import annotations

import httpx

from jarvis.config import SearchCfg
from jarvis.tools.registry import Tool, ToolContext, ToolResult


async def _brave(query: str, key: str, n: int, news: bool) -> list[dict]:
    path = "news/search" if news else "web/search"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"https://api.search.brave.com/res/v1/{path}",
                        params={"q": query, "count": n, "country": "de", "search_lang": "de"},
                        headers={"X-Subscription-Token": key, "Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    items = data.get("results") if news else (data.get("web") or {}).get("results", [])
    return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("description", "")}
            for i in (items or [])[:n]]


async def _tavily(query: str, key: str, n: int, news: bool) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.tavily.com/search",
                         json={"query": query, "max_results": n, "topic": "news" if news else "general",
                               "search_depth": "basic"},
                         headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        data = r.json()
    return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": (i.get("content") or "")[:500]}
            for i in data.get("results", [])[:n]]


def make_search_tools(cfg: SearchCfg, key: str) -> list[Tool]:
    backend = _brave if cfg.provider == "brave" else _tavily

    def make(news: bool):
        async def handler(args: dict, ctx: ToolContext) -> ToolResult:
            query = str(args.get("query") or "").strip()
            if not query:
                return ToolResult(False, "Wonach soll ich suchen?")
            try:
                items = await backend(query, key, cfg.max_results, news)
            except Exception as e:  # noqa: BLE001
                return ToolResult(False, f"Die Websuche ist gerade nicht erreichbar ({type(e).__name__}).")
            if not items:
                return ToolResult(True, "Dazu habe ich nichts gefunden.", {"items": []}, taint=True)
            text = "\n".join(f"- {i['title']}: {i['snippet']} ({i['url']})" for i in items)
            return ToolResult(True, text, {"items": items, "text": text}, taint=True)

        return handler

    desc = f"Websuche über {cfg.provider.capitalize()}"
    return [
        Tool("search_web", f"{desc}: aktuelle Informationen aus dem Internet.",
             {"query": {"type": "string", "description": "Suchanfrage"}}, ["query"], make(False),
             risk="read", taint=True, source=f"search:{cfg.provider}", cloud=True),
        Tool("search_news", f"{desc}: aktuelle Nachrichten zu einem Thema.",
             {"query": {"type": "string", "description": "Thema"}}, ["query"], make(True),
             risk="read", taint=True, source=f"search:{cfg.provider}", cloud=True),
    ]
