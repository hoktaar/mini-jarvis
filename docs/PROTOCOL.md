# Protokolle

## Anmeldung

Jedes Gerät hat ein eigenes Token (Verwaltung → Geräte). Der Server speichert nur den SHA-256-Hash.

| Weg | Wer | Wie |
|---|---|---|
| `Authorization: Bearer <token>` | CYD/ESP32, Apps, REST | bevorzugt – landet nicht in Logs |
| Einmal-Ticket | Browser (WebSockets können keine Header) | `POST /api/ws-ticket` mit Bearer → `{"ticket"}`, 60 s gültig, einmal nutzbar: `/ws/client?ticket=…` |
| `?token=…` | ältere Firmware | weiterhin erlaubt, wird im Log geschwärzt |

Verwaltung: Header `X-Admin-Token` (beim ersten Start im Container-Log, gespeichert in `/config/secrets.yaml`).
Fehlversuche werden gebremst.

## 1. RTVI (PWA, Android, Desktop)

`wss://<server>:8443/ws/client?ticket=…` (oder `ws://…:8080`) mit dem Pipecat-Protobuf-Serializer.
Audio: Mikrofon 16 kHz, Antwort 24 kHz (fest im WavMediaManager des Browsers).

- Jarvis-Ereignisse kommen als RTVI-Server-Message `{"jarvis": {…}}` (Inhalt wie unten).
- Client-Nachrichten als RTVI-Client-Message mit `type: "jarvis"` und den Feldern unten als `data`.

## 2. CYD-Protokoll (schlanke ESP32 ohne PSRAM)

`ws://<server>:8080/ws/cyd` mit `Authorization: Bearer <token>`.
Binärframes = PCM 16 Bit, mono, 16 kHz, little-endian (in beide Richtungen, empfohlen 20 ms = 640 Bytes).
Textframes = JSON (UTF-8).

### Gerät → Server

| Nachricht | Bedeutung |
|---|---|
| `{"type":"hello","fw":"0.3.0","board":"cyd","caps":["mic","speaker","display","touch"],"rssi":-61,"ip":"…"}` | nach dem Verbinden; `board` = Firmware-Variante für OTA |
| `{"type":"ptt","value":"start"\|"stop"}` | Push-to-Talk; `start` unterbricht Jarvis |
| `{"type":"stop"}` | Wiedergabe abbrechen |
| `{"type":"text","content":"…","speak":true}` | getippte Frage |
| `{"type":"alarm_ack","id":42}` / `{"type":"alarm_snooze","id":42,"minutes":5}` | Wecker aus / schlummern |
| `{"type":"private","value":true}` | Privatmodus (nur lokale Dienste) |
| `{"type":"volume","value":70}` | Lautstärke 0–100, wird gespeichert |
| `{"type":"ota_status","state":"downloading\|done\|error","progress":40,"version":"…","error":"…"}` | Update-Fortschritt |
| `{"type":"home_list","group":"light\|media\|all"}` | Smarthome-Seite laden |
| `{"type":"home_toggle","id":"light.flur","group":"light"}` | schalten (nur freigegebene Entitäten) |
| `{"type":"home_media","id":"media_player.wz","action":"play_pause\|next\|previous\|volume_up\|volume_down"}` | Mediaplayer |

### Server → Gerät

