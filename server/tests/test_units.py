"""Einzeltests: Bestätigung, Timer, Konfiguration, Migration, HAProxy, TLS, Firmware, MCP, Budget."""

import asyncio
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis.router.confirm import is_repeat_request, strict_yes_no

TZ = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize("text,expected", [
    ("Ja", 0.97), ("Ja, mach das", 0.97), ("Okay", 0.97), ("Jawohl, sofort", 0.97),
    ("Wie bitte?", 0.5), ("Okay, und wie wird das Wetter?", 0.5), ("Klar ist das blöd", 0.5),
    ("Nein", 0.03), ("Bitte nicht", 0.03), ("Ja, warum nicht", 0.03), ("Mhm", 0.5),
])
def test_strict_yes_no(text, expected):
    assert strict_yes_no(text) == expected


def test_repeat_request():
    assert is_repeat_request("Wie bitte?") and is_repeat_request("Nochmal bitte")
    assert not is_repeat_request("Ja")


# ---------------------------------------------------------------- Timer
async def test_timer_ring_ack_snooze(tmp_path):
    from jarvis.db import Database
    from jarvis.tools.timers import TimerService

    fired = []

    async def notify(row):
        fired.append(row["id"])

    ts = TimerService(Database(tmp_path / "t.db"), notify)
    tid = ts.add("alarm", time.time() - 1, "Aufstehen")
    await ts.check_due()
    assert fired == [tid] and [r["id"] for r in ts.ringing()] == [tid]
    new = ts.snooze(tid, 5)
    assert not ts.ringing() and ts.get(new)["due"] > time.time() + 290
    ts.add("timer", time.time() - 1)
    await ts.check_due()
    assert len(ts.ack()) == 1 and not ts.ringing()


async def test_timer_notify_error_does_not_stop(tmp_path):
    from jarvis.db import Database
    from jarvis.tools.timers import TimerService

    async def broken(row):
        raise RuntimeError("Gerät weg")

    ts = TimerService(Database(tmp_path / "t.db"), broken)
    ts.add("timer", time.time() - 1)
    ts.add("timer", time.time() - 1)
    assert len(await ts.check_due()) == 2       # beide markiert, keine Exception


async def test_timer_tools_and_labels(tmp_path):
    from jarvis.db import Database
    from jarvis.tools.registry import ToolContext
    from jarvis.tools.timers import TimerService

    ts = TimerService(Database(tmp_path / "t.db"))
    tools = {t.name: t for t in ts.tools()}
    r = await tools["set_timer"].handler({"duration": 300, "label": "Pizza"}, ToolContext())
    assert r.speech == "Pizza-Timer, 5 Minuten."
    await tools["set_timer"].handler({"duration": 60}, ToolContext())
    r = await tools["cancel_timer"].handler({"label": "pizza"}, ToolContext())
    assert r.ok and [t["label"] for t in ts.active()] == [""]
    r = await tools["set_alarm"].handler({"datetime": "morgen um 7"}, ToolContext())
    assert r.ok and "morgen um 7:00 Uhr" in r.speech
    r = await tools["set_reminder"].handler({"datetime": "2020-01-01T10:00", "text": "x"}, ToolContext())
    assert not r.ok and "Vergangenheit" in r.speech


# ---------------------------------------------------------------- Konfiguration
def test_config_legacy_and_secrets(tmp_path, monkeypatch):
    from jarvis.config import load_config, shell_env

    (tmp_path / "config.yaml").write_text(
        "server: {web_port: 9000, public_base_url: 'https://j.lan'}\n"
        "gpu: {comfyui_mode: true}\n"
        "mcp_servers:\n  - {name: ha, transport: http, url: 'http://ha:8123/api/mcp', "
        "headers: {Authorization: 'Bearer ${secret:homeassistant_token}'}}\n")
    (tmp_path / "secrets.yaml").write_text("homeassistant_token: geheim\n")
    monkeypatch.setenv("JARVIS_HOSTS", "jarvis.lan, 10.0.0.5")
    cfg = load_config(tmp_path)
    assert cfg.server.port == 9000 and cfg.server.public_url == "https://j.lan"
    assert cfg.gpu.comfyui_mode == "on"
    assert cfg.mcp_servers[0].headers["Authorization"] == "Bearer geheim"
    assert cfg.server.https.hosts == ["jarvis.lan", "10.0.0.5"]
    env = shell_env(cfg)
    assert env["OLLAMA_KEEP_ALIVE"] == "1m" and env["JARVIS_OLLAMA_AUTOSTART"] == "true"


