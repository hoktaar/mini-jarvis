"""Parakeet (lokale Spracherkennung auf der CPU) und die Transkriptions-Schnittstelle /v1/audio/transcriptions."""

import io

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient

import jarvis.main as main
from jarvis import parakeet, providers


class FakeStream:
    def __init__(self, rec):
        self.rec, self.audio = rec, None
        self.result = type("R", (), {"text": ""})()

    def accept_waveform(self, rate, audio):
        assert rate == 16000 and audio.dtype == np.float32
        self.audio = audio


class FakeRecognizer:
    """Liefert je Stück „wortN“ – oder nichts für Stücke, die länger als `empty_above` Sekunden sind."""

    def __init__(self, empty_above=None):
        self.calls, self.empty_above = [], empty_above

    def create_stream(self):
        return FakeStream(self)

    def decode_stream(self, s):
        self.calls.append(s.audio)
        long = self.empty_above and len(s.audio) > self.empty_above * 16000
        s.result.text = "" if long else f" wort{len(self.calls)} "


def test_split_cuts_long_audio_at_a_pause():
    audio = np.full(200 * 16000, 0.3, dtype=np.float32)
    audio[85 * 16000:85 * 16000 + 8000] = 0.0              # Pause bei 85 s
    parts = list(parakeet.split(audio))
    assert sum(len(p) for p in parts) == len(audio)
    assert all(len(p) <= parakeet.MAX_CHUNK_S * 16000 for p in parts)
    assert abs(len(parts[0]) / 16000 - 85.25) < 0.5         # Schnitt mitten in der Pause
    assert list(parakeet.split(audio[:16000])) and len(list(parakeet.split(audio[:16000]))) == 1


def test_transcribe_boosts_quiet_audio_and_retries_empty_pieces(monkeypatch):
    rec = FakeRecognizer()
    monkeypatch.setattr(parakeet, "get_recognizer", lambda threads=4: rec)
    quiet = np.full(2 * 16000, 0.02, dtype=np.float32)
    assert parakeet.transcribe(quiet) == "wort1"
    assert abs(float(np.abs(rec.calls[0]).max()) - parakeet.TARGET_PEAK) < 1e-6     # angehoben
    loud = np.full(16000, 0.9, dtype=np.float32)
    parakeet.transcribe(loud)
    assert float(np.abs(rec.calls[1]).max()) == pytest.approx(0.9)                 # unverändert

    # Ein langes Stück kommt leer zurück → kürzere Stücke derselben Aufnahme
    rec2 = FakeRecognizer(empty_above=parakeet.RETRY_CHUNK_S)
    monkeypatch.setattr(parakeet, "get_recognizer", lambda threads=4: rec2)
    text = parakeet.transcribe(np.full(50 * 16000, 0.3, dtype=np.float32))
    assert len(rec2.calls) > 2 and text.split() == [f"wort{i}" for i in range(2, len(rec2.calls) + 1)]
    assert all(len(c) <= parakeet.RETRY_CHUNK_S * 16000 for c in rec2.calls[1:])


def test_status_and_missing_model(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "MODELS_DIR", tmp_path)
    st = parakeet.status()
    assert st["installed"] is False and st["downloading"] is False and st["size_mb"] > 500
    d = parakeet.model_dir()
    d.mkdir(parents=True)
    for f in parakeet.MODEL_FILES:
        (d / f).write_bytes(b"x")
    assert parakeet.installed() and parakeet.status()["progress"] == 1.0


async def test_parakeet_stt_service(monkeypatch):
    from pipecat.frames.frames import TranscriptionFrame

    from jarvis.config import JarvisConfig

    seen = {}

    def fake(audio, threads):
        seen["n"], seen["threads"] = len(audio), threads
        return "Mach das Licht an"

    monkeypatch.setattr(parakeet, "transcribe", fake)
    cfg = JarvisConfig.model_validate({"providers": {"stt": {"type": "parakeet", "threads": 2}}})
    assert not cfg.providers.stt.cloud
    stt = providers.make_stt(cfg, {})
    assert not stt.wants_wav_segments
    frames = [f async for f in stt.run_stt((np.zeros(16000, dtype=np.int16)).tobytes())]
    assert isinstance(frames[0], TranscriptionFrame) and frames[0].text == "Mach das Licht an"
    assert seen == {"n": 16000, "threads": 2}


