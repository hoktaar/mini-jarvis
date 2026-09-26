#pragma once
#include <Arduino.h>

namespace audio {
// Reihenfolge wichtig: zuerst Lautsprecher (DAC belegt intern I2S0), dann Mikrofon.
bool beginSpeaker();
bool beginMic();
// Liest einen 20-ms-Block (PCM16 mono). Gibt Anzahl Bytes zurück.
size_t readMic(int16_t* out, size_t samples);
// Schreibt PCM16 vom Server in den Wiedergabepuffer (wird auf 8 Bit gewandelt).
void queuePlayback(const uint8_t* pcm16, size_t len);
void clearPlayback();
bool isPlaying();
void loop();
}
