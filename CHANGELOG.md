# Changelog

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
