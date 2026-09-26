"""Aufbau der geteilten Dienste beim Start."""

from __future__ import annotations

from loguru import logger
from pipecat.frames.frames import TTSSpeakFrame

from jarvis.config import CONFIG_DIR, DATA_DIR, ensure_config_dir, load_config, load_secrets, load_yaml
from jarvis.db import Database
from jarvis.devices import DeviceRegistry
from jarvis.router.classifier import build_classifier
from jarvis.router.router import Router, load_intents
from jarvis.runner.registry import load_registry
from jarvis.security.policy import Policy
from jarvis.session import Services
from jarvis.tools.setup import build_registry
from jarvis.tools.timers import TimerService

ALARM_TEXT = {"timer": "Dein Timer ist abgelaufen.", "alarm": "Guten Morgen, dein Wecker.",
              "reminder": "Erinnerung:"}


def build_services(config_dir=CONFIG_DIR, data_dir=DATA_DIR, db_path=None) -> Services:
    ensure_config_dir(config_dir)
    cfg = load_config(config_dir)
    secrets = load_secrets(config_dir)
    db = Database(db_path or data_dir / "jarvis.db")
    try:
        scripts = load_registry(load_yaml("scripts.yaml", config_dir))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Skripte nicht geladen: {e}")
        scripts = {}

    services_ref: dict = {}

    async def notify(row: dict) -> None:
        s = services_ref["s"]
        text = f"{ALARM_TEXT.get(row['kind'], '')} {row['label']}".strip()
        targets = [s.sessions[row["device_id"]]] if row.get("device_id") in s.sessions else list(s.sessions.values())
        for sess in targets:
            if sess.task is not None:
                from jarvis.processors import _msg

                await sess.task.queue_frames([
                    _msg(sess, type="alarm", id=row["id"], label=text),
                    TTSSpeakFrame(text),
                ])

    timers = TimerService(db, notify)
    registry = build_registry(cfg, db, timers, scripts)
    intents = load_intents(load_yaml("intents.yaml", config_dir))
    classifier = build_classifier(
        cfg.providers.classifier.type,
        {n: i.examples for n, i in intents.items()},
        secrets,
        cfg.router.embedding_model,
    )
    whitelist = list((load_yaml("whitelist.yaml", config_dir).get("containers") or {}).keys())
    router = Router(intents, classifier, cfg.router, db, known_names=whitelist) if intents else None
    services = Services(
        cfg=cfg, secrets=secrets, db=db, devices=DeviceRegistry(db), registry=registry,
        policy=Policy(cfg.providers.llm.cloud.allowed_tool_risks), router=router,
        classifier=classifier, timers=timers, scripts=scripts,
    )
    services_ref["s"] = services
    return services
