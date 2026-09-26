# CYD-Firmware

PlatformIO-Projekt für den ESP32-2432S028. Status: **Gerüst** – auf Hardware zu testen.

```bash
pio run -e cyd -t upload && pio device monitor
```

1. Beim ersten Start öffnet das Board den Hotspot **Jarvis-Setup**. Dort WLAN,
   Server (`192.168.1.144`), Port (`8080`) und das Geräte-Token eintragen
   (Gerät vom Typ `cyd` in der Jarvis-Web-UI/API anlegen).
2. Neu einrichten: beim Einschalten 3 Sekunden auf das Display tippen.
3. Bedienung: „Hey Jarvis“ oder Display gedrückt halten (Push-to-Talk).
   Bei Alarm: Display antippen.

Bekannte Punkte für Phase 4/5:
- Touch-Kalibrierung (`ui.cpp`, `x_min`…) für das eigene Panel anpassen.
- Umlaute: eigene Schrift einbinden.
- DAC wird vor dem Mikrofon initialisiert (DAC nutzt intern I2S0).
- Panel ST7789 statt ILI9341? → `pio run -e cyd-st7789`.
- OTA-Updates ergänzen (ArduinoOTA).
