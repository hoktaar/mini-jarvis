"""Router-Auswertung: Trefferquote, Verwechslungen, Schnellweg-Quote.

    python -m jarvis.router.eval                  # mit Konfiguration aus JARVIS_CONFIG_DIR
    python -m jarvis.router.eval --trigram        # ohne Embedding-Modell (wie in den Tests)

Ziel aus dem Plan: ≥ 90 % richtig. Korrekturen aus der Verwaltung fließen mit ein.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from jarvis.router.router import Route, Router

EVAL_FILE = Path(__file__).resolve().parents[1] / "data" / "router_eval.yaml"


@dataclass
class EvalReport:
    total: int = 0
    correct: int = 0
    fast: int = 0
    confusions: Counter = field(default_factory=Counter)
    per_intent: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    errors: list[tuple[str, str, str, float]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "total": self.total, "correct": self.correct, "accuracy": round(self.accuracy, 3),
            "fast_share": round(self.fast / self.total, 3) if self.total else 0.0,
            "per_intent": {k: {"correct": v[0], "total": v[1]} for k, v in sorted(self.per_intent.items())},
            "confusions": [{"expected": e, "got": g, "count": n} for (e, g), n in self.confusions.most_common(15)],
            "errors": [{"text": t, "expected": e, "got": g, "confidence": round(c, 2)} for t, e, g, c in self.errors],
        }


def load_cases(path: Path = EVAL_FILE) -> list[tuple[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [(text, intent) for intent, texts in (data.get("cases") or {}).items() for text in texts or []]


async def evaluate(router: Router, cases: list[tuple[str, str]]) -> EvalReport:
    report = EvalReport()
    db, router.db = router.db, None          # Auswertung nicht ins Router-Log schreiben
    try:
        for text, expected in cases:
            if expected not in router.intents:
                continue
            d = await router.decide(text)
            report.total += 1
            report.per_intent[expected][1] += 1
            if d.route == Route.FAST:
                report.fast += 1
            if d.intent == expected:
                report.correct += 1
                report.per_intent[expected][0] += 1
            else:
                report.confusions[(expected, d.intent)] += 1
                report.errors.append((text, expected, d.intent, d.confidence))
    finally:
        router.db = db
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigram", action="store_true", help="ohne Embedding-Modell auswerten")
    ap.add_argument("--file", default=str(EVAL_FILE))
    a = ap.parse_args()

    from jarvis.config import CONFIG_DIR, load_config, load_yaml
    from jarvis.router.classifier import LocalExampleClassifier
    from jarvis.router.router import load_intents

    cfg = load_config(CONFIG_DIR)
    intents = load_intents(load_yaml("intents.yaml", CONFIG_DIR))
    model = None if a.trigram else cfg.router.embedding_model
    clf = LocalExampleClassifier({n: i.examples for n, i in intents.items()}, embedding_model=model,
                                 floor=cfg.router.similarity_floor, ref=cfg.router.similarity_ref)
    router = Router(intents, clf, cfg.router, timezone=cfg.location.timezone)
    report = asyncio.run(evaluate(router, load_cases(Path(a.file))))
    print(f"Klassifikator: {clf.model}  Sätze: {report.total}")
    print(f"Trefferquote: {report.accuracy:.1%}   Schnellweg: {report.fast / max(1, report.total):.1%}")
    for text, exp, got, conf in report.errors:
        print(f"  ✗ {text!r}: erwartet {exp}, erkannt {got} ({conf:.2f})")


if __name__ == "__main__":
    main()
