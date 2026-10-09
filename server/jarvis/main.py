"""FastAPI-Einstiegspunkt: PWA, REST-API, Geräte-WebSockets, Verwaltung.

HTTP (Standard 8080) für ESP32-Satelliten und Weiterleitungshinweise, HTTPS (8443) mit
eigener CA für Browser – das Mikrofon funktioniert im Browser nur über HTTPS.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import sys
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
_failed_api: dict[str, list[float]] = {}
_servers: list = []                 # laufende uvicorn-Server (für den Neustart aus der Verwaltung)
_restart = False


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
    if services is None and request.url.path.startswith(("/api/", "/v1/")):
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


class SettingsIn(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)          # Pfad → Wert (None = Standard)
    secrets: dict[str, str | None] = Field(default_factory=dict)   # Name → Wert ("" = löschen)
    whitelist: dict[str, list[str]] | None = None                  # Container → Aktionen


class ScriptIn(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    description: str = ""
    confirm: bool = True
    car_allowed: bool = False
    timeout: int = 60
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ExampleIn(BaseModel):
    text: str = Field(min_length=2, max_length=200)


class PullIn(BaseModel):
    model: str = Field(min_length=1, max_length=120)
    base_url: str = ""


class HaTest(BaseModel):
    url: str = ""
    token: str = ""
    verify_tls: bool = True


# --------------------------------------------------------------------------- Öffentlich
@app.get("/api/health")
async def health():
    return {"ok": True, "version": __version__, "boot": int(services.started)}


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


# --------------------------------------------------------------------------- Transkriptions-Schnittstelle
# Wie OpenAI (/v1/audio/transcriptions): Diktier-Apps und andere Geräte im Heimnetz nutzen Jarvis'
# Spracherkennung mit. Aus, bis sie in der Verwaltung eingeschaltet wird.
TRANSCRIPTION_TOKEN = "transcription_api_token"
TRANSCRIPTION_MAX_BYTES = 25 * 1024 * 1024


def _oa_error(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)


def _transcription_token() -> str:
    from jarvis.settings import env_secret

    return env_secret(TRANSCRIPTION_TOKEN) or services.secrets.get(TRANSCRIPTION_TOKEN, "")


def _transcription_engine() -> str:
    from jarvis.providers import LOCAL_TRANSCRIBE, REMOTE_TRANSCRIBE

    t = services.cfg.providers.stt.type
    return t if t in (*LOCAL_TRANSCRIBE, *REMOTE_TRANSCRIBE) else ""


async def _transcription_auth(request: Request, authorization: str) -> JSONResponse | None:
    if not services.cfg.server.transcription_api:
        return _oa_error(404, "Transkriptions-Schnittstelle ist aus (Verwaltung → Einstellungen → Sprache).")
    ip = _client_ip(request)
    token = _bearer(authorization)
    expected = _transcription_token()
    ok = bool(token) and ((bool(expected) and hmac.compare_digest(token, expected))
                          or services.devices.verify(token) is not None)
    if not ok:
        recent = [t for t in _failed_api.get(ip, []) if t > time.time() - 300] + [time.time()]
        _failed_api[ip] = recent
        await asyncio.sleep(min(5.0, 0.5 * len(recent)))
        return _oa_error(401, "Token fehlt oder ist falsch.", "authentication_error")
    _failed_api.pop(ip, None)
    return None


@app.get("/v1/models")
async def v1_models(request: Request, authorization: str = Header(default="")):
    if (err := await _transcription_auth(request, authorization)) is not None:
        return err
    engine = _transcription_engine()
    return {"object": "list", "data": [{"id": engine, "object": "model", "owned_by": "mini-jarvis"}] if engine else []}


@app.post("/v1/audio/transcriptions")
async def v1_transcriptions(request: Request, file: UploadFile = File(...), model: str = Form(""),
                            language: str = Form(""), response_format: str = Form("json"),
                            authorization: str = Header(default="")):
    from jarvis import providers

    if (err := await _transcription_auth(request, authorization)) is not None:
        return err
    if not _transcription_engine():
        return _oa_error(409, "Die eingestellte Spracherkennung kann keine Dateien umwandeln – "
                              "bitte Parakeet, Whisper, OpenAI oder Groq wählen.")
    if response_format not in ("json", "text", "verbose_json"):
        return _oa_error(400, "response_format: nur json, text oder verbose_json.")
    if language and language.split("-")[0].lower() != "de":
        return _oa_error(400, "Jarvis erkennt nur Deutsch (language=de).")
    data = await file.read(TRANSCRIPTION_MAX_BYTES + 1)
    if len(data) > TRANSCRIPTION_MAX_BYTES:
        return _oa_error(413, "Datei zu groß (höchstens 25 MB).")
    if not data:
        return _oa_error(400, "Leere Datei.")
    cfg = services.cfg
    started = time.monotonic()
    duration = 0.0
    try:
        if _transcription_engine() in providers.REMOTE_TRANSCRIBE:
            text = await providers.transcribe_audio(cfg, services.secrets, data, file.filename or "audio.wav")
        else:
            audio = await asyncio.to_thread(providers.decode_audio, data)
            duration = len(audio) / 16000
            text = await asyncio.to_thread(providers.transcribe_float, cfg, audio)
    except providers.AudioFormatError as e:
        return _oa_error(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Transkription fehlgeschlagen: {type(e).__name__}: {e}")
        return _oa_error(500, f"Spracherkennung fehlgeschlagen: {type(e).__name__}", "server_error")
    # Kein Transkript ins Log – nur Länge und Dauer
    logger.info(f"Transkription über die Schnittstelle: {duration:.1f} s Audio, {len(text)} Zeichen, "
                f"{time.monotonic() - started:.2f} s")
    if response_format == "text":
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(text)
    if response_format == "verbose_json":
        return {"task": "transcribe", "language": "german", "duration": round(duration, 2), "text": text, "segments": []}
    return {"text": text}


# --------------------------------------------------------------------------- Verwaltung
admin = [Depends(require_admin)]


def _device_row(d: dict) -> dict:
    session = services.sessions.get(d["id"])
    d["online"] = bool(session and session.voice)
    d["ota"] = services.firmware.status.get(d["id"])
    return d


@app.get("/api/admin/overview", dependencies=admin)
async def overview(request: Request):
    from jarvis import providers
    from jarvis.tls import cert_info

    cfg = services.cfg
    p = cfg.providers
    reachable = await _service_checks()
    sessions = [{"device": s.device.name, "kind": s.device.kind, "room": s.device.room,
                 "since": s.voice.started if s.voice else None, "private": s.private,
                 "transport": "voice" if s.voice else "chat"} for s in services.online()]
    return {
        "version": __version__, "uptime_s": int(time.time() - services.started), "timezone": cfg.location.timezone,
        "warnings": services.warnings + ([providers.whisper_gpu_problem] if providers.whisper_gpu_problem else []),
        "sessions": sessions, "checks": reachable,
        "providers": {
            "llm_primary": p.llm.primary,
            "llm_local": f"{p.llm.local.model} (Ollama)" if p.llm.local.enabled else "aus",
            "llm_cloud": f"{p.llm.cloud.type}: {p.llm.cloud.model}" if p.llm.cloud.enabled else "aus",
            "stt": "aus" if p.stt.type == "none" else "parakeet (CPU)" if p.stt.type == "parakeet"
            else f"{p.stt.type} {p.stt.model}".strip(),
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
        "restart_pending": _restart_pending(),
    }


def _restart_pending() -> dict:
    """Hinweis für die Verwaltung: Neustart von Jarvis bzw. des Containers nötig?"""
    from jarvis.settings import container_restart_reasons

    pending = services.restart_pending
    # Nach einem Neustart von Jarvis wirkt die neue Konfiguration – eingebettete Dienste aber erst mit dem Container.
    return {"core": pending["core"], "container": pending["container"] or container_restart_reasons(services.cfg)}


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
    return [{"id": s.id, "path": s.path, "description": s.description, "confirm": s.confirm, "car_allowed": s.car_allowed,
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


# --------------------------------------------------------------------------- Einstellungen
def _files():
    from jarvis.settings import ConfigFiles

    return ConfigFiles(services.config_dir)


def _settings_http(e) -> HTTPException:
    return HTTPException(e.status, {"message": e.message, "errors": e.errors})


def _reload_runtime() -> None:
    """Skripte, Whitelist-Namen, Absichten und Router-Beispiele neu einlesen – ohne Neustart."""
    from jarvis.config import load_yaml
    from jarvis.runner.registry import load_registry
    from jarvis.settings import scripts_root

    errors: list[str] = []
    services.scripts = load_registry(load_yaml("scripts.yaml", services.config_dir), scripts_root(), errors)
    services.script_errors = errors
    services.router = build_router(services, services.config_dir)
    for s in services.sessions.values():
        s.router = services.router
        s.classifier = services.classifier


# Einstellungen, die sofort wirken (alles andere braucht einen Neustart von Jarvis)
LIVE_PATHS = {"firmware.auto_update", "privacy.retention_days", "server.transcription_api"}


@app.get("/api/admin/settings", dependencies=admin)
async def settings_get():
    from jarvis import settings as st

    files = _files()
    try:
        values = st.config_values(files)
        secrets = st.secret_status(files)
        whitelist = st.whitelist_values(files)
    except st.SettingsError as e:
        raise _settings_http(e) from e
    return {
        "values": values, "secrets": secrets, "secret_names": st.secret_names(), "whitelist": whitelist,
        "readonly": files.readonly_reason(), "restart_pending": _restart_pending(),
        "locked": st.LOCKED_PATHS, "timezones": st.timezones(), "warnings": services.warnings,
        "env": {"hosts": os.environ.get("JARVIS_HOSTS", ""), "public_url": os.environ.get("JARVIS_PUBLIC_URL", ""),
                "admin_token": bool(st.env_secret("admin_token"))},
    }


@app.put("/api/admin/settings", dependencies=admin)
async def settings_put(body: SettingsIn):
    from jarvis import settings as st
    from jarvis.config import config_warnings, secrets_with_env

    files = _files()
    try:
        reason = files.readonly_reason()
        if reason:
            raise st.SettingsError(reason, status=409)
        raw = files.load("config.yaml")
        st.apply_changes(raw, body.changes)
        raw_secrets = files.load("secrets.yaml")
        st.apply_secrets(raw_secrets, body.secrets)
        secrets_map = secrets_with_env(st.plain(raw_secrets))
        cfg = st.validate(raw, secrets_map)
        raw_wl = None
        if body.whitelist is not None:
            raw_wl = files.load("whitelist.yaml")
            st.apply_whitelist(raw_wl, body.whitelist)
        # Erst alles prüfen, dann schreiben
        if body.secrets:
            files.save("secrets.yaml", raw_secrets)
        if body.changes:
            files.save("config.yaml", raw)
        if raw_wl is not None:
            files.save("whitelist.yaml", raw_wl)
    except st.SettingsError as e:
        raise _settings_http(e) from e

    if raw_wl is not None:
        _reload_runtime()                          # neue Containernamen kennt der Router sofort
    live = set(body.changes) <= LIVE_PATHS and not body.secrets
    if live:
        services.cfg.firmware.auto_update = cfg.firmware.auto_update
        services.cfg.privacy.retention_days = cfg.privacy.retention_days
        services.firmware.auto_update = cfg.firmware.auto_update
        services.cfg.server.transcription_api = cfg.server.transcription_api
    elif body.changes or body.secrets:
        services.restart_pending["core"] = True
    services.restart_pending["container"] = st.container_restart_reasons(cfg)
    services.warnings = config_warnings(cfg, secrets_map)
    what = sorted(body.changes) + [f"Geheimnis {n}" for n in sorted(body.secrets)]
    if body.whitelist is not None:
        what.append("Container-Freigaben")
    services.db.audit("admin", "settings", ", ".join(what)[:500] or "–")
    return {"ok": True, "restart_pending": _restart_pending(), "warnings": services.warnings,
            "secrets": st.secret_status(files), "values": st.config_values(files)}


@app.post("/api/admin/restart", dependencies=admin)
async def restart_core():
    if not _servers:
        raise HTTPException(409, "Neustart geht nur, wenn Jarvis als Server läuft.")
    services.db.audit("admin", "restart", "Jarvis neu starten")
    services.feed.add("Jarvis startet neu …", "info", "system")

    def go() -> None:
        global _restart
        _restart = True
        for server in _servers:
            server.should_exit = True

    asyncio.get_running_loop().call_later(0.4, go)
    return {"ok": True}


@app.post("/api/admin/token/rotate", dependencies=admin)
async def rotate_admin_token():
    import secrets as pysecrets

    from ruamel.yaml.scalarstring import DoubleQuotedScalarString

    from jarvis import settings as st

    if st.env_secret("admin_token"):
        raise HTTPException(409, "Der Admin-Token kommt aus JARVIS_ADMIN_TOKEN (Container-Vorlage) "
                                 "und lässt sich nur dort ändern.")
    files = _files()
    token = pysecrets.token_urlsafe(32)
    try:
        raw = files.load("secrets.yaml")
        raw["admin_token"] = DoubleQuotedScalarString(token)
        files.save("secrets.yaml", raw)
    except st.SettingsError as e:
        raise _settings_http(e) from e
    services.secrets["admin_token"] = token
    services.db.audit("admin", "admin_token", "neu erzeugt")
    return {"token": token}


@app.post("/api/admin/reload", dependencies=admin)
async def reload_config():
    """Absichten, Container-Freigaben und Skripte neu einlesen (ohne Neustart)."""
    try:
        _reload_runtime()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Neu einlesen fehlgeschlagen: {e}") from e
    services.db.audit("admin", "reload", "Absichten, Freigaben, Skripte")
    return {"ok": True, "intents": len(services.router.intents) if services.router else 0}


# ---- Skripte
@app.get("/api/admin/script-files", dependencies=admin)
async def script_files():
    from jarvis import settings as st

    return {"root": st.scripts_root(), "files": st.script_files(), "readonly": _files().readonly_reason(),
            "errors": services.script_errors}


@app.put("/api/admin/scripts/{script_id}", dependencies=admin)
async def script_save(script_id: str, body: ScriptIn):
    from jarvis import settings as st

    files = _files()
    try:
        raw = files.load("scripts.yaml")
        st.apply_script(raw, script_id, body.model_dump())
        files.save("scripts.yaml", raw)
    except st.SettingsError as e:
        raise _settings_http(e) from e
    _reload_runtime()
    services.db.audit("admin", "script_save", script_id)
    return {"ok": True}


@app.delete("/api/admin/scripts/{script_id}", dependencies=admin)
async def script_delete(script_id: str):
    from jarvis import settings as st

    files = _files()
    try:
        raw = files.load("scripts.yaml")
        st.apply_script(raw, script_id, None)
        files.save("scripts.yaml", raw)
    except st.SettingsError as e:
        raise _settings_http(e) from e
    _reload_runtime()
    services.db.audit("admin", "script_delete", script_id)
    return {"ok": True}


# ---- Eigene Beispielsätze je Absicht
@app.get("/api/admin/intents/{name}", dependencies=admin)
async def intent_detail(name: str):
    intent = services.router.intents.get(name) if services.router else None
    if intent is None:
        raise HTTPException(404, "Absicht nicht gefunden")
    custom = [dict(r) for r in services.db.query(
        "SELECT id, text, created FROM intent_examples WHERE intent = ? ORDER BY id", (name,))]
    return {"name": name, "tool": intent.tool, "fast": intent.fast, "examples": list(intent.examples), "custom": custom}


@app.post("/api/admin/intents/{name}/examples", dependencies=admin)
async def intent_example_add(name: str, body: ExampleIn):
    if not services.router or name not in services.router.intents:
        raise HTTPException(404, "Absicht nicht gefunden")
    services.db.execute("INSERT OR IGNORE INTO intent_examples (intent, text, created) VALUES (?,?,?)",
                        (name, body.text.strip(), time.time()))
    services.router.retrain(services.extra_examples())
    services.db.audit("admin", "intent_example", f"{name}: {body.text.strip()[:80]}")
    return {"ok": True}


@app.delete("/api/admin/intents/examples/{example_id}", dependencies=admin)
async def intent_example_delete(example_id: int):
    services.db.execute("DELETE FROM intent_examples WHERE id = ?", (example_id,))
    if services.router:
        services.router.retrain(services.extra_examples())
    return {"ok": True}


# ---- Lokales Sprachmodell (Ollama): Modelle anzeigen und laden
def _ollama_base(base_url: str = "") -> str:
    base = (base_url or services.cfg.providers.llm.local.base_url).strip().rstrip("/").removesuffix("/v1")
    if not re.match(r"^https?://[^\s/]+", base):
        raise HTTPException(400, "Adresse muss mit http:// oder https:// beginnen.")
    return base


@app.get("/api/admin/ollama", dependencies=admin)
async def ollama_models(base_url: str = ""):
    import httpx

    base = _ollama_base(base_url)
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{base}/api/tags")
            r.raise_for_status()
        models = [{"name": m.get("name", ""), "size": m.get("size", 0), "modified": m.get("modified_at", "")}
                  for m in r.json().get("models", [])]
        return {"ok": True, "base": base, "models": sorted(models, key=lambda m: m["name"]), "pull": services.ollama_pull}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "base": base, "models": [], "pull": services.ollama_pull,
                "error": f"Ollama unter {base} nicht erreichbar ({type(e).__name__})."}


async def _pull(base: str, model: str) -> None:
    import httpx

    state = services.ollama_pull
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=None)) as c, \
                c.stream("POST", f"{base}/api/pull", json={"model": model, "stream": True}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    state["error"] = msg["error"]
                    break
                state["status"] = msg.get("status", state["status"])
                if msg.get("total"):
                    state["total"], state["completed"] = msg["total"], msg.get("completed", 0)
        if not state["error"]:
            state["status"] = "fertig"
            services.feed.add(f"Modell {model} geladen", "ok", "system")
    except Exception as e:  # noqa: BLE001
        state["error"] = f"{type(e).__name__}: {e}"
    finally:
        state["done"] = True


@app.post("/api/admin/ollama/pull", dependencies=admin)
async def ollama_pull(body: PullIn):
    model = body.model.strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$", model):
        raise HTTPException(400, "Ungültiger Modellname (z. B. qwen3:8b).")
    if services.ollama_pull and not services.ollama_pull.get("done"):
        raise HTTPException(409, f"Es lädt gerade schon {services.ollama_pull['model']}.")
    base = _ollama_base(body.base_url)
    services.ollama_pull = {"model": model, "status": "startet", "completed": 0, "total": 0, "done": False, "error": ""}
    services.ollama_pull["_task"] = asyncio.create_task(_pull(base, model))
    services.db.audit("admin", "ollama_pull", model)
    return {k: v for k, v in services.ollama_pull.items() if not k.startswith("_")}


@app.get("/api/admin/ollama/pull", dependencies=admin)
async def ollama_pull_status():
    state = services.ollama_pull or {}
    return {k: v for k, v in state.items() if not k.startswith("_")}


# ---- Parakeet-Modell und Transkriptions-Schnittstelle
@app.get("/api/admin/parakeet", dependencies=admin)
async def parakeet_status():
    from jarvis import parakeet

    return parakeet.status()


@app.post("/api/admin/parakeet/download", dependencies=admin)
async def parakeet_download():
    from jarvis import parakeet

    if not parakeet.installed() and not parakeet.state["downloading"]:
        parakeet.state.update(downloading=True, error="")      # sofort sichtbar, bevor der Thread läuft

        def run() -> None:
            try:
                parakeet.download()
                services.feed.add("Parakeet-Modell geladen", "ok", "system")
            except Exception as e:  # noqa: BLE001
                logger.warning(str(e))

        asyncio.get_running_loop().run_in_executor(None, run)
        services.db.audit("admin", "parakeet_download", parakeet.MODEL_REPO)
    return parakeet.status()


def _transcription_info() -> dict:
    from jarvis.settings import env_secret

    return {"enabled": services.cfg.server.transcription_api, "token": _transcription_token(),
            "token_env": bool(env_secret(TRANSCRIPTION_TOKEN)), "engine": _transcription_engine(),
            "path": "/v1/audio/transcriptions"}


@app.get("/api/admin/transcription", dependencies=admin)
async def transcription_info():
    return _transcription_info()


@app.post("/api/admin/transcription/token", dependencies=admin)
async def transcription_token():
    import secrets as pysecrets

    from ruamel.yaml.scalarstring import DoubleQuotedScalarString

    from jarvis import settings as st

    if st.env_secret(TRANSCRIPTION_TOKEN):
        raise HTTPException(409, "Der Token kommt aus JARVIS_TRANSCRIPTION_API_TOKEN (Container-Vorlage) "
                                 "und lässt sich nur dort ändern.")
    files = _files()
    token = "jt_" + pysecrets.token_urlsafe(24)
    try:
        if reason := files.readonly_reason():
            raise st.SettingsError(reason, status=409)
        raw = files.load("secrets.yaml")
        raw[TRANSCRIPTION_TOKEN] = DoubleQuotedScalarString(token)
        files.save("secrets.yaml", raw)
    except st.SettingsError as e:
        raise _settings_http(e) from e
    services.secrets[TRANSCRIPTION_TOKEN] = token
    services.db.audit("admin", "transcription_token", "neu erzeugt")
    return _transcription_info()


# ---- Home Assistant: Verbindung testen und Entitäten zur Auswahl laden
@app.post("/api/admin/homeassistant/test", dependencies=admin)
async def homeassistant_test(body: HaTest):
    import httpx

    from jarvis.config import load_secrets

    url = (body.url or services.cfg.homeassistant.url).strip().rstrip("/")
    token = body.token.strip() or load_secrets(services.config_dir).get(services.cfg.homeassistant.token_secret, "")
    if not re.match(r"^https?://[^\s/]+", url):
        return {"ok": False, "error": "Adresse fehlt oder beginnt nicht mit http:// bzw. https://."}
    if not token:
        return {"ok": False, "error": "Token fehlt – in Home Assistant unter Profil → Sicherheit erstellen."}
    try:
        async with httpx.AsyncClient(base_url=url, timeout=8, verify=body.verify_tls,
                                     headers={"Authorization": f"Bearer {token}"}) as c:
            r = await c.get("/api/config")
            if r.status_code == 401:
                return {"ok": False, "error": "Home Assistant lehnt den Token ab."}
            r.raise_for_status()
            version = r.json().get("version", "")
            states = (await c.get("/api/states")).json()
    except httpx.ConnectError:
        return {"ok": False, "error": f"Keine Verbindung zu {url}."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Fehler: {type(e).__name__}"}
    entities = sorted(({"id": s["entity_id"], "domain": s["entity_id"].split(".", 1)[0],
                        "name": (s.get("attributes") or {}).get("friendly_name") or s["entity_id"],
                        "state": s.get("state", "")} for s in states if "entity_id" in s),
                      key=lambda e: (e["domain"], e["name"].lower()))
    return {"ok": True, "version": version, "entities": entities}


# ---- Ortssuche für den Standort (Open-Meteo, nur auf Knopfdruck)
@app.get("/api/admin/geocode", dependencies=admin)
async def geocode(q: str = ""):
    import httpx

    q = q.strip()[:80]
    if len(q) < 2:
        return []
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get("https://geocoding-api.open-meteo.com/v1/search",
                            params={"name": q, "count": 8, "language": "de", "format": "json"})
            r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, "Die Ortssuche ist gerade nicht erreichbar – Koordinaten bitte von Hand eintragen.") from e
    return [{"name": x.get("name", ""), "region": ", ".join(v for v in (x.get("admin1"), x.get("country")) if v),
             "latitude": x.get("latitude"), "longitude": x.get("longitude"), "timezone": x.get("timezone", "")}
            for x in r.json().get("results") or []]


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
                                             ws_max_size=4 * 1024 * 1024, timeout_graceful_shutdown=5))]
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
                                                     ssl_keyfile=keyfile, ws_max_size=4 * 1024 * 1024,
                                                     timeout_graceful_shutdown=5)))
    _servers[:] = servers
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    asyncio.run(_serve())
    if _restart:
        # Gleicher Prozess, frisch geladen: liest die gespeicherten Einstellungen neu ein.
        logger.info("Jarvis startet neu …")
        os.execv(sys.executable, [sys.executable, "-m", "jarvis.main"])


if __name__ == "__main__":
    main()