| Nachricht | Bedeutung |
|---|---|
| `{"type":"hello","device":"Küche","kind":"cyd","room":"…","version":"0.3.0","time":1760000000,"tz":"CET-1CEST,M3.5.0,M10.5.0/3"}` | Gerätename, Uhrzeit, POSIX-Zeitzone |
| `{"type":"state","value":"idle\|listening\|thinking\|speaking"}` | Zustand für Anzeige und Mikrofon |
| `{"type":"text","role":"user\|assistant","content":"…","meta":{"route","intent","provider","confirm"}}` | Transkript und Antwort; `confirm: true` = Jarvis wartet auf Ja/Nein |
| `{"type":"turn_done"}` | Antwort vollständig |
| `{"type":"alarm","id":42,"kind":"timer\|alarm\|reminder","label":"Pizza"}` / `{"type":"alarm_stop","id":42}` | Wecker klingelt / wurde beendet (auch von anderem Gerät) |
| `{"type":"timers","items":[{"id","kind","label","due","ringing"}],"now":…}` | laufende Timer, Wecker, Erinnerungen |
| `{"type":"volume","value":70}` / `{"type":"private","value":false}` | Einstellungen |
| `{"type":"notice","text":"…"}` | kurzer Hinweis |
| `{"type":"cloud","value":true}` | Antwort lief über einen Cloud-Dienst |
| `{"type":"home","group":"light","configured":true,"items":[{"id","name","display","on","kind":"toggle\|activate\|media\|sensor","available"}]}` | Smarthome-Kacheln |
| `{"type":"ota","version":"0.3.1","md5":"…","size":1598448,"path":"/api/firmware/cyd/firmware.bin"}` | Update laden (HTTP GET mit Bearer, MD5 prüfen) |
| `{"type":"clear"}` | Wiedergabepuffer sofort leeren (Unterbrechung) |
| `{"type":"feed","item":{…}}` | Live-Datenfeed (nur Bildschirme mit Dashboard) |

## 3. USB-Einrichtung (serielle Konsole, 115200 Baud)

Vom Web-Flasher der Verwaltung genutzt, siehe [firmware/cyd/README.md](../firmware/cyd/README.md#serielles-einrichtungsprotokoll-115200-baud).
WLAN-Zugangsdaten gehen dabei nur über USB an das Gerät.

## 4. REST

| Methode | Pfad | Zugriff | Zweck |
|---|---|---|---|
| GET | `/api/health`, `/api/info` | offen | Lebenszeichen, Version, HTTPS-Infos |
| GET | `/ca.crt` | offen | CA-Zertifikat zum Installieren |
| POST | `/api/ws-ticket` | Gerät | Einmal-Ticket für WebSockets |
| GET/PATCH | `/api/me` | Gerät | eigenes Gerät, Privatmodus |
| POST | `/api/chat` | Gerät | Textfrage (`{"text","speak"}`) |
| GET/DELETE | `/api/timers[/{id}]` | Gerät | Timer ansehen/löschen |
| POST | `/api/alarms/{id}/ack\|snooze` | Gerät | Wecker |
| GET | `/api/dashboard` | Gerät | alles fürs Dashboard (Wetter, Geräte, Systemwerte, Aufgaben, Feed, Smarthome) |
| POST | `/api/home/{entity}/toggle` | Gerät | Kachel schalten |
| GET | `/api/firmware/{variante}/{datei}.bin` | Gerät oder Admin | OTA und Web-Flasher |
| * | `/api/admin/*` | Admin | Übersicht, Geräte (+ `rotate`, `ota`), Firmware (+ `upload`, `manifest`), Router (`router-log`, `correct`, `test`, `eval`, `retrain`), Absichten (+ eigene Beispielsätze), Gedächtnis, Skripte (+ `run`, anlegen/ändern/entfernen, `script-files`), Timer, Protokoll, `reload`, `provision-info` |
| GET/PUT | `/api/admin/settings` | Admin | Einstellungen lesen (Schlüssel nur als „gesetzt“) bzw. ändern: `{"changes": {"pfad.zum.wert": …}, "secrets": {"name": "…"}, "whitelist": {"container": ["status", …]}}` – Fehler je Feld als `detail.errors` |
| POST | `/api/admin/restart` | Admin | Jarvis neu starten (gleicher Prozess, liest die Einstellungen neu); `/api/health` liefert danach ein neues `boot` |
| POST | `/api/admin/token/rotate` | Admin | neuen Admin-Token erzeugen |
| GET/POST | `/api/admin/ollama`, `/api/admin/ollama/pull` | Admin | Modelle des (lokalen) Ollama anzeigen bzw. herunterladen (Fortschritt per GET) |
| POST | `/api/admin/homeassistant/test` | Admin | Verbindung prüfen und Entitäten zur Auswahl laden |
| GET | `/api/admin/geocode?q=` | Admin | Ortssuche (Open-Meteo) für den Standort |
