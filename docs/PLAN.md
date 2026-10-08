# Mini-Jarvis – Gesamtplan

Stand: 26.09.2026 · Version 1.0

## 1. Ziel

Ein deutschsprachiger Sprachassistent, der standardmäßig komplett lokal auf dem
BigServer (Unraid, RTX 3060 12 GB) läuft. Jarvis reagiert auf „Hey Jarvis“,
beantwortet Fragen, verwaltet Timer, Wecker und Erinnerungen, liefert Wetter,
Nachrichten und Websuche und steuert Container sowie freigegebene Skripte.

Er ist über viele Oberflächen erreichbar: ESP32-Satelliten (zuerst der CYD),
PWA (Browser, iPhone), Android-App mit Android Auto, Desktop-App (Windows/Linux)
und Chat-Bots (Matrix, Telegram).

**Leitlinie:** so viel wie möglich selbst gehostet, externe Dienste (Cloud-LLMs,
Cloud-STT/TTS, Telegram, Jev usw.) optional und pro Komponente zuschaltbar.

Zielwerte: Router-Schnellweg < 1 s, LLM-Antwort < 3 s bis zur ersten Silbe.

## 2. Fundament: vorhandene Bausteine statt Eigenbau

| Baustein | Wofür | Ersetzt |
|---|---|---|
| **Pipecat** (Python) | Sprach-Pipeline, VAD, Whisper, Piper, Ollama, Cloud-Provider, WebSocket/WebRTC-Transporte, Unterbrechungen | eigene Pipeline + Provider-Schicht |
| **RTVI** + Pipecat-Client-SDKs (JS, React, Kotlin, Swift, C++, ESP32) | einheitliches Client-Protokoll | eigenes „Jarvis-Protokoll“ für App/PWA/Desktop |
| **Pipecat Voice UI Kit** | PWA-Oberfläche | eigene Web-Komponenten |
| **Pipecat LLMSwitcher** | lokal ↔ Cloud umschalten, Failover | eigene Eskalationslogik (teilweise) |
| **Pipecat BaseClassifier** | einheitliche System-1-Schnittstelle (Ja/Nein, Auswahl, Score) | – unser lokaler Klassifikator implementiert sie, Jev ist optional einsetzbar |
| **MCP** (Pipecat MCPClient) | Tools anbinden | eigene Tool-Integrationen |
| **SearXNG + SearXNG-MCP-Server** | Websuche | Such-Tool |
| openWakeWord („hey_jarvis“), Silero-VAD, faster-whisper, Piper | Audio-KI lokal | – |

Eigenbau bleibt nur, wo es um Sicherheit oder Besonderheiten geht: Router,
Timer-Scheduler, Sicherheits-Policy, Skript-Runner, Docker-MCP-Server,
Geräteverwaltung, CYD-Firmware, Android-Auto-Oberfläche.

## 3. Architektur

```
 Clients                                   BigServer – ein Container "mini-jarvis"
 ───────                                   ───────────────────────────────────────
 CYD / ESP32 ──WS (PCM, JSON)──┐           supervisord
 PWA / Desktop ─WS (RTVI)──────┤            ├─ jarvis-core  (FastAPI + Pipecat)
 Android / Auto ─WS/WebRTC─────┤──────────▶ │    Wake-Word → VAD → Whisper
 Matrix / Telegram ─Text───────┘            │    → System-1-Router ─▶ Schnellweg
                                            │    → LLMSwitcher (Ollama | Cloud)
                                            │    → Piper → zurück zum Client
                                            ├─ ollama        (nur localhost)
                                            ├─ searxng       (nur localhost)
                                            ├─ socket-proxy  (HAProxy, gefiltert)
                                            ├─ runner        (eigener User)
                                            └─ ntfy          (optional, Push)
```

### Ein Container

Alles läuft in **einem Image** mit supervisord. Trennung der Rechte über eigene
Linux-Benutzer:

