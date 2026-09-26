"""Eigener Docker-MCP-Server: nur Container aus der Whitelist, nur erlaubte Aktionen.

Spricht den gefilterten HAProxy-Socket-Proxy an (nie den rohen Docker-Socket).
Start:  python -m jarvis.mcp_servers.docker_mcp   (stdio, von Pipecats MCPClient)
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import yaml

PROXY = os.environ.get("JARVIS_DOCKER_PROXY", "http://127.0.0.1:2375")
WHITELIST_FILE = Path(os.environ.get("JARVIS_CONFIG_DIR", "/config")) / "whitelist.yaml"
ACTIONS = {"start", "stop", "restart"}


def load_whitelist(path: Path = WHITELIST_FILE) -> dict[str, set[str]]:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return {name: set(actions) for name, actions in (data.get("containers") or {}).items()}


def check_allowed(whitelist: dict[str, set[str]], name: str, action: str) -> str | None:
    """None = erlaubt, sonst Fehlermeldung."""
    if name not in whitelist:
        return f"Container {name} ist nicht freigegeben."
    if action not in whitelist[name]:
        return f"Aktion {action} ist für {name} nicht erlaubt."
    return None


UNREACHABLE = "Ich erreiche die Docker-Steuerung gerade nicht."


async def container_status_impl(name: str) -> str:
    try:
        return await _status(name)
    except httpx.TransportError:
        return UNREACHABLE


async def _status(name: str) -> str:
    wl = load_whitelist()
    names = [name] if name else sorted(wl)
    lines = []
    async with httpx.AsyncClient(base_url=PROXY, timeout=5) as c:
        for n in names:
            err = check_allowed(wl, n, "status")
            if err:
                lines.append(err)
                continue
            r = await c.get(f"/containers/{n}/json")
            if r.status_code == 404:
                lines.append(f"{n}: nicht gefunden")
            else:
                state = r.json().get("State", {})
                lines.append(f"{n}: {'läuft' if state.get('Running') else 'gestoppt'}")
    return "; ".join(lines)


async def container_action_impl(name: str, action: str) -> str:
    if action not in ACTIONS:
        return f"Unbekannte Aktion {action}."
    err = check_allowed(load_whitelist(), name, action)
    if err:
        return err
    try:
        async with httpx.AsyncClient(base_url=PROXY, timeout=30) as c:
            r = await c.post(f"/containers/{name}/{action}")
    except httpx.TransportError:
        return UNREACHABLE
    if r.status_code in (204, 304):
        return f"{name}: {action} ausgeführt."
    return f"{name}: {action} fehlgeschlagen (HTTP {r.status_code})."


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("jarvis-docker")

    @server.tool(description="Status freigegebener Container. Leerer Name = alle.")
    async def container_status(name: str = "") -> str:
        return await container_status_impl(name)

    @server.tool(description="Container starten, stoppen oder neu starten (nur Whitelist). "
                             "KRITISCH: nur nach Bestätigung durch Jarvis-Core aufrufen.")
    async def container_action(name: str, action: str) -> str:
        return await container_action_impl(name, action)

    return server


if __name__ == "__main__":
    build_server().run("stdio")
