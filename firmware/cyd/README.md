# CYD-Firmware

PlatformIO-Projekt für den **ESP32-2432S028** („Cheap Yellow Display“) als Sprach-Satellit für Jarvis.

| | |
|---|---|
| Anzeige | Uhr, Datum, WLAN-Stärke, animierter Reaktor, „J A R V I S“, Wellenform, Status |
| Seiten | **Start** · **Licht** (Home Assistant) · **Musik** (Mediaplayer) · **Einstellungen** |
| Format | Hoch- und Querformat (jeweils auch gedreht), Umlaute über eigene Schriften |
| Sprache | Mikrofon streamt zum Server (Wake-Word dort), Reaktor antippen oder halten = Push-to-Talk |
| Wecker | Weckton bis „Ausschalten“, „5 Minuten schlummern“ |
| Updates | per WLAN vom Jarvis-Server (OTA, MD5-geprüft), Erstinstallation per USB aus der Verwaltung |

## Erstinstallation – ohne Werkzeuge

1. Jarvis-Verwaltung über **HTTPS** öffnen (Chrome/Edge/Opera am Computer), Seite **Firmware**.
2. „CYD per USB einrichten“: Display per Datenkabel anschließen, Variante wählen, Name/Raum und WLAN eintragen.
3. Der Assistent flasht Bootloader, Partitionen und App, überträgt WLAN, Server, Token und Zeitzone über die
   serielle Konsole und wartet, bis das Display online ist.
4. Beim ersten Start fragt das Display nach der **Touch-Kalibrierung** (vier Ecken antippen).

Ohne Computer: Auf dem Display „Hotspot starten“, mit dem Handy das WLAN **Jarvis-Setup** öffnen und WLAN,
Server, Port und Geräte-Token (Verwaltung → Geräte → Typ „CYD“) eintragen.

Alle späteren Updates kommen per WLAN: Verwaltung → Geräte → „Update“ oder automatisch mit
`firmware.auto_update: true`.

## Selbst bauen

```bash
pio run -e cyd                      # ILI9341 (Standard-CYD, ein Micro-USB)
pio run -e cyd-st7789               # ST7789 (CYD2USB, USB-C + Micro-USB)
pio run -e cyd -t upload && pio device monitor
python tools/package.py --out dist  # Paket für JARVIS_FIRMWARE_DIR (Web-Flasher + OTA)
```

Die Version steht in `include/config.h` (`FW_VERSION`). Für ein OTA-Update aus einem eigenen Build genügt
`firmware.bin` – hochladen unter Verwaltung → Firmware.

## Bedienung

- **Reaktor antippen**: Jarvis hört zu, bis du fertig bist (oder nochmal tippen).
  **Halten**: Push-to-Talk, loslassen beendet die Frage. Während Jarvis spricht, unterbricht Antippen.
- **Licht**: Schalter und Szenen aus `homeassistant.entities` der Jarvis-Konfiguration.
- **Musik**: Mediaplayer aus Home Assistant – Zurück, Play/Pause, Weiter, Lautstärke; ‹ › wechselt den Player.
- **Einstellungen**: Lautstärke, Helligkeit, Ausrichtung, Farben umkehren (manche ST7789-Panels),
  Touch kalibrieren, WLAN neu einrichten, Neustart, Infos (IP, Signal, Server, Firmware).
- **BOOT-Taste beim Einschalten halten**: Touch neu kalibrieren.

## Serielles Einrichtungsprotokoll (115200 Baud)

| Senden | Antwort |
|---|---|
| `JARVIS?` | `JARVIS-READY fw=0.3.0 board=cyd` |
| `JARVIS-CONFIG {"ssid","pass","host","port","token","name","tz"}` | `JARVIS-OK` oder `JARVIS-ERR <grund>`, danach `JARVIS-WIFI OK <ip>` / `JARVIS-WIFI FAIL <grund>` |
| `JARVIS-INFO` | `JARVIS-INFO {json}` (ohne Passwörter) |
| `JARVIS-RESET` | `JARVIS-OK`, Werkszustand, Neustart |

## Aufbau

| Datei | Inhalt |
|---|---|
| `src/main.cpp` | Ablauf, Nachrichten vom/zum Server |
| `src/screens.*` | Zeichenfunktionen (ohne Arduino-Abhängigkeit, auch auf dem PC lauffähig) |
| `src/ui.*` | Seiten, Touch, Kalibrierung, Wecker- und Update-Anzeige |
| `src/net.*` | WLAN, Hotspot, NTP, WebSocket mit `Authorization`-Header |
| `src/audio.*` | Mikrofon (INMP441, I2S1) und Lautsprecher (DAC, GPIO 26) in eigenen Tasks |
| `src/ota.*` | Update vom Jarvis-Server |
| `src/provision.*` | Einrichtung über USB |
| `src/fonts.h` | Rajdhani mit Umlauten, erzeugt mit `tools/make_fonts.py` (SIL OFL, siehe `fonts/OFL.txt`) |
| `tools/preview/` | rendert alle Bildschirme auf dem PC (`./build.sh <LovyanGFX> && ./preview out/`) |

Pinbelegung und Verdrahtung: [docs/HARDWARE.md](../../docs/HARDWARE.md).

## Stand

Gebaut und geprüft mit pioarduino 55.03.312 (Arduino-ESP32 3.3.12): beide Varianten kompilieren ohne
Warnungen, die Bildschirme sind in der PC-Vorschau geprüft, das Einrichtungsprotokoll mit der Verwaltung
getestet. **Auf echter Hardware noch nicht getestet** – insbesondere Touch-Ausrichtung, Audiopegel und
die Farben der ST7789-Variante können Nacharbeit brauchen.
