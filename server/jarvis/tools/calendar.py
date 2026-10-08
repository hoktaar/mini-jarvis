"""Kalender über CalDAV (z. B. Nextcloud, Radicale, iCloud): Termine lesen und anlegen."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from jarvis.config import CalendarCfg
from jarvis.tools.registry import Tool, ToolContext, ToolResult

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


class CalendarService:
    def __init__(self, cfg: CalendarCfg, password: str, timezone: str):
        self.cfg = cfg
        self.password = password
        self.tz = ZoneInfo(timezone)
        self._client = None

    def _calendars(self):
        import caldav

        if self._client is None:
            self._client = caldav.DAVClient(url=self.cfg.url, username=self.cfg.username or None,
                                            password=self.password or None, ssl_verify_cert=self.cfg.verify_tls,
                                            require_tls=False, timeout=15)
        cals = self._client.principal().calendars()
        if self.cfg.calendars:
            wanted = {c.lower() for c in self.cfg.calendars}
            cals = [c for c in cals if (c.name or "").lower() in wanted]
        return cals

    def _events_sync(self, start: datetime, end: datetime) -> list[dict]:
        out: list[dict] = []
        for cal in self._calendars():
            for ev in cal.search(start=start, end=end, event=True, expand=True):
                comp = ev.icalendar_component
                dtstart = comp.get("dtstart").dt if comp.get("dtstart") else None
                if dtstart is None:
                    continue
                all_day = not isinstance(dtstart, datetime)
                if all_day:
                    begin = datetime.combine(dtstart, datetime.min.time(), self.tz)
                else:
                    begin = dtstart if dtstart.tzinfo else dtstart.replace(tzinfo=self.tz)
                out.append({"summary": str(comp.get("summary", "Termin")), "start": begin.astimezone(self.tz),
                            "all_day": all_day, "calendar": cal.name or "",
                            "location": str(comp.get("location", "") or "")})
        return sorted(out, key=lambda e: (not e["all_day"], e["start"]))

    async def events(self, day: date) -> list[dict]:
        start = datetime.combine(day, datetime.min.time(), self.tz)
        return await asyncio.to_thread(self._events_sync, start, start + timedelta(days=1))

    def _add_sync(self, title: str, start: datetime, minutes: int) -> str:
        cals = self._calendars()
        if not cals:
            raise RuntimeError("Kein Kalender gefunden")
        cal = next((c for c in cals if (c.name or "").lower() == self.cfg.default_calendar.lower()), cals[0])
        cal.save_event(dtstart=start, dtend=start + timedelta(minutes=minutes), summary=title)
        return cal.name or ""

    async def add(self, title: str, start: datetime, minutes: int = 60) -> str:
        return await asyncio.to_thread(self._add_sync, title, start, minutes)


def say_day(day: date, today: date) -> str:
    delta = (day - today).days
    return {0: "Heute", 1: "Morgen", 2: "Übermorgen"}.get(delta, f"Am {WEEKDAYS[day.weekday()]}")


def make_calendar_tools(service: CalendarService) -> list[Tool]:
    async def agenda(args: dict, ctx: ToolContext) -> ToolResult:
        try:
            offset = max(0, min(60, int(args.get("day_offset") or 0)))
        except (TypeError, ValueError):
            offset = 0
        today = datetime.now(service.tz).date()
        day = today + timedelta(days=offset)
        try:
            events = await service.events(day)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Kalender nicht erreichbar: {e}")
            return ToolResult(False, "Ich erreiche den Kalender gerade nicht.")
        when = say_day(day, today)
        if not events:
            return ToolResult(True, f"{when} stehen keine Termine im Kalender.")
        parts = []
        for e in events[:6]:
            parts.append(f"ganztägig {e['summary']}" if e["all_day"]
                         else f"um {e['start'].hour}:{e['start'].minute:02d} {e['summary']}")
        more = f", und {len(events) - 6} weitere" if len(events) > 6 else ""
        n = len(events)
        speech = f"{when} {'steht ein Termin' if n == 1 else f'stehen {n} Termine'} an: " + "; ".join(parts) + more + "."
        return ToolResult(True, speech, {"events": [{**e, "start": e["start"].isoformat()} for e in events]})

    async def add(args: dict, ctx: ToolContext) -> ToolResult:
        from jarvis.router.slots import parse_datetime

        title = str(args.get("title") or "").strip()
        raw = str(args.get("datetime") or "")
        try:
            start = datetime.fromisoformat(raw)
            start = start if start.tzinfo else start.replace(tzinfo=service.tz)
        except ValueError:
            start = parse_datetime(raw, datetime.now(service.tz), prefer="soonest")
        if not title or start is None:
            return ToolResult(False, "Ich brauche einen Titel und einen Zeitpunkt für den Termin.")
        minutes = int(args.get("duration_minutes") or 60)
        try:
            await service.add(title, start, minutes)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Termin anlegen fehlgeschlagen: {e}")
            return ToolResult(False, "Den Termin konnte ich nicht anlegen.")
        return ToolResult(True, f"Termin {title} am {start.day}.{start.month}. um {start.hour}:{start.minute:02d} "
                                f"eingetragen.")

    return [
        Tool("calendar_agenda", "Termine eines Tages aus dem Kalender vorlesen.",
             {"day_offset": {"type": "integer", "description": "0 = heute, 1 = morgen …"}}, [], agenda, risk="read"),
        Tool("calendar_add", "Einen Termin im Kalender anlegen.",
             {"title": {"type": "string"},
              "datetime": {"type": "string", "description": "Beginn als ISO 8601 (lokale Zeit) oder deutsch"},
              "duration_minutes": {"type": "integer"}},
             ["title", "datetime"], add, risk="write"),
    ]
