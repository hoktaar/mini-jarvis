#pragma once
#include <Arduino.h>

// Einrichtung über USB (serielle Konsole, 115200 Baud) – genutzt vom Web-Flasher der Jarvis-Verwaltung.
//   JARVIS?               → JARVIS-READY fw=<version> board=<variante>
//   JARVIS-CONFIG {json}  → JARVIS-OK | JARVIS-ERR <grund>   (ssid, pass, host, port, token, name, tz)
//   JARVIS-INFO           → JARVIS-INFO {json}   (ohne Geheimnisse)
//   JARVIS-RESET          → JARVIS-OK, danach Werkszustand und Neustart
// Nach JARVIS-CONFIG meldet die Firmware das WLAN-Ergebnis: JARVIS-WIFI OK <ip> | JARVIS-WIFI FAIL <grund>
namespace provision {
using ConfigHandler = void (*)();
void begin(ConfigHandler onConfig);
void loop();
void reportWifi(bool ok, const String& detail);   // nur nach einer Einrichtung über USB
bool busy();                  // gerade eine Einrichtung über USB im Gange?
}
