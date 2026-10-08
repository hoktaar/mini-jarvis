"""Timer, Wecker und Erinnerungen – persistent in SQLite, Scheduler im Core.

Lebenszyklus: offen (fired=0) → klingelt (fired=1, acked=0) → quittiert (acked=1)
oder gelöscht (fired=2). Klingeln endet durch Quittung, „Stopp“, Schlummern oder
nach `ring_timeout` Sekunden automatisch.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from difflib import get_close_matches
from zoneinfo import ZoneInfo

from loguru import logger

from jarvis.db import Database
from jarvis.router.slots import parse_datetime
from jarvis.tools.registry import Tool, ToolContext, ToolResult

Notify = Callable[[dict], Awaitable[None]]
Changed = Callable[[], Awaitable[None]]

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
KIND_NAMES = {"timer": "Timer", "alarm": "Wecker", "reminder": "Erinnerung"}


def say_duration(seconds: int) -> str:
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} Stunde" + ("n" if h != 1 else ""))
    if m:
        parts.append(f"{m} Minute" + ("n" if m != 1 else ""))
    if s and not h:
        parts.append(f"{s} Sekunde" + ("n" if s != 1 else ""))
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " und " + parts[-1]
    return parts[0] if parts else "0 Sekunden"


_say_duration = say_duration      # alter Name


def say_when(when: datetime, now: datetime) -> str:
    """'heute um 7:30', 'morgen um 7:00', 'am Montag, 12.10., um 8:00'."""
    days = (when.date() - now.date()).days
    clock = f"{when.hour}:{when.minute:02d} Uhr"
    if days == 0:
        return f"heute um {clock}"
    if days == 1:
        return f"morgen um {clock}"
    if days == 2:
        return f"übermorgen um {clock}"
    if 0 < days < 7:
        return f"am {WEEKDAYS[when.weekday()]} um {clock}"
    return f"am {when.day}.{when.month}. um {clock}"


class TimerService:
    def __init__(self, db: Database, notify: Notify | None = None, tick: float = 1.0,
                 timezone: str = "Europe/Berlin", changed: Changed | None = None, ring_timeout: float = 600):
        self.db = db
        self.notify = notify
        self.changed = changed
        self.tick = tick
        self.tz = ZoneInfo(timezone)
        self.ring_timeout = ring_timeout
        self._task: asyncio.Task | None = None

    # ---- Daten ----
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def add(self, kind: str, due: float, label: str = "", device_id: int | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO timers (kind, label, due, device_id, created) VALUES (?,?,?,?,?)",
            (kind, label[:120], due, device_id, time.time()),
        )
        self._changed()
        return cur.lastrowid

    def get(self, timer_id: int) -> dict | None:
        rows = self.db.query("SELECT * FROM timers WHERE id=?", (timer_id,))
        return dict(rows[0]) if rows else None

    def active(self, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM timers WHERE fired=0"
        params: tuple = ()
        if kind:
            sql += " AND kind=?"
            params = (kind,)
        return [dict(r) for r in self.db.query(sql + " ORDER BY due", params)]

    def ringing(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM timers WHERE fired=1 AND acked=0 ORDER BY due")]

    def cancel(self, timer_id: int | None = None, kind: str = "timer", label: str | None = None) -> int:
        if timer_id is not None:
            n = self.db.execute("UPDATE timers SET fired=2 WHERE id=? AND fired=0", (timer_id,)).rowcount
        else:
            rows = self.active(kind)
            if label:
                labels = {r["label"].lower(): r for r in rows if r["label"]}
                hit = get_close_matches(label.lower(), list(labels), n=1, cutoff=0.6)
                rows = [labels[hit[0]]] if hit else []
            if not rows:
                return 0
            n = self.db.execute("UPDATE timers SET fired=2 WHERE id=?", (rows[0]["id"],)).rowcount
        if n:
            self._changed()
        return n

    def ack(self, timer_id: int | None = None) -> list[int]:
        """Klingeln beenden. Ohne ID: alle klingelnden."""
        rows = self.ringing() if timer_id is None else [r for r in self.ringing() if r["id"] == timer_id]
        for r in rows:
            self.db.execute("UPDATE timers SET acked=1 WHERE id=?", (r["id"],))
        return [r["id"] for r in rows]

    def snooze(self, timer_id: int, minutes: int = 5) -> int | None:
        row = self.get(timer_id)
        if row is None:
            return None
        self.ack(timer_id)
        return self.add(row["kind"], time.time() + minutes * 60, row["label"], row["device_id"])

    # ---- Scheduler ----
    def _changed(self) -> None:
        if self.changed is not None:
            try:
                asyncio.get_running_loop().create_task(self.changed())
            except RuntimeError:
                pass          # kein Event-Loop (Tests, CLI)

    async def check_due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        due = [dict(r) for r in self.db.query("SELECT * FROM timers WHERE fired=0 AND due<=?", (now,))]
        for row in due:
            self.db.execute("UPDATE timers SET fired=1 WHERE id=?", (row["id"],))
            if self.notify:
                try:
                    await self.notify(row)
                except Exception:  # noqa: BLE001 – ein kaputter Empfänger darf den Scheduler nicht stoppen
                    logger.exception(f"Benachrichtigung für Timer {row['id']} fehlgeschlagen")
        # Vergessene Alarme irgendwann still beenden
        stale = time.time() - self.ring_timeout
        self.db.execute("UPDATE timers SET acked=1 WHERE fired=1 AND acked=0 AND due<?", (stale,))
        if due:
            self._changed()
        return due

    async def run(self) -> None:
        while True:
            try:
                await self.check_due()
            except Exception:  # noqa: BLE001
                logger.exception("Timer-Scheduler: Fehler, versuche es weiter")
            await asyncio.sleep(self.tick)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    # ---- Darstellung ----
    def describe(self, row: dict, now: datetime | None = None) -> str:
        now = now or self.now()
        name = row["label"] or KIND_NAMES.get(row["kind"], row["kind"])
        due = datetime.fromtimestamp(row["due"], self.tz)
        if row["kind"] == "timer":
            return f"{name} noch {say_duration(int(row['due'] - now.timestamp()))}"
        if row["kind"] == "alarm":
            return f"Wecker {say_when(due, now)}"
        return f"Erinnerung {name} {say_when(due, now)}"

    def items(self) -> list[dict]:
        """Für Clients: laufende und klingelnde Einträge."""
        out = []
        for r in self.active() + self.ringing():
            out.append({"id": r["id"], "kind": r["kind"], "label": r["label"], "due": r["due"],
                        "device_id": r["device_id"], "ringing": bool(r["fired"] == 1)})
        return out

    def _parse_when(self, value) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=self.tz)
        if not value:
            return None
        text = str(value).strip()
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return when if when.tzinfo else when.replace(tzinfo=self.tz)
        except ValueError:
            return parse_datetime(text, self.now(), prefer="soonest")

    # ---- Tools ----
    def tools(self) -> list[Tool]:
        async def set_timer(args: dict, ctx: ToolContext) -> ToolResult:
            try:
                seconds = int(float(args["duration"]))
            except (KeyError, TypeError, ValueError):
                return ToolResult(False, "Wie lange soll der Timer laufen?")
            if not 1 <= seconds <= 24 * 3600:
                return ToolResult(False, "Timer gehen von einer Sekunde bis 24 Stunden.")
            label = str(args.get("label") or "")
            tid = self.add("timer", time.time() + seconds, label, ctx.device_id)
            name = f"{label}-Timer" if label else "Timer"
            return ToolResult(True, f"{name}, {say_duration(seconds)}.", {"id": tid})

        async def list_timers(args: dict, ctx: ToolContext) -> ToolResult:
            rows = self.active()
            if not rows:
                return ToolResult(True, "Es laufen keine Timer, Wecker oder Erinnerungen.")
            now = self.now()
            parts = [self.describe(r, now) for r in rows[:4]]
            more = f" und {len(rows) - 4} weitere" if len(rows) > 4 else ""
            return ToolResult(True, "; ".join(parts) + more + ".", {"items": rows})

        async def cancel_timer(args: dict, ctx: ToolContext) -> ToolResult:
            kind = args.get("kind") or "timer"
            ringing = [r for r in self.ringing() if r["kind"] == kind]
            if ringing and args.get("id") is None:
                for r in ringing:
                    self.ack(r["id"])
                return ToolResult(True, f"{KIND_NAMES.get(kind, 'Timer')} aus.", {"acked": [r["id"] for r in ringing]})
            n = self.cancel(args.get("id"), kind=kind, label=args.get("label"))
            name = KIND_NAMES.get(kind, "Timer")
            if n:
                return ToolResult(True, f"{name} gelöscht.")
            return ToolResult(False, "Es läuft kein Timer." if kind == "timer" else f"Es ist kein {name} gestellt.")

        async def set_alarm(args: dict, ctx: ToolContext) -> ToolResult:
            when = self._parse_when(args.get("datetime"))
            if when is None:
                return ToolResult(False, "Wann soll ich dich wecken?")
            if when.timestamp() <= time.time():
                return ToolResult(False, "Dieser Zeitpunkt liegt in der Vergangenheit.")
            tid = self.add("alarm", when.timestamp(), str(args.get("label") or ""), ctx.device_id)
            return ToolResult(True, f"Wecker für {say_when(when.astimezone(self.tz), self.now())} gestellt.",
                              {"id": tid})

        async def set_reminder(args: dict, ctx: ToolContext) -> ToolResult:
            when = self._parse_when(args.get("datetime"))
            text = str(args.get("text") or "").strip()
            if when is None:
                return ToolResult(False, "Wann soll ich dich erinnern?")
            if not text:
                return ToolResult(False, "Woran soll ich dich erinnern?")
            if when.timestamp() <= time.time():
                return ToolResult(False, "Dieser Zeitpunkt liegt in der Vergangenheit.")
            tid = self.add("reminder", when.timestamp(), text, ctx.device_id)
            return ToolResult(True, f"Ich erinnere dich {say_when(when.astimezone(self.tz), self.now())} "
                                    f"an: {text}.", {"id": tid})

        dur = {"duration": {"type": "integer", "description": "Dauer in Sekunden"},
               "label": {"type": "string", "description": "optionale Bezeichnung, z. B. Pizza"}}
        dt = {"datetime": {"type": "string",
                           "description": "Zeitpunkt als ISO 8601 in lokaler Zeit (z. B. 2026-10-09T07:00) "
                                          "oder deutsch ('morgen um 7')"}}
        return [
            Tool("set_timer", "Timer stellen.", dur, ["duration"], set_timer, risk="write"),
            Tool("list_timers", "Laufende Timer, Wecker und Erinnerungen auflisten.", {}, [], list_timers),
            Tool("cancel_timer", "Timer, Wecker oder Erinnerung löschen bzw. ausschalten (ohne ID: den nächsten).",
                 {"id": {"type": "integer"},
                  "kind": {"type": "string", "enum": ["timer", "alarm", "reminder"]},
                  "label": {"type": "string"}}, [], cancel_timer, risk="write"),
            Tool("set_alarm", "Wecker stellen.", {**dt, "label": {"type": "string"}}, ["datetime"],
                 set_alarm, risk="write"),
            Tool("set_reminder", "Erinnerung mit Text anlegen.",
                 {**dt, "text": {"type": "string", "description": "Woran erinnern"}},
                 ["datetime", "text"], set_reminder, risk="write"),
        ]
