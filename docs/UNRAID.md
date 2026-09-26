# Installation auf Unraid

1. **Nvidia-Driver-Plugin** installieren.
2. Image bauen: `docker build -t mini-jarvis -f docker/Dockerfile .`
   (später per GitHub Actions nach `ghcr.io/hoktaar/mini-jarvis`).
3. Template `unraid/mini-jarvis.xml` nach
   `/boot/config/plugins/dockerMan/templates-user/` kopieren und Container anlegen.
4. Pfade:
   - `/config` → `/mnt/user/appdata/mini-jarvis/config`
   - `/data` → `/mnt/user/appdata/mini-jarvis/data`
   - `/models` → `/mnt/cache/appdata/mini-jarvis/models` (groß, Cache-Pool!)
   - `/scripts` → `/mnt/user/appdata/mini-jarvis/scripts` (**read-only**)
   - `/var/run/docker.sock` → `/var/run/docker.sock` (nur für den Proxy)
5. Extra Parameters: `--runtime=nvidia`
6. Beim ersten Start werden Beispielkonfigurationen nach `/config` kopiert und
   Modelle geladen (einige GB, dauert).
7. Web-UI: `http://192.168.1.144:8080`, Admin-Token steht in `/config/secrets.yaml`.

## GPU mit ComfyUI teilen

In `config.yaml`: `gpu.comfyui_mode: true` → Whisper auf CPU,
Ollama `keep_alive` kurz.
