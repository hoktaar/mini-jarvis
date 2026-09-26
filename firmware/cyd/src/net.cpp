#include "net.h"

#include <Preferences.h>
#include <WebSocketsClient.h>
#include <WiFiManager.h>

#include "config.h"

namespace net {
static WebSocketsClient ws;
static Preferences prefs;
static AudioHandler audioCb = nullptr;
static TextHandler textCb = nullptr;
static bool isConnected = false;

static void onEvent(WStype_t type, uint8_t* payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      isConnected = true;
      ws.sendTXT("{\"type\":\"hello\",\"fw\":\"" FW_VERSION
                 "\",\"board\":\"cyd\",\"caps\":[\"mic\",\"speaker\",\"display\",\"touch\"]}");
      break;
    case WStype_DISCONNECTED: isConnected = false; break;
    case WStype_BIN: if (audioCb) audioCb(payload, len); break;
    case WStype_TEXT: if (textCb) textCb((const char*)payload, len); break;
    default: break;
  }
}

void begin(AudioHandler onAudio, TextHandler onText, bool forcePortal) {
  audioCb = onAudio;
  textCb = onText;
  prefs.begin("jarvis", false);
  String host = prefs.getString("host", "192.168.1.144");
  String port = String(prefs.getUShort("port", DEFAULT_PORT));
  String token = prefs.getString("token", "");

  WiFiManager wm;
  WiFiManagerParameter pHost("host", "Jarvis-Server", host.c_str(), 64);
  WiFiManagerParameter pPort("port", "Port", port.c_str(), 6);
  WiFiManagerParameter pToken("token", "Geräte-Token", token.c_str(), 64);
  wm.addParameter(&pHost);
  wm.addParameter(&pPort);
  wm.addParameter(&pToken);
  wm.setConfigPortalTimeout(300);
  bool ok = forcePortal ? wm.startConfigPortal("Jarvis-Setup") : wm.autoConnect("Jarvis-Setup");
  if (!ok) ESP.restart();

  prefs.putString("host", pHost.getValue());
  prefs.putUShort("port", atoi(pPort.getValue()));
  prefs.putString("token", pToken.getValue());

  String path = String(WS_PATH) + "?token=" + pToken.getValue();
  ws.begin(pHost.getValue(), atoi(pPort.getValue()), path.c_str());
  ws.onEvent(onEvent);
  ws.setReconnectInterval(3000);
  ws.enableHeartbeat(15000, 3000, 2);
}

void loop() { ws.loop(); }
bool connected() { return isConnected; }
void sendAudio(const uint8_t* data, size_t len) { if (isConnected) ws.sendBIN(data, len); }
void sendJson(const char* json) { if (isConnected) ws.sendTXT(json); }
}  // namespace net
