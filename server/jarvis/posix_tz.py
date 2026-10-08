"""IANA-Zeitzone → POSIX-TZ-String für ESP32 (`setenv("TZ", …)`), z. B. Europe/Berlin → CET-1CEST,M3.5.0,M10.5.0/3.

TZif-Dateien ab Version 2 enden mit genau diesem String (RFC 8536, Fußzeile).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

FALLBACK = "CET-1CEST,M3.5.0,M10.5.0/3"
_NAME_RE = re.compile(r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$")


def _tzif_bytes(name: str) -> bytes | None:
    for root in ("/usr/share/zoneinfo", "/usr/lib/zoneinfo"):
        path = Path(root) / name
        if path.is_file():
            return path.read_bytes()
    try:
        from importlib.resources import files

        return files("tzdata.zoneinfo").joinpath(*name.split("/")).read_bytes()
    except (ImportError, FileNotFoundError, OSError, ValueError):
        return None


@lru_cache(maxsize=32)
def posix_tz(name: str) -> str:
    if not name or not _NAME_RE.match(name) or ".." in name:
        return FALLBACK
    data = _tzif_bytes(name)
    if not data or not data.startswith(b"TZif"):
        return FALLBACK
    lines = data.rstrip(b"\n").rsplit(b"\n", 1)
    footer = lines[-1].decode("ascii", "ignore").strip() if len(lines) == 2 else ""
    return footer or FALLBACK
