"""REST-API und Geräte-WebSocket (CYD-Protokoll ohne Audio)."""

import json

import pytest
from fastapi.testclient import TestClient
from wsutil import disconnect

import jarvis.main as main


@pytest.fixture
def client(services):
    main.services = services                 # der Lifespan übernimmt vorgegebene Dienste
    with TestClient(main.app) as c:
        yield c
    main.services = None


@pytest.fixture
def admin(services):
    return {"X-Admin-Token": services.secrets["admin_token"]}


def test_health_does_not_leak(client):
    r = client.get("/api/health").json()
    assert r["ok"] and "tools" not in r


def test_admin_requires_token(client):
    assert client.get("/api/admin/devices").status_code == 401
    assert client.get("/api/admin/devices", headers={"X-Admin-Token": "falsch"}).status_code == 401


def test_device_lifecycle_and_chat(client, admin):
    r = client.post("/api/admin/devices", json={"name": "Handy", "kind": "pwa", "room": "Flur"}, headers=admin)
    data = r.json()
    assert data["pair_url"].endswith(f"#pair={data['token']}") and data["qr_svg"].startswith("<svg")
    auth = {"Authorization": f"Bearer {data['token']}"}
    me = client.get("/api/me", headers=auth).json()
    assert me["name"] == "Handy" and me["private"] is False
    reply = client.post("/api/chat", json={"text": "Wie spät ist es?"}, headers=auth).json()
    assert reply["reply"].startswith("Es ist") and reply["route"] == "fast"
    assert client.patch("/api/me", json={"private": True}, headers=auth).json()["private"] is True
    ticket = client.post("/api/ws-ticket", headers=auth).json()["ticket"]
    assert len(ticket) > 10
    # Token erneuern → altes ungültig
    new = client.post(f"/api/admin/devices/{data['id']}/rotate", headers=admin).json()["token"]
    assert client.get("/api/me", headers=auth).status_code == 401
    assert client.get("/api/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200
    client.delete(f"/api/admin/devices/{data['id']}", headers=admin)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {new}"}).status_code == 401


def test_cyd_provisioning_info(client, admin):
    data = client.post("/api/admin/devices", json={"name": "Küche", "kind": "cyd"}, headers=admin).json()
    assert data["provision"]["token"] == data["token"] and data["provision"]["port"] == 8080
    assert "pair_url" not in data


def test_overview_and_router_tools(client, admin):
    o = client.get("/api/admin/overview", headers=admin).json()
    assert o["providers"]["stt"] == "aus" and "warnings" in o and o["timezone"] == "Europe/Berlin"
    t = client.post("/api/admin/router/test", json={"text": "Weck mich morgen um sieben"}, headers=admin).json()
    assert t["intent"] == "alarm_set" and "datetime" in t["slots"]
    ev = client.get("/api/admin/router/eval", headers=admin).json()
    assert ev["total"] > 50 and ev["accuracy"] > 0.8


def test_router_correction_retrains(client, admin, services):
    auth_dev = client.post("/api/admin/devices", json={"name": "T", "kind": "pwa"}, headers=admin).json()
    client.post("/api/chat", json={"text": "Schnapp dir die Uhrzeit"},
                headers={"Authorization": f"Bearer {auth_dev['token']}"})
    log = client.get("/api/admin/router-log?limit=5", headers=admin).json()
    entry = next(e for e in log if e["text"] == "Schnapp dir die Uhrzeit")
    r = client.post(f"/api/admin/router-log/{entry['id']}/correct", json={"intent": "time_now"}, headers=admin)
    assert r.json()["ok"]
    assert "Schnapp dir die Uhrzeit" in services.extra_examples()["time_now"]


def test_memory_admin(client, admin):
    client.post("/api/admin/memory", json={"text": "der Schlüssel liegt im Flur"}, headers=admin)
    items = client.get("/api/admin/memory", headers=admin).json()
    assert items[0]["text"] == "der Schlüssel liegt im Flur"
    assert client.delete(f"/api/admin/memory/{items[0]['id']}", headers=admin).json()["ok"]


def test_firmware_upload_and_download(client, admin, services):
    image = bytes([0xE9]) + b"\x00" * 2000 + b"JARVIS_FW_VERSION=9.9.1\x00" + b"\x00" * 100
    r = client.post("/api/admin/firmware/upload", headers=admin, data={"variant": "cyd"},
                    files={"file": ("firmware.bin", image, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["version"] == "9.9.1"
    assert any(v["variant"] == "cyd" and v["version"] == "9.9.1"
               for v in client.get("/api/admin/firmware", headers=admin).json()["variants"])
    assert client.get("/api/firmware/cyd/firmware.bin").status_code == 401
    assert client.get("/api/firmware/cyd/firmware.bin", headers=admin).content == image
    bad = client.post("/api/admin/firmware/upload", headers=admin, data={"variant": "cyd"},
                      files={"file": ("x.bin", b"kein image" * 200, "application/octet-stream")})
    assert bad.status_code == 400


def test_cyd_websocket_text_and_events(client, admin, services):
    data = client.post("/api/admin/devices", json={"name": "Küche", "kind": "cyd"}, headers=admin).json()
    headers = {"Authorization": f"Bearer {data['token']}"}
    with client.websocket_connect("/ws/cyd", headers=headers) as ws:
        ws.send_text(json.dumps({"type": "hello", "fw": "0.3.0", "board": "cyd"}))
        ws.send_text(json.dumps({"type": "text", "content": "Wie spät ist es?"}))
        events = []
        for _ in range(40):              # Startzustand und Antwort kommen nebenläufig – beides abwarten
            events.append(json.loads(ws.receive_text()))
            seen = {e["type"] for e in events}
            if {"turn_done", "timers", "volume"} <= seen:
                break
        disconnect(ws, services)
    types = [e["type"] for e in events]
    assert "timers" in types and "private" in types and "volume" in types
    answer = next(e for e in events if e["type"] == "text" and e["role"] == "assistant")
    assert answer["content"].startswith("Es ist") and answer["meta"]["route"] == "fast"


def test_ws_rejects_without_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/ws/cyd") as ws:
        ws.receive_text()
    assert e.value.code == 4401


def test_legacy_query_token_still_works(client, admin, services):
    data = client.post("/api/admin/devices", json={"name": "Alt", "kind": "cyd"}, headers=admin).json()
    with client.websocket_connect(f"/ws/cyd?token={data['token']}") as ws:
        first = json.loads(ws.receive_text())
        disconnect(ws, services)
    assert first["type"] in ("hello", "private", "timers", "volume", "state")
