#pragma once
#include <Arduino.h>

// WLAN, Uhrzeit (NTP) und WebSocket zum Jarvis-Server.
namespace net {
enum class State : uint8_t {
  Unconfigured,   // noch keine Zugangsdaten → Einrichtung per USB oder Hotspot
  Portal,         // Hotspot „Jarvis-Setup“ aktiv
  WifiConnecting,
  WifiFailed,     // WLAN nicht erreichbar, neuer Versuch läuft im Hintergrund
  ServerConnecting,
  Online,         // WebSocket verbunden
};

using AudioHandler = void (*)(const uint8_t*, size_t);
using TextHandler = void (*)(const char*, size_t);

void begin(AudioHandler onAudio, TextHandler onText);
void loop();
State state();
bool online();
void reconfigure();            // neue Zugangsdaten übernehmen (nach USB-Einrichtung)
void startPortal();            // Hotspot „Jarvis-Setup“ öffnen
int rssi();                    // dBm, 0 = kein WLAN
String ip();
bool timeValid();
void setTime(uint32_t epoch);  // Uhr vom Server übernehmen, falls NTP noch fehlt
void setTimezone(const String& tz);
void sendAudio(const uint8_t* data, size_t len);
void sendJson(const char* json);
uint32_t serverFailures();     // fehlgeschlagene Verbindungsversuche seit dem letzten Erfolg
}
