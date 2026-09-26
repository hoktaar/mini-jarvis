#pragma once
#include <Arduino.h>

namespace net {
using AudioHandler = void (*)(const uint8_t*, size_t);
using TextHandler = void (*)(const char*, size_t);

// WLAN per Captive Portal ("Jarvis-Setup"), Server/Token werden im Flash gespeichert.
void begin(AudioHandler onAudio, TextHandler onText, bool forcePortal = false);
void loop();
bool connected();
void sendAudio(const uint8_t* data, size_t len);
void sendJson(const char* json);
}