def test_ensure_config_generates_admin_token(tmp_path):
    from jarvis.config import ensure_config_dir, load_secrets

    ensure_config_dir(tmp_path)
    token = load_secrets(tmp_path)["admin_token"]
    assert len(token) > 30 and (tmp_path / "intents.yaml").exists()
    ensure_config_dir(tmp_path)
    assert load_secrets(tmp_path)["admin_token"] == token
    assert oct((tmp_path / "secrets.yaml").stat().st_mode)[-3:] == "600"


def test_cloud_only_config():
    from jarvis.config import JarvisConfig, cloud_services, config_warnings, shell_env

    cfg = JarvisConfig.model_validate({"providers": {
        "stt": {"type": "deepgram"}, "tts": {"type": "elevenlabs", "voice": "abc"},
        "llm": {"primary": "cloud", "local": {"enabled": False},
                "cloud": {"enabled": True, "type": "openai", "model": "gpt-5-mini"}}}})
    assert len(cloud_services(cfg)) == 3
    assert shell_env(cfg)["JARVIS_OLLAMA_AUTOSTART"] == "false"
    w = " ".join(config_warnings(cfg, {"openai_api_key": "x"}))
    assert "deepgram_api_key" in w and "elevenlabs_api_key" in w and "openai_api_key" not in w


# ---------------------------------------------------------------- Datenbank
def test_migration_from_v1(tmp_path):
    from jarvis.db import MIGRATIONS, Database

    path = tmp_path / "alt.db"
    con = sqlite3.connect(path)
    con.executescript(MIGRATIONS[0])
    con.execute("INSERT INTO devices (name, kind, token_hash, created) VALUES ('a','cyd','h',1)")
    con.commit()
    con.close()
    db = Database(path)
    assert db.version == len(MIGRATIONS)
    row = db.query("SELECT settings, last_seen FROM devices")[0]
    assert row["settings"] == "{}"
    db.execute("INSERT INTO memories (text, created) VALUES ('x', 1)")


def test_purge(tmp_path):
    from jarvis.db import Database

    db = Database(tmp_path / "p.db")
    db.execute("INSERT INTO router_log (ts, text) VALUES (?, 'alt')", (time.time() - 40 * 86400,))
    db.execute("INSERT INTO router_log (ts, text) VALUES (?, 'neu')", (time.time(),))
    assert db.purge(30) == 1
    assert [r["text"] for r in db.query("SELECT text FROM router_log")] == ["neu"]


# ---------------------------------------------------------------- Docker-Proxy
def test_haproxy_rules_follow_whitelist():
    from jarvis.mcp_servers.haproxy_gen import render

    cfg = render({"jellyfin": {"status", "restart"}, "nextcloud": {"status"}, "bad name": {"status"}})
    assert "containers/(jellyfin|nextcloud)/json$" in cfg
    assert "containers/(jellyfin)/restart$" in cfg
    assert "do_stop" not in cfg and "bad name" not in cfg
    assert cfg.strip().endswith("server docker /var/run/docker.sock")
    assert "containers/json" not in cfg        # keine Liste aller Container


# ---------------------------------------------------------------- TLS
def test_tls_ca_and_server_cert(tmp_path):
    from jarvis.tls import cert_info, ensure_server_cert

    crt, key = ensure_server_cert(tmp_path, ["jarvis.lan", "192.168.1.144"])
    info = cert_info(crt)
    assert "jarvis.lan" in info["names"] and "192.168.1.144" in info["names"]
    before = crt.read_bytes()
    ensure_server_cert(tmp_path, ["jarvis.lan"])           # nichts Neues → unverändert
    assert crt.read_bytes() == before
    ensure_server_cert(tmp_path, ["neu.lan"])              # neuer Name → neu ausgestellt
    assert "neu.lan" in cert_info(crt)["names"] and (tmp_path / "ca.crt").exists()


# ---------------------------------------------------------------- Firmware
async def test_firmware_offer(tmp_path):
    from jarvis.firmware import FirmwareManager, parse_version

    assert parse_version("0.10.1") > parse_version("0.9.9")
    fm = FirmwareManager(tmp_path, auto_update=True, builtin_dir=tmp_path / "builtin")
    image = bytes([0xE9]) + b"\x00" * 1500 + b"JARVIS_FW_VERSION=0.4.0\x00"
    fm.upload("cyd", image)
    assert fm.update_for("cyd", "0.3.0")["version"] == "0.4.0"
    assert fm.update_for("cyd", "0.4.0") is None

    sent = []

    class FakeDevices:
        def update(self, device_id, settings=None, **kw):
            device.settings.update(settings or {})
            return device

    class FakeSession:
        services = type("S", (), {"devices": FakeDevices()})()

        async def emit(self, ev):
            sent.append(ev)

    from jarvis.devices import Device

    device = Device(1, "Küche", "cyd", "")
    s = FakeSession()
    s.device = device
    assert await fm.maybe_offer(s, "cyd", "0.3.0")
    assert sent[0]["type"] == "ota" and sent[0]["path"] == "/api/firmware/cyd/firmware.bin"


