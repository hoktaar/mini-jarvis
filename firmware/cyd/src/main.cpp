// Mini-Jarvis – CYD-Satellit (ESP32-2432S028)
// Mikrofon streamt, solange Jarvis nicht spricht (Wake-Word erkennt der Server); Touch auf den Reaktor = Push-to-Talk.
#include <Arduino.h>
#include <ArduinoJson.h>

#include "audio.h"
#include "board_cyd.h"
#include "config.h"
#include "net.h"
#include "ota.h"
#include "provision.h"
#include "settings.h"
#include "ui.h"

// Kennung für den Server: hochgeladene Builds verraten so ihre Version
extern "C" {
__attribute__((used)) const char jarvis_fw_marker[] = "JARVIS_FW_VERSION=" FW_VERSION;
}

static uint32_t alarmId = 0;
static uint32_t otaDoneAt = 0;
static bool calibrationAsked = false;

static void send(JsonDocument& doc) {
  char buf[320];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  if (n > 0 && n < sizeof(buf)) net::sendJson(buf);
}

// ---------------------------------------------------------------- Aktionen der Oberfläche
static void pttStart() {
  audio::setDropIncoming(true);              // Rest der alten Antwort verwerfen
  net::sendJson("{\"type\":\"ptt\",\"value\":\"start\"}");
}

static void pttStop() {
  audio::setDropIncoming(false);
  net::sendJson("{\"type\":\"ptt\",\"value\":\"stop\"}");
}

static void stopSpeaking() {
  audio::clear();
  net::sendJson("{\"type\":\"stop\"}");
}

static void alarmAck() {
  audio::alarm(false);
  ui::setAlarm(false, "");
  JsonDocument doc;
  doc["type"] = "alarm_ack";
  if (alarmId) doc["id"] = alarmId;
  send(doc);
}

static void alarmSnooze() {
  audio::alarm(false);
  ui::setAlarm(false, "");
  JsonDocument doc;
  doc["type"] = "alarm_snooze";
  if (alarmId) doc["id"] = alarmId;
  doc["minutes"] = 5;
  send(doc);
}

static void homeList(const char* group) {
  JsonDocument doc;
  doc["type"] = "home_list";
  doc["group"] = group;
  send(doc);
}

static void homeToggle(const char* id, const char* group) {
  JsonDocument doc;
  doc["type"] = "home_toggle";
  doc["id"] = id;
  doc["group"] = group;
  send(doc);
}

static void homeMedia(const char* id, const char* action) {
  JsonDocument doc;
  doc["type"] = "home_media";
  doc["id"] = id;
  doc["action"] = action;
  doc["group"] = "media";
  send(doc);
}

static void volume(uint8_t v) {
  audio::setVolume(v);
  JsonDocument doc;
  doc["type"] = "volume";
  doc["value"] = v;
  send(doc);
}

static void startPortal() { net::startPortal(); }

// ---------------------------------------------------------------- Nachrichten vom Server
static void onServerAudio(const uint8_t* data, size_t len) {
  if (ota::state() != ota::State::Downloading) audio::play(data, len);
}

static uint8_t kindOf(const char* k) {
  if (!strcmp(k, "toggle")) return 0;
  if (!strcmp(k, "activate")) return 1;
  if (!strcmp(k, "media")) return 2;
  return 3;
}

