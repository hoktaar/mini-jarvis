"""Sicherheits-Policy: wer darf welches Tool wann ohne Rückfrage ausführen."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from jarvis.tools.registry import Tool, ToolContext


class Verdict(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass
class TurnState:
    """Zustand eines Gesprächsschritts (wird pro Nutzeräußerung zurückgesetzt)."""

    tainted: bool = False            # Web/RSS-Inhalte wurden gelesen
    private_mode: bool = False       # alles lokal erzwingen
    notes: list[str] = field(default_factory=list)


@dataclass
class ScriptMeta:
    confirm: bool = True
    car_allowed: bool = False


class Policy:
    def __init__(self, cloud_allowed_risks: list[str] | None = None):
        self.cloud_allowed_risks = set(cloud_allowed_risks or ["read", "write"])

    def tools_for_provider(self, tools: list[Tool], provider: str) -> list[Tool]:
        """Cloud-LLMs sehen standardmäßig keine kritischen Tools."""
        if provider == "local":
            return tools
        return [t for t in tools if t.risk in self.cloud_allowed_risks]

    def check(
        self,
        tool: Tool,
        ctx: ToolContext,
        turn: TurnState,
        script: ScriptMeta | None = None,
    ) -> Verdict:
        # Kritisches nie über die Cloud, außer ausdrücklich freigegeben.
        if ctx.provider != "local" and tool.risk not in self.cloud_allowed_risks:
            return Verdict.DENY
        if tool.risk == "read":
            return Verdict.ALLOW
        # Ab hier: schreibende oder kritische Aktion.
        if script is not None and ctx.in_car and not script.car_allowed:
            return Verdict.DENY
        if turn.tainted:
            return Verdict.CONFIRM      # Schutz gegen Prompt-Injection
        if tool.risk == "critical":
            if script is not None and not script.confirm:
                return Verdict.ALLOW
            return Verdict.CONFIRM
        return Verdict.ALLOW            # "write" wie Timer: harmlos