| Benutzer | Prozess | Rechte |
|---|---|---|
| `jarvis` | jarvis-core, MCP-Server | Config lesen, `/data` schreiben, **kein** Docker-Socket |
| `proxy` | HAProxy | einziger Leser des Docker-Sockets |
| `runner` | Skript-Runner | `/scripts` lesen/ausführen, sonst nichts |
| `ollama` | Ollama | `/models/ollama` |

Kompromiss gegenüber getrennten Containern: Trennung über Benutzer statt über
Container-Grenzen – solide, aber nicht ganz so hart. Dafür ein Image, ein
Template, ein Update.

## 4. Modelle und VRAM

| Komponente | Wahl | Gerät | VRAM |
|---|---|---|---|
| Wake-Word | openWakeWord `hey_jarvis` | CPU | – |
| VAD | Silero | CPU | – |
| STT | faster-whisper `large-v3-turbo`, int8_float16 | GPU | ~2–3 GB |
| Router | mehrsprachiges Embedding + Beispiel-Klassifikator | CPU | – |
| LLM | aktuelles Qwen ~8B (Q4) mit Tool-Calling | GPU | ~5–6 GB |
| TTS | Piper `de_DE-thorsten-high` | CPU | – |

**ComfyUI-Modus:** Ollama entlädt nach Leerlauf (`keep_alive`), Whisper kann
auf CPU wechseln, optional Cloud-Failover über den LLMSwitcher.

## 5. Gesprächsablauf

1. Client streamt Audio (CYD: 16 kHz PCM; App/PWA: über RTVI).
2. Wake-Word-Gate (openWakeWord) oder Push-to-Talk öffnet die Aufnahme.
3. Silero-VAD erkennt das Satzende, Whisper transkribiert.
4. **System-1-Router** entscheidet (siehe 6).
5. Schnellweg: Tool direkt + Vorlagenantwort. Sonst LLM (lokal oder Cloud)
   mit vorausgewählten Tools.
6. Piper spricht satzweise gestreamt.
7. Während Jarvis spricht, ist das Mikrofon beim CYD stumm (Halbduplex);
   Unterbrechen per Touch. Clients mit Echo-Unterdrückung dürfen barge-in.

Gesprächskontext pro Gerät (letzte ~10 Wechsel). Timer, Wecker, Erinnerungen
sind global und klingeln auf dem Gerät/Raum, in dem sie gestellt wurden.

## 6. System-1-Router

Implementiert Pipecats `BaseClassifier`-Schnittstelle. Standard ist ein lokaler
Beispiel-Klassifikator (Embeddings, CPU); per Konfiguration austauschbar gegen
`LLMClassifier` oder den gehosteten `JevClassifier`.

**Absichten** (`config/intents.yaml`): Uhrzeit, Timer stellen/auflisten/löschen,
Wecker, Erinnerung, Wetter, Nachrichten, Websuche, Container-Status,
Container-Aktion, Skript, Stopp, Plaudern (Auffangklasse).

**Stufen:**

| Konfidenz | Weg |
|---|---|
| ≥ `fast` (0,85) und Slots vollständig | Tool direkt, Vorlagenantwort, kein LLM |
| ≥ `fast`, Slot fehlt | Rückfrage per Vorlage |
| ≥ `focused` (0,5) | LLM mit den Tools der Top-3-Absichten |
| darunter / Plaudern | LLM mit allen erlaubten Tools |
| „denk gründlich nach“ / Router: komplex | Eskalation an Cloud-LLM (falls konfiguriert) |

Nur lesende/harmlose Absichten laufen über den Schnellweg ohne Bestätigung.
Alle Entscheidungen werden geloggt; Korrekturen in der Web-UI fließen ins
Nachtrainieren.

**Ja/Nein-Klassifikator** für Bestätigungen: *ja / nein / unklar*, hohe Schwelle,
bei *unklar* fragt Jarvis erneut.

