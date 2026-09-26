# Sicherheitskonzept

## Bedrohungen

1. **Verhören / Missverstehen** – Whisper oder Router liegen falsch.
2. **Prompt-Injection** – Webseiten oder RSS-Inhalte enthalten Anweisungen an die KI.
3. **Fremde Geräte im Netz** – schicken Befehle an Jarvis.
4. **Kompromittierter Prozess** – ein Fehler im Core soll nicht den Host übernehmen.
5. **Datenabfluss** – Infos über den Server landen bei Cloud-Anbietern.

## Maßnahmen

| Ebene | Maßnahme | Datei |
|---|---|---|
| Aktionen | Risiko-Stufe pro Tool (`read`, `write`, `critical`) | `jarvis/tools/registry.py` |
| Bestätigung | `critical` immer bestätigen; nach Web-/News-Inhalten jede Aktion | `jarvis/security/policy.py` |
| Ja/Nein | Klassifikator mit Schwelle, *unklar* → erneut fragen | `jarvis/router/confirm.py` |
| Skripte | nur Registry, Typprüfung, kein Shell, Timeout, Audit | `jarvis/runner/` |
| Docker | HAProxy-Filter + Whitelist im eigenen MCP-Server | `docker/haproxy.cfg`, `jarvis/mcp_servers/docker_mcp.py` |
| Rechte | getrennte Linux-Benutzer im Container | `docker/entrypoint.sh` |
| Geräte | Token pro Gerät, nur SHA-256-Hash gespeichert, widerrufbar | `jarvis/devices.py` |
| Admin | Admin-Token für `/api/admin/*` | `jarvis/main.py` |
| Cloud | Tool-Freigaben pro Anbieter, Privatmodus, Budget | `jarvis/security/policy.py`, `config.yaml` |
| Auto | `car_allowed` pro Skript | `scripts.yaml` |
| Netz | kein Port ins Internet, WireGuard | Doku |

## Regel für eigene Skripte

- Skripte liegen in `/scripts` (read-only gemountet), sind ausführbar und
  lesen Parameter **nur** als Argumente.
- Keine Parameter ungeprüft an eine Shell weitergeben (`"$1"` quoten!).
- Host-Aktionen per SSH nur mit Schlüssel, der in `authorized_keys` per
  `command="…"` auf genau einen Befehl festgelegt ist.
