"""Baut die Tool-Registry aus der Konfiguration."""

from __future__ import annotations

from loguru import logger

from jarvis.config import JarvisConfig, secret_name
from jarvis.db import Database
from jarvis.mcp_servers import docker_mcp
from jarvis.runner.client import make_script_tool
from jarvis.runner.registry import ScriptSpec
from jarvis.tools.builtin import make_session_tools, make_stop_tool, make_time_tool
from jarvis.tools.news import make_news_tool
from jarvis.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult
from jarvis.tools.timers import TimerService
from jarvis.tools.weather import make_weather_tool

RUNNER_SOCKET = "/run/jarvis/runner.sock"


def docker_enabled(cfg: JarvisConfig) -> bool:
    return any(s.name == "docker" and s.enabled for s in cfg.mcp_servers)


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
                   scripts: dict[str, ScriptSpec], memory=None, secrets: dict | None = None,
                   runner_socket: str = RUNNER_SOCKET) -> ToolRegistry:
    secrets = secrets or {}
    reg = ToolRegistry()
    reg.add(make_time_tool(cfg.location.timezone))
    reg.add(make_stop_tool())
    for t in make_session_tools():
        reg.add(t)
    for t in timers.tools():
        reg.add(t)
    reg.add(make_weather_tool(cfg.location))
    if cfg.news.feeds:
        reg.add(make_news_tool(cfg.news))
    if docker_enabled(cfg):
        for t in _docker_tools():
            reg.add(t)
    if scripts:
        reg.add(make_script_tool(runner_socket, db, {k: v.description for k, v in scripts.items()},
                                 {k: list(v.params) for k, v in scripts.items()}))
    if memory is not None and cfg.memory.enabled:
        from jarvis.tools.memory import make_memory_tools

        for t in make_memory_tools(memory):
            reg.add(t)
    if cfg.calendar.enabled and cfg.calendar.url:
        try:
            from jarvis.tools.calendar import CalendarService, make_calendar_tools

            service = CalendarService(cfg.calendar, secrets.get(cfg.calendar.password_secret, ""),
                                      cfg.location.timezone)
            reg.calendar = service
            for t in make_calendar_tools(service):
                reg.add(t)
        except ImportError:
            logger.warning("Kalender aktiviert, aber das Paket 'caldav' fehlt (pip install mini-jarvis[extras]).")
    if cfg.search.provider in ("brave", "tavily"):
        key = secrets.get(secret_name(cfg.search.provider, cfg.search.api_key_secret), "")
        if key:
            from jarvis.tools.websearch import make_search_tools

            for t in make_search_tools(cfg.search, key):
                reg.add(t)
    return reg
