"""Nachrichten aus RSS-Feeds. Ergebnisse sind 'tainted' (fremder Inhalt)."""

from __future__ import annotations

import asyncio

import httpx

from jarvis.config import NewsCfg
from jarvis.tools.registry import Tool, ToolContext, ToolResult


def make_news_tool(cfg: NewsCfg) -> Tool:
    async def handler(args: dict, ctx: ToolContext) -> ToolResult:
        import feedparser

        items: list[dict] = []
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            responses = await asyncio.gather(
                *(client.get(f.url) for f in cfg.feeds), return_exceptions=True
            )
        for feed, resp in zip(cfg.feeds, responses, strict=True):
            if isinstance(resp, Exception):
                continue
            parsed = feedparser.parse(resp.text)
            for e in parsed.entries[: cfg.max_items]:
                items.append({"source": feed.name, "title": e.get("title", ""), "summary": e.get("summary", "")[:300]})
        if not items:
            return ToolResult(False, "Ich konnte gerade keine Nachrichten abrufen.")
        headlines = ". ".join(i["title"] for i in items[: cfg.max_items])
        return ToolResult(True, headlines, {"items": items}, taint=True)

    return Tool("get_news", "Aktuelle Schlagzeilen aus den konfigurierten Feeds.", {}, [], handler,
                risk="read", taint=True)
