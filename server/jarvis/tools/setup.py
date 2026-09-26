"""Baut die Tool-Registry aus der Konfiguration."""

from __future__ import annotations

from jarvis.config import JarvisConfig
from jarvis.db import Database
from jarvis.mcp_servers import docker_mcp
from jarvis.runner.client import make_script_tool
from jarvis.runner.registry import ScriptSpec
from jarvis.tools.builtin import make_stop_tool, make_time_tool
from jarvis.tools.news import make_news_tool
from jarvis.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult
from jarvis.tools.timers import TimerService
from jarvis.tools.weather import make_weather_tool

RUNNER_SOCKET = "/run/jarvis/runner.sock"


def _docker_tools() -> list[Tool]:
    # Docker läuft in-process über dieselben Funktionen wie der MCP-Server,
    # damit die Jarvis-Policy (Bestätigung, Taint, Cloud-Sperre) sicher greift.
    async def status(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(True, await docker_mcp.container_status_impl(args.get("name", "")))

    async def action(args: dict, ctx: ToolContext) -> ToolResult:
        text = await docker_mcp.container_action_impl(args["name"], args["action"])
        return ToolResult(text.endswith("ausgeführt."), text)

    return [
        Tool("container_status", "Status freigegebener Container (leer = alle).",
             {"name": {"type": "string"}}, [], status, risk="read"),
        Tool("container_action", "Container starten, stoppen oder neu starten.",
             {"name": {"type": "string"}, "action": {"type": "string", "enum": ["start", "stop", "restart"]}},
             ["name", "action"], action, risk="critical"),
    ]


def build_registry(cfg: JarvisConfig, db: Database, timers: TimerService,
                   scripts: dict[str, ScriptSpec]) -> ToolRegistry:
    reg = ToolRegistry()
    reg.add(make_time_tool(cfg.location.timezone))
    reg.add(make_stop_tool())
    for t in timers.tools():
        reg.add(t)
    reg.add(make_weather_tool(cfg.location))
    if cfg.news.feeds:
        reg.add(make_news_tool(cfg.news))
    if any(s.name == "docker" and s.enabled for s in cfg.mcp_servers):
        for t in _docker_tools():
            reg.add(t)
    if scripts:
        reg.add(make_script_tool(RUNNER_SOCKET, db, {k: v.description for k, v in scripts.items()}))
    return reg
