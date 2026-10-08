#!/usr/bin/env python3
"""Packt die gebauten Firmware-Varianten für die Jarvis-Verwaltung (USB-Flasher + OTA).

    pio run -e cyd -e cyd-st7789
    python tools/package.py --out dist

Ergebnis je Variante: <out>/<variante>/{manifest.json, bootloader.bin, partitions.bin, boot_app0.bin, firmware.bin}
Der Server (jarvis/firmware.py) liest diese Struktur aus JARVIS_FIRMWARE_DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TITLES = {"cyd": "CYD (ILI9341)", "cyd-st7789": "CYD2USB (ST7789)"}
OFFSETS = [("bootloader.bin", 0x1000), ("partitions.bin", 0x8000), ("boot_app0.bin", 0xE000), ("firmware.bin", 0x10000)]


def fw_version() -> str:
    text = (HERE / "include" / "config.h").read_text(encoding="utf-8")
    m = re.search(r'#define\s+FW_VERSION\s+"([^"]+)"', text)
    if not m:
        sys.exit("FW_VERSION nicht in include/config.h gefunden")
    return m.group(1)


def boot_app0() -> Path:
    core = Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))
    for candidate in [core / "packages" / "framework-arduinoespressif32" / "tools" / "partitions" / "boot_app0.bin",
                      *core.glob("packages/framework-arduinoespressif32*/tools/partitions/boot_app0.bin")]:
        if candidate.exists():
            return candidate
    sys.exit("boot_app0.bin nicht gefunden – erst `pio run` ausführen")


def package(env: str, out: Path, version: str) -> dict:
    build = HERE / ".pio" / "build" / env
    app = build / "firmware.bin"
    if not app.exists():
        sys.exit(f"{app} fehlt – erst `pio run -e {env}` ausführen")
    data = app.read_bytes()
    if data[0] != 0xE9 or f"JARVIS_FW_VERSION={version}".encode() not in data:
        sys.exit(f"{app}: kein gültiges Jarvis-App-Image für Version {version}")
    target = out / env
    target.mkdir(parents=True, exist_ok=True)
    sources = {"bootloader.bin": build / "bootloader.bin", "partitions.bin": build / "partitions.bin",
               "boot_app0.bin": boot_app0(), "firmware.bin": app}
    for name, src in sources.items():
        if not src.exists():
            sys.exit(f"{src} fehlt")
        shutil.copyfile(src, target / name)
    manifest = {
        "board": "cyd", "variant": env, "title": TITLES.get(env, env), "version": version,
        "md5": hashlib.md5(data).hexdigest(), "size": len(data), "app": "firmware.bin",
        "parts": [{"path": name, "offset": offset} for name, offset in OFFSETS],
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "dist")
    ap.add_argument("--env", action="append", help="Varianten (Standard: cyd und cyd-st7789)")
    args = ap.parse_args()
    version = fw_version()
    for env in args.env or ["cyd", "cyd-st7789"]:
        m = package(env, args.out, version)
        print(f"{env}: {m['version']} · {m['size']} Bytes · md5 {m['md5']}")


if __name__ == "__main__":
    main()
