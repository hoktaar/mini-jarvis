# Installation auf Unraid

1. **Nvidia-Driver-Plugin** installieren (ohne GPU geht es auch – dann Cloud-Anbieter oder ein externes Ollama nutzen).
2. Template `unraid/mini-jarvis.xml` nach `/boot/config/plugins/dockerMan/templates-user/` kopieren und den
   Container anlegen. Das Image kommt aus `ghcr.io/hoktaar/mini-jarvis` (gebaut von GitHub Actions).
3. Pfade:
   - `/config` → `/mnt/user/appdata/mini-jarvis/config`
   - `/data` → `/mnt/user/appdata/mini-jarvis/data`
   - `/models` → `/mnt/cache/appdata/mini-jarvis/models` (groß, Cache-Pool!)
   - `/scripts` → `/mnt/user/appdata/mini-jarvis/scripts` (**read-only**)
   - `/var/run/docker.sock` → `/var/run/docker.sock` (nur für den Filter-Proxy)
4. **Server-Adressen für das Zertifikat** (`JARVIS_HOSTS`): IP und Namen des Servers, z. B.
   `192.168.1.144,tower.local`. Ports 8080 (HTTP, für CYD/ESP32) und 8443 (HTTPS, Browser) freigeben.
5. Beim ersten Start werden Beispielkonfigurationen nach `/config` kopiert, der Admin-Token erzeugt und
   Modelle geladen (einige GB, dauert).
6. Web-UI: `https://192.168.1.144:8443/` – beim ersten Mal die Zertifikatswarnung bestätigen, dann unter
   **Verwaltung → Übersicht → CA-Zertifikat laden** die CA auf jedem Gerät installieren. Danach gibt es keine
   Warnungen mehr, und Mikrofon sowie USB-Flasher funktionieren.
7. Admin-Token: `docker exec mini-jarvis grep admin_token /config/secrets.yaml`

## Cloud statt (oder zusätzlich zu) lokalen Modellen

In `config.yaml` unter `providers`:

```yaml
providers:
  llm:
    primary: cloud            # oder local (Cloud dann nur bei Ausfall/auf Wunsch)
    local: { enabled: false } # ohne GPU
    cloud: { enabled: true, type: anthropic, model: claude-… }
  stt: { type: deepgram }     # oder whisper (lokal), openai, groq, azure, google, elevenlabs
  tts: { type: elevenlabs }   # oder piper (lokal), openai, cartesia, deepgram, azure, google
```

Schlüssel in `secrets.yaml` oder als Variable im Template (`JARVIS_ANTHROPIC_API_KEY` …). Läuft kein lokales
Modell, startet der Container Ollama nicht (`JARVIS_EMBEDDED_OLLAMA=auto`). Der Privatmodus pro Gerät
hält Sprachmodell und Werkzeuge lokal (Spracherkennung/-ausgabe bleiben beim eingestellten Anbieter – Jarvis
weist darauf hin); das Budget begrenzt die Kosten.

## GPU mit ComfyUI teilen

`gpu.comfyui_mode: auto` erkennt einen laufenden ComfyUI-Container über den Docker-Proxy und entlädt das
Sprachmodell nach kurzer Zeit; `on` erzwingt das dauerhaft.

## CYD-Display einrichten

Verwaltung → **Firmware** → „CYD per USB einrichten“ (Chrome/Edge am Computer, über HTTPS). Updates kommen
danach per WLAN: Verwaltung → Geräte → „Update“ oder automatisch mit `firmware.auto_update: true`.
