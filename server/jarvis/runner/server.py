"""Skript-Runner: eigener Prozess/Benutzer, Unix-Socket, JSON-Zeilen.

Start (im Container als Benutzer 'runner'):
    python -m jarvis.runner.server --socket /run/jarvis/runner.sock
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import yaml

from jarvis.runner.registry import ValidationError, load_registry, validate_params

SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


async def run_script(registry, sid: str, args: dict) -> dict:
    spec = registry.get(sid)
    if spec is None:
        return {"ok": False, "error": f"Unbekanntes Skript: {sid}"}
    try:
        argv = validate_params(spec, args)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    proc = await asyncio.create_subprocess_exec(
        spec.path, *argv, env=SAFE_ENV, cwd="/tmp",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=spec.timeout)
    except TimeoutError:
        proc.kill()
        return {"ok": False, "error": f"Zeitüberschreitung nach {spec.timeout} s"}
    text = out.decode(errors="replace")[-2000:]
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output": text}


class Registry:
    """scripts.yaml bei jeder Änderung neu einlesen – die Verwaltung schreibt sie."""

    def __init__(self, scripts_file: str, scripts_root: str):
        self.file, self.root = Path(scripts_file), scripts_root
        self.mtime: int | None = None
        self.scripts: dict = {}

    def get(self) -> dict:
        try:
            mtime = self.file.stat().st_mtime_ns
        except OSError:
            return self.scripts
        if mtime != self.mtime:
            self.mtime = mtime
            try:
                errors: list[str] = []
                self.scripts = load_registry(yaml.safe_load(self.file.read_text()) or {}, self.root, errors)
                for err in errors:
                    print(f"Runner: übersprungen – {err}", flush=True)
                print(f"Runner: {len(self.scripts)} Skript(e) freigegeben", flush=True)
            except Exception as e:  # noqa: BLE001 – kaputte Datei: alte Liste behalten
                print(f"Runner: scripts.yaml fehlerhaft, alte Liste bleibt aktiv: {e}", flush=True)
        return self.scripts


async def serve(socket_path: str, scripts_file: str, scripts_root: str) -> None:
    registry = Registry(scripts_file, scripts_root)
    registry.get()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            req = json.loads(line or b"{}")
            scripts = registry.get()
            if req.get("op") == "list":
                resp = {"ok": True, "scripts": {k: v.description for k, v in scripts.items()}}
            else:
                resp = await run_script(scripts, req.get("id", ""), req.get("args") or {})
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "error": f"Runner-Fehler: {e}"}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()

    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    server = await asyncio.start_unix_server(handle, path=socket_path)
    os.chmod(socket_path, 0o660)            # Gruppe 'jarvis' darf verbinden
    async with server:
        await server.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/run/jarvis/runner.sock")
    ap.add_argument("--scripts-file", default="/config/scripts.yaml")
    ap.add_argument("--scripts-root", default="/scripts")
    a = ap.parse_args()
    asyncio.run(serve(a.socket, a.scripts_file, a.scripts_root))


if __name__ == "__main__":
    main()
