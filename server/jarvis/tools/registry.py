"""Zentrale Tool-Registry: Beschreibung, Risiko und Handler jedes Tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Risk = Literal["read", "write", "critical"]


@dataclass
class ToolContext:
    """Was ein Tool über den aktuellen Aufruf wissen darf."""

    device_id: int | None = None
    device_kind: str = "test"
    in_car: bool = False
    provider: str = "local"


@dataclass
class ToolResult:
    ok: bool
    speech: str                      # was Jarvis sagt
    data: dict[str, Any] = field(default_factory=dict)
    taint: bool = False              # Ergebnis enthält fremde Inhalte (Web, RSS)


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    handler: Handler
    risk: Risk = "read"
    taint: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_tools_schema(self, names: list[str] | None = None):
        """Pipecat-ToolsSchema für die angegebenen Tools (Standard: alle)."""
        from pipecat.adapters.schemas.function_schema import FunctionSchema
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        selected = [self._tools[n] for n in (names or self.names()) if n in self._tools]
        return ToolsSchema(
            standard_tools=[
                FunctionSchema(
                    name=t.name,
                    description=t.description,
                    properties=t.properties,
                    required=t.required,
                )
                for t in selected
            ]
        )
