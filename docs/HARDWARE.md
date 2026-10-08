# Hardware – ESP32-2432S028 (CYD)

## Board

ESP32-WROOM-32 (4 MB Flash, **kein PSRAM**), 2,8" 320×240 (ILI9341; bei manchen
2-USB-Varianten ST7789), resistiver Touch XPT2046, MicroSD, RGB-LED (4/16/17,
aktiv low), LDR (34), Lautsprecher-Ausgang mit Verstärker an GPIO 26 (DAC).

## Freie Anschlüsse

| Stecker | Pins |
|---|---|
| P3 | GND, 35, 22, 21* |
| CN1 | GND, 22, 27, 3,3 V |
| P1 | VIN, TX (1), RX (3), GND |

\* GPIO 21 ist je nach Revision die Hintergrundbeleuchtung – nicht verwenden.

## Mikrofon INMP441

| INMP441 | CYD |
|---|---|
| SCK | 22 (CN1) |
| WS | 27 (CN1) |
| SD | 35 (P3) |
| L/R | GND |
| VDD | 3,3 V (CN1) |
| GND | GND |

Vor dem Anschließen mit einem Pinout der eigenen Board-Revision abgleichen.

## Lautsprecher

Kleiner Lautsprecher (8 Ω, 1–2 W) an den Stecker **SPEAK** (JST 1,25 mm, 2-polig). Der Verstärker
(SC8002B) hängt am DAC-Ausgang GPIO 26; die Firmware gibt 16 kHz mit 8 Bit aus. Lautstärke in den
Einstellungen des Displays oder per Sprache („Lauter“, „Lautstärke 40“).

## Display-/Touch-Pins (in `firmware/cyd/include/board_cyd.h`)

TFT: SCLK 14, MOSI 13, MISO 12, DC 2, CS 15, BL 21
Touch: CLK 25, MOSI 32, MISO 39, CS 33, IRQ 36

## Varianten

| Board | Erkennung | Firmware |
|---|---|---|
| ESP32-2432S028R | ein Micro-USB | `cyd` (ILI9341) |
| „CYD2USB“ | USB-C **und** Micro-USB | `cyd-st7789`; falsche Farben → Einstellungen → „Farben umkehren“ |

## Erste Schritte

1. Firmware über die Verwaltung flashen (Seite **Firmware**, Chrome/Edge, HTTPS) – siehe
   [firmware/cyd/README.md](../firmware/cyd/README.md).
2. Beim ersten Start die **Touch-Kalibrierung** durchführen (vier Pfeile antippen).
   Später erneut: Einstellungen → „Touch kalibrieren“ oder **BOOT-Taste** beim Einschalten halten.
3. Tippt der Touch daneben oder ist das Bild gedreht: Einstellungen → „Ausrichtung“.
