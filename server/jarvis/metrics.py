"""Latenzen pro Stufe sammeln (STT, Router, LLM, TTS, gesamt) – für die Verwaltung."""

from __future__ import annotations

import statistics
import time
from collections import defaultdict, deque


class Metrics:
    def __init__(self, size: int = 300):
        self._values: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=size))
        self.counters: dict[str, int] = defaultdict(int)
        self.started = time.time()

    def add(self, name: str, ms: float) -> None:
        if ms >= 0:
            self._values[name].append(ms)

    def count(self, name: str, n: int = 1) -> None:
        self.counters[name] += n

    def summary(self) -> dict:
        out = {}
        for name, values in self._values.items():
            data = sorted(values)
            if not data:
                continue
            out[name] = {
                "n": len(data),
                "p50": round(statistics.median(data)),
                "p90": round(data[min(len(data) - 1, int(len(data) * 0.9))]),
                "last": round(values[-1]),
            }
        return {"latency_ms": out, "counters": dict(self.counters), "uptime_s": int(time.time() - self.started)}
