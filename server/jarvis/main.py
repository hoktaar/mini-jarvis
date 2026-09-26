"""FastAPI-Einstiegspunkt: PWA, REST-API, Geräte-WebSockets."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jarvis.app import build_services
from jarvis.router.router import Route

WEB_DIR = Path(__file__).parent / "web"
services = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global services
    services = build_services()
    services.timers.start()
    yield


app = FastAPI(title="Mini-Jarvis", lifespan=lifespan)


def require_admin(x_admin_token: str = Header(default="")):
    if not x_admin_token or x_admin_token != services.secrets.get("admin_token"):
        raise HTTPException(401, "Admin-Token fehlt oder ist falsch")


class NewDevice(BaseModel):
    name: str
    kind: str
    room: str = ""


class ChatIn(BaseModel):
    text: str


@app.get("/api/health")
async def health():
    return {"ok": True, "sessions": len(services.sessions), "tools": services.registry.names()}


@app.get("/api/admin/devices", dependencies=[Depends(require_admin)])
async def list_devices():
    return services.devices.list()


@app.post("/api/admin/devices", dependencies=[Depends(require_admin)])
async def create_device(d: NewDevice):
    device, token = services.devices.create(d.name, d.kind, d.room)
    return {"id": device.id, "token": token, "hint": "Token nur jetzt sichtbar – im Gerät eintragen."}


@app.delete("/api/admin/devices/{device_id}", dependencies=[Depends(require_admin)])
async def revoke_device(device_id: int):
    services.devices.revoke(device_id)
    return {"ok": True}


@app.get("/api/admin/router-log", dependencies=[Depends(require_admin)])
async def router_log(limit: int = 50):
    rows = services.db.query("SELECT * FROM router_log ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


@app.get("/api/admin/audit", dependencies=[Depends(require_admin)])
async def audit(limit: int = 50):
    rows = services.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


@app.post("/api/chat")
async def chat(msg: ChatIn, authorization: str = Header(default="")):
    """Text-Test des Routers (Phase 0/1). Ohne LLM-Anbindung: nur Schnellweg."""
    device = services.devices.verify(authorization.removeprefix("Bearer ").strip())
    if device is None:
        raise HTTPException(401, "Geräte-Token fehlt")
    from jarvis.session import JarvisSession

    session = JarvisSession(services, device)
    d = await services.router.decide(msg.text)
    reply = None
    if d.route == Route.FAST:
        intent = services.router.intents[d.intent]
        result = await session.execute(intent.tool, session.slots_to_args(intent.tool, d.slots))
        reply = result.speech
    elif d.route == Route.ASK_SLOT:
        reply = d.ask
    return {"route": d.route.value, "intent": d.intent, "confidence": round(d.confidence, 3),
            "reply": reply or "(würde an das LLM gehen – Sprachpfad ab Phase 1)"}


async def _device_ws(websocket: WebSocket, token: str):
    device = services.devices.verify(token)
    await websocket.accept()
    if device is None:
        await websocket.close(code=4401)
        return
    from jarvis.pipeline import run_device_session

    await run_device_session(websocket, device, services)


@app.websocket("/ws/cyd")
async def ws_cyd(websocket: WebSocket, token: str = ""):
    await _device_ws(websocket, token)


@app.websocket("/ws/client")
async def ws_client(websocket: WebSocket, token: str = ""):
    await _device_ws(websocket, token)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def main() -> None:
    port = int(os.environ.get("JARVIS_PORT", "8080"))
    # Web-UI, REST und Geräte-WebSockets laufen über denselben Port.
    uvicorn.run("jarvis.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
