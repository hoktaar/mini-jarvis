"""Einstellungen aus der Verwaltung: lesen, prüfen, schreiben (ohne YAML anzufassen)."""

import pytest
import yaml
from fastapi.testclient import TestClient

import jarvis.main as main


@pytest.fixture
def client(services):
    main.services = services
    with TestClient(main.app) as c:
        yield c
    main.services = None


@pytest.fixture
def admin(services):
    return {"X-Admin-Token": services.secrets["admin_token"]}


def put(client, admin, **body):
    return client.put("/api/admin/settings", json=body, headers=admin)


def test_settings_read(client, admin, services):
    r = client.get("/api/admin/settings", headers=admin).json()
    assert r["values"]["providers"]["llm"]["local"]["model"] == "mock"
    assert r["values"]["location"]["name"] == "Berlin"
    assert "Europe/Berlin" in r["timezones"] and r["readonly"] is None
    assert r["secrets"]["openai_api_key"] == {"set": False, "source": None, "label": "OpenAI"}
    assert "admin_token" not in r["secrets"]
    assert r["secret_names"]["anthropic"] == "anthropic_api_key"
    assert r["whitelist"]["jellyfin"] == ["status", "start", "stop", "restart"]
    assert services.secrets["admin_token"] not in str(r)


def test_settings_save_and_restart_flag(client, admin, services):
    r = put(client, admin, changes={"location.name": "Leipzig", "location.latitude": 51.34, "location.longitude": 12.37,
                                    "providers.llm.cloud.enabled": True, "providers.llm.cloud.model": "claude-sonnet-5-5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restart_pending"]["core"] is True
    assert body["values"]["location"]["name"] == "Leipzig"
    assert any("API-Schlüssel fehlt" in w for w in body["warnings"])
    saved = yaml.safe_load((services.config_dir / "config.yaml").read_text())
    assert saved["location"]["latitude"] == 51.34 and saved["providers"]["llm"]["cloud"]["enabled"] is True
    assert services.cfg.location.name == "Berlin"                 # wirkt erst nach dem Neustart
    assert client.get("/api/admin/overview", headers=admin).json()["restart_pending"]["core"] is True
    audit = services.db.query("SELECT detail FROM audit_log WHERE action = 'settings'")
    assert "location.name" in audit[0]["detail"]


def test_settings_validation_errors(client, admin, services):
    before = (services.config_dir / "config.yaml").read_text()
    r = put(client, admin, changes={"providers.llm.cloud.type": "bogus", "location.timezone": "Mond/Krater",
                                    "location.latitude": 123, "homeassistant.url": "homeassistant.local"})
    assert r.status_code == 422
    paths = {e["path"] for e in r.json()["detail"]["errors"]}
    assert "providers.llm.cloud.type" in paths
    r = put(client, admin, changes={"location.timezone": "Mond/Krater", "location.latitude": 123, "homeassistant.url": "ha.local"})
    paths = {e["path"]: e["message"] for e in r.json()["detail"]["errors"]}
    assert set(paths) == {"location.timezone", "location.latitude", "homeassistant.url"}
    assert "Zeitzone" in paths["location.timezone"]
    assert (services.config_dir / "config.yaml").read_text() == before        # nichts geschrieben


def test_settings_rejects_unknown_and_locked_paths(client, admin):
    assert put(client, admin, changes={"providers.llm.magic": 1}).status_code == 400
    assert put(client, admin, changes={"location.name.x": 1}).status_code == 400
    r = put(client, admin, changes={"server.port": 9000})
    assert r.status_code == 400 and "Port-Zuordnung" in r.json()["detail"]["message"]


def test_live_setting_needs_no_restart(client, admin, services):
    r = put(client, admin, changes={"firmware.auto_update": True}).json()
    assert r["restart_pending"]["core"] is False
    assert services.firmware.auto_update is True and services.cfg.firmware.auto_update is True


def test_secrets_are_written_but_never_returned(client, admin, services, monkeypatch):
    r = put(client, admin, secrets={"openai_api_key": "sk-test-123", "my_mcp_token": "abc"})
    assert r.status_code == 200
    assert r.json()["secrets"]["openai_api_key"]["set"] is True
    assert "sk-test-123" not in r.text
    raw = yaml.safe_load((services.config_dir / "secrets.yaml").read_text())
    assert raw["openai_api_key"] == "sk-test-123" and raw["admin_token"] == services.secrets["admin_token"]
    assert "sk-test-123" not in client.get("/api/admin/settings", headers=admin).text
    put(client, admin, secrets={"openai_api_key": ""})
    assert yaml.safe_load((services.config_dir / "secrets.yaml").read_text())["openai_api_key"] == ""
    assert put(client, admin, secrets={"admin_token": "x"}).status_code == 400
    assert put(client, admin, secrets={"Bad Name": "x"}).status_code == 400
    monkeypatch.setenv("JARVIS_GROQ_API_KEY", "aus-env")
    assert client.get("/api/admin/settings", headers=admin).json()["secrets"]["groq_api_key"]["source"] == "env"
    r = put(client, admin, secrets={"groq_api_key": "neu"})
    assert r.status_code == 400 and "Container-Vorlage" in r.json()["detail"]["message"]


def test_whitelist(client, admin, services):
    r = put(client, admin, whitelist={"plex": ["status", "restart"], "jellyfin": ["status"]})
    assert r.status_code == 200
    data = yaml.safe_load((services.config_dir / "whitelist.yaml").read_text())
    assert data["containers"] == {"plex": ["status", "restart"], "jellyfin": ["status"]}
    assert put(client, admin, whitelist={"bad name!": ["status"]}).status_code == 400
    assert put(client, admin, whitelist={"plex": ["exec"]}).status_code == 400


def test_mcp_secrets_masked_and_kept(client, admin, services):
    path = services.config_dir / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["mcp_servers"] = [{"name": "extra", "enabled": False, "transport": "http", "url": "https://mcp.example/mcp",
                           "headers": {"Authorization": "Bearer geheim-123", "X-Ref": "${secret:my_token}"},
                           "env": {"API_KEY": "wörtlich", "MODE": "fast"}, "tools": ["a"]}]
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    values = client.get("/api/admin/settings", headers=admin).json()["values"]
    m = values["mcp_servers"][0]
    assert m["headers"] == {"Authorization": "***", "X-Ref": "${secret:my_token}"}
    assert m["env"] == {"API_KEY": "***", "MODE": "fast"}
    m["tools"] = ["a", "b"]
    assert put(client, admin, changes={"mcp_servers": values["mcp_servers"]}).status_code == 200
    saved = yaml.safe_load(path.read_text())["mcp_servers"][0]
    assert saved["headers"]["Authorization"] == "Bearer geheim-123" and saved["env"]["API_KEY"] == "wörtlich"
    assert saved["tools"] == ["a", "b"]


def test_readonly_mode(client, admin, monkeypatch):
    monkeypatch.setenv("JARVIS_CONFIG_READONLY", "true")
    assert "gesperrt" in client.get("/api/admin/settings", headers=admin).json()["readonly"]
    assert put(client, admin, changes={"location.name": "x"}).status_code == 409


def test_scripts_editor(client, admin, services):
    spec = {"path": "/scripts/licht.sh", "description": "Licht im Flur", "confirm": False, "timeout": 5,
            "params": {"stufe": {"type": "int", "required": True, "min": 0, "max": 100}}}
    r = client.put("/api/admin/scripts/flur_licht", json=spec, headers=admin)
    assert r.status_code == 200, r.text
    saved = yaml.safe_load((services.config_dir / "scripts.yaml").read_text())["scripts"]
    assert saved["flur_licht"]["params"]["stufe"] == {"type": "int", "required": True, "min": 0, "max": 100}
    assert "say_hello" in saved                                   # andere bleiben stehen
    assert "flur_licht" in services.scripts
    listed = {s["id"]: s for s in client.get("/api/admin/scripts", headers=admin).json()}
    assert listed["flur_licht"]["path"] == "/scripts/licht.sh"
    bad = dict(spec, params={"x": {"type": "str", "pattern": "("}})
    assert client.put("/api/admin/scripts/flur_licht", json=bad, headers=admin).status_code == 400
    assert client.put("/api/admin/scripts/Böse", json=spec, headers=admin).status_code == 400
    outside = dict(spec, path="/etc/passwd")
    assert client.put("/api/admin/scripts/raus", json=outside, headers=admin).status_code == 400
    assert client.delete("/api/admin/scripts/flur_licht", headers=admin).status_code == 200
    assert "flur_licht" not in yaml.safe_load((services.config_dir / "scripts.yaml").read_text())["scripts"]
    assert "flur_licht" not in services.scripts


def test_script_files(client, admin, tmp_path, monkeypatch):
    root = tmp_path / "skripte"
    root.mkdir()
    (root / "licht.sh").write_text("#!/bin/sh\necho $1\n")
    (root / "licht.sh").chmod(0o755)
    (root / "notiz.txt").write_text("x")
    monkeypatch.setenv("JARVIS_SCRIPTS_ROOT", str(root))
    files = client.get("/api/admin/script-files", headers=admin).json()
    assert files["root"] == str(root)
    assert files["files"] == [{"path": str(root / "licht.sh"), "executable": True},
                              {"path": str(root / "notiz.txt"), "executable": False}]


def test_intent_examples(client, admin, services):
    d = client.get("/api/admin/intents/time_now", headers=admin).json()
    assert d["tool"] == "get_time" and "Wie spät ist es?" in d["examples"] and d["custom"] == []
    assert client.post("/api/admin/intents/time_now/examples", json={"text": "Was zeigt die Uhr"}, headers=admin).status_code == 200
    d = client.get("/api/admin/intents/time_now", headers=admin).json()
    assert [c["text"] for c in d["custom"]] == ["Was zeigt die Uhr"]
    assert services.extra_examples()["time_now"] == ["Was zeigt die Uhr"]
    assert client.delete(f"/api/admin/intents/examples/{d['custom'][0]['id']}", headers=admin).status_code == 200
    assert services.extra_examples() == {}
    assert client.get("/api/admin/intents/gibtsnicht", headers=admin).status_code == 404


def test_admin_token_rotation(client, admin, services):
    r = client.post("/api/admin/token/rotate", headers=admin)
    token = r.json()["token"]
    assert token != admin["X-Admin-Token"]
    assert client.get("/api/admin/settings", headers=admin).status_code == 401
    assert client.get("/api/admin/settings", headers={"X-Admin-Token": token}).status_code == 200
    assert yaml.safe_load((services.config_dir / "secrets.yaml").read_text())["admin_token"] == token


def test_restart_and_health(client, admin):
    assert client.post("/api/admin/restart", headers=admin).status_code == 409       # kein Serverbetrieb im Test
    assert isinstance(client.get("/api/health").json()["boot"], int)


# ---------------------------------------------------------------- ohne API
def test_roundtrip_keeps_comments(config_dir):
    from jarvis.settings import ConfigFiles, apply_changes, validate

    files = ConfigFiles(config_dir)
    before = (config_dir / "config.yaml").read_text()
    raw = files.load("config.yaml")
    apply_changes(raw, {"providers.llm.local.model": "qwen3:14b", "homeassistant.entities": ["light.flur"],
                        "persona": "Zeile eins\nZeile zwei"})
    validate(raw, {})
    files.save("config.yaml", raw)
    after = (config_dir / "config.yaml").read_text()
    assert "# Mini-Jarvis Hauptkonfiguration" in after
    assert "primary: local        # local | cloud – wer normale Fragen beantwortet" in after
    assert "model: qwen3:14b" in after and "entities: [light.flur]" in after
    assert "persona: |\n  Zeile eins\n  Zeile zwei\n" in after
    changed = [line for line in after.splitlines() if line not in before.splitlines()]
    assert len(changed) <= 5, changed
    backups = list((config_dir / "backups").glob("config.yaml.*"))
    assert len(backups) == 1 and backups[0].read_text() == before


def test_runner_reloads_scripts(tmp_path):
    import os
    import time

    from jarvis.runner.server import Registry

    root = tmp_path / "s"
    root.mkdir()
    f = tmp_path / "scripts.yaml"
    f.write_text("scripts: {}\n")
    reg = Registry(str(f), str(root))
    assert reg.get() == {}
    f.write_text(f"scripts:\n  a:\n    path: {root}/a.sh\n")
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 10_000_000))
    assert list(reg.get()) == ["a"]
    f.write_text("scripts: [kaputt\n")
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 20_000_000))
    assert list(reg.get()) == ["a"]                               # alte Liste bleibt aktiv


def test_container_restart_reasons(client, admin, services, monkeypatch):
    from jarvis.config import shell_env

    for k, v in shell_env(services.cfg).items():                  # so, wie der Container gestartet wurde
        monkeypatch.setenv(k, v)
    r = put(client, admin, changes={"location.name": "Ort"}).json()
    assert r["restart_pending"]["container"] == []
    r = put(client, admin, changes={"providers.llm.local.base_url": "http://192.168.1.50:11434/v1"}).json()
    assert r["restart_pending"]["container"] == ["eingebautes Ollama an/aus"]
