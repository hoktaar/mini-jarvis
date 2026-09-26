#!/bin/sh
set -e

mkdir -p /config /data /models/ollama /models/piper /models/hf /run/jarvis /scripts
# Beispielkonfiguration beim ersten Start
for f in /opt/jarvis/config/examples/*.yaml; do
  [ -f "/config/$(basename "$f")" ] || cp "$f" /config/
done

# Rechte: Core schreibt /data, liest /config; nur 'proxy-docker' liest den Docker-Socket
chown -R jarvis:jarvis /data /models/piper /models/hf /run/jarvis
chown -R ollama-svc /models/ollama
chown -R root:jarvis /config && chmod -R g+rX /config && chmod 640 /config/secrets.yaml
if [ -S /var/run/docker.sock ]; then
  chown proxy-docker /var/run/docker.sock && chmod 600 /var/run/docker.sock
fi
# SearXNG-Schlüssel erzeugen
if grep -q "CHANGE-SEARXNG-SECRET" /etc/searxng/settings.yml; then
  sed -i "s/CHANGE-SEARXNG-SECRET/$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')/" /etc/searxng/settings.yml
fi

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