# ---------------------------------------------------------------- MCP
async def test_mcp_manager_with_stdio_server(tmp_path):
    from jarvis.config import McpServerCfg
    from jarvis.mcp import McpManager
    from jarvis.tools.registry import ToolContext, ToolRegistry

    reg = ToolRegistry()
    server_dir = str(Path(__file__).resolve().parents[1])
    cfg = McpServerCfg(name="dockertest", command=sys.executable, args=["-m", "jarvis.mcp_servers.docker_mcp"],
                       env={"PYTHONPATH": server_dir, "JARVIS_CONFIG_DIR": str(tmp_path),
                            "JARVIS_DOCKER_PROXY": "http://127.0.0.1:9"},
                       tools=["container_status"], risk="read", taint=True)
    mgr = McpManager([cfg], reg)
    mgr.start()
    for _ in range(100):
        if reg.get("container_status"):
            break
        await asyncio.sleep(0.1)
    try:
        tool = reg.get("container_status")
        assert tool is not None and tool.source == "mcp:dockertest" and tool.taint
        assert reg.get("container_action") is None             # nicht in der Allowlist
        result = await tool.handler({"name": ""}, ToolContext())
        assert result.taint and isinstance(result.speech, str)
    finally:
        await mgr.close()


# ---------------------------------------------------------------- Budget, Gedächtnis, Router
def test_budget(tmp_path):
    from jarvis.budget import Budget
    from jarvis.config import CloudLlmCfg
    from jarvis.db import Database

    b = Budget(Database(tmp_path / "b.db"), CloudLlmCfg(budget_eur_day=0.01, price_input_eur_per_mtok=10,
                                                         price_output_eur_per_mtok=10))
    assert b.allows()
    b.record("cloud", "m", 1000, 0)          # 0,01 €
    assert not b.allows() and b.summary()["today"] == pytest.approx(0.01)


def test_memory_phrasing():
    from jarvis.tools.memory import normalize_fact, to_second_person

    assert normalize_fact("ich Tee mag") == "ich mag Tee"
    assert to_second_person(normalize_fact("mein Auto in der Garage steht")) == "dein Auto steht in der Garage"


async def test_router_dialog_and_eval(intents_data):
    from jarvis.config import RouterCfg
    from jarvis.router.classifier import LocalExampleClassifier
    from jarvis.router.eval import evaluate, load_cases
    from jarvis.router.router import Route, Router, load_intents

    intents = load_intents(intents_data)
    clf = LocalExampleClassifier({n: i.examples for n, i in intents.items()})
    router = Router(intents, clf, RouterCfg(), known_names=["jellyfin"], scripts=["say_hello", "backup_appdata"])
    d = await router.decide("Starte einen Timer für die Nudeln")
    assert d.route == Route.ASK_SLOT and d.dialog.missing == ["duration"]
    d2 = await router.decide("zwölf Minuten", dialog=d.dialog)
    assert d2.route == Route.FAST and d2.slots == {"label": "Nudeln", "duration": 720}
    d = await router.decide("Wie wird das Wetter morgen?")
    assert d.route == Route.FAST and d.slots == {"day_offset": 1}
    d = await router.decide("Wie ist der Status der Container?")
    assert d.route == Route.FAST and d.slots == {}
    d = await router.decide("Lösch den Wecker")
    assert d.intent == "alarm_cancel"
    report = await evaluate(router, load_cases())
    assert report.accuracy >= 0.85, report.errors       # Trigramm-Untergrenze; mit e5 deutlich höher


def test_wake_prefix_and_hallucinations():
    from jarvis.processors import clean_transcript

    assert clean_transcript("Hey Jarvis, wie spät ist es?") == "wie spät ist es?"
    assert clean_transcript("Untertitel im Auftrag des ZDF, 2020") == ""
    assert clean_transcript("Jarvis") == ""


def test_slots_now_tz():
    from jarvis.router.slots import parse_datetime

    now = datetime(2026, 10, 8, 12, 0, tzinfo=TZ)                    # Donnerstag
    assert parse_datetime("Wecker für Montag um acht", now) == datetime(2026, 10, 12, 8, 0, tzinfo=TZ)
    assert parse_datetime("Weck mich um halb sieben", now) == datetime(2026, 10, 9, 6, 30, tzinfo=TZ)
    assert parse_datetime("um sieben abends", now) == datetime(2026, 10, 8, 19, 0, tzinfo=TZ)
    assert parse_datetime("am 12.10. um 9 Uhr", now) == datetime(2026, 10, 12, 9, 0, tzinfo=TZ)
