"""Erzeugt die HAProxy-Konfiguration für den Docker-Socket-Proxy aus whitelist.yaml.

Der Proxy erzwingt die Freigaben damit selbst – auch ein kompromittierter Prozess im
Container kommt nur an die freigegebenen Container und Aktionen.

    python -m jarvis.mcp_servers.haproxy_gen /config/whitelist.yaml /etc/haproxy/haproxy.cfg
"""

from __future__ import annotations

import re
import sys
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


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/config/whitelist.yaml")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "/etc/haproxy/haproxy.cfg")
    wl = load_whitelist(src)
    skipped = [n for n in wl if not NAME_RE.match(n)]
    for n in skipped:
        print(f"Warnung: ungültiger Containername in der Whitelist übersprungen: {n!r}", file=sys.stderr)
    dst.write_text(render(wl), encoding="utf-8")
    print(f"HAProxy-Regeln für {len(wl) - len(skipped)} Container geschrieben: {dst}")


if __name__ == "__main__":
    main()
