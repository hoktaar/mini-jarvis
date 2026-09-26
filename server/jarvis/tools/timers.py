"""Timer, Wecker und Erinnerungen – persistent in SQLite, Scheduler im Core."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from jarvis.db import Database
from jarvis.tools.registry import Tool, ToolContext, ToolResult

Notify = Callable[[dict], Awaitable[None]]


def _say_duration(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} Stunde" + ("n" if h != 1 else ""))
    if m:
        parts.append(f"{m} Minute" + ("n" if m != 1 else ""))
    if s and not h:
        parts.append(f"{s} Sekunde" + ("n" if s != 1 else ""))
    return " und ".join(parts) or "0 Sekunden"


class TimerService:
    def __init__(self, db: Database, notify: Notify | None = None, tick: float = 1.0):
        self.db = db
        self.notify = notify
        self.tick = tick
        self._task: asyncio.Task | None = None

    def add(self, kind: str, due: float, label: str = "", device_id: int | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO timers (kind, label, due, device_id, created) VALUES (?,?,?,?,?)",
            (kind, label, due, device_id, time.time()),
        )
        return cur.lastrowid

    def active(self, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM timers WHERE fired=0"
        params: tuple = ()
        if kind:
            sql += " AND kind=?"
            params = (kind,)
        return [dict(r) for r in self.db.query(sql + " ORDER BY due", params)]

    def cancel(self, timer_id: int | None = None, kind: str = "timer") -> int:
        if timer_id is not None:
            return self.db.execute("UPDATE timers SET fired=2 WHERE id=? AND fired=0", (timer_id,)).rowcount
        # ohne ID: den nächsten fälligen dieses Typs
        rows = self.active(kind)
        if not rows:
            return 0
        return self.db.execute("UPDATE timers SET fired=2 WHERE id=?", (rows[0]["id"],)).rowcount

    async def check_due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        due = [dict(r) for r in self.db.query("SELECT * FROM timers WHERE fired=0 AND due<=?", (now,))]
        for row in due:
            self.db.execute("UPDATE timers SET fired=1 WHERE id=?", (row["id"],))
            if self.notify:
                await self.notify(row)
        return due

    async def run(self) -> None:
        while True:
            await self.check_due()
            await asyncio.sleep(self.tick)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    # ---- Tools ----
    def tools(self) -> list[Tool]:
        async def set_timer(args: dict, ctx: ToolContext) -> ToolResult:
            seconds = int(args["duration"])
            label = args.get("label", "")
            tid = self.add("timer", time.time() + seconds, label, ctx.device_id)
            return ToolResult(True, f"Timer, {_say_duration(seconds)}.", {"id": tid})

        async def list_timers(args: dict, ctx: ToolContext) -> ToolResult:
            rows = self.active()
            if not rows:
                return ToolResult(True, "Es laufen keine Timer.")
            now = time.time()
            parts = [
                f"{r['label'] or r['kind']} noch {_say_duration(max(0, int(r['due'] - now)))}"
                for r in rows[:3]
            ]
            return ToolResult(True, "; ".join(parts) + ".", {"items": rows})

        async def cancel_timer(args: dict, ctx: ToolContext) -> ToolResult:
            n = self.cancel(args.get("id"))
            return ToolResult(bool(n), "Timer gelöscht." if n else "Es läuft kein Timer.")

        async def set_alarm(args: dict, ctx: ToolContext) -> ToolResult:
            when = args["datetime"]
            if isinstance(when, str):
                when = datetime.fromisoformat(when)
            tid = self.add("alarm", when.timestamp(), args.get("label", "Wecker"), ctx.device_id)
            return ToolResult(True, f"Wecker für {when.strftime('%d.%m. um %H:%M')} gestellt.", {"id": tid})

        async def set_reminder(args: dict, ctx: ToolContext) -> ToolResult:
            when = args["datetime"]
            if isinstance(when, str):
                when = datetime.fromisoformat(when)
            tid = self.add("reminder", when.timestamp(), args.get("text", ""), ctx.device_id)
            return ToolResult(True, f"Ich erinnere dich am {when.strftime('%d.%m. um %H:%M')}.", {"id": tid})

        dur = {"duration": {"type": "integer", "description": "Dauer in Sekunden"},
               "label": {"type": "string", "description": "optionale Bezeichnung"}}
        dt = {"datetime": {"type": "string", "description": "Zeitpunkt ISO 8601, lokale Zeit"}}
        return [
            Tool("set_timer", "Timer stellen.", dur, ["duration"], set_timer, risk="write"),
            Tool("list_timers", "Laufende Timer, Wecker und Erinnerungen auflisten.", {}, [], list_timers),
            Tool("cancel_timer", "Timer löschen (ohne ID: den nächsten).",
                 {"id": {"type": "integer"}}, [], cancel_timer, risk="write"),
            Tool("set_alarm", "Wecker stellen.", {**dt, "label": {"type": "string"}}, ["datetime"],
                 set_alarm, risk="write"),
            Tool("set_reminder", "Erinnerung mit Text anlegen.",
                 {**dt, "text": {"type": "string", "description": "Woran erinnern"}},
                 ["datetime", "text"], set_reminder, risk="write"),
        ]
