#include "provision.h"

#include <ArduinoJson.h>
#include <WiFi.h>

#include "config.h"
#include "settings.h"

namespace provision {
static ConfigHandler configCb = nullptr;
static String line;
static bool awaitingWifi = false;
static uint32_t lastLine = 0;

void begin(ConfigHandler onConfig) {
  configCb = onConfig;
  line.reserve(640);
}

static void handleConfig(const String& json) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) { Serial.println("JARVIS-ERR json"); return; }
  const char* ssid = doc["ssid"] | "";
  const char* host = doc["host"] | "";
  const char* token = doc["token"] | "";
  if (!*ssid) { Serial.println("JARVIS-ERR ssid fehlt"); return; }
  if (!*host || !*token) { Serial.println("JARVIS-ERR host/token fehlt"); return; }
  if (strlen(ssid) > 32) { Serial.println("JARVIS-ERR ssid zu lang"); return; }
  Settings& s = settings::s;
  s.ssid = ssid;
  s.pass = doc["pass"] | "";
  s.host = host;
  s.port = doc["port"] | DEFAULT_PORT;
  s.token = token;
  if (doc["name"].is<const char*>()) s.name = doc["name"].as<const char*>();
  if (doc["tz"].is<const char*>()) s.tz = doc["tz"].as<const char*>();
  settings::save();
  Serial.println("JARVIS-OK");
  awaitingWifi = true;
  if (configCb) configCb();
}

static void handleLine(const String& l) {
  if (l == "JARVIS?") {
    Serial.printf("JARVIS-READY fw=%s board=%s\n", FW_VERSION, FW_BOARD);
  } else if (l.startsWith("JARVIS-CONFIG ")) {
    handleConfig(l.substring(14));
  } else if (l == "JARVIS-INFO") {
    JsonDocument doc;
    doc["fw"] = FW_VERSION;
    doc["board"] = FW_BOARD;
    doc["name"] = settings::s.name;
    doc["host"] = settings::s.host;
    doc["port"] = settings::s.port;
    doc["ssid"] = settings::s.ssid;
    doc["wifi"] = WiFi.status() == WL_CONNECTED;
    doc["ip"] = WiFi.localIP().toString();
    doc["rssi"] = WiFi.RSSI();
    Serial.print("JARVIS-INFO ");
    serializeJson(doc, Serial);
    Serial.println();
  } else if (l == "JARVIS-RESET") {
    settings::clear();
    Serial.println("JARVIS-OK");
    Serial.flush();
    delay(200);
    ESP.restart();
  }
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line.trim();
      if (line.startsWith("JARVIS")) lastLine = millis();
      if (line.length()) handleLine(line);
      line = "";
    } else if (line.length() < 600) {
      line += c;
    } else {
      line = "";                     // überlange Zeile verwerfen
    }
  }
}

bool busy() { return awaitingWifi || (lastLine && millis() - lastLine < 8000); }

void reportWifi(bool ok, const String& detail) {
  if (!awaitingWifi) return;
  awaitingWifi = false;
  Serial.printf("JARVIS-WIFI %s %s\n", ok ? "OK" : "FAIL", detail.c_str());
}
}  // namespace provision
