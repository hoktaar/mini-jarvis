"""Erzeugt die HAProxy-Konfiguration für den Docker-Socket-Proxy aus whitelist.yaml.

Der Proxy erzwingt die Freigaben damit selbst – auch ein kompromittierter Prozess im
Container kommt nur an die freigegebenen Container und Aktionen (nie exec/create).

    python -m jarvis.mcp_servers.haproxy_gen /config/whitelist.yaml /etc/haproxy/haproxy.cfg
    python -m jarvis.mcp_servers.haproxy_gen --watch …   # als root unter supervisord:
        Änderungen aus der Verwaltung sofort übernehmen und den Proxy neu starten
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from jarvis.mcp_servers.docker_mcp import ACTIONS, load_whitelist

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")

HEADER = """# Automatisch erzeugt aus whitelist.yaml – nicht von Hand ändern.
global
    log stdout format raw local0
    maxconn 64

defaults
    mode http
    timeout connect 5s
    timeout client 60s
    timeout server 60s
    log global

frontend docker_api
    bind 127.0.0.1:2375
"""

FOOTER = """    http-request deny
    default_backend docker_sock

backend docker_sock
    server docker /var/run/docker.sock
"""


def _alt(names: list[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(names))


def render(whitelist: dict[str, set[str]]) -> str:
    valid = {n: a for n, a in whitelist.items() if NAME_RE.match(n)}
    lines = [HEADER]
    status = [n for n, a in valid.items() if "status" in a]
    if status:
        lines.append(f"    acl inspect path_reg ^(/v[0-9.]+)?/containers/({_alt(status)})/json$\n")
        lines.append("    http-request allow if { method GET } inspect\n")
    for action in sorted(ACTIONS):
        names = [n for n, a in valid.items() if action in a]
        if names:
            lines.append(f"    acl do_{action} path_reg ^(/v[0-9.]+)?/containers/({_alt(names)})/{action}$\n")
            lines.append(f"    http-request allow if {{ method POST }} do_{action}\n")
    lines.append(FOOTER)
    return "".join(lines)


def write(src: Path, dst: Path) -> bool:
    """Regeln schreiben; True, wenn sich etwas geändert hat."""
    try:
        wl = load_whitelist(src)
    except Exception as e:  # noqa: BLE001 – kaputte Datei: alte Regeln behalten
        print(f"Warnung: {src} nicht lesbar, Proxy-Regeln bleiben unverändert: {e}", file=sys.stderr, flush=True)
        return False
    skipped = [n for n in wl if not NAME_RE.match(n)]
    for n in skipped:
        print(f"Warnung: ungültiger Containername in der Whitelist übersprungen: {n!r}", file=sys.stderr, flush=True)
    text = render(wl)
    if dst.exists() and dst.read_text(encoding="utf-8") == text:
        return False
    dst.write_text(text, encoding="utf-8")
    print(f"HAProxy-Regeln für {len(wl) - len(skipped)} Container geschrieben: {dst}", flush=True)
    return True


def watch(src: Path, dst: Path, interval: float = 2.0) -> None:
    last = src.stat().st_mtime_ns if src.exists() else None
    while True:
        time.sleep(interval)
        mtime = src.stat().st_mtime_ns if src.exists() else None
        if mtime == last:
            continue
        last = mtime
        if write(src, dst):
            subprocess.run(["supervisorctl", "restart", "docker-proxy"], check=False)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--watch"]
    src = Path(args[0] if args else "/config/whitelist.yaml")
    dst = Path(args[1] if len(args) > 1 else "/etc/haproxy/haproxy.cfg")
    write(src, dst)
    if "--watch" in sys.argv:
        watch(src, dst)


if __name__ == "__main__":
    main()
