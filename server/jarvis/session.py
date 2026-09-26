"""Geteilte Dienste (App-weit) und Sitzungszustand (pro Gerät/Verbindung)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from jarvis.config import JarvisConfig
from jarvis.db import Database
from jarvis.devices import Device, DeviceRegistry
from jarvis.router.router import Router
from jarvis.runner.registry import ScriptSpec
from jarvis.security.policy import Policy, ScriptMeta, TurnState, Verdict
from jarvis.tools.registry import ToolContext, ToolRegistry, ToolResult
from jarvis.tools.timers import TimerService


@dataclass
class Services:
    cfg: JarvisConfig
    secrets: dict
    db: Database
    devices: DeviceRegistry
    registry: ToolRegistry
    policy: Policy
    router: Router | None
    classifier: Any
    timers: TimerService
    scripts: dict[str, ScriptSpec] = field(default_factory=dict)
    sessions: dict[int, "JarvisSession"] = field(default_factory=dict)


@dataclass
class Pending:
    tool: str
    args: dict
    question: str


class JarvisSession:
    def __init__(self, services: Services, device: Device):
        self.services = services
        self.cfg = services.cfg
        self.device = device
        self.router = services.router
        self.classifier = services.classifier
        self.turn = TurnState()
        self.pending: Pending | None = None
        self.tainted_tools: set[str] = {t.name for t in services.registry.all() if t.taint}
        self.local_llm = None
        self.cloud_llm = None
        self.switcher = None
        self.task = None                 # PipelineTask, für Alarme von außen
        self.extra_tools: list[tuple[Any, str]] = []   # (FunctionSchema, risk) aus MCP-Servern
        self.mcp_clients: list[Any] = []
        self.context = None              # LLMContext der Sitzung
        self.last_assistant_text = ""
        self.uses_rtvi = device.kind not in {"cyd", "esp32"}

    # ---- Zustand ----
    def new_turn(self) -> None:
        self.turn = TurnState()

    def ctx(self, provider: str = "local") -> ToolContext:
        return ToolContext(self.device.id, self.device.kind, self.device.kind == "android_auto", provider)

    # ---- Tool-Auswahl ----
    def _with_extra(self, schema, provider: str, names: list[str] | None = None):
        allowed = self.services.policy.cloud_allowed_risks
        for fn, risk in self.extra_tools:
            if (provider == "local" or risk in allowed) and (names is None or fn.name in names):
                schema.standard_tools.append(fn)
        return schema

    def tools_for(self, provider: str):
        tools = self.services.policy.tools_for_provider(self.services.registry.all(), provider)
        schema = self.services.registry.to_tools_schema([t.name for t in tools])
        return self._with_extra(schema, provider)

    def default_tools(self):
        return self.tools_for("local")

    def focus_tools(self, names: list[str]):
        if not names:
            return self.default_tools()
        return self._with_extra(self.services.registry.to_tools_schema(names), "local", names)

    # ---- Ausführung mit Policy ----
    async def execute(self, name: str, args: dict, confirmed: bool = False, provider: str = "local") -> ToolResult:
        reg, policy = self.services.registry, self.services.policy
        tool = reg.get(name)
        if tool is None:
            return ToolResult(False, "Dieses Werkzeug kenne ich nicht.")
        script = None
        if name == "run_script":
            spec = self.services.scripts.get(args.get("script_id", ""))
            script = ScriptMeta(spec.confirm, spec.car_allowed) if spec else None
        if not confirmed:
            verdict = policy.check(tool, self.ctx(provider), self.turn, script)
            if verdict == Verdict.DENY:
                return ToolResult(False, "Das darf ich von hier aus nicht ausführen.")
            if verdict == Verdict.CONFIRM:
                question = self._describe(name, args)
                self.pending = Pending(name, args, question)
                return ToolResult(False, f"{question} Soll ich das tun?", {"needs_confirmation": True})
        try:
            result = await tool.handler(args, self.ctx(provider))
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Tool {name} fehlgeschlagen")
            return ToolResult(False, f"Das hat nicht geklappt: {e}")
        if result.taint:
            self.turn.tainted = True
        if tool.risk != "read":
            self.services.db.audit(f"device:{self.device.id}", name,
                                   json.dumps(args, ensure_ascii=False, default=str),
                                   "ok" if result.ok else "fehler")
        return result

    @staticmethod
    def _describe(name: str, args: dict) -> str:
        if name == "container_action":
            return f"Container {args.get('name')}: {args.get('action')}."
        if name == "run_script":
            return f"Skript {args.get('script_id')} ausführen."
        return f"Aktion {name}."

    @staticmethod
    def slots_to_args(tool: str | None, slots: dict) -> dict:
        args = dict(slots)
        if isinstance(args.get("datetime"), datetime):
            args["datetime"] = args["datetime"].isoformat()
        return args

    # ---- LLM-Funktionen registrieren (Policy greift auch hier) ----
    def register_functions(self, llm, provider: str) -> None:
        for tool in self.services.registry.all():
            async def handler(params, _name=tool.name):
                result = await self.execute(_name, dict(params.arguments or {}), provider=provider)
                await params.result_callback({"ok": result.ok, "speech": result.speech,
                                              "data": result.data if not result.taint else {"items": result.data.get("items")}})
            llm.register_function(tool.name, handler)
