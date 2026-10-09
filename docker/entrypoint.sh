#!/bin/sh
# Startet als root, richtet Rechte ein und übergibt an supervisord.
set -e
PY=/opt/venv/bin/python

mkdir -p /config /data /models/ollama /models/piper /models/hf /scripts
# Runner-Socket: Verzeichnis gehört runner, Gruppe jarvis (setgid → Socket erbt die Gruppe)
install -d -o runner -g jarvis -m 2770 /run/jarvis

# Beispielkonfiguration und Admin-Token beim ersten Start (der Token steht dann im Container-Log)
$PY -m jarvis.config --init --config-dir /config

chown -R jarvis:jarvis /data /models/piper /models/hf
chown -R ollama-svc /models/ollama
# /config: Die Verwaltung schreibt die Einstellungen (Gruppe jarvis). JARVIS_CONFIG_READONLY=true sperrt das –
# dann gilt nur, was in den Dateien steht.
chown -R root:jarvis /config
if [ "${JARVIS_CONFIG_READONLY:-false}" = "true" ]; then
  chmod -R u+rwX,g+rX,g-w,o-rwx /config
  chmod 640 /config/secrets.yaml
  echo "Einstellungen gesperrt (JARVIS_CONFIG_READONLY=true) – die Verwaltung zeigt sie nur an."
else
  chmod -R u+rwX,g+rwX,o-rwx /config
  find /config -type d -exec chmod g+s {} +
  chmod 660 /config/secrets.yaml
fi

# Docker-Proxy: Regeln aus der Whitelist erzeugen. Den Host-Socket NIE umbiegen –
# stattdessen tritt der Proxy-Benutzer der Gruppe des Sockets bei.
$PY -m jarvis.mcp_servers.haproxy_gen /config/whitelist.yaml /etc/haproxy/haproxy.cfg
if [ -S /var/run/docker.sock ]; then
  gid=$(stat -c %g /var/run/docker.sock)
  if [ "$gid" = "0" ]; then
    echo "Hinweis: docker.sock gehört der Gruppe root – der Proxy-Benutzer tritt ihr bei."
    usermod -aG root proxy-docker
  else
    grp=$(getent group "$gid" | cut -d: -f1 || true)
    if [ -z "$grp" ]; then
      groupadd -g "$gid" dockerhost
      grp=dockerhost
    fi
    usermod -aG "$grp" proxy-docker
  fi
fi

# SearXNG-Schlüssel (einmal pro Container)
if grep -q "CHANGE-SEARXNG-SECRET" /etc/searxng/settings.yml; then
  sed -i "s/CHANGE-SEARXNG-SECRET/$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')/" /etc/searxng/settings.yml
fi

# Ollama-Parameter und Autostart der eingebetteten Dienste aus config.yaml
eval "$($PY -m jarvis.config --env --config-dir /config)"
echo "Eingebettetes Ollama: $JARVIS_OLLAMA_AUTOSTART, SearXNG: $JARVIS_SEARXNG_AUTOSTART"

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