static void onServerText(const char* json, size_t len) {
  JsonDocument doc;
  if (deserializeJson(doc, json, len)) return;
  const char* type = doc["type"] | "";

  if (!strcmp(type, "state")) {
    const char* v = doc["value"] | "idle";
    if (!strcmp(v, "listening")) ui::setState(scr::St::Listening);
    else if (!strcmp(v, "thinking")) ui::setState(scr::St::Thinking);
    else if (!strcmp(v, "speaking")) ui::setState(scr::St::Speaking);
    else ui::setState(scr::St::Idle);
  } else if (!strcmp(type, "text")) {
    ui::setText(doc["role"] | "assistant", doc["content"] | "");
  } else if (!strcmp(type, "alarm")) {
    alarmId = doc["id"] | 0;
    const char* label = doc["label"] | "Wecker";
    ui::setAlarm(true, label);
    audio::alarm(true);
  } else if (!strcmp(type, "alarm_stop")) {
    uint32_t id = doc["id"] | 0;
    if (!id || id == alarmId) {
      audio::alarm(false);
      ui::setAlarm(false, "");
    }
  } else if (!strcmp(type, "timers")) {
    uint32_t now = doc["now"] | 0;
    net::setTime(now);
    std::vector<ui::TimerInfo> items;
    for (JsonObject t : doc["items"].as<JsonArray>()) {
      ui::TimerInfo info;
      info.id = t["id"] | 0;
      info.due = (time_t)(t["due"] | 0.0);
      info.label = (const char*)(t["label"] | "");
      info.ringing = t["ringing"] | false;
      items.push_back(info);
    }
    ui::setTimers(items);
  } else if (!strcmp(type, "volume")) {
    uint8_t v = doc["value"] | settings::s.volume;
    audio::setVolume(v);
    ui::setVolume(v);
  } else if (!strcmp(type, "private")) {
    ui::setPrivate(doc["value"] | false);
  } else if (!strcmp(type, "notice")) {
    ui::toast(doc["text"] | "");
  } else if (!strcmp(type, "home")) {
    std::vector<ui::HomeItem> items;
    for (JsonObject it : doc["items"].as<JsonArray>()) {
      ui::HomeItem h;
      h.id = (const char*)(it["id"] | "");
      h.name = (const char*)(it["name"] | "");
      h.display = (const char*)(it["display"] | "");
      h.on = it["on"] | false;
      h.kind = kindOf(it["kind"] | "sensor");
      h.available = it["available"] | true;
      items.push_back(h);
    }
    ui::setHome(doc["group"] | "light", doc["configured"] | false, items);
  } else if (!strcmp(type, "ota")) {
    audio::clear();
    ota::start(doc["path"] | "", doc["md5"] | "", doc["size"] | 0, doc["version"] | "");
  } else if (!strcmp(type, "hello")) {
    net::setTimezone(String((const char*)(doc["tz"] | "")));
    net::setTime(doc["time"] | 0);
    const char* name = doc["device"] | "";
    if (*name && settings::s.name != name) {
      settings::s.name = name;
      settings::save();
    }
  } else if (!strcmp(type, "clear")) {
    audio::clear();
  }
}

static void onProvisioned() { net::reconfigure(); }

// ---------------------------------------------------------------- Start
void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(115200);
  Serial.printf("\nJarvis CYD %s (%s)\n", FW_VERSION, FW_BOARD);
  Serial.println(jarvis_fw_marker);          // hält die Kennung auch im gelinkten Image
  pinMode(BOOT_BUTTON, INPUT_PULLUP);
  settings::load();

  ui::Callbacks cb{pttStart, pttStop, stopSpeaking, alarmAck, alarmSnooze, homeList, homeToggle, homeMedia, volume, startPortal};
  ui::begin(cb);
  ui::splash();
  if (!audio::begin()) Serial.println("Audio: Lautsprecher oder Mikrofon nicht bereit");
  audio::setVolume(settings::s.volume);
  provision::begin(onProvisioned);
  delay(700);

  // BOOT-Taste beim Einschalten gedrückt → Touch neu kalibrieren
  bool forceCal = digitalRead(BOOT_BUTTON) == LOW;
  if (forceCal || settings::s.hasTouchCal) {
    ui::calibrateTouch(forceCal);
    calibrationAsked = true;
  }
  net::begin(onServerAudio, onServerText);
}

void loop() {
  provision::loop();
  net::loop();
  ui::loop();

  // Erste Kalibrierung nach dem Start – nicht mitten in eine Einrichtung über USB hinein
  if (!calibrationAsked && millis() > 4000 && !provision::busy()) {
    calibrationAsked = true;
    ui::calibrateTouch(true);
  }

  // OTA: Fortschritt melden, nach Erfolg neu starten
  char status[200];
  if (ota::statusJson(status, sizeof(status))) net::sendJson(status);
  if (ota::state() == ota::State::Done) {
    if (!otaDoneAt) otaDoneAt = millis();
    else if (millis() - otaDoneAt > 1500) ESP.restart();
  }

  // Mikrofon nur senden, wenn verbunden und Jarvis gerade nicht spricht (kein Echo)
  bool stream = net::online() && audio::micOk() && ota::state() != ota::State::Downloading && !audio::alarmActive() &&
                (ui::pttActive() || !audio::playing());
  audio::setMicStreaming(stream);
  static int16_t frame[MIC_FRAME_SAMPLES];
  for (int i = 0; i < 4; i++) {
    size_t n = audio::readFrame(frame);
    if (!n) break;
    net::sendAudio((const uint8_t*)frame, n);
  }
  delay(2);
}
