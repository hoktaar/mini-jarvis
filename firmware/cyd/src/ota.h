#pragma once
#include <Arduino.h>

// OTA-Update vom Jarvis-Server: HTTP-Download mit Geräte-Token, MD5-Prüfung, danach Neustart.
namespace ota {
enum class State : uint8_t { Idle, Downloading, Done, Error };
bool start(const char* path, const char* md5, uint32_t size, const char* version);
State state();
int progress();                     // 0–100
const char* error();
const char* version();
bool statusJson(char* out, size_t len);   // true, wenn sich seit dem letzten Aufruf etwas geändert hat
}
