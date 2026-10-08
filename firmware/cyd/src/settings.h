#pragma once
#include <Arduino.h>

// Dauerhafte Einstellungen (NVS, Namensraum „jarvis“).
struct Settings {
  String ssid, pass;          // WLAN (nur 2,4 GHz)
  String host;                // Jarvis-Server (IP oder Name)
  uint16_t port = 8080;       // HTTP-Port des Servers
  String token;               // Geräte-Token aus der Verwaltung
  String name;                // Anzeigename („Küche“)
  String tz;                  // POSIX-Zeitzone, z. B. CET-1CEST,M3.5.0,M10.5.0/3
  uint8_t volume = 70;        // 0–100
  uint8_t brightness = 180;   // 10–255
  uint8_t rotation = 0;       // 0/2 = Hochformat, 1/3 = Querformat
#ifdef PANEL_ST7789
  bool invert = true;         // Farben umkehren (manche ST7789-Panels brauchen das)
#else
  bool invert = false;
#endif
  bool hasTouchCal = false;
  uint16_t touchCal[8] = {0};
};

namespace settings {
extern Settings s;
void load();
void save();
bool configured();            // WLAN + Server + Token vorhanden
void clear();                 // alles löschen (Werkszustand)
}
