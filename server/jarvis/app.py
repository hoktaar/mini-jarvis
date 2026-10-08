"""Aufbau der geteilten Dienste und Hintergrundaufgaben."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from loguru import logger

from jarvis.budget import Budget
from jarvis.config import (
    CONFIG_DIR,
    DATA_DIR,
    config_warnings,
    ensure_config_dir,
    load_config,
    load_secrets,
    load_yaml,
)
from jarvis.db import Database
from jarvis.devices import DeviceRegistry
from jarvis.feed import Feed
from jarvis.firmware import FirmwareManager
from jarvis.gpu import GpuMonitor
from jarvis.mcp import McpManager
from jarvis.metrics import Metrics
from jarvis.notify import Notifier
from jarvis.router.classifier import build_classifier
from jarvis.router.router import Router, load_intents
from jarvis.runner.registry import load_registry
from jarvis.security.policy import Policy
from jarvis.session import Services
from jarvis.tools.memory import MemoryStore
from jarvis.tools.setup import RUNNER_SOCKET, build_registry, docker_enabled
from jarvis.tools.timers import KIND_NAMES, TimerService

ALARM_SPEECH = {
    "timer": lambda label: f"Dein {label}-Timer ist abgelaufen." if label else "Dein Timer ist abgelaufen.",
    "alarm": lambda label: f"Guten Morgen! Dein Wecker klingelt. {label}".strip() if label else
    "Guten Morgen! Dein Wecker klingelt.",
    "reminder": lambda label: f"Erinnerung: {label}" if label else "Erinnerung!",
}


def _whitelist_names(config_dir: Path) -> list[str]:
    return list((load_yaml("whitelist.yaml", config_dir).get("containers") or {}).keys())


def build_router(services: Services, config_dir: Path = CONFIG_DIR) -> Router | None:
    cfg = services.cfg
    intents = load_intents(load_yaml("intents.yaml", config_dir))
    if not intents:
        return None
    examples = {n: list(i.examples) for n, i in intents.items()}
    for intent, texts in services.extra_examples().items():
        if intent in examples:
            examples[intent] += texts
    classifier = build_classifier(cfg.providers.classifier.type, examples, services.secrets,
                                  cfg.router.embedding_model, cfg.router.similarity_floor, cfg.router.similarity_ref)
    services.classifier = classifier
    return Router(intents, classifier, cfg.router, services.db, known_names=_whitelist_names(config_dir),
                  timezone=cfg.location.timezone, scripts=list(services.scripts), log_text=cfg.privacy.log_text)


def build_services(config_dir: Path = CONFIG_DIR, data_dir: Path = DATA_DIR, db_path=None,
                   runner_socket: str = RUNNER_SOCKET) -> Services:
    try:
        ensure_config_dir(config_dir)
    except PermissionError:
        pass                      # Im Container erledigt das der Entrypoint als root.
    secrets = load_secrets(config_dir)
    cfg = load_config(config_dir, secrets)
    from jarvis.mcp_servers import docker_mcp

    docker_mcp.WHITELIST_FILE = Path(config_dir) / "whitelist.yaml"
    db = Database(db_path or data_dir / "jarvis.db")
    try:
        scripts = load_registry(load_yaml("scripts.yaml", config_dir))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Skripte nicht geladen: {e}")
        scripts = {}

    services_ref: dict = {}

    async def notify(row: dict) -> None:
        await deliver_alarm(services_ref["s"], row)

    async def changed() -> None:
        await services_ref["s"].broadcast_timers()

    memory = MemoryStore(db)
    timers = TimerService(db, notify, timezone=cfg.location.timezone, changed=changed)
    registry = build_registry(cfg, db, timers, scripts, memory, secrets, runner_socket)
    services = Services(
        cfg=cfg, secrets=secrets, db=db, devices=DeviceRegistry(db), registry=registry,
        policy=Policy(cfg.providers.llm.cloud.allowed_tool_risks), router=None,
        classifier=None, timers=timers, scripts=scripts,
    )
    services_ref["s"] = services
    services.router = build_router(services, config_dir)
    services.memory = memory
    services.budget = Budget(db, cfg.providers.llm.cloud, cfg.location.timezone)
    services.metrics = Metrics()
    services.notifier = Notifier(cfg.push.ntfy, secrets)
    services.gpu = GpuMonitor(cfg, docker_enabled(cfg))
    mcp_servers = [m for m in cfg.mcp_servers if not (m.name == "searxng" and cfg.search.provider != "searxng")]
    services.mcp = McpManager(mcp_servers, registry)
    services.firmware = FirmwareManager(Path(data_dir), cfg.firmware.auto_update)
    services.warnings = config_warnings(cfg, secrets)
    services.config_dir = config_dir
    services.calendar = registry.calendar
    services.feed = Feed()

    async def push_feed(item: dict) -> None:
        await services.broadcast({"type": "feed", "item": item}, screens_only=True)

    services.feed.on_add = push_feed
    from jarvis.homeassistant import HomeAssistant
    from jarvis.system_stats import SystemStats

    services.home = HomeAssistant(cfg.homeassistant, secrets.get(cfg.homeassistant.token_secret, ""))
    services.stats = SystemStats({"Daten": Path(data_dir), "Modelle": Path(os.environ.get("JARVIS_MODELS_DIR", "/models"))})
    services.mcp.on_change = lambda: services.feed.add("Werkzeuge verbunden (MCP)", "ok", "system")
    for w in services.warnings:
        logger.warning(f"Konfiguration: {w}")
    return services


async def deliver_alarm(services: Services, row: dict) -> None:
    """Abgelaufenen Timer/Wecker/Erinnerung zustellen: am Gerät, sonst überall – plus Push."""
    kind = row["kind"]
    label = row["label"] or ""
    speech = ALARM_SPEECH.get(kind, ALARM_SPEECH["timer"])(label)
    event = {"type": "alarm", "id": row["id"], "kind": kind, "label": label or KIND_NAMES.get(kind, kind),
             "text": speech, "due": row["due"]}
    target = services.sessions.get(row.get("device_id"))
    target_online = target is not None and target.online
    receivers = [target] if target_online else services.online()
    for s in receivers:
        await s.emit(event)
        await s.speak(speech)
    if services.feed is not None:
        services.feed.add(f"{KIND_NAMES.get(kind, kind)} {label or ''} ausgelöst".replace("  ", " "), "ok", "timer")
    if services.notifier is not None and services.notifier.wants(kind, target_online):
        title = {"timer": "Timer abgelaufen", "alarm": "Wecker", "reminder": "Erinnerung"}.get(kind, "Jarvis")
        await services.notifier.send(title, speech)
    logger.info(f"{KIND_NAMES.get(kind, kind)} {row['id']} ausgelöst → {len(receivers)} Gerät(e)")


async def _purge_loop(services: Services) -> None:
    while True:
        try:
            n = services.db.purge(services.cfg.privacy.retention_days)
            if n:
                logger.info(f"Datenschutz: {n} alte Protokolleinträge gelöscht")
        except Exception:  # noqa: BLE001
            logger.exception("Aufräumen fehlgeschlagen")
        await asyncio.sleep(6 * 3600)


async def start_background(services: Services) -> list[asyncio.Task]:
    from jarvis.adapters import start_adapters
    from jarvis.providers import preload
    from jarvis.textpipe import reap_idle

    services.timers.start()
    services.mcp.start()
    services.gpu.start()
    services.stats.start()
    services.feed.add(f"Jarvis gestartet – {len(services.warnings)} Hinweis(e)" if services.warnings
                      else "Jarvis gestartet – alle Systeme bereit", "warn" if services.warnings else "ok")
    tasks = [asyncio.create_task(_purge_loop(services)), asyncio.create_task(reap_idle(services))]
    tasks.append(asyncio.create_task(asyncio.to_thread(preload, services.cfg)))
    services.adapters = await start_adapters(services)
    services.started = time.time()
    return tasks


async def stop_background(services: Services, tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    await services.timers.stop()
    await services.stats.stop()
    for stop in getattr(services, "adapters", []) or []:
        try:
            await stop()
        except Exception:  # noqa: BLE001
            pass
    for s in list(services.sessions.values()):
        await s.disconnect(1001, "Server wird beendet")
    await services.mcp.close()
