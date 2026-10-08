#pragma once
#include <Arduino.h>

// Audio in eigenen FreeRTOS-Tasks (Kern 0): Mikrofon → Puffer → WebSocket, WebSocket → Puffer → DAC.
namespace audio {
bool begin();                             // zuerst DAC (belegt I2S0), dann Mikrofon (I2S1)
bool micOk();
void setMicStreaming(bool on);            // Mikrofon an den Server senden?
size_t readFrame(int16_t* out);           // 20-ms-Block aus dem Puffer, 0 = nichts da (nicht blockierend)
void play(const uint8_t* pcm16, size_t len);
void clear();                             // Wiedergabe sofort abbrechen
void setDropIncoming(bool drop);          // eingehendes Audio verwerfen (während Push-to-Talk)
bool playing();
void setVolume(uint8_t v);                // 0–100
void alarm(bool on);                      // Weckton bis zum Quittieren
bool alarmActive();
void beep();                              // kurzer Bestätigungston
float level();                            // 0…1 für die Wellenform (Mikrofon oder Wiedergabe)
}
