# Mini-Jarvis

[![CI](https://github.com/hoktaar/mini-jarvis/actions/workflows/ci.yml/badge.svg)](https://github.com/hoktaar/mini-jarvis/actions/workflows/ci.yml)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](LICENSE)
[![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg)](docs/UNRAID.md)
[![Image](https://img.shields.io/badge/ghcr.io-mini--jarvis-2496ED.svg)](https://github.com/hoktaar/mini-jarvis/pkgs/container/mini-jarvis)
[![Status: Work in Progress](https://img.shields.io/badge/Status-Work%20in%20Progress-orange.svg)](#stand-und-roadmap)

> [!WARNING]
> **Work in Progress.** Mini-Jarvis ist ein Hobbyprojekt in aktiver Entwicklung – kein fertiges Produkt.
> Vieles läuft schon, manches ist nur im Test und mit simulierten Geräten geprüft (u. a. die CYD-Firmware auf
> echter Hardware und die lokalen Modelle auf der GPU). Einstellungen, Schnittstellen und Firmware können sich
> zwischen Versionen ändern, Fehler sind zu erwarten.
>
> - Nicht für sicherheitskritische Steuerungen verwenden (Schlösser, Alarmanlagen, Heizung ohne Rückfallebene).
> - Jarvis nicht ungeschützt ins Internet stellen – Zugriff von außen nur über VPN.
> - Vor Updates die Einstellungen sichern (Ordner `appdata/mini-jarvis/config`).
>
> Rückmeldungen und Fehlerberichte sind willkommen: [Issues](https://github.com/hoktaar/mini-jarvis/issues).

**Dein eigener, deutschsprachiger Sprachassistent – auf deinem Server, lokal als Standard, Cloud nur wenn du willst.**
Ein Container für Unraid oder Docker, dazu kleine Touch-Displays (CYD/ESP32) für jeden Raum, eine App fürs Handy
(PWA) und Chat-Bots für Telegram und Matrix.

<p align="center">
  <img src="docs/images/jarvis-in-aktion.gif" alt="Jarvis in Aktion: Wetterfrage, Timer stellen, Kaffeemaschine einschalten" width="960">
</p>

<p align="center"><em>Jarvis in Aktion: Wetter abfragen, einen Timer stellen, die Kaffeemaschine einschalten – alles live im Dashboard.</em></p>

---

## Inhalt

- [Was Jarvis kann](#was-jarvis-kann)
- [Screenshots](#screenshots)
- [Schnellstart](#schnellstart) – Unraid · Docker Compose
- [Hardware](#hardware) – Server · CYD-Display · Einkaufsliste · Verkabelung
- [So funktioniert Jarvis](#so-funktioniert-jarvis)
- [Sprachbefehle](#sprachbefehle)
- [Konfiguration](#konfiguration) – lokal, Cloud, gemischt
- [Sicherheit und Datenschutz](#sicherheit-und-datenschutz)
- [Entwicklung](#entwicklung)
- [Stand und Roadmap](#stand-und-roadmap)
- [Dokumentation](#dokumentation) · [Danksagungen und Lizenz](#danksagungen-und-lizenz)

## Was Jarvis kann

| Bereich | |
|---|---|
| 🎙️ **Sprache** | „Hey Jarvis“ oder Push-to-Talk, Unterbrechen jederzeit, Folgefragen ohne erneutes Wake-Word |
| ⚡ **Schnellweg** | Uhrzeit, Timer, Wecker, Erinnerungen, Wetter, Lautstärke, Privatmodus … ohne Sprachmodell, Entscheidung in Millisekunden |
| 🧰 **Werkzeuge** | Websuche (SearXNG, Brave, Tavily), Nachrichten (RSS), Kalender (CalDAV), Gedächtnis („Merk dir …“), Home Assistant, Docker-Container, eigene Skripte |
| 🧠 **Modelle** | lokal (Ollama, Whisper, Piper) **oder** Cloud: Anthropic, OpenAI, Google, Mistral, Groq, OpenRouter, DeepSeek, OpenAI-kompatibel |
| 🔊 **Stimme** | Spracherkennung: Whisper, Parakeet (schnell auf dem Prozessor), OpenAI, Groq, Deepgram, Azure, Google, ElevenLabs · Sprachausgabe: Piper, OpenAI, ElevenLabs, Cartesia, Deepgram, Azure, Google |
| 🔁 **Ausfallsicher** | Lokal oder Cloud als Standard, der andere Weg springt bei Fehlern ein; Budget pro Tag/Monat |
| 🔒 **Sicher** | Rückfrage bei kritischen Aktionen, Schutz vor Prompt-Injection aus Webinhalten, Geräte-Tokens, HTTPS mit eigener CA, Privatmodus pro Gerät |
| 🖥️ **Oberflächen** | HUD-Dashboard (Desktop, Tablet, Handy, hell/dunkel), Verwaltung mit allen Einstellungen (ohne YAML), CYD-Display mit Licht- und Musikseiten |
| 🔌 **Firmware** | CYD per USB direkt aus dem Browser flashen und einrichten, alle Updates danach per WLAN |
| 💬 **Überall** | PWA fürs Handy, Telegram- und Matrix-Bot (mit Ja/Nein-Knöpfen und Sprachnachrichten), REST-API |

## Screenshots

### Dashboard

![Dashboard](docs/images/dashboard.png)

<details>
<summary>Helles Design</summary>

![Dashboard hell](docs/images/dashboard-hell.png)
</details>

### Handy (PWA)

<p align="center"><img src="docs/images/handy.png" alt="Jarvis auf dem Handy: Start, Smarthome, Aufgaben" width="900"></p>

### Verwaltung

| | |
|---|---|
| ![Einstellungen: Sprachmodell](docs/images/verwaltung-einstellungen.png) | ![Einstellungen: Smart Home](docs/images/verwaltung-smarthome.png) |
| **Einstellungen** – alles per Formular, lokal oder Cloud, Modelle laden | **Smart Home** – Home Assistant testen, Geräte ankreuzen |
| ![Übersicht](docs/images/verwaltung-uebersicht.png) | ![CYD per USB einrichten](docs/images/verwaltung-firmware.png) |
| **Übersicht** – Dienste, KI-Anbieter, Antwortzeiten, HTTPS | **Firmware** – CYD per USB flashen und einrichten |
| ![Geräte](docs/images/verwaltung-geraete.png) | ![Router](docs/images/verwaltung-router.png) |
| **Geräte** – koppeln per QR-Code, Updates, Lautstärke | **Router** – Sätze testen, Fehler korrigieren, Auswertung |

### CYD-Display

<p align="center">
  <img src="docs/images/cyd-in-aktion.gif" alt="CYD: bereit, hört zu, denkt nach, antwortet" width="300">
</p>

![CYD-Oberfläche: Start, Licht, Musik, Einstellungen, Querformat, Wecker](docs/images/cyd-oberflaeche.png)

*Bilder mit Beispieldaten; die CYD-Bildschirme sind mit derselben Grafikbibliothek auf dem PC gerendert
(`firmware/cyd/tools/preview`).*

## Schnellstart

### Unraid

Im Unraid-Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/hoktaar/mini-jarvis/main/unraid/install.sh | bash
```

Dann **Docker → Container hinzufügen → Vorlage „mini-jarvis“ → Anwenden**. Das Skript erkennt die GPU, legt die
Ordner an und trägt die Server-IP ein. Alles Weitere – auch der Betrieb ohne GPU – steht in
**[docs/UNRAID.md](docs/UNRAID.md)**.

### Docker Compose

```bash
git clone https://github.com/hoktaar/mini-jarvis.git && cd mini-jarvis
docker compose up -d                 # ohne GPU: den deploy-Block in docker-compose.yml entfernen
docker compose logs mini-jarvis | grep -A3 "Admin-Token"     # Token für die Verwaltung (erster Start)
```

Oder das fertige Image: `ghcr.io/hoktaar/mini-jarvis:latest`.

### Danach

1. `https://<server>:8443/` öffnen, Zertifikatswarnung einmal bestätigen.
2. **Verwaltung** (`/admin.html`) mit dem Admin-Token öffnen – er steht beim ersten Start im Container-Log.
   Unter **Übersicht** das **CA-Zertifikat** laden und auf deinen Geräten installieren.
3. **Einstellungen**: Ort suchen, Sprachmodell wählen (lokal oder Cloud), Schlüssel eintragen, Home Assistant
   verbinden – alles per Formular, keine Datei bearbeiten. Danach **Jetzt neu starten**; die Übersicht zeigt, was noch fehlt.
4. **Geräte → Neues Gerät**: Handy per QR-Code koppeln.
5. **Firmware → CYD per USB einrichten**: Display anschließen, WLAN eintragen, fertig.

## Hardware

### Server

| Profil | Hardware | Modelle |
|---|---|---|
| **Alles lokal** | NVIDIA-GPU ab 12 GB VRAM, 16 GB RAM | Whisper large-v3-turbo (≈ 1,5 GB VRAM) + qwen3:8b (≈ 6 GB) + Piper (CPU) |
| **Lokal, kleine GPU** | NVIDIA-GPU mit 8 GB | Whisper + qwen3:4b (≈ 3,5 GB) |
| **Ohne GPU** | beliebige x86-CPU, 8 GB RAM | Sprachmodell aus der Cloud oder von einem externen Ollama, Whisper „small“ auf der CPU oder Cloud-Spracherkennung, Piper |

Speicherbedarf: ca. 12 GB für das Image, 8–15 GB für Modelle (am besten auf SSD/Cache-Pool).
Die GPU lässt sich mit ComfyUI teilen (Einstellungen → Werkzeuge → Grafikkarte teilen).

### CYD-Display (ESP32-2432S028)

Das „Cheap Yellow Display“ ist ein ESP32 mit 2,8"-Touchdisplay (320 × 240), Lautsprecher-Verstärker und
RGB-LED – ideal als Jarvis-Satellit für jeden Raum. Es braucht nur ein Mikrofon dazu.

| | |
|---|---|
| Prozessor | ESP32-WROOM-32, 240 MHz, 4 MB Flash, kein PSRAM |
| Display | 2,8" ILI9341 (Variante „CYD2USB“ mit USB-C: ST7789), resistiver Touch XPT2046 |
| Audio | Verstärker SC8002B am DAC (GPIO 26), Stecker „SPEAK“ |
| Mikrofon | INMP441 über I²S (GPIO 22/27/35) |
| Firmware | PlatformIO, LovyanGFX, WebSocket mit Token, OTA-Updates – siehe [firmware/cyd](firmware/cyd/README.md) |

#### Einkaufsliste

| Teil | Hinweis |
|---|---|
| ESP32-2432S028R („Cheap Yellow Display“) | mit einem Micro-USB = Firmware `cyd`; mit USB-C **und** Micro-USB = `cyd-st7789` |
| INMP441 I²S-Mikrofonmodul | 3,3 V, gibt es einzeln oder im 3er-Pack |
| Lautsprecher 8 Ω, 1–2 W | mit JST-1,25-mm-Stecker (passt in „SPEAK“) |
| Jumperkabel | dem CYD liegen meist Kabel für CN1/P3 bei |
| USB-Datenkabel + Netzteil 5 V / 1 A | zum Flashen ein **Datenkabel**, kein reines Ladekabel |
| optional: Gehäuse | 3D-Druckvorlagen für den CYD gibt es zahlreich |

#### Verkabelung

![Verkabelung CYD, INMP441 und Lautsprecher](docs/images/verkabelung.svg)

| INMP441 | CYD | Stecker |
|---|---|---|
| SCK | GPIO 22 | CN1 |
| WS | GPIO 27 | CN1 |
| SD | GPIO 35 | P3 |
| L/R | GND | P3 |
| VDD | 3,3 V | CN1 |
| GND | GND | CN1 |

Pinbelegung vor dem Anschließen mit der eigenen Board-Revision abgleichen. Mehr in [docs/HARDWARE.md](docs/HARDWARE.md).

#### Einrichten

1. Verwaltung über **HTTPS** in Chrome/Edge öffnen → **Firmware** → „CYD per USB einrichten“.
2. Variante wählen, Name/Raum und WLAN (2,4 GHz) eintragen, Display anschließen, *USB-Gerät wählen*.
3. Der Assistent flasht, überträgt WLAN, Server und Token und wartet, bis das Display online ist.
4. Am Display einmal die Touch-Kalibrierung durchführen (vier Pfeile antippen).

Bedienung: Reaktor **antippen** = zuhören, **halten** = Push-to-Talk; unten **Start · Licht · Musik · Einstellungen**.

## So funktioniert Jarvis

```mermaid
flowchart LR
    subgraph Geräte
        CYD["CYD-Display<br/>(ESP32)"]
        PWA["Browser / Handy<br/>(PWA)"]
        BOT["Telegram / Matrix"]
    end
    subgraph Container["Container mini-jarvis"]
        WEB["Web-UI · REST · WebSocket<br/>HTTPS mit eigener CA"]
        PIPE["Sprach-Pipeline (Pipecat)<br/>VAD → STT → Router → LLM → TTS"]
        ROUTER["System-1-Router<br/>Schnellweg"]
        POLICY["Policy<br/>Rückfrage · Privatmodus · Budget"]
        TOOLS["Werkzeuge<br/>Timer · Wetter · Suche · Kalender<br/>Gedächtnis · Smarthome"]
        RUNNER["Skript-Runner<br/>eigener Benutzer"]
        PROXY["Docker-Filter-Proxy"]
        OLLAMA[("Ollama")]
        SEARX[("SearXNG")]
    end
    CLOUD[("Cloud-Anbieter<br/>optional")]
    HA[("Home Assistant")]
    CYD --> WEB
    PWA --> WEB
    BOT --> WEB
    WEB --> PIPE
    PIPE --> ROUTER
    ROUTER --> POLICY
    POLICY --> TOOLS
    PIPE <--> OLLAMA
    PIPE -.-> CLOUD
    TOOLS --> SEARX
    TOOLS --> HA
    POLICY --> RUNNER
    POLICY --> PROXY
```

1. **Wake-Word / Push-to-Talk** – das Display streamt Audio, der Server erkennt „Hey Jarvis“ (openWakeWord).
2. **Spracherkennung** – Whisper lokal (oder ein Cloud-Dienst) macht Text daraus.
3. **System-1-Router** – ein kleiner Klassifikator erkennt einfache Anliegen („Timer zehn Minuten“) samt Angaben
   (Dauer, Uhrzeit, Ort) und erledigt sie sofort – ohne Sprachmodell.
4. **Sprachmodell** – alles andere beantwortet das LLM (lokal oder Cloud) mit passenden Werkzeugen.
5. **Policy** – kritische Aktionen (Container neu starten, Skripte) brauchen ein klares „Ja“; nach Webinhalten
   fragt Jarvis vor jeder schreibenden Aktion nach.
6. **Sprachausgabe** – Piper (oder Cloud-TTS) spricht die Antwort; Antippen unterbricht sofort.

## Sprachbefehle

| Sag … | Jarvis … |
|---|---|
| „Wie spät ist es?“ | sagt Uhrzeit und Datum |
| „Stell einen Timer auf zehn Minuten für die Nudeln“ | stellt einen benannten Timer |
| „Weck mich morgen um halb sieben“ · „Lösch den Wecker“ | stellt bzw. löscht Wecker |
| „Erinnere mich um 18 Uhr an den Müll“ | legt eine Erinnerung an |
| „Wie wird das Wetter am Samstag in München?“ | Vorhersage bis 15 Tage, beliebige Orte |
| „Was gibt es Neues?“ | liest Schlagzeilen aus RSS-Feeds |
| „Such im Internet nach …“ | Websuche (SearXNG, Brave oder Tavily) |
| „Merk dir, dass Anna gern grünen Tee trinkt“ · „Was weißt du über Anna?“ | Gedächtnis |
| „Was steht morgen im Kalender?“ · „Trag Zahnarzt am Freitag um zehn ein“ | Kalender (CalDAV) |
| „Schalte das Licht im Wohnzimmer ein“ | Home Assistant |
| „Läuft Jellyfin?“ · „Starte Jellyfin neu“ | Container-Status, Neustart nach Rückfrage |
| „Führe das Backup-Skript aus“ | freigegebene Skripte, nach Rückfrage |
| „Lauter“ · „Lautstärke 40“ · „Stopp“ | Lautstärke, Unterbrechen |
| „Privatmodus an“ | bleibt für dieses Gerät lokal |
| „Neues Thema“ · „Wiederhole das“ · „Was kannst du?“ | Gesprächssteuerung und Hilfe |
| „Denk gründlich nach: …“ · „Frag die Cloud …“ | nutzt ausdrücklich das große Cloud-Modell |

## Konfiguration

Alles wird in der **Verwaltung** eingestellt – keine YAML-Datei anfassen:

| Wo | Was |
|---|---|
| **Einstellungen → Allgemein** | Ort suchen (füllt Koordinaten und Zeitzone), Persönlichkeit, Gedächtnis |
| **Einstellungen → Sprachmodell** | lokal (Ollama, Modelle direkt herunterladen) und/oder Cloud, Anbieter, Schlüssel, Budget |
| **Einstellungen → Sprache** | Spracherkennung, Sprachausgabe, Aktivierungswort „Hey Jarvis“ |
| **Einstellungen → Suche & Nachrichten** | Websuche, RSS-Quellen |
| **Einstellungen → Smart Home** | Home Assistant verbinden, Verbindung testen, Geräte ankreuzen, Sprachsteuerung |
| **Einstellungen → Kalender · Benachrichtigungen** | CalDAV, Push (ntfy), Telegram, Matrix |
| **Einstellungen → Werkzeuge** | Docker-Container freigeben, Grafikkarte mit ComfyUI teilen, MCP-Server |
| **Einstellungen → Netzwerk & Sicherheit** | HTTPS, Adressen fürs Zertifikat, Aufbewahrung der Protokolle, Firmware-Updates |
| **Einstellungen → Schlüssel & Zugänge** | alle API-Schlüssel und Passwörter – Werte werden nie angezeigt |
| **Skripte** | eigene Skripte freigeben, Parameter und Rückfrage festlegen |
| **Router** | Absicht antippen → eigene Beispielsätze lernen |
| **System** | Jarvis neu starten, Admin-Token erneuern |

Jede Eingabe wird vor dem Speichern geprüft – Fehler stehen direkt am Feld. Gespeicherte Änderungen übernimmt
Jarvis nach **Jetzt neu starten** (wenige Sekunden, Geräte verbinden sich von selbst wieder). Skripte,
Beispielsätze und Container-Freigaben wirken sofort.

**Typische Aufstellungen:**

| | Sprachmodell | Spracherkennung / -ausgabe |
|---|---|---|
| **Alles lokal** (GPU) | Lokal zuerst, Ollama eingebaut, `qwen3:8b` | Whisper (Grafikkarte) / Piper |
| **Ohne GPU** | Cloud zuerst (z. B. Anthropic), lokales Modell aus | Parakeet auf dem Prozessor oder Cloud / Piper |
| **GPU nur fürs Sprachmodell** | Lokal zuerst, größeres Modell | Parakeet auf dem Prozessor / Piper – die ganze Grafikkarte bleibt für Ollama |
| **Lokal mit Rückfallebene** | Lokal zuerst + Cloud-Modell „bei Ausfall einspringen“ | wie oben |

| Rolle | Anbieter |
|---|---|
| Sprachmodell | Anthropic · OpenAI · Google · Mistral · Groq · OpenRouter · DeepSeek · OpenAI-kompatibel (eigene Adresse) |
| Spracherkennung | Whisper (lokal) · Parakeet (lokal, Prozessor) · OpenAI · Groq · Deepgram · Azure · Google · ElevenLabs |
| Sprachausgabe | Piper (lokal) · OpenAI · ElevenLabs · Cartesia · Deepgram · Azure · Google |
| Websuche | SearXNG (eingebaut) · Brave · Tavily |

**Parakeet** ist ein deutsches Spracherkennungsmodell (NVIDIA Parakeet TDT 0.6B, angepasst von primeline), das
auf dem Prozessor läuft – etwa 0,1 s für einen kurzen Satz, ohne Grafikspeicher. Das Modell (~670 MB) lädt Jarvis
beim ersten Start selbst oder per Knopf unter **Einstellungen → Sprache**.

### Transkriptions-Schnittstelle für andere Programme

Unter **Einstellungen → Sprache → Schnittstelle für andere Programme** lässt sich Jarvis' Spracherkennung für
andere Geräte im Heimnetz freigeben – im Format der OpenAI-Schnittstelle (`POST /v1/audio/transcriptions`).
Damit können Diktier-Apps wie [dictate](https://github.com/winidi/dictate) oder eigene Skripte das Modell auf dem
Server mitbenutzen, statt selbst eines mitzubringen.

- Schalter an, **Token erzeugen**, Adresse und Token ins Programm eintragen (Adresse: `http://<server>:8080/v1`).
- Es gilt die eingestellte Spracherkennung (Parakeet, Whisper, OpenAI oder Groq); Sprache ist Deutsch.
- Formate: WAV, FLAC, OGG/Opus, MP3 bis 25 MB; Antwort `json`, `text` oder `verbose_json`.
- Statt des Schnittstellen-Tokens geht auch der Token eines gekoppelten Geräts.

```bash
curl http://192.168.1.10:8080/v1/audio/transcriptions \
  -H "Authorization: Bearer jt_…" -F file=@aufnahme.wav -F model=parakeet
# {"text": "Mach das Licht im Wohnzimmer an"}
```

<details>
<summary>Für Fortgeschrittene: die Dateien dahinter</summary>

Die Verwaltung speichert alles im Volume `/config` (beim ersten Start aus [`config/examples`](config/examples)
angelegt). Sie schreibt die Dateien so, dass Kommentare und Reihenfolge erhalten bleiben, und legt vor jeder
Änderung eine Sicherung unter `/config/backups/` an (die letzten 20 je Datei).

| Datei | Inhalt |
|---|---|
| `config.yaml` | alle Einstellungen der Seite „Einstellungen“ |
| `secrets.yaml` | Admin-Token, API-Schlüssel, Passwörter – Umgebungsvariablen `JARVIS_<NAME>` haben Vorrang |
| `scripts.yaml` | freigegebene Skripte |
| `whitelist.yaml` | freigegebene Container |
| `intents.yaml` | Absichten des Schnellwegs (eigene Beispielsätze speichert die Verwaltung in der Datenbank) |

Wer lieber Dateien pflegt: `JARVIS_CONFIG_READONLY=true` in der Container-Vorlage sperrt das Schreiben – die
Verwaltung zeigt die Werte dann nur an. Nach Änderungen von Hand: **System → Jarvis neu starten**.
</details>

## Sicherheit und Datenschutz

- **Lokal als Standard** – ohne Cloud-Schlüssel verlässt nichts dein Netz. Der Privatmodus pro Gerät hält
  Sprachmodell und Werkzeuge lokal, das Wolken-Symbol zeigt Cloud-Antworten an.
- **Rückfragen** – kritische Aktionen nur nach eindeutigem „Ja“; unklare Antworten führen zum Abbruch.
- **Schutz vor Prompt-Injection** – nach Web- und Nachrichteninhalten fragt Jarvis vor jeder schreibenden Aktion.
- **Rechtetrennung** – Skripte laufen als eigener Benutzer ohne Shell und nur, wenn sie freigegeben sind; Docker nur
  über einen Filter-Proxy, der höchstens Status, Start, Stopp und Neustart erlaubt.
- **Einstellungen** – nur mit Admin-Token, jede Änderung geprüft, protokolliert und vorher gesichert; Schlüssel
  verlassen den Server nie. Wer Dateien bevorzugt, sperrt die Verwaltung mit `JARVIS_CONFIG_READONLY=true`.
- **Geräte** – eigenes Token pro Gerät (nur als Hash gespeichert), jederzeit sperrbar; HTTPS mit eigener CA.
- **Protokolle** – Router- und Aktionsprotokoll mit Aufbewahrungsfrist; Sätze auf Wunsch gar nicht speichern.

Details: [docs/SECURITY.md](docs/SECURITY.md).

## Entwicklung

```bash
cd server
pip install -e ".[dev,cloud,chat,extras]"
cp ../config/examples/*.yaml ../config/      # anpassen, z. B. stt/tts: none und ein Cloud-LLM
JARVIS_CONFIG_DIR=../config python -m jarvis.main        # http://localhost:8080 · https://localhost:8443
pytest && ruff check .
python -m jarvis.router.eval --trigram                   # Trefferquote des Routers
```

Firmware:

```bash
cd firmware/cyd
pio run -e cyd -e cyd-st7789                 # bauen
python tools/package.py --out dist           # Paket für Web-Flasher und OTA
cd tools/preview && ./build.sh /pfad/zu/LovyanGFX && ./preview out/   # Bildschirme auf dem PC rendern
```

```
docker/        Dockerfile, supervisord, Entrypoint, Rauchtest
unraid/        Vorlagen (mit/ohne GPU) und Installationsskript
config/        Beispielkonfiguration
server/        Jarvis-Core (Python, Pipecat, FastAPI) inkl. Web-Oberfläche (server/jarvis/web)
firmware/cyd/  CYD-Firmware (PlatformIO)
clients/       Android, Android Auto, Desktop – Pläne
docs/          Plan, Protokolle, Sicherheit, Hardware, Unraid, Bilder
scripts/       Beispiel-Skripte für den Runner
```

Die CI prüft Lint, Tests, Router-Trefferquote, baut beide Firmware-Varianten, rendert die Bildschirme, baut
das Image, startet es ohne GPU im Rauchtest (inklusive Speichern einer Einstellung und Neustart) und
veröffentlicht es unter `ghcr.io/hoktaar/mini-jarvis`.

## Stand und Roadmap

> [!NOTE]
> **Work in Progress** – die Tabelle zeigt ehrlich, was wie weit geprüft ist. ✅ heißt: automatisch getestet
> und im Browser oder Container ausprobiert, nicht „jahrelang im Alltag bewährt“.

| Teil | Stand |
|---|---|
| Server: Sprachweg, Router, Werkzeuge, Policy, Runner, Timer, Gedächtnis, Kalender, Home Assistant, Cloud-Anbieter, Telegram/Matrix | ✅ 107 Tests, Router 92,7 % auf dem Testsatz |
| Dashboard und Verwaltung | ✅ im Browser getestet (Desktop, Tablet, Handy, hell/dunkel) |
| Einstellungen ohne YAML (inkl. Neustart aus der Verwaltung) | ✅ im Browser und im Container-Rauchtest geprüft |
| USB-Einrichtung aus dem Browser | ✅ Ablauf mit simuliertem Gerät getestet; Flashen braucht echte Hardware |
| CYD-Firmware 0.3.0 | 🟡 kompiliert (beide Varianten), Bildschirme geprüft – **auf Hardware noch ungetestet** |
| Lokale Modelle mit GPU | 🟡 verdrahtet, auf dem Zielserver zu prüfen |
| Räume und Wake-Word-Schlichtung (mehrere Displays) | ⬜ geplant |
| Android-App, Android Auto, Desktop (Tauri) | ⬜ geplant – siehe [docs/PLAN.md](docs/PLAN.md) |

## Dokumentation

| | |
|---|---|
| [docs/UNRAID.md](docs/UNRAID.md) | Installation, Zertifikate, Profile je GPU, Updates, Backup, Fehlerbehebung |
| [docs/HARDWARE.md](docs/HARDWARE.md) | CYD, Mikrofon, Lautsprecher, Varianten |
| [firmware/cyd/README.md](firmware/cyd/README.md) | Firmware bauen, bedienen, serielles Einrichtungsprotokoll |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | WebSocket-, USB- und REST-Schnittstellen |
| [docs/SECURITY.md](docs/SECURITY.md) | Sicherheitskonzept |
| [docs/PLAN.md](docs/PLAN.md) | Architektur, Phasen, Roadmap |
| [CHANGELOG.md](CHANGELOG.md) | Änderungen |

## Danksagungen und Lizenz

Jarvis steht auf den Schultern von [Pipecat](https://github.com/pipecat-ai/pipecat),
[Ollama](https://ollama.com), [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) mit [parakeet-primeline](https://huggingface.co/flozen1981/parakeet-primeline-onnx)
(CC-BY-4.0, primeline und NVIDIA; Aufteilen langer Aufnahmen nach dem Vorbild von [dictate](https://github.com/winidi/dictate)),
[Piper](https://github.com/rhasspy/piper), [openWakeWord](https://github.com/dscripka/openWakeWord),
[SearXNG](https://github.com/searxng/searxng), [LovyanGFX](https://github.com/lovyan03/LovyanGFX) und
[esptool-js](https://github.com/espressif/esptool-js).

Lizenz: [MIT](LICENSE). Die CYD-Firmware enthält die Schrift Rajdhani (SIL Open Font License,
`firmware/cyd/fonts/OFL.txt`).
