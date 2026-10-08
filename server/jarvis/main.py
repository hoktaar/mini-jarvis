"""FastAPI-Einstiegspunkt: PWA, REST-API, Geräte-WebSockets, Verwaltung.

HTTP (Standard 8080) für ESP32-Satelliten und Weiterleitungshinweise, HTTPS (8443) mit
eigener CA für Browser – das Mikrofon funktioniert im Browser nur über HTTPS.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from jarvis import __version__
from jarvis.app import build_router, build_services, start_background, stop_background
from jarvis.config import DATA_DIR, cloud_services
from jarvis.devices import KINDS, Device
from jarvis.router.router import Route

WEB_DIR = Path(__file__).parent / "web"
services = None
_failed_admin: dict[str, list[float]] = {}


class _RedactTokens(logging.Filter):
    """Tokens/Tickets nie im Zugriffslog."""

    _re = re.compile(r"((?:token|ticket)=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._re.sub(r"\1***", record.msg)
        if record.args:
            record.args = tuple(self._re.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


for _name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_name).addFilter(_RedactTokens())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global services
    if services is None:                      # Tests/Einbettung können eigene Dienste vorgeben
        services = build_services()
        services.matrix_token_file = Path(DATA_DIR) / "matrix_login.json"
    app.state.services = services
    tasks = await start_background(services)
    yield
    await stop_background(services, tasks)


app = FastAPI(title="Mini-Jarvis", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def _starting(request: Request, call_next):
    # Der HTTPS-Server nimmt schon Anfragen an, während der erste Server die Dienste aufbaut.
    if services is None and request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Jarvis startet noch …"}, status_code=503)
    return await call_next(request)


# --------------------------------------------------------------------------- Auth
def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


async def require_admin(request: Request, x_admin_token: str = Header(default="")):
    ip = _client_ip(request)
    recent = [t for t in _failed_admin.get(ip, []) if t > time.time() - 300]
    expected = services.secrets.get("admin_token", "")
    if not expected or not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        recent.append(time.time())
        _failed_admin[ip] = recent
        await asyncio.sleep(min(5.0, 0.5 * len(recent)))       # Raten bremsen
        raise HTTPException(401, "Admin-Token fehlt oder ist falsch")
    _failed_admin.pop(ip, None)


def _bearer(authorization: str) -> str:
    return authorization.removeprefix("Bearer ").strip() if authorization else ""


def require_device(authorization: str = Header(default="")) -> Device:
    device = services.devices.verify(_bearer(authorization))
    if device is None:
        raise HTTPException(401, "Geräte-Token fehlt oder ist ungültig")
    return device


def _pair_base(request: Request) -> str:
    cfg = services.cfg.server
    if cfg.public_url:
        return cfg.public_url.rstrip("/")
    host = request.url.hostname or "localhost"
    if cfg.https.enabled:
        return f"https://{host}:{cfg.https.port}"
    return str(request.base_url).rstrip("/")


def _qr_svg(data: str) -> str:
    import segno

    return segno.make(data, error="m").svg_inline(scale=5, dark="#10181d", light="#ffffff", border=2)


# --------------------------------------------------------------------------- Modelle
class NewDevice(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str
    room: str = ""


class DevicePatch(BaseModel):
    name: str | None = None
    room: str | None = None
    private: bool | None = None
    volume: int | None = None


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speak: bool = True


class MePatch(BaseModel):
    private: bool | None = None


class Correction(BaseModel):
    intent: str
    add_example: bool = True


class RouterTest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ScriptRun(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class MemoryIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)


class Snooze(BaseModel):
    minutes: int = 5


# --------------------------------------------------------------------------- Öffentlich
@app.get("/api/health")
async def health():
    return {"ok": True, "version": __version__}


@app.get("/api/info")
async def info(request: Request):
    """Für die PWA: HTTPS-Adresse und ob es eine CA zum Installieren gibt."""
    cfg = services.cfg.server
    ca = Path(DATA_DIR) / "tls" / "ca.crt"
    return {"version": __version__, "https": cfg.https.enabled, "https_port": cfg.https.port,
            "https_url": _pair_base(request) if cfg.https.enabled else "",
            "ca": ca.exists() and not cfg.https.certfile}


@app.get("/ca.crt")
async def ca_cert():
    ca = Path(DATA_DIR) / "tls" / "ca.crt"
    if not ca.exists():
        raise HTTPException(404, "Keine eigene CA vorhanden")
    return FileResponse(ca, media_type="application/x-x509-ca-cert", filename="mini-jarvis-ca.crt")


@app.post("/api/ws-ticket")
async def ws_ticket(device: Device = Depends(require_device)):
    return {"ticket": services.devices.issue_ticket(device), "expires_in": 60}


@app.get("/api/me")
async def me(device: Device = Depends(require_device)):
    session = services.sessions.get(device.id)
    return {"id": device.id, "name": device.name, "kind": device.kind, "room": device.room,
            "private": bool(device.settings.get("private")), "version": __version__,
            "cloud_services": cloud_services(services.cfg), "connected": bool(session and session.voice),
            "timezone": services.cfg.location.timezone,
            "timers": services.timers.items(), "now": time.time()}


@app.patch("/api/me")
async def me_patch(patch: MePatch, device: Device = Depends(require_device)):
    session = services.session_for(device)
    if patch.private is not None:
        await session.set_private(patch.private)
    return {"ok": True, "private": session.private}


@app.post("/api/chat")
async def chat_endpoint(msg: ChatIn, device: Device = Depends(require_device)):
    from jarvis.textpipe import chat

    return await chat(services.session_for(device), msg.text.strip(), speak=msg.speak)


@app.get("/api/timers")
async def timers_list(device: Device = Depends(require_device)):
    return {"items": services.timers.items(), "now": time.time()}


@app.delete("/api/timers/{timer_id}")
async def timers_cancel(timer_id: int, device: Device = Depends(require_device)):
    n = services.timers.cancel(timer_id)
    services.db.audit(f"device:{device.id}", "cancel_timer", str(timer_id), "ok" if n else "nicht gefunden")
    return {"ok": bool(n)}


@app.post("/api/alarms/{timer_id}/ack")
async def alarm_ack(timer_id: int, device: Device = Depends(require_device)):
    acked = services.timers.ack(timer_id)
    for tid in acked:
        await services.broadcast({"type": "alarm_stop", "id": tid})
    await services.broadcast_timers()
    return {"ok": bool(acked)}


@app.post("/api/alarms/{timer_id}/snooze")
async def alarm_snooze(timer_id: int, body: Snooze, device: Device = Depends(require_device)):
    new_id = services.timers.snooze(timer_id, max(1, min(60, body.minutes)))
    await services.broadcast({"type": "alarm_stop", "id": timer_id})
    return {"ok": new_id is not None, "id": new_id}


_calendar_cache: dict[str, tuple[float, list]] = {}


async def _upcoming_calendar() -> list[dict]:
    """Termine heute und morgen (5 Minuten zwischengespeichert)."""
    from datetime import datetime, timedelta

    cal = services.calendar
    if cal is None:
        return []
    hit = _calendar_cache.get("events")
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    today = datetime.now(cal.tz).date()
    events = []
    for offset in (0, 1):
        for e in await cal.events(today + timedelta(days=offset)):
            events.append({"kind": "event", "label": e["summary"], "due": e["start"].timestamp(),
                           "all_day": e["all_day"], "source": e["calendar"]})
    _calendar_cache["events"] = (time.time(), events)
    return events


def _capabilities() -> list[dict]:
    reg = services.registry
    cfg = services.cfg
    has = lambda *names: any(reg.get(n) for n in names)  # noqa: E731
    return [
        {"name": "Timer & Wecker", "ok": has("set_timer")},
        {"name": "Wetter", "ok": not (cfg.location.latitude == 0 and cfg.location.longitude == 0)},
        {"name": "Websuche", "ok": has("search_web")},
        {"name": "Smarthome", "ok": services.home.configured or has("HassTurnOn", "GetLiveContext")},
        {"name": "Kalender", "ok": has("calendar_agenda")},
        {"name": "Gedächtnis", "ok": has("remember")},
        {"name": "Container", "ok": has("container_status")},
        {"name": "Cloud-KI", "ok": cfg.providers.llm.cloud.enabled},
    ]


@app.get("/api/dashboard")
async def dashboard(device: Device = Depends(require_device)):
    """Alles für die Startseite in einer Anfrage (Teile, die hängen, liefern einfach nichts)."""
    from jarvis.tools.weather import current_weather

    cfg = services.cfg

    async def safe(coro, default):
        try:
            return await asyncio.wait_for(coro, 6)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Dashboard-Teil fehlgeschlagen: {e}")
            return default

    weather, tiles, events = await asyncio.gather(
        safe(current_weather(cfg.location), None),
        safe(services.home.tiles(), []) if services.home.configured else asyncio.sleep(0, []),
        safe(_upcoming_calendar(), []),
    )
    devices = [d for d in services.devices.list() if not d["revoked"]]
    online = {s.device.id for s in services.online()}
    recent = [dict(r) for r in services.db.query(
        "SELECT text, intent, route, ts FROM router_log WHERE device_id=? AND text != '…' ORDER BY id DESC LIMIT 8",
        (device.id,))]
    upcoming = sorted(
        [{"kind": t["kind"], "label": t["label"], "due": t["due"], "id": t["id"], "ringing": t["ringing"]}
         for t in services.timers.items()] + events, key=lambda x: x["due"])[:12]
    return {
        "now": time.time(), "timezone": cfg.location.timezone, "place": cfg.location.name,
        "weather": weather, "version": __version__,
        "devices": {"online": len(online), "total": len(devices),
                    "rooms": sorted({d["room"] for d in devices if d["room"]}),
                    "list": [{"name": d["name"], "room": d["room"], "kind": d["kind"], "online": d["id"] in online}
                             for d in devices]},
        "warnings": len(services.warnings), "system": services.stats.snapshot() if services.stats else {},
        "capabilities": _capabilities(), "recent": recent, "upcoming": upcoming,
        "feed": services.feed.latest(20) if services.feed else [],
        "home": {"configured": services.home.configured, "tiles": tiles},
        "budget": services.budget.summary() if cfg.providers.llm.cloud.enabled else None,
    }


@app.post("/api/home/{entity_id}/toggle")
async def home_toggle(entity_id: str, device: Device = Depends(require_device)):
    if not services.home.configured:
        raise HTTPException(400, "Home Assistant ist nicht eingerichtet")
    try:
        result = await services.home.toggle(entity_id)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Home Assistant: {type(e).__name__}") from e
    services.db.audit(f"device:{device.id}", "ha_toggle", entity_id, "ok")
    services.feed.add(f"{result['name']} geschaltet ({device.name})", "ok", "home")
    return result


@app.get("/api/firmware/{variant}/{name}")
async def firmware_file(variant: str, name: str, authorization: str = Header(default=""),
                        x_admin_token: str = Header(default="")):
    """Firmware-Teile: für Geräte (OTA, Bearer-Token) und den Web-Flasher (Admin-Token)."""
    expected = services.secrets.get("admin_token", "")
    admin_ok = bool(x_admin_token) and hmac.compare_digest(x_admin_token, expected)
    if not admin_ok and services.devices.verify(_bearer(authorization)) is None:
        raise HTTPException(401, "Nicht angemeldet")
    path = services.firmware.file(variant, name)
    if path is None:
        raise HTTPException(404, "Firmware nicht gefunden")
    return FileResponse(path, media_type="application/octet-stream")


# --------------------------------------------------------------------------- Verwaltung
admin = [Depends(require_admin)]


def _device_row(d: dict) -> dict:
    session = services.sessions.get(d["id"])
    d["online"] = bool(session and session.voice)
    d["ota"] = services.firmware.status.get(d["id"])
    return d


@app.get("/api/admin/overview", dependencies=admin)
async def overview(request: Request):
    from jarvis.tls import cert_info

    cfg = services.cfg
    p = cfg.providers
    reachable = await _service_checks()
    sessions = [{"device": s.device.name, "kind": s.device.kind, "room": s.device.room,
                 "since": s.voice.started if s.voice else None, "private": s.private,
                 "transport": "voice" if s.voice else "chat"} for s in services.online()]
    return {
        "version": __version__, "uptime_s": int(time.time() - services.started), "timezone": cfg.location.timezone,
        "warnings": services.warnings, "sessions": sessions, "checks": reachable,
        "providers": {
            "llm_primary": p.llm.primary,
            "llm_local": f"{p.llm.local.model} (Ollama)" if p.llm.local.enabled else "aus",
            "llm_cloud": f"{p.llm.cloud.type}: {p.llm.cloud.model}" if p.llm.cloud.enabled else "aus",
            "stt": "aus" if p.stt.type == "none" else f"{p.stt.type} {p.stt.model}".strip(),
            "tts": "aus" if p.tts.type == "none" else f"{p.tts.type} {p.tts.voice}".strip(),
            "search": cfg.search.provider, "cloud_services": cloud_services(cfg),
        },
        "metrics": services.metrics.summary(), "budget": services.budget.summary(),
        "gpu": services.gpu.status(),
        "mcp": [vars(st) for st in services.mcp.status.values()],
        "tools": sorted(services.registry.names()),
        "https": {"enabled": cfg.server.https.enabled, "port": cfg.server.https.port,
                  "url": _pair_base(request), "cert": cert_info(Path(DATA_DIR) / "tls" / "server.crt")},
        "timers": len(services.timers.active()), "ringing": len(services.timers.ringing()),
    }


async def _service_checks() -> dict:
    import httpx

    from jarvis.mcp_servers.docker_mcp import PROXY
    from jarvis.runner.client import call_runner
    from jarvis.tools.setup import RUNNER_SOCKET, docker_enabled

    cfg = services.cfg
    checks: dict[str, dict] = {}

    async def probe(name: str, url: str, ok_codes=(200,)):
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(url)
            checks[name] = {"ok": r.status_code in ok_codes, "detail": f"HTTP {r.status_code}"}
        except Exception as e:  # noqa: BLE001
            checks[name] = {"ok": False, "detail": type(e).__name__}

    jobs = []
    local = cfg.providers.llm.local
    if local.enabled:
        jobs.append(probe("ollama", local.base_url.rstrip("/").removesuffix("/v1") + "/api/tags"))
    if docker_enabled(cfg):
        jobs.append(probe("docker", f"{PROXY}/_ping", ok_codes=(200, 403)))
    await asyncio.gather(*jobs)
    if services.scripts:
        resp = await call_runner(RUNNER_SOCKET, {"op": "list"}, timeout=3)
        checks["runner"] = {"ok": bool(resp.get("ok")), "detail": resp.get("error", "bereit")}
    return checks


@app.get("/api/admin/provision-info", dependencies=admin)
async def provision_info(request: Request):
    """Vorschläge für den USB-Einrichtungsassistenten (Server-Adresse, Port, Zeitzone)."""
    from jarvis.posix_tz import posix_tz

    return {"hosts": _host_suggestions(request), "port": services.cfg.server.port,
            "tz": posix_tz(services.cfg.location.timezone)}


@app.get("/api/admin/devices", dependencies=admin)
async def list_devices():
    return [_device_row(d) for d in services.devices.list()]


@app.post("/api/admin/devices", dependencies=admin)
async def create_device(d: NewDevice, request: Request):
    if d.kind not in KINDS:
        raise HTTPException(400, f"Unbekannter Gerätetyp: {d.kind}")
    device, token = services.devices.create(d.name, d.kind, d.room)
    return _pairing(device, token, request)


def _host_suggestions(request: Request) -> list[str]:
    """Adressen, unter denen ein ESP32 den Server erreichen könnte (ohne localhost/Platzhalter)."""
    names = [request.url.hostname or "", *services.cfg.server.https.hosts]
    out = []
    for n in names:
        n = n.strip()
        if n and n not in out and n not in ("localhost", "127.0.0.1", "::1", "*") and not n.startswith("*."):
            out.append(n)
    return out


def _pairing(device: Device, token: str, request: Request) -> dict:
    out = {"id": device.id, "name": device.name, "kind": device.kind, "token": token,
           "hint": "Token nur jetzt sichtbar."}
    if device.satellite:
        from jarvis.posix_tz import posix_tz

        out["provision"] = {"host": request.url.hostname or "", "port": services.cfg.server.port, "token": token,
                            "name": device.name, "tz": posix_tz(services.cfg.location.timezone),
                            "hosts": _host_suggestions(request)}
    else:
        url = f"{_pair_base(request)}/#pair={token}"
        out["pair_url"] = url
        out["qr_svg"] = _qr_svg(url)
    return out


@app.patch("/api/admin/devices/{device_id}", dependencies=admin)
async def patch_device(device_id: int, patch: DevicePatch):
    settings = {}
    if patch.volume is not None:
        settings["volume"] = max(5, min(100, patch.volume))
    try:
        device = services.devices.update(device_id, patch.name, patch.room, settings or None)
    except KeyError as e:
        raise HTTPException(404, "Gerät nicht gefunden") from e
    session = services.sessions.get(device_id)
    if session is not None:
        session.device = device
        if patch.private is not None:
            await session.set_private(patch.private)
        if patch.volume is not None:
            await session.emit({"type": "volume", "value": settings["volume"]})
    elif patch.private is not None:
        services.devices.update(device_id, settings={"private": patch.private})
    return {"ok": True}


@app.post("/api/admin/devices/{device_id}/rotate", dependencies=admin)
async def rotate_device(device_id: int, request: Request):
    try:
        token = services.devices.rotate(device_id)
    except KeyError as e:
        raise HTTPException(404, "Gerät nicht gefunden") from e
    session = services.sessions.get(device_id)
    if session is not None:
        await session.disconnect(4401, "Token erneuert")
    return _pairing(services.devices.get(device_id), token, request)


@app.delete("/api/admin/devices/{device_id}", dependencies=admin)
async def revoke_device(device_id: int):
    services.devices.revoke(device_id)
    session = services.sessions.pop(device_id, None)
    if session is not None:
        await session.disconnect(4401, "Gerät gesperrt")
    return {"ok": True}


@app.post("/api/admin/devices/{device_id}/ota", dependencies=admin)
async def device_ota(device_id: int):
    device = services.devices.get(device_id)
    if device is None or not device.satellite:
        raise HTTPException(400, "Nur ESP32-Satelliten bekommen OTA-Updates")
    variant = device.settings.get("fw_variant", "cyd")
    m = services.firmware.update_for(variant, "0")
    if m is None:
        raise HTTPException(404, f"Keine Firmware für {variant} vorhanden")
    session = services.sessions.get(device_id)
    if session is not None and session.voice is not None:
        await services.firmware.offer(session, variant, m)
        return {"ok": True, "state": "offered", "version": m["version"]}
    services.devices.update(device_id, settings={"ota_requested": True})
    return {"ok": True, "state": "queued", "version": m["version"]}


@app.get("/api/admin/timers", dependencies=admin)
async def admin_timers():
    names = {d["id"]: d["name"] for d in services.devices.list()}
    items = services.timers.items()
    for i in items:
        i["device"] = names.get(i["device_id"], "")
    return {"items": items, "now": time.time()}


@app.delete("/api/admin/timers/{timer_id}", dependencies=admin)
async def admin_cancel_timer(timer_id: int):
    n = services.timers.cancel(timer_id) or len(services.timers.ack(timer_id))
    await services.broadcast({"type": "alarm_stop", "id": timer_id})
    services.db.audit("admin", "cancel_timer", str(timer_id), "ok" if n else "nicht gefunden")
    return {"ok": bool(n)}


@app.get("/api/admin/router-log", dependencies=admin)
async def router_log(limit: int = 50, offset: int = 0, route: str = ""):
    limit = max(1, min(500, limit))
    sql = "SELECT r.*, d.name AS device FROM router_log r LEFT JOIN devices d ON d.id = r.device_id"
    params: tuple = ()
    if route:
        sql += " WHERE r.route = ?"
        params = (route,)
    rows = services.db.query(sql + " ORDER BY r.id DESC LIMIT ? OFFSET ?", (*params, limit, max(0, offset)))
    return [dict(r) for r in rows]


@app.post("/api/admin/router-log/{log_id}/correct", dependencies=admin)
async def correct(log_id: int, c: Correction):
    if services.router is None or c.intent not in services.router.intents:
        raise HTTPException(400, "Unbekannte Absicht")
    rows = services.db.query("SELECT text FROM router_log WHERE id=?", (log_id,))
    if not rows:
        raise HTTPException(404, "Eintrag nicht gefunden")
    services.db.execute("UPDATE router_log SET corrected_intent=? WHERE id=?", (c.intent, log_id))
    if c.add_example and rows[0]["text"] not in ("…", ""):
        services.db.execute("INSERT OR IGNORE INTO intent_examples (intent, text, created) VALUES (?,?,?)",
                            (c.intent, rows[0]["text"], time.time()))
        services.router.retrain(services.extra_examples())
    services.db.audit("admin", "router_correct", f"{log_id} → {c.intent}")
    return {"ok": True}


@app.get("/api/admin/intents", dependencies=admin)
async def intents():
    if services.router is None:
        return []
    extra = services.extra_examples()
    return [{"name": n, "tool": i.tool, "fast": i.fast, "examples": len(i.examples) + len(extra.get(n, [])),
             "available": i.tool is None or services.registry.get(i.tool) is not None}
            for n, i in services.router.intents.items()]


@app.post("/api/admin/router/test", dependencies=admin)
async def router_test(t: RouterTest):
    if services.router is None:
        raise HTTPException(400, "Router ist nicht konfiguriert")
    db, services.router.db = services.router.db, None
    try:
        d = await services.router.decide(t.text)
    finally:
        services.router.db = db
    slots = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.slots.items()}
    return {"route": d.route.value, "intent": d.intent, "confidence": round(d.confidence, 3), "slots": slots,
            "ask": d.ask, "candidates": d.candidates, "latency_ms": round(d.latency_ms, 1),
            "fast": d.route == Route.FAST}


@app.get("/api/admin/router/eval", dependencies=admin)
async def router_eval():
    from jarvis.router.eval import evaluate, load_cases

    if services.router is None:
        raise HTTPException(400, "Router ist nicht konfiguriert")
    report = await evaluate(services.router, load_cases())
    return report.as_dict()


@app.post("/api/admin/router/retrain", dependencies=admin)
async def retrain():
    services.router.retrain(services.extra_examples())
    return {"ok": True, "examples": sum(len(v) for v in services.extra_examples().values())}


@app.get("/api/admin/audit", dependencies=admin)
async def audit(limit: int = 50, offset: int = 0):
    rows = services.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                             (max(1, min(500, limit)), max(0, offset)))
    return [dict(r) for r in rows]


@app.get("/api/admin/scripts", dependencies=admin)
async def scripts():
    return [{"id": s.id, "description": s.description, "confirm": s.confirm, "car_allowed": s.car_allowed,
             "timeout": s.timeout, "params": {k: vars(p) for k, p in s.params.items()}}
            for s in services.scripts.values()]


@app.post("/api/admin/scripts/{script_id}/run", dependencies=admin)
async def run_script(script_id: str, body: ScriptRun):
    from jarvis.runner.client import call_runner
    from jarvis.tools.setup import RUNNER_SOCKET

    if script_id not in services.scripts:
        raise HTTPException(404, "Skript nicht gefunden")
    resp = await call_runner(RUNNER_SOCKET, {"id": script_id, "args": body.args})
    services.db.audit("admin", "run_script", script_id, "ok" if resp.get("ok") else resp.get("error", "fehler"))
    return resp


@app.get("/api/admin/memory", dependencies=admin)
async def memory_list():
    return services.memory.list(200)


@app.post("/api/admin/memory", dependencies=admin)
async def memory_add(m: MemoryIn):
    return {"id": services.memory.add(m.text)}


@app.delete("/api/admin/memory/{memory_id}", dependencies=admin)
async def memory_delete(memory_id: int):
    return {"ok": services.memory.delete(memory_id)}


@app.get("/api/admin/config", dependencies=admin)
async def config_view():
    data = services.cfg.model_dump(mode="json")
    for m in data.get("mcp_servers", []):
        m["headers"] = {k: "***" for k in m.get("headers", {})}
        m["env"] = {k: ("***" if any(w in k.lower() for w in ("key", "token", "secret", "pass")) else v)
                    for k, v in m.get("env", {}).items()}
    return {"config": data, "secrets": sorted(k for k in services.secrets if k != "admin_token"),
            "warnings": services.warnings}


@app.post("/api/admin/reload", dependencies=admin)
async def reload_config():
    """Absichten, Whitelist und Skripte neu einlesen (Konfiguration selbst braucht einen Neustart)."""
    from jarvis.config import load_yaml
    from jarvis.runner.registry import load_registry

    config_dir = services.config_dir
    try:
        services.scripts = load_registry(load_yaml("scripts.yaml", config_dir))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"scripts.yaml fehlerhaft: {e}") from e
    services.router = build_router(services, config_dir)
    for s in services.sessions.values():
        s.router = services.router
        s.classifier = services.classifier
    services.db.audit("admin", "reload", "intents, whitelist, scripts")
    return {"ok": True, "intents": len(services.router.intents) if services.router else 0,
            "hint": "Container-Whitelist für den Docker-Proxy wirkt erst nach einem Neustart."}


@app.get("/api/admin/firmware", dependencies=admin)
async def firmware_list():
    return {"variants": services.firmware.variants(), "auto_update": services.firmware.auto_update}


@app.get("/api/admin/firmware/{variant}/manifest", dependencies=admin)
async def firmware_manifest(variant: str):
    m = services.firmware.manifest(variant)
    if m is None:
        raise HTTPException(404, "Firmware nicht gefunden")
    return m


@app.post("/api/admin/firmware/upload", dependencies=admin)
async def firmware_upload(variant: str = Form(...), version: str = Form(""), file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(400, "Datei zu groß")
    try:
        manifest = services.firmware.upload(variant, data, version or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    services.db.audit("admin", "firmware_upload", f"{variant} {manifest['version']}")
    return manifest


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    logger.exception(f"Fehler bei {request.url.path}")
    return JSONResponse({"detail": "Interner Fehler – Details im Log."}, status_code=500)


# --------------------------------------------------------------------------- WebSockets
async def _device_ws(websocket: WebSocket, token: str, ticket: str):
    device = services.devices.redeem_ticket(ticket) if ticket else None
    if device is None:
        device = services.devices.verify(_bearer(websocket.headers.get("authorization", "")))
    if device is None and token:
        device = services.devices.verify(token)          # alt (0.2): Token in der URL
    await websocket.accept()
    if device is None:
        await websocket.close(code=4401, reason="Nicht angemeldet")
        return
    from jarvis.pipeline import run_device_session

    await run_device_session(websocket, device, services)


@app.websocket("/ws/cyd")
async def ws_cyd(websocket: WebSocket, token: str = "", ticket: str = ""):
    await _device_ws(websocket, token, ticket)


@app.websocket("/ws/client")
async def ws_client(websocket: WebSocket, token: str = "", ticket: str = ""):
    await _device_ws(websocket, token, ticket)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


# --------------------------------------------------------------------------- Start
async def _serve() -> None:
    from jarvis.config import load_config
    from jarvis.tls import ensure_server_cert

    cfg = load_config()
    port = int(os.environ.get("JARVIS_PORT", cfg.server.port))
    servers = [uvicorn.Server(uvicorn.Config(app, host=cfg.server.host, port=port, log_level="info",
                                             ws_max_size=4 * 1024 * 1024))]
    if cfg.server.https.enabled:
        certfile, keyfile = cfg.server.https.certfile, cfg.server.https.keyfile
        if not (certfile and keyfile):
            hosts = list(cfg.server.https.hosts)
            if cfg.server.public_url:
                from urllib.parse import urlparse

                hosts.append(urlparse(cfg.server.public_url).hostname or "")
            crt, key = ensure_server_cert(Path(DATA_DIR) / "tls", [h for h in hosts if h])
            certfile, keyfile = str(crt), str(key)
        # Zweiter Server ohne eigenen Lifespan – die Dienste baut nur der erste auf.
        servers.append(uvicorn.Server(uvicorn.Config(app, host=cfg.server.host, port=cfg.server.https.port,
                                                     log_level="info", lifespan="off", ssl_certfile=certfile,
                                                     ssl_keyfile=keyfile, ws_max_size=4 * 1024 * 1024)))
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
