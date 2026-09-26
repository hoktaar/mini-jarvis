#!/bin/sh
# Lädt beim Start fehlende Modelle (einmalig, danach in /models persistent).
MODEL=$(python3 -c "import yaml;print(yaml.safe_load(open('/config/config.yaml'))['providers']['llm']['local']['model'])" 2>/dev/null || echo qwen3:8b)
for i in $(seq 1 60); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 2; done
ollama list | grep -q "^${MODEL}" || ollama pull "$MODEL"
/opt/venv/bin/python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])" || true
echo "Modelle bereit."
