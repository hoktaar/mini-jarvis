#pragma once
#include <Arduino.h>

enum class JState { Offline, Idle, Listening, Thinking, Speaking, Alarm };

namespace ui {
void begin();
void setState(JState s);
JState state();
void showText(const char* role, const char* text);
bool touched();          // true, solange der Bildschirm berührt wird
void loop();             // Animation
}
