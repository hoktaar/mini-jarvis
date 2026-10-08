#!/bin/sh
# Lädt beim Start fehlende Modelle (einmalig, danach in /models persistent).
if [ "$JARVIS_OLLAMA_AUTOSTART" = "true" ]; then
  MODEL="${OLLAMA_MODEL:-qwen3:8b}"
  for i in $(seq 1 60); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 2; done
  ollama list | grep -q "^${MODEL}" || ollama pull "$MODEL"
else
  echo "Externes Ollama konfiguriert – kein Modell-Download."
fi
# openWakeWord legt seine Modelle im Paket ab – Rechte für den Core setzen
/opt/venv/bin/python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])" || true
echo "Modelle bereit."
