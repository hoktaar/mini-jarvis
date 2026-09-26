"""Einfache lokale Tools: Uhrzeit, Stopp."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.tools.registry import Tool, ToolContext, ToolResult

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def make_time_tool(timezone: str) -> Tool:
    async def handler(args: dict, ctx: ToolContext) -> ToolResult:
        now = datetime.now(ZoneInfo(timezone))
        speech = (
            f"Es ist {now.hour} Uhr {now.minute:02d}, {WEEKDAYS[now.weekday()]}, "
            f"der {now.day}. {MONTHS[now.month - 1]}."
        )
        return ToolResult(True, speech, {"iso": now.isoformat()})

    return Tool("get_time", "Aktuelle Uhrzeit und Datum.", {}, [], handler, risk="read")


def make_stop_tool() -> Tool:
    async def handler(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(True, "", {"stop": True})

    return Tool("stop", "Laufende Ausgabe oder Alarm beenden.", {}, [], handler, risk="read")
