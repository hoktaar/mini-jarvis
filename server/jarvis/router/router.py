"""System-1-Router: entscheidet Schnellweg, Rückfrage, fokussiertes oder volles LLM.

Neu in 0.3: Dialogzustand für Rückfragen („Wie lange?“ → „fünf Minuten“), optionale
Slots, zeitzonenbewusste Zeitangaben und Korrektur-Beispiele aus der Verwaltung.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from pipecat.classifiers.base_classifier import BaseClassifier, ChoiceQuestion

from jarvis.config import RouterCfg
from jarvis.db import Database
from jarvis.router import slots as slotlib

ESCALATION_PHRASES = ("denk gründlich nach", "denk genau nach", "frag die cloud", "frag das große modell",
                      "denk mal gründlich", "frag claude")
FREE_TEXT_SLOTS = {"text", "memory"}


class Route(str, Enum):
    FAST = "fast"              # Tool direkt ausführen, Vorlagenantwort
    ASK_SLOT = "ask_slot"      # Rückfrage per Vorlage
    FOCUSED = "focused"        # LLM mit Top-3-Tools
    FULL = "full"              # LLM mit allen erlaubten Tools
    ESCALATE = "escalate"      # Cloud-LLM (falls konfiguriert)


@dataclass
class Intent:
    name: str
    tool: str | None
    risk: str = "read"
    fast: bool = False
    slots: list[str] = field(default_factory=list)        # Pflicht
    optional: list[str] = field(default_factory=list)     # werden mitgenommen, wenn vorhanden
    ask: str = ""
    asks: dict[str, str] = field(default_factory=dict)    # Rückfrage je fehlendem Slot
    args: dict[str, Any] = field(default_factory=dict)    # feste Argumente (z. B. kind: alarm)
    tools: list[str] = field(default_factory=list)        # weitere Tools für den fokussierten LLM-Weg
    prefer: str = "next"                                   # Zeitdeutung: next | soonest
    examples: list[str] = field(default_factory=list)

    def question_for(self, missing: list[str]) -> str:
        for slot in missing:
            if slot in self.asks:
                return self.asks[slot]
        return self.ask or "Kannst du das genauer sagen?"


@dataclass
class DialogState:
    """Offene Rückfrage: welche Absicht, was schon bekannt ist, was fehlt."""

    intent: str
    slots: dict[str, Any]
    missing: list[str]
    expires: float
    asked: int = 1


@dataclass
class Decision:
    route: Route
    intent: str
    confidence: float
    slots: dict[str, Any] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)   # Tools für FOCUSED
    ask: str = ""
    dialog: DialogState | None = None
    latency_ms: float = 0.0


def load_intents(data: dict) -> dict[str, Intent]:
    out: dict[str, Intent] = {}
    for name, spec in (data.get("intents") or {}).items():
        spec = dict(spec or {})
        out[name] = Intent(name=name, **{k: v for k, v in spec.items() if k in Intent.__dataclass_fields__
                                         and k != "name"})
    return out


class Router:
    def __init__(
        self,
        intents: dict[str, Intent],
        classifier: BaseClassifier,
        cfg: RouterCfg,
        db: Database | None = None,
        known_names: list[str] | None = None,
        timezone: str = "Europe/Berlin",
        scripts: list[str] | None = None,
        log_text: bool = True,
    ):
        self.intents = intents
        self.classifier = classifier
        self.cfg = cfg
        self.db = db
        self.known_names = known_names or []
        self.scripts = scripts or []
        self.tz = ZoneInfo(timezone)
        self.log_text = log_text
        self._question = ChoiceQuestion(
            instructions="Welche Absicht hat der Satz an einen Sprachassistenten?",
            options={name: (i.examples[0] if i.examples else name) for name, i in intents.items()},
        )

    # ---- Beispiele (Korrekturen aus der Verwaltung) ----
    def examples(self, extra: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
        merged = {n: list(i.examples) for n, i in self.intents.items()}
        for intent, texts in (extra or {}).items():
            if intent in merged:
                merged[intent] += [t for t in texts if t not in merged[intent]]
        return merged

    def retrain(self, extra: dict[str, list[str]]) -> None:
        if hasattr(self.classifier, "set_examples"):
            self.classifier.set_examples(self.examples(extra))

    # ---- Slots ----
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _thresholds(self, intent: str) -> tuple[float, float]:
        t = self.cfg.per_intent.get(intent, self.cfg.thresholds)
        return t.fast, t.focused

    def extract_slot(self, intent: Intent, slot: str, text: str, followup: bool = False) -> Any:
        now = self.now()
        if slot == "duration":
            return slotlib.parse_duration(text)
        if slot == "datetime":
            return slotlib.parse_datetime(text, now, prefer=intent.prefer)
        if slot == "day_offset":
            return slotlib.parse_day_offset(text, now)
        if slot == "place":
            return slotlib.parse_place(text)
        if slot == "name":
            return slotlib.match_name(text, self.known_names)
        if slot == "action":
            return slotlib.parse_action(text)
        if slot == "script_id":
            return match_script(text, self.scripts)
        if slot == "label":
            return slotlib.extract_timer_label(text)
        if slot == "volume":
            return slotlib.parse_volume(text)
        if slot == "enabled":
            return slotlib.parse_toggle(text)
        if slot == "text":
            value = slotlib.extract_reminder_text(text)
            if value is None and followup:
                value = text.strip(" .!?") or None
            return value
        if slot == "memory":
            value = slotlib.extract_memory_text(text)
            if value is None and followup:
                value = text.strip(" .!?") or None
            return value
        return None

    def _extract(self, intent: Intent, text: str, only: list[str] | None = None,
                 followup: bool = False) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for slot in only if only is not None else intent.slots + intent.optional:
            value = self.extract_slot(intent, slot, text, followup)
            if value is not None:
                found[slot] = value
        return found

    # ---- Entscheidung ----
    async def decide(self, text: str, dialog: DialogState | None = None, device_id: int | None = None) -> Decision:
        start = time.perf_counter()
        decision = await self._decide(text, dialog)
        decision.latency_ms = (time.perf_counter() - start) * 1000
        self._log(text, decision, device_id)
        return decision

    async def _decide(self, text: str, dialog: DialogState | None) -> Decision:
        lowered = text.lower()
        if any(p in lowered for p in ESCALATION_PHRASES):
            return Decision(Route.ESCALATE, "chat", 1.0)

        if dialog is not None and dialog.expires > time.time() and dialog.intent in self.intents:
            intent = self.intents[dialog.intent]
            found = self._extract(intent, text, only=dialog.missing, followup=True)
            slots = {**dialog.slots, **found}
            missing = [s for s in intent.slots if s not in slots]
            if not missing:
                return Decision(Route.FAST, intent.name, 1.0, slots)
            if found:
                return self._ask(intent, 1.0, slots, missing)
            # Nichts Passendes – vielleicht ein ganz neues Anliegen?
            other = await self._classify(text)
            if other[0] != intent.name and other[1] >= self._thresholds(other[0])[1]:
                return await self._route(text, *other)
            if dialog.asked < 2:
                d = self._ask(intent, 1.0, dialog.slots, dialog.missing)
                d.dialog.asked = dialog.asked + 1
                return d
            return Decision(Route.FULL, intent.name, other[1])

        return await self._route(text, *(await self._classify(text)))

    async def _classify(self, text: str) -> tuple[str, float, list[str]]:
        result = (await self.classifier.choice(text, {"intent": self._question}))["intent"]
        ranked = sorted(result.probabilities, key=result.probabilities.get, reverse=True)
        return result.choice, result.confidence, ranked

    def _ask(self, intent: Intent, confidence: float, slots: dict, missing: list[str]) -> Decision:
        state = DialogState(intent.name, dict(slots), list(missing), time.time() + self.cfg.dialog_timeout)
        return Decision(Route.ASK_SLOT, intent.name, confidence, dict(slots), ask=intent.question_for(missing),
                        dialog=state)

    async def _route(self, text: str, name: str, confidence: float, ranked: list[str]) -> Decision:
        intent = self.intents[name]
        fast_t, focused_t = self._thresholds(name)
        candidates: list[str] = []
        for n in ranked[:3]:
            i = self.intents[n]
            candidates += ([i.tool] if i.tool else []) + list(i.tools)

        if intent.tool is None and not intent.tools:
            return Decision(Route.FULL, name, confidence)
        if intent.fast and intent.tool and intent.slots and fast_t > confidence >= max(focused_t, fast_t - self.cfg.slot_boost):
            # Der Slot-Parser bestätigt die Absicht (z. B. „Timer“ + erkannte Dauer) → Schnellweg.
            found = self._extract(intent, text)
            if all(s in found for s in intent.slots):
                return Decision(Route.FAST, name, confidence, found)
        if confidence >= fast_t and intent.fast and intent.tool:
            found = self._extract(intent, text)
            missing = [s for s in intent.slots if s not in found]
            if missing:
                return self._ask(intent, confidence, found, missing)
            return Decision(Route.FAST, name, confidence, found)
        if confidence >= focused_t:
            return Decision(Route.FOCUSED, name, confidence, candidates=candidates)
        return Decision(Route.FULL, name, confidence)

    def _log(self, text: str, d: Decision, device_id: int | None) -> None:
        if self.db is not None:
            self.db.execute(
                "INSERT INTO router_log (ts, text, intent, confidence, route, device_id, latency_ms) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), text if self.log_text else "…", d.intent, d.confidence, d.route.value,
                 device_id, round(d.latency_ms, 1)),
            )


def match_script(text: str, script_ids: list[str]) -> str | None:
    """Skript-IDs mit Unterstrich auch gesprochen finden ('say hello' → 'say_hello')."""
    if not script_ids:
        return None
    plain = {sid.replace("_", "").replace("-", "").lower(): sid for sid in script_ids}
    hit = slotlib.match_name(text, list(plain))
    if hit:
        return plain[hit]
    lowered = text.lower()
    for sid in script_ids:
        if sid.replace("_", " ").lower() in lowered:
            return sid
    return None
