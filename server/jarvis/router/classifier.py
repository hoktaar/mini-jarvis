"""Lokaler System-1-Klassifikator mit Pipecats BaseClassifier-Schnittstelle.

Dadurch ist er gegen ``JevClassifier`` (gehostet) oder ``LLMClassifier``
austauschbar, ohne dass sich der Router ändert.

Backends:
- ``sentence-transformers`` (Standard auf dem Server, CPU, wenige ms)
- Zeichen-Trigramme (Fallback ohne Modell, für Tests und Notbetrieb)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ChoiceQuestion,
    ChoiceResult,
    ClassifierError,
    ClassifierQuestion,
    YesNoQuestion,
    YesNoResult,
)

from jarvis.router.confirm import strict_yes_no


def _text(state: str | dict[str, Any] | list[Any]) -> str:
    return state if isinstance(state, str) else str(state)


class _TrigramEmbedder:
    # Ähnlichkeit unter `floor` gilt als fremd, ab `ref` als sicherer Treffer.
    floor, ref = 0.0, 0.6

    def encode(self, texts: list[str]) -> list[Counter]:
        out = []
        for t in texts:
            t = f"  {re.sub(r'[^a-zäöüß0-9 ]', '', t.lower())}  "
            out.append(Counter(t[i : i + 3] for i in range(len(t) - 2)))
        return out

    @staticmethod
    def similarity(a: Counter, b: Counter) -> float:
        dot = sum(a[k] * b.get(k, 0) for k in a)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0


class _SentenceEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # optional dependency

        self._model = SentenceTransformer(model_name, device="cpu")
        self._prefix = "query: " if "e5" in model_name else ""
        # e5-Modelle liefern auch für fremde Sätze hohe Kosinuswerte (~0,75) – Skala anpassen.
        self.floor, self.ref = (0.78, 0.9) if "e5" in model_name else (0.3, 0.75)

    def encode(self, texts: list[str]):
        return self._model.encode([self._prefix + t for t in texts], normalize_embeddings=True)

    @staticmethod
    def similarity(a, b) -> float:
        return float((a * b).sum())


class LocalExampleClassifier(BaseClassifier):
    """Klassifiziert per Ähnlichkeit zu Beispielsätzen je Option."""

    def __init__(
        self,
        examples: Mapping[str, list[str]],
        embedding_model: str | None = None,
        temperature: float | None = None,
        floor: float | None = None,
        ref: float | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._embedder: Any
        if embedding_model:
            try:
                self._embedder = _SentenceEmbedder(embedding_model)
                self._temperature = temperature or 0.05
            except Exception as e:  # noqa: BLE001 – Modell fehlt → Fallback
                from loguru import logger

                logger.warning(f"Embedding-Modell {embedding_model} nicht verfügbar ({e}) – Trigramm-Ersatz")
                self._embedder = _TrigramEmbedder()
                self._temperature = temperature or 0.08
        else:
            self._embedder = _TrigramEmbedder()
            self._temperature = temperature or 0.08
        self._floor = floor if floor is not None else self._embedder.floor
        self._ref = ref if ref is not None else self._embedder.ref
        self._examples: dict[str, list] = {}
        self.set_examples(examples)

    @property
    def model(self) -> str | None:
        return type(self._embedder).__name__

    def set_examples(self, examples: Mapping[str, list[str]]) -> None:
        """Beispiele (neu) setzen – z. B. nach Korrekturen in der Web-UI."""
        self._examples = {
            option: list(self._embedder.encode(list(texts)))
            for option, texts in examples.items()
            if texts
        }

    def _choice(self, text: str, q: ChoiceQuestion) -> ChoiceResult:
        vec = self._embedder.encode([text])[0]
        scores: dict[str, float] = {}
        for option, desc in q.options.items():
            refs = self._examples.get(option)
            if refs is None and desc:
                refs = list(self._embedder.encode([str(desc)]))
            if not refs:
                continue
            scores[option] = max(self._embedder.similarity(vec, r) for r in refs)
        if not scores:
            raise ClassifierError("Keine Beispiele für die Optionen vorhanden")
        m = max(scores.values())
        exp = {k: math.exp((v - m) / self._temperature) for k, v in scores.items()}
        total = sum(exp.values())
        probs = {k: v / total for k, v in exp.items()}
        best = max(probs, key=probs.get)
        # Konfidenz: Wahrscheinlichkeit gedämpft durch die absolute Ähnlichkeit,
        # damit völlig fremde Sätze nicht mit hoher Sicherheit zugeordnet werden.
        span = max(1e-6, self._ref - self._floor)
        confidence = probs[best] * max(0.0, min(1.0, (scores[best] - self._floor) / span))
        return ChoiceResult(choice=best, probabilities=probs, confidence=confidence)

    @staticmethod
    def _yes_no(text: str) -> YesNoResult:
        return YesNoResult(probability=strict_yes_no(text))

    async def _ask(self, state, questions: Mapping[str, ClassifierQuestion]):
        text = _text(state)
        results: dict[str, Any] = {}
        for name, q in questions.items():
            if isinstance(q, ChoiceQuestion):
                results[name] = self._choice(text, q)
            elif isinstance(q, YesNoQuestion):
                results[name] = self._yes_no(text)
            else:
                raise ClassifierError(f"Fragetyp nicht unterstützt: {type(q).__name__}")
        return results, None


def build_classifier(kind: str, examples: Mapping[str, list[str]], secrets: dict, embedding_model: str | None,
                     floor: float | None = None, ref: float | None = None):
    """Fabrik: local | jev."""
    if kind == "jev":
        from pipecat.classifiers.jev.classifier import JevClassifier

        return JevClassifier(api_key=secrets.get("typesafe_api_key"))
    return LocalExampleClassifier(examples, embedding_model=embedding_model, floor=floor, ref=ref)
