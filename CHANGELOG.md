# Changelog

## 0.4.0 – Einstellungen ohne YAML

**Verwaltung → Einstellungen** (neu)
- Alle Einstellungen per Formular: Allgemein (Ortssuche füllt Koordinaten und Zeitzone), Sprachmodell (lokal und
  Cloud, Ollama-Modelle anzeigen und herunterladen), Sprache, Suche & Nachrichten, Smart Home (Verbindung testen,
  Geräte ankreuzen, Sprachsteuerung per HA-MCP), Kalender, Benachrichtigungen, Werkzeuge (Docker-Freigaben,
  ComfyUI, MCP-Server), Netzwerk & Sicherheit, Schlüssel & Zugänge, Erweitert.
- Prüfung vor dem Speichern mit Meldungen am Feld; Schlüssel werden nie angezeigt; Hinweise in der Übersicht
  führen direkt zur passenden Stelle.
- YAML wird rundgeschrieben: Kommentare und Reihenfolge bleiben, vor jeder Änderung eine Sicherung unter
  `/config/backups/`.
- **Jetzt neu starten**: Jarvis startet aus der Verwaltung neu (gleicher Prozess); Änderungen, die einen Neustart
  des Containers brauchen, werden benannt.
- `JARVIS_CONFIG_READONLY=true` sperrt das Schreiben (bisheriges Verhalten).

**Weitere Seiten**
- Skripte freigeben, ändern und entfernen (mit Parametern); der Runner übernimmt Änderungen sofort, fehlerhafte
  Einträge werden übersprungen statt alle Skripte abzuschalten.
- Router: Absicht antippen → eigene Beispielsätze lernen und löschen.
- Firmware: automatische Updates per Schalter. System: Neustart, Admin-Token neu erzeugen, Rohansicht.
- Container-Freigaben wirken sofort im Docker-Proxy (root-Wächter erzeugt die Regeln neu).

**Betrieb und Doku**
- Admin-Token erscheint beim ersten Start im Container-Log.
- Rauchtest prüft Speichern einer Einstellung und Neustart im Container.
- README und Unraid-Anleitung ohne YAML, deutlicher Hinweis „Work in Progress“.

## 0.3.0 – Vollwertiger Betrieb, Cloud-Anbieter, neue Oberflächen, CYD-Firmware

**Betrieb und Sicherheit**
- Container startet zuverlässig: Konfiguration und Admin-Token werden als root angelegt, Runner-Socket mit
  passenden Rechten, Docker-Socket über Gruppenmitgliedschaft statt `chmod`, HAProxy-Regeln aus der Whitelist.
- HTTPS mit eigener CA auf Port 8443 (`/ca.crt`), Zertifikat folgt `JARVIS_HOSTS`.
- Geräte-Token per `Authorization`-Header oder Einmal-Ticket, Tokens im Log geschwärzt; Admin-Token mit
  konstantzeitigem Vergleich und Bremse gegen Raten.
- Strengere Ja/Nein-Bestätigung (Zeitlimit, „wie bitte?“, zwei unklare Antworten = Abbruch), Taint bleibt
  mehrere Runden bestehen, MCP-Tools mit Allowlist und Risikostufen.

**Sprache und Werkzeuge**
- Eine Sitzung pro Gerät (Sprache und Text teilen Verlauf), Text-Pipeline für REST, Telegram und Matrix.
- Router mit Dialogzustand, optionalen Angaben, deutscher Datums-/Zeiterkennung („halb sieben“, „übermorgen
  früh“) – 92,7 % auf dem Testsatz; Auswertung per `python -m jarvis.router.eval` und in der Verwaltung.
- Neue Werkzeuge: Wecker löschen, Gedächtnis, Kalender (CalDAV), Home Assistant, Lautstärke, Privatmodus,
  Wiederholen, Neues Thema, Hilfe; Wetter mit Ort und bis 15 Tage.
- Push über ntfy, Telegram- und Matrix-Bots mit Ja/Nein-Knöpfen und Sprachnachrichten.

**Cloud-Anbieter (gleichwertig zu lokal)**
- Sprachmodell: Anthropic, OpenAI, Google, Mistral, Groq, OpenRouter, DeepSeek, OpenAI-kompatibel;
  `primary: local|cloud` mit Ausfall in beide Richtungen, lokales Modell optional.
