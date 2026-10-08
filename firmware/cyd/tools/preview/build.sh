#!/bin/sh
# Baut die PC-Vorschau der CYD-Bildschirme. Aufruf: ./build.sh /pfad/zu/LovyanGFX
set -e
LGFX=${1:?Pfad zu LovyanGFX angeben}
cd "$(dirname "$0")"
g++ -std=c++17 -O1 -DLGFX_LINUX_FB -I"$LGFX/src" -I../../src \
  preview.cpp ../../src/screens.cpp \
  "$LGFX"/src/lgfx/v1/*.cpp "$LGFX"/src/lgfx/v1/misc/*.cpp \
  "$LGFX"/src/lgfx/v1/panel/Panel_Device.cpp "$LGFX"/src/lgfx/v1/platforms/framebuffer/*.cpp \
  "$LGFX"/src/lgfx/utility/*.c "$LGFX"/src/lgfx/Fonts/efont/*.c "$LGFX"/src/lgfx/Fonts/IPA/*.c \
  -lpthread -o preview
