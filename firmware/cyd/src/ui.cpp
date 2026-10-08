#include "ui.h"

#include <WiFi.h>
#include <time.h>

#include "audio.h"
#include "board_cyd.h"
#include "config.h"
#include "net.h"
#include "ota.h"
#include "settings.h"

using namespace scr;

class LGFX : public lgfx::LGFX_Device {
#ifdef PANEL_ST7789
  lgfx::Panel_ST7789 panel;
#else
  lgfx::Panel_ILI9341 panel;
#endif
  lgfx::Bus_SPI bus;
  lgfx::Light_PWM light;
  lgfx::Touch_XPT2046 touch;

 public:
  LGFX() {
    {
      auto c = bus.config();
      c.spi_host = HSPI_HOST;
      c.spi_mode = 0;
      c.freq_write = 40000000;
      c.freq_read = 16000000;
      c.pin_sclk = TFT_SCLK;
      c.pin_mosi = TFT_MOSI;
      c.pin_miso = TFT_MISO;
      c.pin_dc = TFT_DC;
      bus.config(c);
      panel.setBus(&bus);
    }
    {
      auto c = panel.config();
      c.pin_cs = TFT_CS;
      c.pin_rst = -1;
      c.panel_width = 240;
      c.panel_height = 320;
      c.readable = true;
      c.bus_shared = false;
      panel.config(c);
    }
    {
      auto c = light.config();
      c.pin_bl = TFT_BL;
      c.freq = 12000;
      c.pwm_channel = 7;
      light.config(c);
      panel.setLight(&light);
    }
    {
      auto c = touch.config();
      c.spi_host = VSPI_HOST;
      c.freq = 1000000;
      c.pin_sclk = TOUCH_CLK;
      c.pin_mosi = TOUCH_MOSI;
      c.pin_miso = TOUCH_MISO;
      c.pin_cs = TOUCH_CS;
      c.pin_int = TOUCH_IRQ;
      c.bus_shared = false;
      c.x_min = 300;               // grobe Werte – beim ersten Start wird kalibriert
      c.x_max = 3900;
      c.y_min = 200;
      c.y_max = 3700;
      touch.config(c);
      panel.setTouch(&touch);
    }
    setPanel(&panel);
  }
};

