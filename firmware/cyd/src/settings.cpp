#include "settings.h"

#include <Preferences.h>

#include "config.h"

namespace settings {
Settings s;
static Preferences prefs;

void load() {
  prefs.begin("jarvis", true);
  s.ssid = prefs.getString("ssid", "");
  s.pass = prefs.getString("pass", "");
  s.host = prefs.getString("host", "");
  s.port = prefs.getUShort("port", DEFAULT_PORT);
  s.token = prefs.getString("token", "");
  s.name = prefs.getString("name", "Jarvis");
  s.tz = prefs.getString("tz", DEFAULT_TZ);
  s.volume = prefs.getUChar("volume", 70);
  s.brightness = prefs.getUChar("bright", 180);
  s.rotation = prefs.getUChar("rotation", 0) & 3;
  s.invert = prefs.getBool("invert", Settings().invert);
  s.hasTouchCal = prefs.getBytes("tcal", s.touchCal, sizeof(s.touchCal)) == sizeof(s.touchCal);
  prefs.end();
}

void save() {
  prefs.begin("jarvis", false);
  prefs.putString("ssid", s.ssid);
  prefs.putString("pass", s.pass);
  prefs.putString("host", s.host);
  prefs.putUShort("port", s.port);
  prefs.putString("token", s.token);
  prefs.putString("name", s.name);
  prefs.putString("tz", s.tz);
  prefs.putUChar("volume", s.volume);
  prefs.putUChar("bright", s.brightness);
  prefs.putUChar("rotation", s.rotation);
  prefs.putBool("invert", s.invert);
  if (s.hasTouchCal) prefs.putBytes("tcal", s.touchCal, sizeof(s.touchCal));
  else prefs.remove("tcal");
  prefs.end();
}

bool configured() { return s.ssid.length() && s.host.length() && s.token.length(); }

void clear() {
  prefs.begin("jarvis", false);
  prefs.clear();
  prefs.end();
  s = Settings();
  s.name = "Jarvis";
  s.tz = DEFAULT_TZ;
}
}  // namespace settings
