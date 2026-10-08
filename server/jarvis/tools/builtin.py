"""Einfache lokale Tools: Uhrzeit, Hilfe und Sitzungsbefehle (Stopp, Privatmodus, Lautstärke …)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.tools.registry import Tool, ToolContext, ToolResult

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

HELP_TEXT = (
    "Ich kann Timer, Wecker und Erinnerungen stellen, das Wetter und die Nachrichten sagen, "
    "im Internet suchen, mir Dinge merken und Fragen beantworten. "
    "Auf Wunsch steuere ich freigegebene Container und Skripte – nach Rückfrage. "
    "Sag zum Beispiel: Timer fünf Minuten, oder: Wie wird das Wetter morgen?"
)


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
        if ctx.session is not None:
            await ctx.session.stop_output()
        return ToolResult(True, "", {"stop": True})

    return Tool("stop", "Laufende Ausgabe beenden und klingelnde Alarme ausschalten.", {}, [], handler, risk="read")


def make_session_tools() -> list[Tool]:
    async def help_(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(True, HELP_TEXT)

    async def repeat_last(args: dict, ctx: ToolContext) -> ToolResult:
        last = getattr(ctx.session, "previous_answer", "") if ctx.session else ""
        return ToolResult(bool(last), last or "Ich habe noch nichts gesagt.")

    async def reset(args: dict, ctx: ToolContext) -> ToolResult:
        if ctx.session is not None:
            ctx.session.reset_conversation()
        return ToolResult(True, "Alles klar, neues Thema.")

    async def private(args: dict, ctx: ToolContext) -> ToolResult:
        enabled = args.get("enabled")
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("1", "true", "an", "ein", "ja")
        if enabled is None:
            return ToolResult(False, "Soll ich den Privatmodus ein- oder ausschalten?")
        if ctx.session is not None:
            await ctx.session.set_private(bool(enabled))
        return ToolResult(True, "Privatmodus an. Ich verarbeite jetzt alles nur noch lokal." if enabled
                          else "Privatmodus aus.")

    async def volume(args: dict, ctx: ToolContext) -> ToolResult:
        value = args.get("volume")
        if ctx.session is None:
            return ToolResult(False, "Das geht nur auf einem Gerät mit Lautsprecher.")
        level = await ctx.session.set_volume(value)
        if level is None:
            return ToolResult(False, "Die Lautstärke stellst du hier am Gerät selbst ein.")
        return ToolResult(True, f"Lautstärke {level} Prozent.")

    return [
        Tool("help", "Erklärt, was Jarvis kann.", {}, [], help_, risk="read"),
        Tool("repeat_last", "Die letzte Antwort wiederholen.", {}, [], repeat_last, risk="read"),
        Tool("reset_conversation", "Gesprächsverlauf vergessen und neu anfangen.", {}, [], reset, risk="read"),
        Tool("set_private_mode", "Privatmodus ein/aus: keine Cloud-Dienste mehr für dieses Gerät.",
             {"enabled": {"type": "boolean"}}, ["enabled"], private, risk="write"),
        Tool("set_volume", "Lautstärke des Geräts ändern ('+', '-' oder 0–100).",
             {"volume": {"type": "string", "description": "'+', '-' oder Prozentwert"}}, ["volume"], volume,
             risk="read"),
    ]