namespace ui {
static LGFX tft;
static Callbacks cb{};
static Layout L;
static Pg page = Pg::Home;
static St st = St::Offline;

// Sprites (nur solange die jeweilige Seite sie braucht – der ESP32 hat kein PSRAM)
static LGFX_Sprite reactorSp(&tft), waveSp(&tft), rowSp(&tft), chipSp(&tft);
static float waveSmooth[48];

// Zustand
static bool dirtyAll = true, dirtyStatus = true, dirtyList = true, dirtyBody = false;
static String lastStatus, lastHeaderKey, lastChip;
static String assistantText, userText;
static uint32_t textAt = 0;
static bool alarmOn = false;
static String alarmLabel;
static uint32_t toastUntil = 0;
static String toastText;
static bool toastShown = false;
static bool priv = false;
static bool ptt = false, pttTap = false;
static uint32_t lastFrame = 0, serverSince = 0;
static net::State lastNet = net::State::Unconfigured;
static int lastOtaPct = -1;
static ota::State lastOta = ota::State::Idle;
static uint32_t saveAt = 0;

// Smarthome
static std::vector<HomeItem> lights, players;
static bool lightsLoaded = false, playersLoaded = false, haConfigured = true;
static int playerIdx = 0;
static int scrollY = 0;
static int pressedRow = -1;
static std::vector<TimerInfo> timers;

// Touch-Kalibrierung (nicht blockierend, damit USB-Einrichtung und WLAN weiterlaufen)
static bool calibrating = false, calRelease = false;
static int calStep = 0, calSamples = 0;
static int32_t calX = 0, calY = 0;
static uint16_t calOrig[8];
static uint8_t calRot = 0;

// Touch
static bool touchDown = false, touchMoved = false;
static int tx0 = 0, ty0 = 0, tx = 0, ty = 0, scroll0 = 0;
static uint32_t touchT0 = 0, lastScrollDraw = 0;

// ---------------------------------------------------------------- Hilfen
static void led(bool r, bool g, bool b) {   // aktiv LOW
  digitalWrite(LED_R, !r);
  digitalWrite(LED_G, !g);
  digitalWrite(LED_B, !b);
}

static void updateLed() {
  if (alarmOn) led(1, 1, 0);
  else if (st == St::Listening) led(0, 0, 1);
  else if (net::state() == net::State::WifiFailed) led(1, 0, 0);
  else led(0, 0, 0);
}

static String clean(const String& s, size_t max = 400) {
  std::vector<char> buf(max + 1);
  scr::sanitize(s.c_str(), buf.data(), buf.size());
  return String(buf.data());
}

static void scheduleSave() { saveAt = millis() + 2000; }

static bool netUsable() { return net::state() == net::State::Online; }

static void freeSprites() {
  reactorSp.deleteSprite();
  waveSp.deleteSprite();
  rowSp.deleteSprite();
}

static void ensureHomeSprites() {
  if (!reactorSp.getBuffer()) {
    reactorSp.setColorDepth(16);
    reactorSp.createSprite(L.rsize, L.rsize);
  }
  if (!waveSp.getBuffer()) {
    waveSp.setColorDepth(16);
    waveSp.createSprite(L.waveW, L.waveH);
  }
}

static void ensureRowSprite() {
  if (!rowSp.getBuffer()) {
    rowSp.setColorDepth(16);
    rowSp.createSprite(L.w, kTileH > kSetH ? kTileH : kSetH);
  }
}

static void relayout() {
  tft.setRotation(settings::s.rotation & 3);
  L = layout(tft.width(), tft.height());
  freeSprites();
  chipSp.deleteSprite();
  chipSp.setColorDepth(16);
  chipSp.createSprite(kChipW, kChipH);
  dirtyAll = true;
  lastHeaderKey = "";
  lastChip = "-";
}

static void setPage(Pg p) {
  if (p == page && !dirtyAll) return;
  page = p;
  scrollY = 0;
  pressedRow = -1;
  freeSprites();
  dirtyAll = true;
  if (p == Pg::Light && cb.homeList) { lightsLoaded = false; cb.homeList("light"); }
  if (p == Pg::Music && cb.homeList) { playersLoaded = false; cb.homeList("media"); }
}

// ---------------------------------------------------------------- Kopfzeile
static const char* const WD[] = {"So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"};
static const char* const MO[] = {"Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."};

static String nextTimerChip() {
  time_t now = time(nullptr);
  const TimerInfo* best = nullptr;
  for (auto& t : timers) {
    if (t.ringing || t.due <= now) continue;
    if (!best || t.due < best->due) best = &t;
  }
  if (!best || !net::timeValid()) return "";
  long s = (long)(best->due - now);
  char buf[16];
  if (s < 3600) snprintf(buf, sizeof(buf), "%ld:%02ld", s / 60, s % 60);
  else if (s < 86400) {
    struct tm tmv;
    localtime_r(&best->due, &tmv);
    snprintf(buf, sizeof(buf), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
  } else return "";
  return String(buf);
}

static void drawHeaderIfNeeded(bool force) {
  char tbuf[8] = "--:--", dbuf[24] = "";
  if (net::timeValid()) {
    time_t now = time(nullptr);
    struct tm tmv;
    localtime_r(&now, &tmv);
    snprintf(tbuf, sizeof(tbuf), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
    snprintf(dbuf, sizeof(dbuf), "%s, %d. %s", WD[tmv.tm_wday], tmv.tm_mday, MO[tmv.tm_mon]);
  }
  int rssi = net::rssi();
  int bucket = rssi == 0 ? 0 : rssi >= -60 ? 3 : rssi >= -72 ? 2 : 1;
  String key = String(tbuf) + dbuf + bucket + (netUsable() ? "o" : "x") + (priv ? "p" : "");
  if (force || key != lastHeaderKey) {
    lastHeaderKey = key;
    Header h{tbuf, dbuf, rssi, netUsable(), priv, nullptr};
    drawHeader(tft, L, h);
    lastChip = "-";
  }
  String chip = nextTimerChip();
  if (chip != lastChip) {
    lastChip = chip;
    int cx, cy;
    chipPos(L, priv, cx, cy);
    drawChip(chipSp, chip.c_str());
    chipSp.pushSprite(cx, cy);
  }
}

// ---------------------------------------------------------------- Startseite
static String statusText(uint16_t& color) {
  color = col::ink2;
  const Settings& s = settings::s;
  switch (net::state()) {
    case net::State::WifiConnecting:
      return "Verbinde mit WLAN „" + s.ssid + "“ …";
    case net::State::WifiFailed:
      color = col::warn;
      return "WLAN „" + s.ssid + "“ nicht erreichbar – neuer Versuch läuft";
    case net::State::ServerConnecting:
      if (millis() - serverSince > 7000) {
        color = col::warn;
        return "Jarvis nicht erreichbar (" + s.host + ":" + String(s.port) + ")";
      }
      return "Verbinde mit Jarvis …";
    default:
      break;
  }
  switch (st) {
    case St::Listening: return "Ich höre dir zu …";
    case St::Thinking: return "Einen Moment …";
    case St::Speaking:
      color = col::ink;
      return assistantText.length() ? assistantText : String("…");
    default:
      break;
  }
  if (millis() - textAt < 15000 && assistantText.length()) {
    color = col::ink;
    return assistantText;
  }
  color = col::muted;
  return audio::micOk() ? "Sag „Hey Jarvis“ oder tippe auf den Kreis" : "Tippe auf den Kreis und halte zum Sprechen";
}

static St visualState() {
  if (alarmOn) return St::Alarm;
  if (!netUsable()) return St::Offline;
  return st;
}

static void drawTitleSprite() {
  LGFX_Sprite t(&tft);
  t.setColorDepth(16);
  int w = 150, h = 32;
  if (!t.createSprite(w, h)) { drawTitle(tft, L); return; }
  t.fillScreen(col::bg);
  Layout l = L;
  l.titleX = w / 2;
  l.titleY = h / 2;
  drawTitle(t, l);
  t.pushSprite(L.titleX - w / 2, L.titleY - h / 2);
  t.deleteSprite();
}

static void homeFrame(float t) {
  ensureHomeSprites();
  St vs = visualState();
  drawReactor(reactorSp, L.rsize, t, vs, audio::level());
  reactorSp.pushSprite(L.rcx - L.rsize / 2, L.rcy - L.rsize / 2);
  if (!alarmOn) {
    drawWave(waveSp, L.waveW, L.waveH, t, vs, audio::level(), waveSmooth, L.land ? 30 : 34);
    waveSp.pushSprite(L.waveX, L.waveY);
  }
}

// ---------------------------------------------------------------- Listen (Licht, Einstellungen)
static int listTop() { return L.contentY + kPageHead; }
static int listHeight() { return L.navY - listTop(); }

static std::vector<SetRow> settingRows(std::vector<String>& store) {
  const Settings& s = settings::s;
  store.clear();
  store.reserve(12);
  auto keep = [&](const String& v) { store.push_back(v); return store.back().c_str(); };
  std::vector<SetRow> rows;
  rows.push_back({"Lautstärke", keep(String(s.volume) + " %"), s.volume, true, false});
  int bright = (s.brightness * 100 + 127) / 255;
  rows.push_back({"Helligkeit", keep(String(bright) + " %"), bright, true, false});
  static const char* const ROT[] = {"Hochformat", "Querformat", "Hochformat (gedreht)", "Querformat (gedreht)"};
  rows.push_back({"Ausrichtung", ROT[s.rotation & 3], -1, false, true});
  rows.push_back({"Farben umkehren", s.invert ? "an" : "aus", -1, false, true});
  rows.push_back({"Touch kalibrieren", "", -1, false, true});
  rows.push_back({"WLAN neu einrichten", "Hotspot „" SETUP_AP_NAME "“ öffnen", -1, false, true});
  rows.push_back({"Neu starten", "", -1, false, true});
  rows.push_back({"Name", keep(s.name), -1, false, false});
  rows.push_back({"Netzwerk", keep(net::ip() + (net::rssi() ? "  ·  " + String(net::rssi()) + " dBm" : String(""))), -1, false, false});
  rows.push_back({"Jarvis-Server", keep(s.host + ":" + String(s.port) + (netUsable() ? "  ·  verbunden" : "  ·  getrennt")), -1, false, false});
  rows.push_back({"Firmware", FW_VERSION "  ·  " FW_BOARD, -1, false, false});
  return rows;
}

static int listCount() {
  if (page == Pg::Light) return (int)lights.size();
  if (page == Pg::Settings) return 11;
  return 0;
}

static int rowH() { return page == Pg::Light ? kTileH : kSetH; }

static int maxScroll() {
  int total = listCount() * rowH();
  return total > listHeight() ? total - listHeight() : 0;
}

static void drawList() {
  ensureRowSprite();
  int top = listTop(), h = listHeight(), rh = rowH();
  tft.setClipRect(0, top, L.w, h);
  std::vector<String> store;
  std::vector<SetRow> srows;
  if (page == Pg::Settings) srows = settingRows(store);
  int n = listCount();
  int first = scrollY / rh;
  int y = top - (scrollY % rh);
  for (int i = first; i < n && y < top + h; i++, y += rh) {
    if (page == Pg::Light) {
      const HomeItem& it = lights[i];
      Tile t{it.name.c_str(), it.display.c_str(), it.on, it.kind, it.available};
      drawTileRow(rowSp, L.w, t, i == pressedRow);
    } else {
      drawSettingRow(rowSp, L.w, srows[i]);
    }
    rowSp.pushSprite(0, y);
  }
  if (y < top + h) tft.fillRect(0, y, L.w, top + h - y, col::bg);
  tft.clearClipRect();
}

static void drawPage() {
  switch (page) {
    case Pg::Home:
      if (net::state() == net::State::Unconfigured || net::state() == net::State::Portal) {
        drawSetup(tft, L, net::state() == net::State::Portal, SETUP_AP_NAME, FW_VERSION);
      } else {
        drawTitleSprite();
        dirtyStatus = true;
      }
      break;
    case Pg::Light: {
      int on = 0;
      for (auto& l : lights) on += l.on;
      String sub = lights.size() ? String(on) + " von " + String(lights.size()) + " an" : String("");
      drawPageHead(tft, L, "Licht", sub.c_str());
      if (!haConfigured) drawMessage(tft, L, "Home Assistant ist nicht eingerichtet.", "In der Jarvis-Konfiguration „homeassistant“ aktivieren und Entitäten freigeben.");
      else if (!lightsLoaded) drawMessage(tft, L, "Lade …", "");
      else if (lights.empty()) drawMessage(tft, L, "Keine Lichter freigegeben.", "Entitäten in config.yaml unter homeassistant.entities eintragen.");
      else drawList();
      break;
    }
    case Pg::Music: {
      drawPageHead(tft, L, "Musik", players.size() > 1 ? (String(playerIdx + 1) + " / " + String(players.size())).c_str() : "");
      if (!haConfigured) drawMessage(tft, L, "Home Assistant ist nicht eingerichtet.", "Mediaplayer kommen aus Home Assistant.");
      else if (!playersLoaded) drawMessage(tft, L, "Lade …", "");
      else if (players.empty()) drawMessage(tft, L, "Kein Mediaplayer freigegeben.", "media_player-Entitäten in homeassistant.entities eintragen.");
      else {
        if (playerIdx >= (int)players.size()) playerIdx = 0;
        const HomeItem& p = players[playerIdx];
        Player pl{p.name.c_str(), p.display.c_str(), p.on, p.available, playerIdx, (int)players.size()};
        drawMusic(tft, L, pl);
      }
      break;
    }
    case Pg::Settings:
      drawPageHead(tft, L, "Einstellungen", settings::s.name.c_str());
      drawList();
      break;
  }
}

// ---------------------------------------------------------------- Überlagerungen
static void drawAlarmScreen() {
  tft.fillScreen(col::bg);
  drawHeaderIfNeeded(true);
  drawAlarm(tft, L, alarmLabel.length() ? alarmLabel.c_str() : "Wecker", 0);
}

static bool otaScreen() {
  ota::State s = ota::state();
  if (s == ota::State::Idle) return false;
  int pct = ota::progress();
  if (s != lastOta || pct != lastOtaPct) {
    lastOta = s;
    lastOtaPct = pct;
    const char* status = s == ota::State::Error ? ota::error()
                         : s == ota::State::Done ? "Fertig – starte neu …"
                                                  : "Lade Firmware vom Jarvis-Server …";
    drawOta(tft, L, pct, ota::version(), status, s == ota::State::Error);
  }
  return s != ota::State::Error;           // nach einem Fehler wieder bedienbar
}

// ---------------------------------------------------------------- Touch
static void onTap(int x, int y) {
  if (alarmOn) {
    int hit = alarmHit(L, x, y);
    if (hit == 0 && cb.alarmAck) cb.alarmAck();
    if (hit == 1 && cb.alarmSnooze) cb.alarmSnooze();
    return;
  }
  int nav = navHit(L, x, y);
  if (nav >= 0) {
    audio::beep();
    setPage((Pg)nav);
    return;
  }
  switch (page) {
    case Pg::Home:
      if ((net::state() == net::State::Unconfigured) && setupHit(L, x, y) && cb.startPortal) cb.startPortal();
      break;
    case Pg::Light: {
      if (y < listTop() || !lightsLoaded) break;
      int i = (y - listTop() + scrollY) / kTileH;
      if (i < 0 || i >= (int)lights.size()) break;
      HomeItem& it = lights[i];
      if (!it.available || (it.kind != 0 && it.kind != 1)) break;
      audio::beep();
      if (it.kind == 0) it.on = !it.on;         // sofort zeigen, der Server meldet den echten Zustand
      pressedRow = -1;
      dirtyList = true;
      if (cb.homeToggle) cb.homeToggle(it.id.c_str(), "light");
      break;
    }
    case Pg::Music: {
      if (players.empty()) break;
      int hit = musicHit(L, x, y);
      const HomeItem& p = players[playerIdx < (int)players.size() ? playerIdx : 0];
      static const char* const ACTIONS[] = {"previous", "play_pause", "next", "volume_down", "volume_up"};
      if (hit == 5) {
        playerIdx = (playerIdx + 1) % (int)players.size();
        dirtyBody = true;
      } else if (hit >= 0 && cb.homeMedia) {
        audio::beep();
        cb.homeMedia(p.id.c_str(), ACTIONS[hit]);
      }
      break;
    }
    case Pg::Settings: {
      if (y < listTop()) break;
      int i = (y - listTop() + scrollY) / kSetH;
      Settings& s = settings::s;
      int step = stepperHit(L.w, x);
      switch (i) {
        case 0:
          if (step) {
            int v = (int)s.volume + step * 10;
            s.volume = (uint8_t)(v < 0 ? 0 : v > 100 ? 100 : v);
            audio::setVolume(s.volume);
            audio::beep();
            if (cb.volume) cb.volume(s.volume);
            scheduleSave();
          }
          break;
        case 1:
          if (step) {
            int v = (int)s.brightness + step * 25;
            s.brightness = (uint8_t)(v < 15 ? 15 : v > 255 ? 255 : v);
            tft.setBrightness(s.brightness);
            scheduleSave();
          }
          break;
        case 2:
          s.rotation = (s.rotation + 1) & 3;
          settings::save();
          relayout();
          page = Pg::Settings;
          return;
        case 3:
          s.invert = !s.invert;
          tft.invertDisplay(s.invert);
          scheduleSave();
          break;
        case 4:
          calibrateTouch(true);
          return;
        case 5:
          if (cb.startPortal) cb.startPortal();
          setPage(Pg::Home);
          return;
        case 6:
          settings::save();
          tft.fillScreen(col::bg);
          ESP.restart();
          break;
        default:
          break;
      }
      dirtyList = true;
      break;
    }
  }
}

static void onPress(int x, int y) {
  if (alarmOn) return;
  if (page == Pg::Home && !netUsable() && net::state() != net::State::Unconfigured &&
      net::state() != net::State::Portal && reactorHit(L, x, y)) {
    toast("Keine Verbindung zu Jarvis");
    return;
  }
  if (page == Pg::Home && netUsable() && reactorHit(L, x, y)) {
    if (pttTap) {                            // zweites Antippen beendet das Zuhören
      pttTap = false;
      ptt = false;
      if (cb.pttStop) cb.pttStop();
      return;
    }
    if (st == St::Speaking && cb.stopSpeaking) cb.stopSpeaking();
    ptt = true;
    if (cb.pttStart) cb.pttStart();
    st = St::Listening;
    dirtyStatus = true;
    return;
  }
  if (page == Pg::Light && y >= listTop() && y < L.navY && lightsLoaded) {
    int i = (y - listTop() + scrollY) / kTileH;
    if (i >= 0 && i < (int)lights.size()) {
      pressedRow = i;
      dirtyList = true;
    }
  }
}

static void onRelease(int x, int y, uint32_t held) {
  if (ptt) {
    if (held >= 450) {                       // gehalten = Push-to-Talk
      ptt = false;
      if (cb.pttStop) cb.pttStop();
    } else {
      pttTap = true;                         // kurz angetippt: zuhören, bis der Server das Ende erkennt
    }
    return;
  }
  if (pressedRow >= 0) {
    pressedRow = -1;
    dirtyList = true;
  }
  if (!touchMoved) onTap(x, y);
}

static void pollTouch() {
  int32_t x, y;
  bool down = tft.getTouch(&x, &y) > 0;
  uint32_t now = millis();
  if (down && !touchDown) {
    touchDown = true;
    touchMoved = false;
    tx0 = tx = x;
    ty0 = ty = y;
    touchT0 = now;
    scroll0 = scrollY;
    onPress(x, y);
  } else if (down && touchDown) {
    tx = x;
    ty = y;
    if (!touchMoved && (abs(ty - ty0) > 10 || abs(tx - tx0) > 14)) {
      touchMoved = true;
      if (pressedRow >= 0) { pressedRow = -1; dirtyList = true; }
    }
    if (touchMoved && (page == Pg::Light || page == Pg::Settings) && !ptt) {
      int ns = scroll0 - (ty - ty0);
      int ms = maxScroll();
      ns = ns < 0 ? 0 : ns > ms ? ms : ns;
      if (ns != scrollY && now - lastScrollDraw > 35) {
        scrollY = ns;
        lastScrollDraw = now;
        dirtyList = true;
      }
    }
  } else if (!down && touchDown) {
    touchDown = false;
    onRelease(tx, ty, now - touchT0);
  }
}

// ---------------------------------------------------------------- Öffentliche Funktionen
void begin(const Callbacks& c) {
  cb = c;
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  led(0, 0, 0);
  initFonts();
  tft.init();
  tft.invertDisplay(settings::s.invert);
  tft.setBrightness(settings::s.brightness);
  relayout();
}

void splash() {
  drawSplash(tft, L, FW_VERSION);
}

// Ablauf wie LGFX_Device::calibrateTouch, aber Schritt für Schritt aus loop() heraus
static void drawCalTarget() {
  tft.fillScreen(col::bg);
  tft.setFont(&fText);
  tft.setTextColor(col::ink, col::bg);
  drawWrapped(tft, "Touch einrichten", 20, tft.height() / 2 - 44, tft.width() - 40, 1, 20, true);
  tft.setFont(&fSmall);
  tft.setTextColor(col::ink2, col::bg);
  drawWrapped(tft, "Tippe genau auf die Spitze des Pfeils. Danach folgt die nächste Ecke.", 24, tft.height() / 2 - 16, tft.width() - 48, 3, 16, true);
  char step[16];
  snprintf(step, sizeof(step), "%d von 4", calStep + 1);
  tft.setTextColor(col::muted, col::bg);
  drawWrapped(tft, step, 20, tft.height() / 2 + 34, tft.width() - 40, 1, 16, true);
  int px = (tft.width() - 1) * ((calStep >> 1) & 1);
  int py = (tft.height() - 1) * (calStep & 1);
  int dx = px ? -1 : 1, dy = py ? -1 : 1;
  tft.fillTriangle(px, py, px + dx * 24, py + dy * 8, px + dx * 8, py + dy * 24, col::accent);
  tft.drawWideLine(px + dx * 10, py + dy * 10, px + dx * 34, py + dy * 34, 2.0f, col::accent);
}

static void finishCalibration() {
  Settings& s = settings::s;
  memcpy(s.touchCal, calOrig, sizeof(calOrig));
  s.hasTouchCal = true;
  settings::save();
  tft.setTouchCalibrate(calOrig);
  calibrating = false;
  tft.setRotation(calRot);
  relayout();
}

static void calibrationLoop() {
  lgfx::touch_point_t tp, tp2;
  if (calRelease) {                           // erst loslassen, dann nächste Ecke
    if (!tft.getTouchRaw(&tp)) {
      calRelease = false;
      if (++calStep == 4) finishCalibration();
      else drawCalTarget();
    }
    return;
  }
  if (!tft.getTouchRaw(&tp)) return;
  delay(10);
  if (!tft.getTouchRaw(&tp2) || abs(tp.x - tp2.x) > 20 || abs(tp.y - tp2.y) > 20) return;
  calX += tp.x + tp2.x;
  calY += tp.y + tp2.y;
  if (++calSamples == 8) {
    calOrig[calStep * 2] = (uint16_t)(calX >> 4);
    calOrig[calStep * 2 + 1] = (uint16_t)(calY >> 4);
    calX = calY = 0;
    calSamples = 0;
    calRelease = true;
    audio::beep();
  }
}

void calibrateTouch(bool force) {
  Settings& s = settings::s;
  if (s.hasTouchCal && !force) {
    tft.setTouchCalibrate(s.touchCal);
    return;
  }
  if (calibrating) return;
  calibrating = true;
  calStep = calSamples = 0;
  calX = calY = 0;
  calRelease = false;
  calRot = tft.getRotation();
  tft.setRotation(0);                         // Kalibrierung im Grundformat des Panels
  drawCalTarget();
}

bool calibrationActive() { return calibrating; }

void setState(St s) {
  if (s == st) return;
  if (s != St::Listening && pttTap) {        // Server hat das Ende der Frage erkannt
    pttTap = false;
    ptt = false;
    if (cb.pttStop) cb.pttStop();
  }
  st = s;
  dirtyStatus = true;
  updateLed();
}

St state() { return st; }

void setText(const char* role, const char* text) {
  String t = clean(text);
  if (!strcmp(role, "user")) userText = t;
  else assistantText = t;
  textAt = millis();
  dirtyStatus = true;
}

void setAlarm(bool on, const char* label) {
  if (on == alarmOn && (!on || alarmLabel == label)) return;
  alarmOn = on;
  alarmLabel = on ? clean(label ? label : "", 60) : String();
  if (on) {
    if (page != Pg::Home) setPage(Pg::Home);
    tft.setBrightness(255);
  } else {
    tft.setBrightness(settings::s.brightness);
  }
  dirtyAll = true;
  updateLed();
}

bool alarmShown() { return alarmOn; }

void toast(const char* text) {
  toastText = clean(text, 120);
  toastUntil = millis() + 3500;
  toastShown = false;
}

void setHome(const char* group, bool configured, std::vector<HomeItem>& items) {
  haConfigured = configured;
  // Seite nur neu zeichnen (ohne den ganzen Bildschirm zu leeren) – flackert beim Schalten nicht
  if (!strcmp(group, "media")) {
    players.swap(items);
    playersLoaded = true;
    if (page == Pg::Music) dirtyBody = true;
  } else {
    lights.swap(items);
    lightsLoaded = true;
    if (scrollY > maxScroll()) scrollY = maxScroll();
    if (page == Pg::Light) dirtyBody = true;
  }
}

void setTimers(std::vector<TimerInfo>& items) { timers.swap(items); }

void setPrivate(bool on) {
  if (priv == on) return;
  priv = on;
  lastHeaderKey = "";
}

void setVolume(uint8_t v) {
  settings::s.volume = v;
  if (page == Pg::Settings) dirtyList = true;
  scheduleSave();
}

bool pttActive() { return ptt; }

void loop() {
  uint32_t now = millis();
  if (saveAt && now > saveAt) {
    saveAt = 0;
    settings::save();
  }
  if (otaScreen()) return;
  if (calibrating) {
    calibrationLoop();
    return;
  }
  if (lastOta == ota::State::Error && ota::state() == ota::State::Idle) dirtyAll = true;

  net::State ns = net::state();
  if (ns != lastNet) {
    if (ns == net::State::ServerConnecting) serverSince = now;
    bool setupChanged = (lastNet == net::State::Unconfigured || lastNet == net::State::Portal) !=
                        (ns == net::State::Unconfigured || ns == net::State::Portal);
    lastNet = ns;
    dirtyStatus = true;
    lastHeaderKey = "";
    if (setupChanged && page == Pg::Home) dirtyAll = true;
    updateLed();
  }

  pollTouch();

  if (dirtyAll) {
    dirtyAll = false;
    tft.fillScreen(col::bg);
    lastHeaderKey = "";
    lastChip = "-";
    if (alarmOn) {
      drawAlarmScreen();
    } else {
      drawNav(tft, L, page);
      drawPage();
      dirtyList = false;
    }
    toastShown = false;
  }
  if (dirtyBody && !alarmOn) {
    dirtyBody = false;
    drawPage();
    dirtyList = false;
  }
  drawHeaderIfNeeded(false);

  bool setup = ns == net::State::Unconfigured || ns == net::State::Portal;
  if (alarmOn) {
    if (now - lastFrame >= 50) {
      lastFrame = now;
      homeFrame(now / 1000.0f);
    }
    return;
  }

  if (page == Pg::Home && !setup) {
    uint32_t interval = visualState() == St::Offline ? 120 : 45;
    if (now - lastFrame >= interval) {
      lastFrame = now;
      homeFrame(now / 1000.0f);
    }
    uint16_t color;
    String s = statusText(color);
    if (dirtyStatus || s != lastStatus) {
      dirtyStatus = false;
      lastStatus = s;
      if (!(toastUntil > now)) drawStatus(tft, L, s.c_str(), color);
    }
  }
  if (dirtyList && (page == Pg::Light || page == Pg::Settings)) {
    dirtyList = false;
    if (page == Pg::Settings || lightsLoaded) drawList();
  }

  // Hinweis einblenden / wieder entfernen
  if (toastUntil) {
    if (now < toastUntil && !toastShown) {
      toastShown = true;
      drawToast(tft, L, toastText.c_str(), page == Pg::Home && !setup);
    } else if (now >= toastUntil) {
      toastUntil = 0;
      toastShown = false;
      if (page == Pg::Home && !setup) dirtyStatus = true;
      else dirtyAll = true;
    }
  }
}
}  // namespace ui