- Spracherkennung: Whisper, OpenAI, Groq, Deepgram, Azure, Google, ElevenLabs; Sprachausgabe: Piper, OpenAI,
  ElevenLabs, Cartesia, Deepgram, Azure, Google; Websuche: SearXNG, Brave, Tavily.
- Budget pro Tag/Monat, Privatmodus pro Gerät, Hinweise auf fehlende Schlüssel in der Verwaltung.

**Oberflächen**
- Neues HUD-Dashboard: Reaktor mit Zuständen, Wellenform, Chat, Globaler Status, Systemressourcen, Smarthome,
  Bevorstehend, Live-Datenfeed, Netzwerkaktivität; passt sich Desktop, Tablet und Handy an, hell/dunkel.
- Neue Verwaltung im selben Design: Übersicht, Geräte (QR-Kopplung, OTA), Firmware mit USB-Assistent,
  Router (Test, Auswertung, Korrektur), Gedächtnis, Skripte, Timer, Protokoll, System.

**CYD-Firmware 0.3.0**
- Oberfläche nach Entwurf (Uhr, WLAN, Reaktor, Wellenform, Start/Licht/Musik/Einstellungen), Hoch- und
  Querformat, Umlaute; Audio in eigenen Tasks, Weckton, Push-to-Talk.
- Erstinstallation per USB aus der Verwaltung (esptool-js + serielle Einrichtung), Updates per OTA.
- Baut mit pioarduino 55.03.312 (Arduino-ESP32 3.3.12). Docker-Image enthält die fertige Firmware.

**Build**
- CI: Lint, Tests, Router-Auswertung, Firmware-Build mit Paket und PC-Vorschau, Image mit Rauchtest ohne GPU,
  Tags `latest`, Version und Commit.

**Unraid und Doku**
- `unraid/install.sh`: erkennt die GPU, legt Ordner an, lädt Beispiel-Skripte und schreibt eine ausgefüllte
  Vorlage (mit IP für das Zertifikat); Vorlagen mit und ohne GPU, nutzbar auch als Template-Repository.
- Ausführliche Anleitung (Zertifikat je Betriebssystem, Profile je GPU, Updates, Backup, Fehlerbehebung),
  README mit Animationen, Screenshots, Verkabelungsgrafik und Einkaufsliste.
- Router: Bonus für erkannte Angaben wächst mit der Zahl der Pflichtangaben („Erinnere mich um 22 Uhr an den
  Müll“ geht jetzt direkt über den Schnellweg).
- Dashboard: Eingabefeld bleibt auch bei niedrigen Bildschirmen sichtbar (Vorschläge einzeilig).

## 0.2.1 – Image-Build

- SearXNG-Installation im Dockerfile korrigiert (Requirements vor Editable-Install).
- torch als CPU-Variante, openWakeWord 0.6 ohne tflite (Python 3.12) – Image deutlich kleiner.
- CI: Speicherplatz auf dem Runner freimachen, Buildx einrichten.

## 0.2.0 – Phase 1 (Kern)

- Sprachweg Ende-zu-Ende getestet: simulierter CYD und PWA im Browser mit Mikrofon.
- PWA: Sprachmodus über Pipecat JS-SDK (lokal gebündelt, kein CDN), Verwaltungsseite
  für Geräte, Router-Log und Aktionsprotokoll.
- VAD als eigener Prozessor vor Whisper (segmentierte STT braucht die VAD-Frames).
- Schnellweg-Antworten lösen kein LLM mehr aus und erscheinen nicht doppelt.
- Container-Aktionen über den Schnellweg („Starte Jellyfin neu“) – mit Pflicht-Bestätigung.
- Whisper-Hotwords für Container-Namen; Namen mit Bindestrich („Jellyfin-Container“).
- Doppelte Transkripte werden verworfen (verhindert doppelte Timer).
- Freundliche Ansage, wenn das LLM oder die Docker-Steuerung nicht erreichbar ist.
- Eigener Serializer für Pipecat-JS-Clients (keine Konsolenfehler).

## 0.1.0 – Grundgerüst

- Plan, Container, Router, Policy, Runner, Tools, Docker-MCP, Firmware-Gerüst.
