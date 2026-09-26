"""System-1-Router: entscheidet Schnellweg, Rückfrage, fokussiertes oder volles LLM."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pipecat.classifiers.base_classifier import BaseClassifier, ChoiceQuestion

from jarvis.config import RouterCfg
from jarvis.db import Database
from jarvis.router import slots as slotlib

ESCALATION_PHRASES = ("denk gründlich nach", "denk genau nach", "frag die cloud", "frag das große modell")


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
    slots: list[str] = field(default_factory=list)
    ask: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class Decision:
    route: Route
    intent: str
    confidence: float
    slots: dict[str, Any] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)   # Top-3 Tools für FOCUSED
    ask: str = ""


def load_intents(data: dict) -> dict[str, Intent]:
    return {
        name: Intent(name=name, **{k: v for k, v in spec.items() if k in Intent.__dataclass_fields__})
        for name, spec in (data.get("intents") or {}).items()
    }


class Router:
    def __init__(
        self,
        intents: dict[str, Intent],
        classifier: BaseClassifier,
        cfg: RouterCfg,
        db: Database | None = None,
        known_names: list[str] | None = None,
    ):
        self.intents = intents
        self.classifier = classifier
        self.cfg = cfg
        self.db = db
        self.known_names = known_names or []
        self._question = ChoiceQuestion(
            instructions="Welche Absicht hat der Satz an einen Sprachassistenten?",
            options={name: (i.examples[0] if i.examples else name) for name, i in intents.items()},
        )

    def _thresholds(self, intent: str) -> tuple[float, float]:
        t = self.cfg.per_intent.get(intent, self.cfg.thresholds)
        return t.fast, t.focused

    def _extract(self, intent: Intent, text: str) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for slot in intent.slots:
            if slot == "duration":
                value = slotlib.parse_duration(text)
            elif slot == "datetime":
                value = slotlib.parse_datetime(text)
            elif slot == "name":
                value = slotlib.match_name(text, self.known_names)
            elif slot == "action":
                value = slotlib.parse_action(text)
            else:
                value = None           # z. B. freier Text → LLM
            if value is not None:
                found[slot] = value
        return found

    async def decide(self, text: str) -> Decision:
        lowered = text.lower()
        if any(p in lowered for p in ESCALATION_PHRASES):
            decision = Decision(Route.ESCALATE, "chat", 1.0)
            self._log(text, decision)
            return decision

        result = (await self.classifier.choice(text, {"intent": self._question}))["intent"]
        intent = self.intents[result.choice]
        fast_t, focused_t = self._thresholds(intent.name)
        ranked = sorted(result.probabilities, key=result.probabilities.get, reverse=True)
        candidates = [self.intents[n].tool for n in ranked[:3] if self.intents[n].tool]

        if intent.name == "chat":
            decision = Decision(Route.FULL, intent.name, result.confidence)
        elif result.confidence >= fast_t and intent.fast and intent.tool:
            found = self._extract(intent, text)
            missing = [s for s in intent.slots if s not in found]
            if missing:
                decision = Decision(Route.ASK_SLOT, intent.name, result.confidence, found, ask=intent.ask)
            else:
                decision = Decision(Route.FAST, intent.name, result.confidence, found)
        elif result.confidence >= focused_t:
            decision = Decision(Route.FOCUSED, intent.name, result.confidence, candidates=candidates)
        else:
            decision = Decision(Route.FULL, intent.name, result.confidence)
        self._log(text, decision)
        return decision

    def _log(self, text: str, d: Decision) -> None:
        if self.db is not None:
            self.db.execute(
                "INSERT INTO router_log (ts, text, intent, confidence, route) VALUES (?,?,?,?,?)",
                (time.time(), text, d.intent, d.confidence, d.route.value),
            )