## 7. Tools

| Tool | Umsetzung | Risiko |
|---|---|---|
| Uhrzeit/Datum | lokal | lesen |
| Timer, Wecker, Erinnerungen | SQLite + Scheduler im Core | schreiben (harmlos) |
| Wetter | Open-Meteo, Standort aus Config | lesen |
| Nachrichten | RSS-Feeds | lesen, **taint** |
| Websuche | SearXNG-MCP | lesen, **taint** |
| Container-Status | eigener Docker-MCP über Socket-Proxy | lesen |
| Container-Aktion | eigener Docker-MCP, Whitelist | **kritisch** |
| Skripte | Runner, Registry `scripts.yaml` | **kritisch** |

*Taint:* Nach dem Lesen von Web-/News-Inhalten verlangt im selben Schritt jede
Server-Aktion eine Bestätigung (Schutz vor Prompt-Injection).

## 8. Provider (lokal zuerst, extern optional)

| Komponente | Lokal | Extern |
|---|---|---|
| LLM | Ollama | Anthropic, OpenAI, Google, Mistral, Groq, OpenRouter, DeepSeek, OpenAI-kompatibel |
| STT | faster-whisper | OpenAI, Groq, Deepgram, Azure, Google, ElevenLabs |
| TTS | Piper | OpenAI, ElevenLabs, Cartesia, Deepgram, Azure, Google |
| System-1 | lokaler Klassifikator | Jev, LLM-Klassifikator |
| Suche | SearXNG | Brave, Tavily (MCP) |
| Push | ntfy, Web Push | Firebase |
| Chat | Matrix | Telegram |
| Fernzugriff | WireGuard | Tailscale / Headscale |

Regeln: `providers.llm.primary` wählt lokal oder Cloud als Standard, der andere Weg springt bei Ausfall
ein (beide Richtungen); das lokale Modell ist optional (Betrieb ganz ohne GPU möglich).
Tool-Freigaben pro Anbieter (Cloud standardmäßig ohne Server-Tools), Privatmodus pro Gerät
(Sprachmodell und Werkzeuge lokal), Wolken-Symbol im Client bei externer Verarbeitung,
Tages-/Monatsbudget, Schlüssel nur in `secrets.yaml` oder `JARVIS_<NAME>`, nie im Log.

## 9. Sicherheit

Details in [SECURITY.md](SECURITY.md). Kurzfassung:

- Skripte nur aus `scripts.yaml`, Parameter typgeprüft, Ausführung ohne Shell,
  eigener Benutzer, Timeout, Audit-Log.
- Docker nur über HAProxy-Filter (Status, Start, Stopp, Neustart) + Whitelist.
- Bestätigungen per Ja/Nein-Klassifikator; im Auto pro Skript `car_allowed`.
- Geräte-Tokens (gehasht gespeichert, widerrufbar), Admin-Token für die Web-UI.
- Kein Port ins Internet; unterwegs nur über WireGuard.
- HTTPS für PWA (Mikrofon im Browser), eigene CA oder Let's Encrypt DNS-Challenge.

## 10. Clients

| Client | Technik | Besonderheiten |
|---|---|---|
| CYD | PlatformIO, LovyanGFX, WebSocket, INMP441, interner DAC | Server-Wake-Word, Halbduplex, Arc-Reactor-UI |
| weitere ESP32 | Board-Profile; S3+PSRAM mit Pipecat-ESP32-SDK oder xiaozhi | lokales Wake-Word, Räume, Wake-Word-Schlichtung |
| PWA | Pipecat JS-SDK + Voice UI Kit | Web Push, HTTPS nötig |
| Desktop | Tauri um die PWA | Tray, globaler Hotkey, Autostart |
| Android | Kotlin + Compose + Pipecat Kotlin-SDK | Standard-Assistent, Widget, ntfy/UnifiedPush |
| Android Auto | Car App Library, Kategorie IoT, CarAudioRecord | Knopf statt Wake-Word, Sideload über Entwicklermodus |
| Chat | matrix-nio / python-telegram-bot | Sprachnachrichten, Knöpfe für Bestätigung |

