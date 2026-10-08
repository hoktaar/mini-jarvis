#pragma once
#include <Arduino.h>

#include <vector>

#include "screens.h"

// Bedienoberfläche: Seiten Start/Licht/Musik/Einstellungen, Touch, Wecker- und Update-Anzeige.
namespace ui {
struct HomeItem {
  String id, name, display;
  bool on = false;
  uint8_t kind = 3;             // 0 Schalter, 1 Szene, 2 Medien, 3 Sensor
  bool available = true;
};

struct TimerInfo {
  uint32_t id = 0;
  time_t due = 0;
  String label;
  bool ringing = false;
};

struct Callbacks {
  void (*pttStart)();
  void (*pttStop)();
  void (*stopSpeaking)();
  void (*alarmAck)();
  void (*alarmSnooze)();
  void (*homeList)(const char* group);
  void (*homeToggle)(const char* id, const char* group);
  void (*homeMedia)(const char* id, const char* action);
  void (*volume)(uint8_t v);
  void (*startPortal)();
};

void begin(const Callbacks& cb);
void splash();
void calibrateTouch(bool force);   // startet die Kalibrierung (läuft dann in loop())
bool calibrationActive();
void loop();

void setState(scr::St s);
scr::St state();
void setText(const char* role, const char* text);
void setAlarm(bool on, const char* label);
bool alarmShown();
void toast(const char* text);
void setHome(const char* group, bool configured, std::vector<HomeItem>& items);
void setTimers(std::vector<TimerInfo>& items);
void setPrivate(bool on);
void setVolume(uint8_t v);        // vom Server gemeldet
bool pttActive();
}
