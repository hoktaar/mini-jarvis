"""MCP-Server (SearXNG, Home Assistant …) einmal pro Prozess verbinden und ihre Tools
als normale Jarvis-Tools registrieren – damit gelten Policy, Bestätigung, Taint,
Cloud-Sperre und Audit-Log auch für sie.

Sicherheit: Pro Server legt `tools:` fest, welche Tools überhaupt sichtbar sind
(z. B. nur `search_web`, nicht `fetch_url`, das beliebige interne Adressen abrufen könnte).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from jarvis.config import McpServerCfg
from jarvis.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult

# MCP-Server, die Jarvis selbst in-process abbildet (Policy!), nicht per MCPClient.
IN_PROCESS = {"docker"}
VALID_RISKS = {"read", "write", "critical"}
MAX_RESULT_CHARS = 6000


@dataclass
class McpStatus:
    name: str
    ok: bool = False
    tools: list[str] = field(default_factory=list)
    error: str = ""


def _server_params(m: McpServerCfg):
    if m.transport == "stdio":
        from mcp import StdioServerParameters

        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp"), **m.env}
        return StdioServerParameters(command=m.command, args=m.args, env=env)
    from mcp.client.session_group import SseServerParameters, StreamableHttpParameters

    headers = {k: v for k, v in m.headers.items() if v}
    if m.transport == "sse":
        return SseServerParameters(url=m.url, headers=headers or None)
    return StreamableHttpParameters(url=m.url, headers=headers or None)


class McpManager:
    def __init__(self, servers: list[McpServerCfg], registry: ToolRegistry):
        self.servers = [m for m in servers if m.enabled and m.name not in IN_PROCESS]
        self.registry = registry
        self.status: dict[str, McpStatus] = {m.name: McpStatus(m.name) for m in self.servers}
        self._clients: dict[str, Any] = {}
        self._tasks: list[asyncio.Task] = []
        self.on_change = None            # Callback, wenn neue Tools verfügbar sind

    def start(self) -> None:
        for m in self.servers:
            self._tasks.append(asyncio.create_task(self._connect_loop(m)))

    async def _connect_loop(self, m: McpServerCfg) -> None:
        delay = 5.0
        while True:
            try:
                await self._connect(m)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.status[m.name].error = str(e)[:200]
                logger.warning(f"MCP-Server {m.name} nicht verfügbar ({e}) – neuer Versuch in {delay:.0f} s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

    async def _connect(self, m: McpServerCfg) -> None:
        from pipecat.services.mcp_service import MCPClient

        client = MCPClient(_server_params(m), tools_filter=m.tools)
        schema = await client.tools()
        self._clients[m.name] = client
        names = []
        for fn in schema.standard_tools:
            if m.tools is not None and fn.name not in m.tools:
                continue
            risk = m.tool_risks.get(fn.name, m.risk)
            if risk not in VALID_RISKS:
                risk = "write"
            self.registry.add(Tool(fn.name, fn.description or fn.name, dict(fn.properties or {}),
                                   list(fn.required or []), self._handler(client, fn.name, m.taint),
                                   risk=risk, taint=m.taint, source=f"mcp:{m.name}"))
            names.append(fn.name)
        self.status[m.name] = McpStatus(m.name, True, names)
        logger.info(f"MCP-Server {m.name}: {len(names)} Tools ({', '.join(names)})")
        if self.on_change is not None:
            self.on_change()

    @staticmethod
    def _handler(client, name: str, taint: bool):
        async def handler(args: dict, ctx: ToolContext) -> ToolResult:
            # _call_tool_text liefert den Text oder eine Fehlermeldung (Pipecat 1.12, Version gepinnt).
            text = await client._call_tool_text(name, args)
            ok = not text.startswith("Error calling mcp tool")
            return ToolResult(ok, text[:MAX_RESULT_CHARS], {"text": text[:MAX_RESULT_CHARS]}, taint=taint)

        return handler

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