## 11. CYD-Hardware

| INMP441 | CYD |
|---|---|
| SCK | GPIO 22 |
| WS | GPIO 27 |
| SD | GPIO 35 |
| L/R | GND |
| VDD | 3,3 V |

Lautsprecher 8 Ω, 1–2 W, MX1.25-Stecker an SPEAK (GPIO 26, DAC).
Pinbelegung vor dem Anschließen mit der eigenen Board-Revision abgleichen.
Mehr in [HARDWARE.md](HARDWARE.md).

## 12. Phasen

| Phase | Inhalt | Fertig, wenn … | Stand (0.3.0) |
|---|---|---|---|
| 0 | **Grundgerüst** (dieses Repo) | Tests grün, Container baut | ✅ |
| 1 | Pipeline end-to-end, Geräteverwaltung, PWA-Sprachtest, HTTPS | „Hey Jarvis, wie spät ist es?“ im Browser wird gesprochen beantwortet | ✅ HTTPS mit eigener CA, HUD-Dashboard |
| 2a | Tools: Zeit, Timer, Wetter, News, Websuche (MCP) | alle Tools per Sprache, Timer überleben Neustart | ✅ dazu Kalender (CalDAV), Gedächtnis, Smarthome |
| 2b | Router live, Ja/Nein, Cloud-Eskalation, Budget | ≥ 90 % Testsätze richtig, Schnellweg < 1 s | ✅ 92,7 % (Trigramm-Klassifikator), Entscheidung in Millisekunden |
| 3 | Docker-MCP, Runner, Bestätigungen, Audit-UI | Test-Skript läuft nur nach Bestätigung | ✅ |
| 4 | CYD-Firmware: WLAN-Setup, Audio, Protokoll | Gespräch über den CYD | 🟡 fertig und kompiliert, Hardwaretest offen |
| 5 | Display-UI, Räume, Wake-Word-Schlichtung, OTA | Alltagsbetrieb stabil | 🟡 Display-UI, USB-Flasher und OTA fertig; Räume/Schlichtung offen |
| 6 | Android-App, WireGuard, ntfy | Gespräch von unterwegs | 🟡 ntfy fertig, PWA unterwegs nutzbar; App offen |
| 7 | Android Auto | Jarvis-Knopf im Auto, Antwort über Autolautsprecher | ⬜ |
| 8 | Desktop (Tauri) | Hotkey startet Jarvis | ⬜ |
| 9 | Chat-Bots | Text + Sprachnachricht über Matrix | 🟡 Telegram und Matrix implementiert, mit echten Konten ungetestet |

## 13. Einkaufsliste (Phase 4)

INMP441, Lautsprecher 8 Ω mit MX1.25-Stecker, MX1.25-Kabelset 4-polig,
optional 3D-gedrucktes Gehäuse (Variante mit zwei USB-Ports beachten).

## 14. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| 8-Bit-DAC klingt blechern | für Sprache ok; bessere Satelliten mit I²S-Verstärker |
| RAM des ESP32 (kein PSRAM) | schlanke UI, kleine Puffer |
| DAC nutzt intern I2S0 | DAC vor dem Mikrofon initialisieren (Mikrofon auf I2S1) |
| Wake-Word-Fehlauslöser | Schwelle einstellen, „an Jarvis gerichtet?“-Filter |
| VRAM-Konkurrenz mit ComfyUI | ComfyUI-Modus, Failover |
| Fehl-Routing | konservative Schwellen, Logs, Nachtrainieren, Bestätigung bei Aktionen |
| Pipecat-API ändert sich | Version pinnen (`pipecat-ai==1.12.*`), Updates bewusst |
| Android Auto sperrt freie Assistenten | IoT-Kategorie, Sideload |
