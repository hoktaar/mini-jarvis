#!/usr/bin/env python3
"""Erzeugt geglättete VLW-Schriften (LovyanGFX `loadFont`) mit deutschen Umlauten für den CYD.

    pip install freetype-py
    python tools/make_fonts.py --fonts-dir /pfad/zu/rajdhani

Schreibt src/fonts.h. Die Schrift Rajdhani steht unter der SIL Open Font License (fonts/OFL.txt).
Format (Processing VLW, big-endian): 6×int32 Kopf (Anzahl, Version, Größe, 0, Ascent, Descent),
je Glyphe 7×int32 (Unicode, Höhe, Breite, Vorschub, dY, dX, 0), danach die 8-Bit-Alphamasken.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import freetype

LATIN = [*range(0x20, 0x7F), *range(0xA0, 0x100)]
EXTRA = [0x2013, 0x2014, 0x2018, 0x2019, 0x201A, 0x201C, 0x201D, 0x201E, 0x2022, 0x2026, 0x20AC]
# (Name im Code, Datei, Pixelgröße, Zeichen)
FONTS = [
    ("font_clock", "Rajdhani-SemiBold.ttf", 46, "0123456789:- "),
    ("font_title", "Rajdhani-Bold.ttf", 26, "ABCDEFGHIJKLMNOPQRSTUVWXYZ "),
    ("font_large", "Rajdhani-SemiBold.ttf", 22, None),
    ("font_text", "Rajdhani-Medium.ttf", 18, None),
    ("font_small", "Rajdhani-SemiBold.ttf", 14, None),
]


def build(path: Path, size: int, chars: list[int]) -> bytes:
    face = freetype.Face(str(path))
    face.set_pixel_sizes(0, size)
    glyphs = []
    for code in sorted(set(chars)):
        if face.get_char_index(code) == 0 and code != 0x20:
            continue
        face.load_char(chr(code), freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
        g = face.glyph
        bmp = g.bitmap
        width, height = bmp.width, bmp.rows
        data = bytes(bmp.buffer) if width and height else b""
        if bmp.pitch != width and data:      # Zeilen ohne Füllbytes ablegen
            data = b"".join(bytes(bmp.buffer[r * bmp.pitch:r * bmp.pitch + width]) for r in range(height))
        glyphs.append((code, height, width, g.advance.x >> 6, g.bitmap_top, g.bitmap_left, data))
    ascent = face.size.ascender >> 6
    descent = -(face.size.descender >> 6)
    out = bytearray(struct.pack(">6i", len(glyphs), 11, size, 0, ascent, descent))
    for code, h, w, adv, top, left, _ in glyphs:
        out += struct.pack(">7i", code, h, w, adv, top, left, 0)
    for *_, data in glyphs:
        out += data
    return bytes(out)


def to_c(name: str, data: bytes) -> str:
    rows = [", ".join(f"0x{b:02x}" for b in data[i:i + 24]) for i in range(0, len(data), 24)]
    body = ",\n  ".join(rows)
    return f"// {len(data)} Bytes\nstatic const uint8_t {name}[] PROGMEM = {{\n  {body}\n}};\n"


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts-dir", type=Path, default=here / "fonts")
    ap.add_argument("--out", type=Path, default=here / "src" / "fonts.h")
    args = ap.parse_args()
    parts = ["#pragma once\n// Automatisch erzeugt mit tools/make_fonts.py – nicht von Hand ändern.\n"
             "// Schrift: Rajdhani (Indian Type Foundry), SIL Open Font License 1.1.\n"
             "#ifdef ARDUINO\n#include <Arduino.h>\n#else\n#include <stdint.h>\n#define PROGMEM\n#endif\n"]
    for name, file, size, chars in FONTS:
        codes = [ord(c) for c in chars] if chars else LATIN + EXTRA
        data = build(args.fonts_dir / file, size, codes)
        parts.append(to_c(name, data))
        print(f"{name}: {size}px, {len(data)} Bytes")
    args.out.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
