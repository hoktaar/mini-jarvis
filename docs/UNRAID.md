# Mini-Jarvis auf Unraid

Diese Anleitung führt von null bis zum ersten Gespräch: Container installieren, HTTPS einrichten, Geräte koppeln,
Modelle wählen – mit oder ohne GPU.

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation) – per Skript, Template-Repository oder von Hand
- [Container-Einstellungen](#container-einstellungen)
- [Erster Start](#erster-start)
- [HTTPS-Zertifikat installieren](#https-zertifikat-installieren)
- [Grundkonfiguration](#grundkonfiguration) – Standort, Modelle, Profile für jede GPU
- [Geräte koppeln](#geräte-koppeln)
- [Home Assistant, Kalender, Telegram](#home-assistant-kalender-telegram)
- [GPU mit ComfyUI teilen](#gpu-mit-comfyui-teilen)
- [Updates](#updates) · [Backup](#backup) · [Fernzugriff](#fernzugriff)
- [Fehlerbehebung](#fehlerbehebung) · [Deinstallation](#deinstallation)

## Voraussetzungen

| | Mit GPU (alles lokal) | Ohne GPU (Cloud oder externes Ollama) |
|---|---|---|
| Unraid | 6.12 oder neuer | 6.12 oder neuer |
| Plugins | **Nvidia-Driver** (Community Applications) | – |
| GPU | NVIDIA ab 8 GB VRAM, empfohlen 12 GB | – |
| RAM | 16 GB empfohlen | 8 GB |
| Speicher | ca. 12 GB Image + 8–15 GB Modelle (Cache-Pool) | ca. 12 GB Image + 1 GB |
| Netz | feste IP für den Server (Router/DHCP-Reservierung) | dito |

Das Image ist für NVIDIA gebaut, läuft aber auch ohne GPU (dann auf der CPU bzw. mit Cloud-Diensten).

## Installation

### Weg A – Installationsskript (empfohlen)

Im Unraid-Terminal (oben rechts `>_`):

```bash
curl -fsSL https://raw.githubusercontent.com/hoktaar/mini-jarvis/main/unraid/install.sh | bash
```

Das Skript

- erkennt eine NVIDIA-GPU und wählt die passende Vorlage (`mini-jarvis` bzw. `mini-jarvis-cpu`),
- legt `/mnt/user/appdata/mini-jarvis/{config,data,scripts}` und den Modellordner auf dem Cache-Pool an,
- kopiert die Beispiel-Skripte,
- trägt IP und Namen des Servers für das HTTPS-Zertifikat ein,
- prüft, ob die Ports 8080/8443 frei sind.

Danach: **Docker → Container hinzufügen → Vorlage „mini-jarvis“** (unter *Benutzervorlagen*) → *Anwenden*.

Optionen per Umgebungsvariable, z. B. ohne Cache-Pool und mit anderem Namen:

```bash
curl -fsSL https://raw.githubusercontent.com/hoktaar/mini-jarvis/main/unraid/install.sh \
  | MODELS=/mnt/user/appdata/mini-jarvis/models HOSTS=192.168.1.144,jarvis.lan bash
```

| Variable | Standard | Bedeutung |
|---|---|---|
| `GPU` | `auto` | `yes`/`no` erzwingt die Vorlage mit/ohne GPU |
| `APPDATA` | `/mnt/user/appdata/mini-jarvis` | Konfiguration, Daten, Skripte |
| `MODELS` | `/mnt/cache/appdata/mini-jarvis/models` (ohne Cache-Pool: unter `APPDATA`) | Modelle |
| `HOSTS` | IP von `br0` + `<hostname>.local` | Namen im HTTPS-Zertifikat |
| `BRANCH` | `main` | anderer Zweig des Repositorys |

### Weg B – Template-Repository

Docker → Einstellungen (erweiterte Ansicht) → **Template repositories**: `https://github.com/hoktaar/mini-jarvis`
eintragen und speichern. Danach stehen unter *Container hinzufügen* die Vorlagen `mini-jarvis` und
`mini-jarvis-cpu` bereit. Ordner und Skripte dann von Hand anlegen (siehe Weg C, Schritt 1).

### Weg C – von Hand

1. Ordner anlegen und Beispiel-Skripte kopieren:
   ```bash
   mkdir -p /mnt/user/appdata/mini-jarvis/{config,data,scripts} /mnt/cache/appdata/mini-jarvis/models
   ```
2. Vorlage herunterladen:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/hoktaar/mini-jarvis/main/unraid/mini-jarvis.xml \
     -o /boot/config/plugins/dockerMan/templates-user/my-mini-jarvis.xml
   ```
   (ohne GPU: `mini-jarvis-ohne-gpu.xml` → `my-mini-jarvis-cpu.xml`)
3. Docker → Container hinzufügen → Vorlage wählen → `JARVIS_HOSTS` ausfüllen → Anwenden.

## Container-Einstellungen

| Feld | Container | Standard | Hinweis |
|---|---|---|---|
| Web-UI und Geräte (HTTP) | `8080` | 8080 | CYD/ESP32, Apps, Health-Check |
| Web-UI (HTTPS) | `8443` | 8443 | Browser mit Mikrofon, USB-Flasher |
| Server-Adressen für das Zertifikat | `JARVIS_HOSTS` | – | z. B. `192.168.1.144,tower.local` |
| Zeitzone | `TZ` | Europe/Berlin | für Wecker und Uhr |
| Konfiguration | `/config` | appdata/…/config | YAML-Dateien, Admin-Token |
| Daten | `/data` | appdata/…/data | SQLite, Zertifikate, Firmware-Uploads |
| Modelle | `/models` | Cache-Pool | mehrere GB |
| Skripte (nur lesen) | `/scripts` | appdata/…/scripts | eigene Skripte |
| Docker-Socket | `/var/run/docker.sock` | – | optional, nur über den Filter-Proxy |
| Eingebettetes Ollama | `JARVIS_EMBEDDED_OLLAMA` | `auto` (CPU-Vorlage: `false`) | `false` bei externem Ollama |
| Eingebettetes SearXNG | `JARVIS_EMBEDDED_SEARXNG` | `auto` | lokale Websuche |
| Öffentliche Adresse | `JARVIS_PUBLIC_URL` | – | nur hinter Reverse-Proxy |
| Cloud-Schlüssel | `JARVIS_<NAME>` | – | z. B. `JARVIS_ANTHROPIC_API_KEY`, alternativ in `secrets.yaml` |

Netzwerk: **Bridge** genügt. Die Displays brauchen nur die IP des Servers und Port 8080.

## Erster Start

1. Container starten und das Log öffnen (Docker → Symbol → *Logs*). Beim ersten Start werden
   Beispielkonfiguration und Admin-Token angelegt und Modelle geladen – mit GPU einige GB, das dauert.
2. Web-UI öffnen: `https://<server-ip>:8443/` – die Zertifikatswarnung einmal bestätigen.
3. Admin-Token anzeigen (Container `mini-jarvis-cpu` bei der Vorlage ohne GPU):
   ```bash
   docker exec mini-jarvis grep admin_token /config/secrets.yaml
   ```
4. **Verwaltung** öffnen (Schild-Symbol bzw. `/admin.html`) und mit dem Token anmelden. Die **Übersicht** zeigt
   den Zustand aller Dienste und Hinweise auf fehlende Einstellungen.

![Verwaltung – Übersicht](images/verwaltung-uebersicht.png)

## HTTPS-Zertifikat installieren

Browser erlauben Mikrofon und USB nur über HTTPS. Jarvis erzeugt dafür eine eigene Zertifizierungsstelle (CA).
Einmal pro Gerät installieren, dann gibt es keine Warnungen mehr:
**Verwaltung → Übersicht → „CA-Zertifikat laden“** oder direkt `https://<server-ip>:8443/ca.crt`.

| System | So geht's |
|---|---|
| Windows | `jarvis-ca.crt` doppelklicken → *Zertifikat installieren* → *Lokaler Computer* → Speicher *Vertrauenswürdige Stammzertifizierungsstellen*. Chrome/Edge übernehmen das automatisch. |
| macOS | Datei öffnen → Schlüsselbund *System* → Zertifikat doppelklicken → *Vertrauen* → *Immer vertrauen*. |
| iPhone/iPad | In Safari öffnen → *Profil laden* → Einstellungen → *Profil geladen* → Installieren → Einstellungen → Allgemein → Info → *Zertifikatsvertrauenseinstellungen* → Jarvis einschalten. |
| Android | Einstellungen → Sicherheit → *Verschlüsselung und Anmeldedaten* → *Zertifikat installieren* → *CA-Zertifikat* (Menü je nach Hersteller). |
| Linux | `sudo cp jarvis-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates` |
| Firefox | Einstellungen → Datenschutz & Sicherheit → Zertifikate → *Importieren* → „Websites identifizieren“ |

Ändert sich die IP oder der Name des Servers, `JARVIS_HOSTS` anpassen und den Container neu starten – das
Serverzertifikat wird dann neu ausgestellt, die CA bleibt gleich.

## Grundkonfiguration

Alle Einstellungen stehen in `/mnt/user/appdata/mini-jarvis/config/config.yaml`; die Datei ist ausführlich
kommentiert. Nach Änderungen den Container neu starten. Absichten und Skripte lassen sich ohne Neustart
neu einlesen (Verwaltung → System).

**Pflicht:** Standort für Wetter und Zeitzone.

```yaml
location:
  name: Berlin
  latitude: 52.52
  longitude: 13.40
  timezone: Europe/Berlin
```

### Profile je nach Hardware

**12 GB VRAM oder mehr – alles lokal (Standard):**

```yaml
providers:
  stt: { type: whisper, model: large-v3-turbo }
  tts: { type: piper, voice: de_DE-thorsten-high }
  llm:
    primary: local
    local: { enabled: true, model: qwen3:8b }
```

**8 GB VRAM:** wie oben, aber `model: qwen3:4b` (schneller, etwas weniger klug) oder `num_ctx: 4096`.

**Ohne GPU – Cloud-Sprachmodell, Rest lokal auf der CPU:**

```yaml
providers:
  stt: { type: whisper, model: small, device: cpu, compute_type: int8 }   # oder deepgram/openai
  tts: { type: piper }
  llm:
    primary: cloud
    local: { enabled: false }
    cloud: { enabled: true, type: anthropic, model: claude-sonnet-5-5 }
```

**Externes Ollama** (anderer Rechner im Netz): `local.base_url: http://192.168.1.50:11434/v1` und in der
Vorlage `JARVIS_EMBEDDED_OLLAMA=false`.

**Lokal zuerst, Cloud als Rückfallebene:** `primary: local` und `cloud.enabled: true` – Jarvis nutzt die Cloud nur,
wenn das lokale Modell ausfällt oder du es ausdrücklich verlangst („frag die Cloud …“). Ein Budget begrenzt die
Kosten:

```yaml
    cloud:
      budget_eur_day: 1.0
      budget_eur_month: 10.0
```

Schlüssel gehören in `secrets.yaml` (oder als Variable in die Vorlage). Der **Privatmodus** pro Gerät hält
Sprachmodell und Werkzeuge lokal.

## Geräte koppeln

| Gerät | So geht's |
|---|---|
| Handy/Tablet/PC (PWA) | Verwaltung → Geräte → *Neues Gerät*, Typ „Browser / Handy“ → QR-Code scannen. Im Browser „Zum Startbildschirm hinzufügen“. |
| CYD-Display | Verwaltung → **Firmware** → *CYD per USB einrichten* (Chrome/Edge am PC, über HTTPS). Details in [HARDWARE.md](HARDWARE.md). |
| Telegram | Bot bei @BotFather anlegen, Token in `secrets.yaml`, eigene ID in `adapters.telegram.allowed_user_ids`. |
| Matrix | Bot-Konto anlegen, `adapters.matrix` ausfüllen, Passwort in `secrets.yaml`. |

![Gerät koppeln](images/verwaltung-koppeln.png)

## Home Assistant, Kalender, Telegram

```yaml
homeassistant:            # Kacheln im Dashboard, Seiten „Licht“ und „Musik“ auf dem CYD
  enabled: true
  url: http://192.168.1.20:8123
  entities: [light.wohnzimmer, switch.kaffeemaschine, media_player.wohnzimmer, scene.filmabend]

mcp_servers:              # Sprachsteuerung: HA-Integration „Model Context Protocol Server“ aktivieren,
  - name: homeassistant   # dann im vorhandenen Eintrag enabled und url anpassen
    enabled: true
    url: http://192.168.1.20:8123/api/mcp

calendar:                 # CalDAV, z. B. Nextcloud
  enabled: true
  url: https://cloud.example.lan/remote.php/dav
  username: anna
```

Token/Passwörter: `homeassistant_token`, `caldav_password`, `telegram_bot_token` in `secrets.yaml`.

## GPU mit ComfyUI teilen

```yaml
gpu:
  comfyui_mode: auto      # erkennt einen laufenden ComfyUI-Container (Docker-Socket nötig)
```

`auto` gibt den Grafikspeicher kurz nach einer Antwort frei, solange ComfyUI läuft; `on` macht das immer.
Whisper weicht dann auf die CPU aus.

## Updates

- **Jarvis:** Docker → *Nach Updates suchen* → *Aktualisieren*. Konfiguration und Daten bleiben erhalten.
- **CYD-Firmware:** Das Image bringt die passende Firmware mit. Verwaltung → Geräte → *Update* – oder
  automatisch mit `firmware.auto_update: true`. Die Displays laden die Firmware per WLAN, prüfen die MD5-Summe
  und starten neu.

## Backup

Sichern: `/mnt/user/appdata/mini-jarvis/config` und `…/data` (z. B. mit dem Plugin *Appdata Backup*).
Die Modelle lassen sich jederzeit neu laden und müssen nicht gesichert werden.

## Fernzugriff

Keinen Port ins Internet freigeben. Stattdessen Unraid → Einstellungen → **VPN-Manager** (WireGuard), Tunnel
„Fernzugriff auf LAN“ anlegen und das Handy damit verbinden – die PWA funktioniert dann auch unterwegs.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `could not select device driver "nvidia"` | Plugin *Nvidia-Driver* installieren und Docker neu starten – oder die Vorlage ohne GPU nutzen. |
| Image lässt sich nicht laden (`unauthorized`) | Paket auf GitHub öffentlich machen: Profil → Packages → mini-jarvis → Package settings → *Change visibility* → Public. |
| Seite zeigt lange „Jarvis startet …“ | Modelle werden geladen – Container-Log ansehen. |
| Mikrofon geht im Browser nicht | Über `https://…:8443` öffnen und das CA-Zertifikat installieren. |
| USB-Flasher: „USB nicht verfügbar“ | Chrome, Edge oder Opera am Computer und HTTPS nötig. Unter Windows/macOS ggf. den CH340-Treiber installieren. |
| CYD findet den Server nicht | Feste IP statt `.local`-Namen verwenden, Port 8080 erreichbar? Der ESP32 kann nur 2,4-GHz-WLAN. |
| Antworten sind langsam | Verwaltung → Übersicht → *Antwortzeiten*. Ohne GPU läuft Whisper auf der CPU – kleineres Modell oder Cloud-STT wählen. |
| „Ollama FEHLER“ in der Übersicht | Modell lädt noch oder passt nicht in den Grafikspeicher – kleineres Modell wählen. |
| Container-Steuerung geht nicht | Docker-Socket in der Vorlage eintragen und den Container in `whitelist.yaml` freigeben. |
| Admin-Token vergessen | `docker exec mini-jarvis grep admin_token /config/secrets.yaml` |

Mehr Details zeigt das Log: Docker → Symbol → *Logs* oder `docker logs -f mini-jarvis`.

## Deinstallation

Container entfernen (Docker → Symbol → *Entfernen*, Häkchen bei *Image entfernen*), dann

```bash
rm -rf /mnt/user/appdata/mini-jarvis /mnt/cache/appdata/mini-jarvis
rm -f /boot/config/plugins/dockerMan/templates-user/my-mini-jarvis*.xml
```
