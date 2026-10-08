#include "net.h"

#include <WebSocketsClient.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <sys/time.h>
#include <time.h>

#include "config.h"
#include "provision.h"
#include "settings.h"

namespace net {
static WebSocketsClient ws;
static AudioHandler audioCb = nullptr;
static TextHandler textCb = nullptr;
static State st = State::Unconfigured;
static bool wsStarted = false;
static uint32_t wifiStart = 0, lastRetry = 0;
static uint32_t failures = 0;

// Hotspot-Einrichtung (WiFiManager, nicht blockierend)
static WiFiManager* wm = nullptr;
static WiFiManagerParameter* pHost = nullptr;
static WiFiManagerParameter* pPort = nullptr;
static WiFiManagerParameter* pToken = nullptr;

static String hostname() {
  String h = "jarvis-";
  for (char c : settings::s.name) {
    if (isalnum((unsigned char)c)) h += (char)tolower((unsigned char)c);
    else if ((c == ' ' || c == '-') && !h.endsWith("-")) h += '-';
  }
  if (h.endsWith("-")) h.remove(h.length() - 1);
  return h.length() > 7 ? h.substring(0, 31) : String("jarvis-cyd");
}

static const char* wifiReason(wl_status_t w) {
  switch (w) {
    case WL_NO_SSID_AVAIL: return "WLAN nicht gefunden (nur 2,4 GHz)";
    case WL_CONNECT_FAILED: return "Verbindung abgelehnt – Passwort prüfen";
    case WL_CONNECTION_LOST: return "Verbindung verloren";
    default: return "Zeitüberschreitung";
  }
}

static void onEvent(WStype_t type, uint8_t* payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED: {
      st = State::Online;
      failures = 0;
      char hello[220];
      snprintf(hello, sizeof(hello),
               "{\"type\":\"hello\",\"fw\":\"%s\",\"board\":\"%s\",\"caps\":[\"mic\",\"speaker\",\"display\",\"touch\"],"
               "\"rssi\":%d,\"ip\":\"%s\"}",
               FW_VERSION, FW_BOARD, WiFi.RSSI(), WiFi.localIP().toString().c_str());
      ws.sendTXT(hello);
      break;
    }
    case WStype_DISCONNECTED:
      failures++;
      if (st == State::Online) st = State::ServerConnecting;
      break;
    case WStype_BIN:
      if (audioCb) audioCb(payload, len);
      break;
    case WStype_TEXT:
      if (textCb) textCb((const char*)payload, len);
      break;
    default:
      break;
  }
}

static void stopWs() {
  if (wsStarted) {
    ws.disconnect();
    wsStarted = false;
  }
}

static void startWs() {
  stopWs();
  // Token im Header statt in der URL (landet so nicht in Proxy-Logs)
  String auth = "Authorization: Bearer " + settings::s.token;
  ws.setExtraHeaders(auth.c_str());
  ws.begin(settings::s.host, settings::s.port, WS_PATH);
  ws.onEvent(onEvent);
  ws.setReconnectInterval(3000);
  ws.enableHeartbeat(15000, 4000, 2);
  wsStarted = true;
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname().c_str());
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);                       // geringere Latenz für den Audiostrom
  WiFi.begin(settings::s.ssid.c_str(), settings::s.pass.c_str());
  wifiStart = lastRetry = millis();
  st = State::WifiConnecting;
}

static void onWifiUp() {
  configTzTime(settings::s.tz.c_str(), NTP_SERVER_1, NTP_SERVER_2);
  provision::reportWifi(true, WiFi.localIP().toString());
  st = State::ServerConnecting;
  failures = 0;
  startWs();
}

void begin(AudioHandler onAudio, TextHandler onText) {
  audioCb = onAudio;
  textCb = onText;
  setenv("TZ", settings::s.tz.c_str(), 1);
  tzset();
  if (settings::configured()) connectWifi();
  else st = State::Unconfigured;
}

void reconfigure() {
  stopWs();
  if (wm) {
    wm->stopConfigPortal();
  }
  WiFi.disconnect(true);
  delay(100);
  connectWifi();
}

static void portalSaved() {
  Settings& s = settings::s;
  s.ssid = WiFi.SSID();
  s.pass = WiFi.psk();
  s.host = pHost->getValue();
  s.port = (uint16_t)atoi(pPort->getValue());
  if (!s.port) s.port = DEFAULT_PORT;
  s.token = pToken->getValue();
  settings::save();
}

void startPortal() {
  stopWs();
  if (!wm) {
    wm = new WiFiManager();
    static char port[8];
    snprintf(port, sizeof(port), "%u", settings::s.port);
    pHost = new WiFiManagerParameter("host", "Jarvis-Server (IP)", settings::s.host.c_str(), 64);
    pPort = new WiFiManagerParameter("port", "Port", port, 6);
    pToken = new WiFiManagerParameter("token", "Geräte-Token", settings::s.token.c_str(), 64);
    wm->addParameter(pHost);
    wm->addParameter(pPort);
    wm->addParameter(pToken);
    wm->setTitle("Jarvis einrichten");
    wm->setConfigPortalBlocking(false);
    wm->setBreakAfterConfig(true);
    wm->setSaveParamsCallback(portalSaved);
    wm->setConnectTimeout(20);
  }
  WiFi.mode(WIFI_AP_STA);
  wm->startConfigPortal(SETUP_AP_NAME);
  st = State::Portal;
}

void loop() {
  if (st == State::Portal) {
    if (wm->process()) {                       // neue Daten gespeichert und verbunden
      portalSaved();
      wm->stopConfigPortal();
      WiFi.mode(WIFI_STA);
      onWifiUp();
    }
    return;
  }
  if (st == State::Unconfigured) return;

  wl_status_t w = WiFi.status();
  switch (st) {
    case State::WifiConnecting:
      if (w == WL_CONNECTED) onWifiUp();
      else if (millis() - wifiStart > WIFI_TIMEOUT_MS) {
        st = State::WifiFailed;
        lastRetry = millis();
        provision::reportWifi(false, wifiReason(w));
      }
      break;
    case State::WifiFailed:
      if (w == WL_CONNECTED) onWifiUp();
      else if (millis() - lastRetry > 30000) {
        WiFi.disconnect();
        WiFi.begin(settings::s.ssid.c_str(), settings::s.pass.c_str());
        lastRetry = millis();
      }
      break;
    case State::ServerConnecting:
    case State::Online:
      if (w != WL_CONNECTED) {
        stopWs();
        st = State::WifiConnecting;           // WiFi verbindet sich selbst neu
        wifiStart = millis();
        break;
      }
      ws.loop();
      break;
    default:
      break;
  }
}

State state() { return st; }
bool online() { return st == State::Online; }
int rssi() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }
String ip() { return WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String("–"); }
bool timeValid() { return time(nullptr) > 1700000000; }
uint32_t serverFailures() { return failures; }

void setTime(uint32_t epoch) {
  if (timeValid() || epoch < 1700000000) return;
  struct timeval tv = {(time_t)epoch, 0};
  settimeofday(&tv, nullptr);
}

void setTimezone(const String& tz) {
  if (!tz.length() || tz == settings::s.tz) return;
  settings::s.tz = tz;
  settings::save();
  setenv("TZ", tz.c_str(), 1);
  tzset();
}

void sendAudio(const uint8_t* data, size_t len) {
  if (st == State::Online) ws.sendBIN(data, len);
}

void sendJson(const char* json) {
  if (st == State::Online) ws.sendTXT(json);
}
}  // namespace net
