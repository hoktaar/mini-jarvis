"""Home Assistant über die REST-API: Zustände für die Smarthome-Kacheln und einfache Schalter.

Sprachsteuerung läuft über den MCP-Server von Home Assistant (siehe mcp_servers);
hier geht es nur um das Dashboard: konfigurierte Entitäten anzeigen und umschalten.
"""

from __future__ import annotations

import time

import httpx
from loguru import logger

from jarvis.config import HomeAssistantCfg

TOGGLE_DOMAINS = {"light", "switch", "fan", "input_boolean", "automation"}
ACTIVATE_DOMAINS = {"scene", "script"}
ICONS = {"light": "bulb", "switch": "power", "fan": "fan", "lock": "lock", "cover": "garage",
         "climate": "thermo", "sensor": "gauge", "binary_sensor": "dot", "camera": "camera",
         "media_player": "music", "scene": "film", "script": "play", "input_boolean": "power",
         "alarm_control_panel": "shield", "vacuum": "robot", "automation": "auto"}
STATE_DE = {"on": "an", "off": "aus", "locked": "verschlossen", "unlocked": "offen", "open": "offen",
            "closed": "geschlossen", "opening": "öffnet", "closing": "schließt", "playing": "spielt",
            "paused": "pausiert", "idle": "bereit", "unavailable": "nicht erreichbar", "unknown": "unbekannt",
            "heat": "heizt", "cool": "kühlt", "auto": "automatisch", "armed_away": "scharf",
            "disarmed": "unscharf", "home": "zuhause", "not_home": "weg", "docked": "angedockt",
            "cleaning": "saugt"}
# Seiten auf dem CYD: „Licht“ und „Musik“
GROUPS = {"light": {"light", "switch", "fan", "input_boolean", "scene", "script"}, "media": {"media_player"}}
MEDIA_ACTIONS = {"play_pause": "media_play_pause", "next": "media_next_track", "previous": "media_previous_track",
                 "volume_up": "volume_up", "volume_down": "volume_down"}


class HomeAssistant:
    def __init__(self, cfg: HomeAssistantCfg, token: str):
        self.cfg = cfg
        self.token = token
        self._cache: tuple[float, list[dict]] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.url and self.token)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.cfg.url.rstrip("/"), timeout=6, verify=self.cfg.verify_tls,
                                 headers={"Authorization": f"Bearer {self.token}"})

    @staticmethod
    def tile(state: dict) -> dict:
        entity = state["entity_id"]
        domain = entity.split(".", 1)[0]
        attrs = state.get("attributes", {})
        value = state.get("state", "unknown")
        unit = attrs.get("unit_of_measurement", "")
        if domain == "climate" and attrs.get("current_temperature") is not None:
            display = f"{attrs['current_temperature']}°"
        elif domain in ACTIVATE_DOMAINS:
            display = "Szene starten" if domain == "scene" else "Skript starten"
        elif domain == "sensor":
            display = f"{value}{unit if unit in ('°C', '°F', '%') else ' ' + unit if unit else ''}".strip()
        else:
            display = STATE_DE.get(value, value)
        if domain == "media_player" and value == "playing" and attrs.get("media_title"):
            artist = attrs.get("media_artist")
            display = f"{artist} – {attrs['media_title']}" if artist else attrs["media_title"]
        return {"entity_id": entity, "name": attrs.get("friendly_name", entity), "domain": domain,
                "state": value, "display": display, "icon": ICONS.get(domain, "dot"),
                "on": value in ("on", "open", "unlocked", "playing", "heat", "cool"),
                "toggle": domain in TOGGLE_DOMAINS or domain == "media_player", "activate": domain in ACTIVATE_DOMAINS,
                "available": value not in ("unavailable", "unknown")}

    async def tiles(self, max_age: float = 5.0) -> list[dict]:
        if not self.configured:
            return []
        if self._cache and time.time() - self._cache[0] < max_age:
            return self._cache[1]
        async with self._client() as c:
            r = await c.get("/api/states")
            r.raise_for_status()
            states = {s["entity_id"]: s for s in r.json()}
        tiles = [self.tile(states[e]) for e in self.cfg.entities if e in states]
        self._cache = (time.time(), tiles)
        return tiles

    async def group(self, name: str) -> list[dict]:
        """Kacheln einer CYD-Seite in kompakter Form (wenig RAM auf dem ESP32)."""
        domains = GROUPS.get(name)
        out = []
        for t in await self.tiles():
            if domains is not None and t["domain"] not in domains:
                continue
            kind = "media" if t["domain"] == "media_player" else "toggle" if t["toggle"] else \
                "activate" if t["activate"] else "sensor"
            out.append({"id": t["entity_id"], "name": t["name"][:28], "display": t["display"][:40], "on": t["on"],
                        "kind": kind, "available": t["available"]})
        return out[:12]

    async def media(self, entity_id: str, action: str) -> dict:
        if entity_id not in self.cfg.entities or not entity_id.startswith("media_player."):
            raise PermissionError("Kein freigegebener Mediaplayer")
        service = MEDIA_ACTIONS.get(action)
        if service is None:
            raise PermissionError("Unbekannte Aktion")
        async with self._client() as c:
            r = await c.post(f"/api/services/media_player/{service}", json={"entity_id": entity_id})
            r.raise_for_status()
        self._cache = None
        return {"ok": True, "service": service}

    async def toggle(self, entity_id: str) -> dict:
        if entity_id not in self.cfg.entities:
            raise PermissionError("Entität ist nicht für das Dashboard freigegeben")
        domain = entity_id.split(".", 1)[0]
        if domain in TOGGLE_DOMAINS:
            service = "toggle"
        elif domain == "media_player":
            service = "media_play_pause"
        elif domain in ACTIVATE_DOMAINS:
            service = "turn_on"
        else:
            raise PermissionError("Diese Entität lässt sich im Dashboard nicht schalten")
        async with self._client() as c:
            r = await c.post(f"/api/services/{domain}/{service}", json={"entity_id": entity_id})
            r.raise_for_status()
        name = next((t["name"] for t in (self._cache[1] if self._cache else []) if t["entity_id"] == entity_id), entity_id)
        self._cache = None
        logger.info(f"Home Assistant: {entity_id} {service}")
        return {"ok": True, "service": service, "name": name}
