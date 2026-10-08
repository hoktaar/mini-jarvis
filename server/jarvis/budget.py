"""Kosten der Cloud-LLMs erfassen und gegen Tages-/Monatsbudget prüfen."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.config import CloudLlmCfg
from jarvis.db import Database


class Budget:
    def __init__(self, db: Database, cfg: CloudLlmCfg, timezone: str = "Europe/Berlin"):
        self.db = db
        self.cfg = cfg
        self.tz = ZoneInfo(timezone)

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.cfg.price_input_eur_per_mtok
                + completion_tokens * self.cfg.price_output_eur_per_mtok) / 1_000_000

    def record(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        cost = self.cost(prompt_tokens, completion_tokens)
        self.db.execute(
            "INSERT INTO usage (ts, provider, model, prompt_tokens, completion_tokens, cost_eur) VALUES (?,?,?,?,?,?)",
            (time.time(), provider, model, prompt_tokens, completion_tokens, cost),
        )
        return cost

    def _since(self, start: datetime) -> float:
        rows = self.db.query("SELECT COALESCE(SUM(cost_eur), 0) AS s FROM usage WHERE ts >= ?", (start.timestamp(),))
        return float(rows[0]["s"])

    def spent_today(self) -> float:
        now = datetime.now(self.tz)
        return self._since(now.replace(hour=0, minute=0, second=0, microsecond=0))

    def spent_month(self) -> float:
        now = datetime.now(self.tz)
        return self._since(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))

    def allows(self) -> bool:
        return self.spent_today() < self.cfg.budget_eur_day and self.spent_month() < self.cfg.budget_eur_month

    def summary(self) -> dict:
        return {"today": round(self.spent_today(), 4), "month": round(self.spent_month(), 4),
                "limit_day": self.cfg.budget_eur_day, "limit_month": self.cfg.budget_eur_month,
                "allowed": self.allows()}
