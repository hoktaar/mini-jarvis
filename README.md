# Mini-Jarvis

Lokaler, deutschsprachiger Sprachassistent für den eigenen Server – mit dem
ESP32-2432S028 („Cheap Yellow Display“) als erstem Satelliten, später Android
(inkl. Android Auto), PWA, Desktop, Chat-Bots und weiteren ESP32-Geräten.

**Prinzip:** lokal als Standard, externe Dienste (Cloud-LLMs, Cloud-STT/TTS,
Telegram, Jev …) als Option – alles per Konfiguration austauschbar.

## Stand

Phase 0 (Grundgerüst) und der Kern von Phase 1 sind fertig. Lauffähig bzw. getestet:

| Teil | Status |
|---|---|
| Konfiguration, Geräteverwaltung, SQLite | ✅ implementiert + Tests |
| System-1-Router (lokaler Klassifikator, Stufenlogik, Slots, Ja/Nein) | ✅ implementiert + Tests |
| Sicherheits-Policy (Tool-Freigaben, Web-Taint, Auto-Modus) | ✅ implementiert + Tests |
| Skript-Runner (Registry, Validierung, Timeout, Audit) | ✅ implementiert + Tests |
| Timer/Wecker/Erinnerungen (Scheduler) | ✅ implementiert + Tests |
| Wetter (Open-Meteo), News (RSS), Uhrzeit | ✅ implementiert |
| Docker-MCP-Server mit Whitelist | ✅ implementiert (braucht Socket-Proxy) |
| Sprachweg VAD → Whisper → Router → Piper | ✅ Ende-zu-Ende getestet (CPU, simulierter CYD + Browser) |
| CYD-Protokoll (Serializer) | ✅ mit simuliertem Gerät getestet |
| PWA mit Sprachmodus (Pipecat JS, lokal gebündelt) + Verwaltung | ✅ im Headless-Browser mit Mikrofon getestet |
| LLM-Pfad (Ollama, Tool-Calling), Wake-Word | 🟡 verdrahtet, auf dem BigServer zu testen |
| CYD-Firmware | 🟡 Gerüst, auf Hardware zu testen |
| HTTPS für die PWA | ⬜ offen (Phase 1) |
| Android, Android Auto, Desktop, Chat-Bots | ⬜ Struktur + Plan |

Der vollständige Plan steht in **[docs/PLAN.md](docs/PLAN.md)**.

## Schnellstart (Entwicklung, ohne GPU)

```bash
cd server
pip install -e ".[dev]"
cp ../config/examples/*.yaml ../config/   # dann anpassen
JARVIS_CONFIG_DIR=../config python -m jarvis.main
# → http://localhost:8080  (PWA)   ws://localhost:8080/ws/cyd?token=…
pytest
```

## Unraid

Siehe [docs/UNRAID.md](docs/UNRAID.md) und `unraid/mini-jarvis.xml`.

## Struktur

```
docker/        Dockerfile, supervisord, Socket-Proxy, Entrypoint
unraid/        Community-Apps-Template
config/        Beispielkonfigurationen (config, secrets, intents, scripts, whitelist)
server/        Jarvis-Core (Python, Pipecat)
firmware/cyd/  PlatformIO-Firmware für den CYD
clients/       Android, Android Auto, Desktop (Tauri) – Pläne und Gerüste
docs/          Plan, Protokoll, Sicherheit, Hardware, Unraid
scripts/       Beispiel-Skripte für den Runner
```

## Lizenz

MIT
