// Mini-Jarvis – CYD-Satellit
// Mikrofon streamt dauerhaft (Wake-Word erkennt der Server), Touch = Push-to-Talk.
#include <Arduino.h>
#include <ArduinoJson.h>

#include "audio.h"
#include "config.h"
#include "net.h"
#include "ui.h"

static bool pttActive = false;

static void onServerAudio(const uint8_t* data, size_t len) { audio::queuePlayback(data, len); }

static void onServerText(const char* json, size_t len) {
  JsonDocument doc;
  if (deserializeJson(doc, json, len)) return;
  const char* type = doc["type"] | "";
  if (!strcmp(type, "state")) {
    const char* v = doc["value"] | "idle";
    if (!strcmp(v, "listening")) ui::setState(JState::Listening);
    else if (!strcmp(v, "thinking")) ui::setState(JState::Thinking);
    else if (!strcmp(v, "speaking")) ui::setState(JState::Speaking);
    else if (!strcmp(v, "alarm")) ui::setState(JState::Alarm);
    else ui::setState(JState::Idle);
  } else if (!strcmp(type, "text")) {
    ui::showText(doc["role"] | "assistant", doc["content"] | "");
  } else if (!strcmp(type, "alarm")) {
    ui::setState(JState::Alarm);
    ui::showText("assistant", doc["label"] | "Alarm");
  } else if (!strcmp(type, "clear")) {
    audio::clearPlayback();
  }
}

void setup() {
  Serial.begin(115200);
  ui::begin();
  if (!audio::beginSpeaker()) Serial.println("DAC-Start fehlgeschlagen");
  if (!audio::beginMic()) Serial.println("Mikrofon-Start fehlgeschlagen");
  // Beim Start 3 s Touch halten → WLAN-Einrichtung erzwingen
  bool forcePortal = false;
  uint32_t t0 = millis();
  while (millis() - t0 < 3000 && ui::touched()) forcePortal = millis() - t0 > 2500;
  net::begin(onServerAudio, onServerText, forcePortal);
}

void loop() {
  net::loop();
  audio::loop();
  ui::loop();

  if (!net::connected()) {
    if (ui::state() != JState::Offline) ui::setState(JState::Offline);
    return;
  }
  if (ui::state() == JState::Offline) ui::setState(JState::Idle);

  // Touch: Alarm quittieren oder Push-to-Talk
  bool touch = ui::touched();
  if (touch && ui::state() == JState::Alarm) {
    net::sendJson("{\"type\":\"alarm_ack\"}");
    ui::setState(JState::Idle);
  } else if (touch && !pttActive) {
    pttActive = true;
    audio::clearPlayback();
    net::sendJson("{\"type\":\"ptt\",\"value\":\"start\"}");
  } else if (!touch && pttActive) {
    pttActive = false;
    net::sendJson("{\"type\":\"ptt\",\"value\":\"stop\"}");
  }

  // Halbduplex: während Jarvis spricht, kein Mikrofon senden (kein Echo)
  static int16_t buf[MIC_FRAME_SAMPLES];
  size_t bytes = audio::readMic(buf, MIC_FRAME_SAMPLES);
  if (bytes && !audio::isPlaying()) net::sendAudio((uint8_t*)buf, bytes);
}
