#include "ota.h"

#include <HTTPClient.h>
#include <Update.h>
#include <WiFi.h>

#include "settings.h"

namespace ota {
static volatile State st = State::Idle;
static volatile int pct = 0;
static char err[96] = "";
static char ver[24] = "";
static char md5[33] = "";
static char path[96] = "";
static uint32_t expected = 0;
static State reportedState = State::Idle;
static int reportedPct = -1;

static const char* run() {
  HTTPClient http;
  NetworkClient client;
  String url = "http://" + settings::s.host + ":" + String(settings::s.port) + path;
  http.setTimeout(15000);
  if (!http.begin(client, url)) return "Adresse ungültig";
  http.addHeader("Authorization", "Bearer " + settings::s.token);
  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    static char buf[40];
    snprintf(buf, sizeof(buf), "HTTP %d", code);
    http.end();
    return buf;
  }
  int len = http.getSize();
  if (len <= 0 && expected) len = (int)expected;
  if (!Update.begin(len > 0 ? (size_t)len : UPDATE_SIZE_UNKNOWN, U_FLASH)) {
    http.end();
    return Update.errorString();
  }
  if (strlen(md5) == 32) Update.setMD5(md5);
  NetworkClient* stream = http.getStreamPtr();
  static uint8_t buf[2048];
  size_t written = 0;
  uint32_t last = millis();
  while (http.connected() && (len <= 0 || written < (size_t)len)) {
    size_t avail = stream->available();
    if (!avail) {
      if (millis() - last > 15000) { Update.abort(); http.end(); return "Zeitüberschreitung"; }
      vTaskDelay(pdMS_TO_TICKS(2));
      continue;
    }
    int r = stream->readBytes(buf, avail < sizeof(buf) ? avail : sizeof(buf));
    if (r <= 0) continue;
    if (Update.write(buf, (size_t)r) != (size_t)r) { const char* e = Update.errorString(); Update.abort(); http.end(); return e; }
    written += (size_t)r;
    last = millis();
    if (len > 0) pct = (int)(written * 100 / (size_t)len);
  }
  http.end();
  if (len > 0 && written != (size_t)len) { Update.abort(); return "Download unvollständig"; }
  if (!Update.end(true)) return Update.errorString();      // prüft auch die MD5-Summe
  return nullptr;
}

static void task(void*) {
  const char* e = run();
  if (e) {
    strlcpy(err, e, sizeof(err));
    st = State::Error;
  } else {
    pct = 100;
    st = State::Done;
  }
  vTaskDelete(nullptr);
}

bool start(const char* p, const char* m, uint32_t size, const char* v) {
  if (st == State::Downloading || !p || p[0] != '/') return false;
  strlcpy(path, p, sizeof(path));
  strlcpy(md5, m ? m : "", sizeof(md5));
  strlcpy(ver, v ? v : "", sizeof(ver));
  expected = size;
  err[0] = 0;
  pct = 0;
  st = State::Downloading;
  if (xTaskCreatePinnedToCore(task, "ota", 8192, nullptr, 3, nullptr, 1) != pdPASS) {
    strlcpy(err, "kein Speicher", sizeof(err));
    st = State::Error;
    return false;
  }
  return true;
}

State state() { return st; }
int progress() { return pct; }
const char* error() { return err; }
const char* version() { return ver; }

bool statusJson(char* out, size_t len) {
  State s = st;
  int p = pct;
  if (s == State::Idle) return false;
  // Fortschritt nur in 10-%-Schritten melden
  if (s == reportedState && (s != State::Downloading || p / 10 == reportedPct / 10)) return false;
  reportedState = s;
  reportedPct = p;
  const char* name = s == State::Downloading ? "downloading" : s == State::Done ? "done" : "error";
  snprintf(out, len, "{\"type\":\"ota_status\",\"state\":\"%s\",\"progress\":%d,\"version\":\"%s\",\"error\":\"%s\"}",
           name, p, ver, s == State::Error ? err : "");
  return true;
}
}  // namespace ota
