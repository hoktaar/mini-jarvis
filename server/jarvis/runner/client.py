"""Client für den Runner und das zugehörige Tool 'run_script'."""

from __future__ import annotations

import asyncio
import json

from jarvis.db import Database
from jarvis.tools.registry import Tool, ToolContext, ToolResult


async def call_runner(socket_path: str, payload: dict, timeout: float = 700) -> dict:
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(socket_path), 5)
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout)
    writer.close()
    return json.loads(line)


def make_script_tool(socket_path: str, db: Database, descriptions: dict[str, str]) -> Tool:
    listing = "; ".join(f"{k}: {v}" for k, v in descriptions.items()) or "keine"

    async def handler(args: dict, ctx: ToolContext) -> ToolResult:
        sid = args.get("script_id", "")
        resp = await call_runner(socket_path, {"id": sid, "args": args.get("args") or {}})
        db.audit(f"device:{ctx.device_id}", "run_script", json.dumps(args, ensure_ascii=False),
                 "ok" if resp.get("ok") else resp.get("error", "fehler"))
        if resp.get("ok"):
            return ToolResult(True, f"Skript {sid} ausgeführt.", resp)
        return ToolResult(False, f"Skript {sid} fehlgeschlagen: {resp.get('error', 'unbekannt')}.", resp)

    return Tool(
        "run_script", f"Freigegebenes Skript ausführen. Verfügbar: {listing}",
        {"script_id": {"type": "string", "enum": list(descriptions)},
         "args": {"type": "object", "description": "Parameter laut Skriptbeschreibung"}},
        ["script_id"], handler, risk="critical",
    )
