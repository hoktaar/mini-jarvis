"""Firmware für ESP32-Satelliten: Web-Flasher (Erstinstallation per USB) und OTA-Updates.

Ablage je Variante (z. B. `cyd`, `cyd-st7789`):
    <dir>/<variante>/manifest.json   Version, Teile mit Flash-Offsets, MD5 der App
    <dir>/<variante>/*.bin           bootloader.bin, partitions.bin, boot_app0.bin, firmware.bin

Quellen: im Image gebaute Firmware (JARVIS_FIRMWARE_DIR) und hochgeladene Builds (/data/firmware).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from loguru import logger

BUILTIN_DIR = Path(os.environ.get("JARVIS_FIRMWARE_DIR", Path(__file__).resolve().parents[2] / "firmware" / "dist"))
VARIANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
VERSION_RE = re.compile(rb"JARVIS_FW_VERSION=([0-9][0-9A-Za-z.+-]{0,31})")
ESP_IMAGE_MAGIC = 0xE9


def parse_version(v: str) -> tuple:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts[:3]) + (0,) * (3 - len(parts[:3]))


def version_from_binary(data: bytes) -> str | None:
    m = VERSION_RE.search(data)
    return m.group(1).decode() if m else None


class FirmwareManager:
    def __init__(self, data_dir: Path, auto_update: bool = False, builtin_dir: Path = BUILTIN_DIR):
        self.upload_dir = data_dir / "firmware"
        self.builtin_dir = builtin_dir
        self.auto_update = auto_update
        self.status: dict[int, dict] = {}         # device_id → letzter OTA-Status

    # ---- Bestand ----
    def _manifests(self) -> list[tuple[dict, Path, str]]:
        out = []
        for source, root in (("builtin", self.builtin_dir), ("upload", self.upload_dir)):
            if not root.exists():
                continue
            for mf in sorted(root.glob("*/manifest.json")):
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                out.append((data, mf.parent, source))
        return out

    def variants(self) -> list[dict]:
        best: dict[str, dict] = {}
        for data, path, source in self._manifests():
            variant = data.get("variant") or path.name
            entry = {"variant": variant, "board": data.get("board", "cyd"), "version": data.get("version", "0"),
                     "source": source, "built": data.get("built", ""), "size": data.get("size", 0),
                     "flashable": bool(data.get("parts")), "title": data.get("title", variant)}
            current = best.get(variant)
            if current is None or parse_version(entry["version"]) >= parse_version(current["version"]):
                best[variant] = entry
        return sorted(best.values(), key=lambda e: e["variant"])

    def find(self, variant: str) -> tuple[dict, Path] | None:
        hits = [(d, p) for d, p, _ in self._manifests() if (d.get("variant") or p.name) == variant]
        if not hits:
            return None
        return max(hits, key=lambda h: parse_version(h[0].get("version", "0")))

    def file(self, variant: str, name: str) -> Path | None:
        found = self.find(variant)
        if found is None or not re.fullmatch(r"[A-Za-z0-9_.-]+\.bin", name):
            return None
        path = found[1] / name
        return path if path.exists() else None

    def manifest(self, variant: str) -> dict | None:
        found = self.find(variant)
        return found[0] if found else None

    # ---- Upload eigener Builds (nur App-Image für OTA, Teile vom Basis-Build) ----
    def upload(self, variant: str, data: bytes, version: str | None = None) -> dict:
        if not VARIANT_RE.match(variant):
            raise ValueError("Ungültiger Variantenname")
        if len(data) < 1024 or data[0] != ESP_IMAGE_MAGIC:
            raise ValueError("Das ist kein ESP32-App-Image (firmware.bin).")
        version = version or version_from_binary(data)
        if not version:
            raise ValueError("Version nicht gefunden – bitte angeben.")
        target = self.upload_dir / variant
        target.mkdir(parents=True, exist_ok=True)
        (target / "firmware.bin").write_bytes(data)
        parts = []
        base = self.find(variant)
        if base is not None:
            for part in base[0].get("parts", []):
                if part["path"] != "firmware.bin" and (base[1] / part["path"]).exists():
                    (target / part["path"]).write_bytes((base[1] / part["path"]).read_bytes())
                    parts.append(part)
            parts.append({"path": "firmware.bin", "offset": 0x10000})
        manifest = {"board": variant.split("-")[0], "variant": variant, "version": version,
                    "md5": hashlib.md5(data).hexdigest(), "size": len(data), "app": "firmware.bin",
                    "parts": parts, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "title": f"{variant} (Upload)"}
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info(f"Firmware {variant} {version} hochgeladen ({len(data)} Bytes)")
        return manifest

    # ---- OTA ----
    def update_for(self, variant: str, current: str) -> dict | None:
        m = self.manifest(variant)
        if m is None or not m.get("md5"):
            return None
        if parse_version(m.get("version", "0")) <= parse_version(current or "0"):
            return None
        return m

    async def maybe_offer(self, session, board: str, fw: str, force: bool = False) -> bool:
        device = session.device
        variant = device.settings.get("fw_variant") or board or "cyd"
        if variant != device.settings.get("fw_variant"):
            session.device = session.services.devices.update(device.id, settings={"fw_variant": variant})
        wanted = force or self.auto_update or device.settings.get("ota_requested")
        m = self.update_for(variant, fw)
        if not (wanted and m):
            return False
        await self.offer(session, variant, m)
        return True

    async def offer(self, session, variant: str, m: dict) -> None:
        self.status[session.device.id] = {"state": "offered", "version": m["version"], "ts": time.time()}
        session.device = session.services.devices.update(session.device.id, settings={"ota_requested": False})
        await session.emit({"type": "ota", "version": m["version"], "md5": m["md5"], "size": m["size"],
                            "path": f"/api/firmware/{variant}/firmware.bin"})
        logger.info(f"OTA-Update {m['version']} an {session.device.name} angeboten")

    def status_update(self, device, msg: dict) -> None:
        state = str(msg.get("state") or "")[:20]
        self.status[device.id] = {"state": state, "progress": msg.get("progress"),
                                  "error": str(msg.get("error") or "")[:120], "ts": time.time(),
                                  "version": self.status.get(device.id, {}).get("version")}
        logger.info(f"OTA {device.name}: {state} {msg.get('progress') or ''} {msg.get('error') or ''}")
