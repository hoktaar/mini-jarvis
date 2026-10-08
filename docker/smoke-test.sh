#!/bin/sh
# Rauchtest für das Image ohne GPU: schlanke Konfiguration (kein lokales LLM, keine Audio-Modelle),
# dann Health, Web-UI, Verwaltung, Skript-Runner und eingebaute Firmware prüfen.
#   docker build -t mini-jarvis:test -f docker/Dockerfile . && sh docker/smoke-test.sh mini-jarvis:test
set -eu
IMAGE=${1:-mini-jarvis:test}
NAME=jarvis-smoke
PORT=${PORT:-18080}
WORK=$(mktemp -d)
trap 'docker rm -f $NAME >/dev/null 2>&1 || true' EXIT

mkdir -p "$WORK/config" "$WORK/scripts"
cp config/examples/*.yaml "$WORK/config/"
cp scripts/say_hello.sh "$WORK/scripts/" && chmod 755 "$WORK/scripts/say_hello.sh"
python3 - "$WORK/config/config.yaml" <<'PY'
import sys
import yaml
path = sys.argv[1]
cfg = yaml.safe_load(open(path, encoding="utf-8"))
cfg["providers"]["stt"] = {"type": "none"}
cfg["providers"]["tts"] = {"type": "none"}
cfg["providers"]["llm"]["local"]["enabled"] = False
cfg["router"]["embedding_model"] = ""
cfg["search"]["provider"] = "none"
for m in cfg["mcp_servers"]:
    if m["name"] == "searxng":
        m["enabled"] = False
yaml.safe_dump(cfg, open(path, "w", encoding="utf-8"), allow_unicode=True)
PY

docker run -d --name $NAME -p "$PORT:8080" -v "$WORK/config:/config" -v "$WORK/scripts:/scripts" "$IMAGE" >/dev/null
fail() { echo "FEHLER: $1"; docker logs --tail 200 $NAME; exit 1; }

i=0
until curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null; do
  i=$((i + 1)); [ $i -gt 60 ] && fail "/api/health antwortet nicht"
  sleep 3
done
echo "Health ok"
curl -fs "http://127.0.0.1:$PORT/" | grep -q "JARVIS" || fail "Web-UI fehlt"
curl -fs "http://127.0.0.1:$PORT/admin.html" | grep -q "Verwaltung" || fail "Verwaltung fehlt"

TOKEN=$(docker exec $NAME python3 -c "import yaml; print(yaml.safe_load(open('/config/secrets.yaml'))['admin_token'])")
H="X-Admin-Token: $TOKEN"
curl -fs -H "$H" "http://127.0.0.1:$PORT/api/admin/overview" | grep -q '"version"' || fail "Übersicht"
curl -fs -H "$H" -H "Content-Type: application/json" -d '{"args": {"name": "Rauchtest"}}' \
  "http://127.0.0.1:$PORT/api/admin/scripts/say_hello/run" | grep -q "Rauchtest" || fail "Skript-Runner"
curl -fs -H "$H" "http://127.0.0.1:$PORT/api/admin/firmware" | grep -q '"cyd"' || fail "eingebaute Firmware fehlt"
echo "Rauchtest bestanden"
