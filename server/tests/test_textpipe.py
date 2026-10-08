"""Ende-zu-Ende über die Text-Pipeline (Router, Schnellweg, Bestätigung, LLM mit Tools)."""

import pytest

from jarvis.textpipe import chat


@pytest.fixture
async def session(services):
    dev, _ = services.devices.create("Test", "pwa")
    s = services.session_for(dev)
    yield s
    if s.text is not None:
        await s.text.stop()


async def test_fast_path(session):
    r = await chat(session, "Wie spät ist es?")
    assert r["route"] == "fast" and r["reply"].startswith("Es ist")


async def test_llm_answer_and_system_prompt(session, services):
    from mock_llm import REQUESTS

    r = await chat(session, "Erzähl mir einen Witz über Pinguine")
    assert r["reply"].startswith("Antwort auf:")
    system = REQUESTS[-1]["messages"][0]["content"]
    assert "Jetzt ist" in system and "Berlin" in system      # Datum/Ort für das LLM
    assert "/no_think" not in system                          # Modell heißt "mock", nicht qwen3


async def test_llm_tool_call(session, services):
    r = await chat(session, "Erzähl mir was llm-timer")
    assert "Erledigt" in r["reply"]
    assert any(t["label"] == "Test" for t in services.timers.items())


async def test_dialog_followup(session, services):
    r = await chat(session, "Starte einen Timer für die Nudeln")
    assert r["route"] == "ask" and "Wie lange" in r["reply"]
    r = await chat(session, "zwölf Minuten")
    assert r["reply"].startswith("Nudeln-Timer, 12 Minuten")


async def test_confirmation_flow(session):
    r = await chat(session, "Starte den Jellyfin Container neu")
    assert r["needs_confirmation"] and "Soll ich das tun" in r["reply"]
    r = await chat(session, "Wie bitte?")
    assert r["needs_confirmation"] and "ja oder nein" in r["reply"]
    r = await chat(session, "Nein")
    assert not r["needs_confirmation"] and "abgebrochen" in r["reply"]


async def test_confirmation_needs_clear_yes(session):
    await chat(session, "Starte den Jellyfin Container neu")
    r = await chat(session, "Okay, und wie wird das Wetter?")      # kein Ja!
    assert r["needs_confirmation"]
    r = await chat(session, "Mhm vielleicht später irgendwann")
    assert not r["needs_confirmation"]


async def test_confirmation_expires(session, services):
    await chat(session, "Starte den Jellyfin Container neu")
    session.pending.expires = 0
    r = await chat(session, "ja")
    assert session.pending is None
    assert "freigegeben" not in r["reply"] and "ausgeführt" not in r["reply"]


async def test_llm_error_message(session):
    r = await chat(session, "Erzähl mir llm-fehler")
    assert "nicht erreichbar" in r["reply"]


async def test_memory(session, services):
    await chat(session, "Merk dir, dass ich Kaffee schwarz trinke")
    assert services.memory.list()[0]["text"] == "ich trinke Kaffee schwarz"
    r = await chat(session, "Was weißt du über mich?")
    assert "du trinkst Kaffee schwarz" in r["reply"]
    assert "ich trinke Kaffee schwarz" in session.system_prompt()


async def test_private_mode(session):
    r = await chat(session, "Schalte den Privatmodus ein")
    assert session.private and "lokal" in r["reply"]
    r = await chat(session, "Denk gründlich nach: was ist der Sinn des Lebens?")
    assert r["reply"]          # lokale Antwort statt Cloud


async def test_context_is_trimmed(session, services):
    services.cfg.providers.llm.context_turns = 3
    for i in range(6):
        await chat(session, f"Wie spät ist es? {i}")
    session.trim_context()
    users = [m for m in session.context.messages if m.get("role") == "user"]
    assert len(users) == 3