def test_short_clips_are_ignored(monkeypatch):
    from jarvis.config import JarvisConfig

    monkeypatch.setattr(parakeet, "transcribe", lambda *a: pytest.fail("nicht aufrufen"))
    cfg = JarvisConfig.model_validate({"providers": {"stt": {"type": "parakeet"}}})
    assert providers.transcribe_float(cfg, np.zeros(1600, dtype=np.float32)) == ""


# ---------------------------------------------------------------- Schnittstelle
@pytest.fixture
def client(services):
    main.services = services
    with TestClient(main.app) as c:
        yield c
    main.services = None


@pytest.fixture
def admin(services):
    return {"X-Admin-Token": services.secrets["admin_token"]}


def wav(seconds=1.0, rate=44100) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    t = np.arange(int(seconds * rate)) / rate
    sf.write(buf, (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate, format="WAV")
    return buf.getvalue()


def post(client, token=None, data=None, **form):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/v1/audio/transcriptions", headers=headers,
                       files={"file": ("a.wav", wav() if data is None else data, "audio/wav")}, data=form)


def test_transcription_api(client, admin, services, monkeypatch):
    services.cfg.providers.stt.type = "parakeet"
    got = {}

    def fake(cfg, audio):
        got["seconds"] = len(audio) / 16000
        return "Hallo Jarvis"

    monkeypatch.setattr(providers, "transcribe_float", fake)

    # Aus: nicht erreichbar
    assert post(client).status_code == 404
    r = client.put("/api/admin/settings", json={"changes": {"server.transcription_api": True}}, headers=admin)
    assert r.status_code == 200 and r.json()["restart_pending"]["core"] is False        # wirkt sofort
    assert services.cfg.server.transcription_api is True

    # Ohne/mit falschem Token abgelehnt
    assert post(client).status_code == 401
    assert post(client, "falsch").json()["error"]["type"] == "authentication_error"

    info = client.post("/api/admin/transcription/token", headers=admin).json()
    token = info["token"]
    assert token.startswith("jt_") and info["enabled"] and info["engine"] == "parakeet"
    assert yaml.safe_load((services.config_dir / "secrets.yaml").read_text())["transcription_api_token"] == token
    assert "transcription_api_token" not in client.get("/api/admin/settings", headers=admin).json()["secrets"]

    r = post(client, token, model="parakeet", language="de")
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "Hallo Jarvis"}
    assert abs(got["seconds"] - 1.0) < 0.01                                            # 44,1 kHz → 16 kHz
    assert post(client, token, response_format="text").text == "Hallo Jarvis"
    assert post(client, token, response_format="verbose_json").json()["duration"] == pytest.approx(1.0, abs=0.01)
    assert post(client, token, response_format="srt").status_code == 400
    assert post(client, token, language="en").status_code == 400
    assert post(client, token, data=b"kein audio").status_code == 400

    # Geräte-Tokens gekoppelter Geräte gehen auch
    dev = client.post("/api/admin/devices", json={"name": "Laptop", "kind": "pwa"}, headers=admin).json()
    assert post(client, dev["token"]).status_code == 200
    models = client.get("/v1/models", headers={"Authorization": f"Bearer {token}"}).json()
    assert models["data"][0]["id"] == "parakeet"

    # Spracherkennung, die keine Dateien kann
    services.cfg.providers.stt.type = "deepgram"
    assert post(client, token).status_code == 409


def test_transcription_token_cannot_be_set_via_settings(client, admin):
    r = client.put("/api/admin/settings", json={"secrets": {"transcription_api_token": "abc"}}, headers=admin)
    assert r.status_code == 400


def test_parakeet_admin_status(client, admin, monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "MODELS_DIR", tmp_path)
    st = client.get("/api/admin/parakeet", headers=admin).json()
    assert st["installed"] is False and "progress" in st
