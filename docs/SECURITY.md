# Sicherheitskonzept

## Bedrohungen

1. **Verhören / Missverstehen** – Whisper oder Router liegen falsch.
2. **Prompt-Injection** – Webseiten, RSS oder Smarthome-Inhalte enthalten Anweisungen an die KI.
3. **Fremde Geräte im Netz** – schicken Befehle an Jarvis oder raten Tokens.
4. **Kompromittierter Prozess** – ein Fehler im Core soll nicht den Host übernehmen.
5. **Datenabfluss** – Inhalte landen ungewollt bei Cloud-Anbietern.

## Maßnahmen

| Ebene | Maßnahme | Datei |
|---|---|---|
| Aktionen | Risiko-Stufe pro Tool (`read`, `write`, `critical`), auch für MCP-Tools (`tool_risks`) | `jarvis/tools/registry.py`, `jarvis/mcp.py` |
| Bestätigung | `critical` immer bestätigen; nach Web-/News-Inhalten jede schreibende Aktion – der „Taint“ bleibt für die nächsten Gesprächsrunden bestehen | `jarvis/security/policy.py` |
| Ja/Nein | nur eindeutige Antworten zählen („ja“, „mach“ – nicht „ja, aber …“), Zeitlimit, „wie bitte?“ wiederholt die Frage, zweimal unklar = Abbruch | `jarvis/router/confirm.py` |
| MCP | Allowlist pro Server (`tools: […]`), alle Aufrufe laufen durch die Policy | `config.yaml`, `jarvis/mcp.py` |
| Skripte | nur Registry, Typ-/Musterprüfung, keine Shell, Timeout, Audit; Runner als eigener Benutzer, Socket nur für Gruppe `jarvis` | `jarvis/runner/`, `docker/entrypoint.sh` |
| Docker | HAProxy-Regeln werden aus der Whitelist erzeugt (nur `inspect`, `start`, `stop`, `restart` der freigegebenen Container); der Host-Socket wird nie umgebogen | `jarvis/mcp_servers/haproxy_gen.py` |
| Rechte | getrennte Linux-Benutzer (Core, Runner, Proxy, Ollama); `/config` für den Core nur lesbar, `secrets.yaml` 640 | `docker/entrypoint.sh` |
| Geräte | Token pro Gerät, nur SHA-256 gespeichert, erneuer- und sperrbar; Übergabe per `Authorization`-Header oder Einmal-Ticket, Tokens im Log geschwärzt | `jarvis/devices.py`, `jarvis/main.py` |
| Verwaltung | Admin-Token mit konstantzeitigem Vergleich, Fehlversuche werden pro IP gebremst | `jarvis/main.py` |
| Transport | HTTPS mit eigener CA (Port 8443); Zertifikat wird bei geänderten Namen/IPs erneuert | `jarvis/tls.py` |
| Cloud | Privatmodus pro Gerät sperrt Cloud-LLM und Cloud-Werkzeuge (Brave/Tavily); laufen Spracherkennung oder -ausgabe über die Cloud, weist Jarvis beim Einschalten darauf hin; erlaubte Tool-Risiken pro Cloud-Anbieter; Tages-/Monatsbudget | `jarvis/security/policy.py`, `jarvis/budget.py` |
| Smarthome | Dashboard und CYD schalten nur Entitäten aus `homeassistant.entities`; Schlösser u. Ä. nie per Kachel | `jarvis/homeassistant.py` |
| Firmware | OTA nur mit Geräte-Token, MD5-Prüfung auf dem Gerät; Upload prüft ESP32-Image-Kennung; WLAN-Daten bei der USB-Einrichtung gehen nie an den Server | `jarvis/firmware.py`, `firmware/cyd/src/ota.cpp` |
| Datenschutz | Router- und Aktionsprotokoll nach `retention_days` löschen; `log_text: false` speichert keine Sätze | `jarvis/db.py` |
| Auto | `car_allowed` pro Skript | `scripts.yaml` |
| Netz | kein Port ins Internet, Fernzugriff über WireGuard | Doku |

## Regel für eigene Skripte

- Skripte liegen in `/scripts` (read-only gemountet), sind ausführbar und lesen Parameter **nur** als Argumente.
- Keine Parameter ungeprüft an eine Shell weitergeben (`"$1"` quoten!).
- Host-Aktionen per SSH nur mit Schlüssel, der in `authorized_keys` per `command="…"` auf genau einen Befehl
  festgelegt ist.
