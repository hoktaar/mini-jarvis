"""Live-Datenfeed: was gerade im System passiert (für das Dashboard)."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class Feed:
    def __init__(self, size: int = 120):
        self.items: deque[dict] = deque(maxlen=size)
        self.on_add = None            # Callback: neues Ereignis an verbundene Dashboards

    def add(self, text: str, level: str = "ok", kind: str = "system") -> dict:
        item = {"ts": time.time(), "text": text[:160], "level": level, "kind": kind}
        self.items.append(item)
        if self.on_add is not None:
            try:
                asyncio.get_running_loop().create_task(self.on_add(item))
            except RuntimeError:
                pass                  # kein Event-Loop (Tests/CLI)
        return item

    def latest(self, n: int = 20) -> list[dict]:
        return list(self.items)[-n:][::-1]
