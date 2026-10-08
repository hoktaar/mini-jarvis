"""Dashboard-Endpunkt, Home-Assistant-Kacheln, Live-Feed und Systemwerte."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import jarvis.main as main
from jarvis.config import HomeAssistantCfg
from jarvis.feed import Feed
from jarvis.homeassistant import HomeAssistant
from jarvis.system_stats import SystemStats

STATES = [
    {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {"friendly_name": "Licht Wohnzimmer"}},
    {"entity_id": "lock.haustuer", "state": "locked", "attributes": {"friendly_name": "Haustür"}},
    {"entity_id": "climate.bad", "state": "heat", "attributes": {"friendly_name": "Bad", "current_temperature": 21.5}},
    {"entity_id": "sensor.aussen", "state": "12.4", "attributes": {"friendly_name": "Außen", "unit_of_measurement": "°C"}},
    {"entity_id": "scene.film", "state": "scening", "attributes": {"friendly_name": "Filmabend"}},
    {"entity_id": "switch.kaffee", "state": "unavailable", "attributes": {"friendly_name": "Kaffee"}},
    {"entity_id": "light.nicht_freigegeben", "state": "off", "attributes": {}},
]


class FakeHA:
    """Minimaler Home-Assistant-REST-Server über httpx.MockTransport."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer geheim"
        if request.url.path == "/api/states":
            return httpx.Response(200, json=STATES)
        if request.url.path.startswith("/api/services/"):
            self.calls.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json=[])
        return httpx.Response(404)


@pytest.fixture
def ha(monkeypatch):
    fake = FakeHA()
    cfg = HomeAssistantCfg(enabled=True, url="http://ha.local:8123",
                           entities=[s["entity_id"] for s in STATES if "nicht" not in s["entity_id"]])
    home = HomeAssistant(cfg, "geheim")
    monkeypatch.setattr(home, "_client", lambda: httpx.AsyncClient(
        base_url="http://ha.local:8123", transport=httpx.MockTransport(fake.handler),
        headers={"Authorization": "Bearer geheim"}))
    return home, fake


def test_tile_mapping():
    tile = HomeAssistant.tile(STATES[0])
    assert tile["display"] == "an" and tile["on"] and tile["toggle"] and tile["icon"] == "bulb"
    assert HomeAssistant.tile(STATES[2])["display"] == "21.5°"
    assert HomeAssistant.tile(STATES[3])["display"] == "12.4°C"
    scene = HomeAssistant.tile(STATES[4])
    assert scene["activate"] and not scene["toggle"] and scene["display"] == "Szene starten"
    assert HomeAssistant.tile(STATES[5])["available"] is False
    assert HomeAssistant.tile(STATES[1])["toggle"] is False          # Schlösser nie per Kachel


async def test_tiles_only_configured_entities(ha):
    home, _ = ha
    tiles = await home.tiles()
    ids = [t["entity_id"] for t in tiles]
    assert "light.nicht_freigegeben" not in ids and ids[0] == "light.wohnzimmer"


async def test_toggle_services_and_permissions(ha):
    home, fake = ha
    await home.tiles()
    result = await home.toggle("light.wohnzimmer")
    assert result["name"] == "Licht Wohnzimmer"
    await home.toggle("scene.film")
    assert fake.calls == [("/api/services/light/toggle", {"entity_id": "light.wohnzimmer"}),
                          ("/api/services/scene/turn_on", {"entity_id": "scene.film"})]
    with pytest.raises(PermissionError):
        await home.toggle("light.nicht_freigegeben")       # nicht freigegeben
    with pytest.raises(PermissionError):
        await home.toggle("lock.haustuer")                 # freigegeben, aber nicht schaltbar


def test_feed_latest_order_and_limit():
    feed = Feed(size=3)
    for i in range(5):
        feed.add(f"Ereignis {i}", "info")
    latest = feed.latest(10)
    assert [f["text"] for f in latest] == ["Ereignis 4", "Ereignis 3", "Ereignis 2"]


def test_system_stats_snapshot(tmp_path):
    stats = SystemStats({"Daten": tmp_path})
    stats.sample()
    snap = stats.snapshot()
    assert 0 <= snap["cpu"] <= 100 and 0 < snap["ram"] <= 100
    assert snap["disks"]["Daten"]["total_gb"] > 0
    assert len(snap["history"]["down"]) == 2               # sample() + snapshot()


@pytest.fixture
def client(services):
    main.services = services
    with TestClient(main.app) as c:
        yield c
    main.services = None


@pytest.fixture
def device(client, services):
    data = client.post("/api/admin/devices", json={"name": "Tablet", "kind": "pwa", "room": "Küche"},
                       headers={"X-Admin-Token": services.secrets["admin_token"]}).json()
    return {"Authorization": f"Bearer {data['token']}"}


def test_dashboard_without_home_assistant(client, device):
    assert client.get("/api/dashboard").status_code == 401
    client.post("/api/chat", json={"text": "Stelle einen Timer auf 5 Minuten"}, headers=device)
    d = client.get("/api/dashboard", headers=device).json()
    assert d["home"] == {"configured": False, "tiles": []}
    assert d["devices"]["total"] == 1 and d["devices"]["rooms"] == ["Küche"]
    assert d["upcoming"][0]["kind"] == "timer"
    assert d["recent"][0]["text"].startswith("Stelle einen Timer")
    assert "cpu" in d["system"] and "history" in d["system"]
    assert {c["name"] for c in d["capabilities"] if c["ok"]} >= {"Timer & Wecker", "Wetter"}
    assert d["budget"] is None
    assert client.post("/api/home/light.x/toggle", headers=device).status_code == 400


def test_dashboard_with_home_assistant(client, device, services, ha):
    services.home = ha[0]
    d = client.get("/api/dashboard", headers=device).json()
    assert d["home"]["configured"] and len(d["home"]["tiles"]) == 6
    assert client.post("/api/home/light.wohnzimmer/toggle", headers=device).json()["ok"]
    assert client.post("/api/home/light.nicht_freigegeben/toggle", headers=device).status_code == 403
    feed = client.get("/api/dashboard", headers=device).json()["feed"]
    assert any(f["text"].startswith("Licht Wohnzimmer geschaltet") for f in feed)
