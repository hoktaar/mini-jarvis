#!/bin/bash
# Mini-Jarvis auf Unraid vorbereiten: Ordner, Beispiel-Skripte und ein fertig ausgefülltes Template.
#
#   curl -fsSL https://raw.githubusercontent.com/hoktaar/mini-jarvis/main/unraid/install.sh | bash
#
# Danach: Docker → Container hinzufügen → Vorlage „mini-jarvis“ (Benutzervorlagen) → Anwenden.
#
# Optionen (Umgebungsvariablen):
#   GPU=auto|yes|no        NVIDIA-GPU nutzen (auto = erkennen)
#   APPDATA=/mnt/user/appdata/mini-jarvis
#   MODELS=/mnt/cache/appdata/mini-jarvis/models   (Standard: Cache-Pool, falls vorhanden)
#   HOSTS=192.168.1.144,tower.local                (Standard: IP und Name dieses Servers)
#   BRANCH=main  REPO=hoktaar/mini-jarvis
set -euo pipefail

REPO="${REPO:-hoktaar/mini-jarvis}"
BRANCH="${BRANCH:-main}"
RAW="${RAW:-https://raw.githubusercontent.com/$REPO/$BRANCH}"
APPDATA="${APPDATA:-/mnt/user/appdata/mini-jarvis}"
TEMPLATES="${TEMPLATES:-/boot/config/plugins/dockerMan/templates-user}"
GPU="${GPU:-auto}"

say()  { printf '\033[1;36m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || die "curl fehlt."
[ -d /boot/config ] || warn "Kein Unraid erkannt (/boot/config fehlt) – Vorlage wird trotzdem nach $TEMPLATES geschrieben."

# ---------------------------------------------------------------- Modelle: Cache-Pool bevorzugen
if [ -z "${MODELS:-}" ]; then
  if [ -d /mnt/cache ]; then MODELS=/mnt/cache/appdata/mini-jarvis/models; else MODELS="$APPDATA/models"; fi
fi

# ---------------------------------------------------------------- GPU erkennen
if [ "$GPU" = auto ]; then
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then GPU=yes; else GPU=no; fi
fi
if [ "$GPU" = yes ]; then
  ok "NVIDIA-GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo erkannt)"
  if command -v docker >/dev/null && ! docker info 2>/dev/null | grep -qi nvidia; then
    warn "Docker kennt die NVIDIA-Laufzeit nicht – Plugin „Nvidia-Driver“ installieren und Docker neu starten."
  fi
  TEMPLATE=mini-jarvis.xml
  NAME=mini-jarvis
else
  warn "Keine NVIDIA-GPU gefunden → Vorlage ohne GPU (Cloud-Modelle oder externes Ollama, siehe docs/UNRAID.md)."
  TEMPLATE=mini-jarvis-ohne-gpu.xml
  NAME=mini-jarvis-cpu
fi

# ---------------------------------------------------------------- Adressen für das HTTPS-Zertifikat
if [ -z "${HOSTS:-}" ]; then
  IP=""
  if command -v ip >/dev/null 2>&1; then
    for ifc in br0 bond0 eth0; do
      IP=$(ip -4 -o addr show "$ifc" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1 || true)
      [ -n "$IP" ] && break
    done
  fi
  [ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
  HOST=$(hostname 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo tower)
  HOSTS="${IP:+$IP,}$HOST.local"
fi
ok "Zertifikat für: $HOSTS"

# ---------------------------------------------------------------- Ordner und Beispiel-Skripte
say "Ordner anlegen unter $APPDATA und $MODELS"
mkdir -p "$APPDATA/config" "$APPDATA/data" "$APPDATA/scripts" "$MODELS"
for f in say_hello.sh backup_appdata.sh; do
  if [ ! -e "$APPDATA/scripts/$f" ]; then
    curl -fsSL "$RAW/scripts/$f" -o "$APPDATA/scripts/$f" && chmod 755 "$APPDATA/scripts/$f"
    ok "Beispiel-Skript $f"
  fi
done

# ---------------------------------------------------------------- Vorlage
say "Vorlage $TEMPLATE laden"
tmp=$(mktemp)
curl -fsSL "$RAW/unraid/$TEMPLATE" -o "$tmp" || die "Vorlage nicht ladbar: $RAW/unraid/$TEMPLATE"
sed -i \
  -e "s#/mnt/cache/appdata/mini-jarvis/models#$MODELS#g" \
  -e "s#/mnt/user/appdata/mini-jarvis#$APPDATA#g" \
  -e "s#\(Target=\"JARVIS_HOSTS\"[^>]*>\)[^<]*<#\1$HOSTS<#" \
  "$tmp"
mkdir -p "$TEMPLATES"
install -m 644 "$tmp" "$TEMPLATES/my-$NAME.xml"
rm -f "$tmp"
ok "Vorlage gespeichert: $TEMPLATES/my-$NAME.xml"

# ---------------------------------------------------------------- Ports prüfen
for port in 8080 8443; do
  if command -v ss >/dev/null && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port\$"; then
    warn "Port $port ist schon belegt – in der Vorlage einen anderen Host-Port wählen."
  fi
done

cat <<EOF

$(printf '\033[1m')Fertig. Nächste Schritte:$(printf '\033[0m')
  1. Unraid → Docker → „Container hinzufügen“ → Vorlage „$NAME“ (Benutzervorlagen) → Anwenden.
     Der erste Start lädt Modelle (mehrere GB) – Fortschritt im Container-Log.
  2. Web-UI: https://${HOSTS%%,*}:8443/  (Zertifikatswarnung einmal bestätigen)
  3. Admin-Token: steht beim ersten Start im Container-Log (Docker → $NAME → Log),
     später: docker exec $NAME grep admin_token /config/secrets.yaml
  4. Verwaltung → Übersicht → „CA-Zertifikat laden“ und auf allen Geräten installieren.
  5. Verwaltung → Einstellungen: Ort, Sprachmodell, Schlüssel, Home Assistant – ohne Dateien zu bearbeiten.

Hinweis: Mini-Jarvis ist Work in Progress – vor Updates $APPDATA/config sichern.

Anleitung: https://github.com/$REPO/blob/$BRANCH/docs/UNRAID.md
EOF
