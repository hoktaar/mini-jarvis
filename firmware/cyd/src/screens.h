#pragma once
// Zeichenfunktionen der CYD-Oberfläche. Bewusst ohne Arduino-Abhängigkeiten, damit sich die
// Bildschirme auch auf dem PC rendern lassen (tools/preview).
#include <stddef.h>
#include <stdint.h>

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

namespace scr {
enum class St : uint8_t { Offline, Idle, Listening, Thinking, Speaking, Alarm };
enum class Pg : uint8_t { Home, Light, Music, Settings };

// Farben (RGB565) im Stil des Web-Dashboards
constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) { return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)); }
namespace col {
constexpr uint16_t bg = rgb(5, 11, 22);
constexpr uint16_t panel = rgb(11, 26, 51);
constexpr uint16_t panel2 = rgb(16, 38, 72);
constexpr uint16_t line = rgb(28, 62, 104);
constexpr uint16_t accent = rgb(63, 208, 255);
constexpr uint16_t accent2 = rgb(31, 143, 224);
constexpr uint16_t ink = rgb(220, 236, 255);
constexpr uint16_t ink2 = rgb(169, 195, 230);
constexpr uint16_t muted = rgb(111, 141, 179);
constexpr uint16_t ok = rgb(46, 229, 157);
constexpr uint16_t warn = rgb(255, 181, 71);
constexpr uint16_t danger = rgb(255, 93, 108);
constexpr uint16_t cloud = rgb(180, 156, 255);
}  // namespace col
uint16_t blend(uint16_t a, uint16_t b, float t);   // t = 0 → a, 1 → b

void initFonts();
extern lgfx::VLWfont fClock, fTitle, fLarge, fText, fSmall;

struct Layout {
  int w, h;
  bool land;
  int headerH;
  int navY, navH;
  int contentY, contentH;
  int rcx, rcy, rsize;          // Reaktor: Mittelpunkt und Kantenlänge des Sprites
  int titleX, titleY;           // Mitte von „J A R V I S“
  int waveX, waveY, waveW, waveH;
  int textX, textY, textW, textLines;
};
Layout layout(int w, int h);

// Kopfzeile
struct Header {
  const char* time;             // „14:26“ oder „--:--“
  const char* date;             // „So, 27. Apr.“
  int rssi;                     // dBm, 0 = kein WLAN
  bool online;                  // mit Jarvis verbunden
  bool priv;                    // Privatmodus
  const char* chip;             // nächster Timer, z. B. „4:59“ (nullptr = keiner)
};
void drawHeader(lgfx::LovyanGFX& g, const Layout& L, const Header& h);
// Timer-Anzeige in der Kopfzeile (eigener kleiner Sprite, damit die Uhr nicht flackert)
constexpr int kChipW = 92, kChipH = 18;
void chipPos(const Layout& L, bool priv, int& x, int& y);
void drawChip(lgfx::LovyanGFX& sp, const char* chip);

// Untere Leiste: Start / Licht / Musik / Einstellungen
void drawNav(lgfx::LovyanGFX& g, const Layout& L, Pg active);
int navHit(const Layout& L, int x, int y);

// Startseite
void drawReactor(lgfx::LovyanGFX& sp, int size, float t, St st, float level);
void drawWave(lgfx::LovyanGFX& sp, int w, int h, float t, St st, float level, float* smooth, int bars);
void drawTitle(lgfx::LovyanGFX& g, const Layout& L);
void drawStatus(lgfx::LovyanGFX& g, const Layout& L, const char* text, uint16_t color);
bool reactorHit(const Layout& L, int x, int y);

// Seiten mit Listen
void drawPageHead(lgfx::LovyanGFX& g, const Layout& L, const char* title, const char* sub);
void drawMessage(lgfx::LovyanGFX& g, const Layout& L, const char* title, const char* text);
constexpr int kPageHead = 34;   // Höhe der Seitenüberschrift
struct Tile {
  const char* name;
  const char* display;
  bool on;
  uint8_t kind;                 // 0 Schalter, 1 Szene, 2 Medien, 3 Sensor
  bool available;
};
constexpr int kTileH = 50;
void drawTileRow(lgfx::LovyanGFX& g, int w, const Tile& t, bool pressed);

// Musik
struct Player {
  const char* name;
  const char* display;
  bool playing;
  bool available;
  int index, count;
};
void drawMusic(lgfx::LovyanGFX& g, const Layout& L, const Player& p);
int musicHit(const Layout& L, int x, int y);   // 0 zurück, 1 Play/Pause, 2 weiter, 3 leiser, 4 lauter, 5 nächster Player

// Einstellungen
struct SetRow {
  const char* label;
  const char* value;
  int bar;                      // 0–100, -1 = kein Balken
  bool stepper;                 // −/+ Tasten
  bool action;                  // Pfeil rechts
};
constexpr int kSetH = 46;
void drawSettingRow(lgfx::LovyanGFX& g, int w, const SetRow& r);
int stepperHit(int w, int x);   // -1 minus, +1 plus, 0 sonst

// Überlagerungen
void drawAlarm(lgfx::LovyanGFX& g, const Layout& L, const char* label, float t);
int alarmHit(const Layout& L, int x, int y);   // 0 aus, 1 schlummern, -1 nichts
void drawOta(lgfx::LovyanGFX& g, const Layout& L, int pct, const char* version, const char* status, bool error);
void drawSetup(lgfx::LovyanGFX& g, const Layout& L, bool portal, const char* apName, const char* fw);
bool setupHit(const Layout& L, int x, int y);
void drawToast(lgfx::LovyanGFX& g, const Layout& L, const char* text, bool home);
void drawSplash(lgfx::LovyanGFX& g, const Layout& L, const char* fw);

// Text
size_t sanitize(const char* in, char* out, size_t len);    // UTF-8 auf die Zeichen der Schriften abbilden
int drawWrapped(lgfx::LovyanGFX& g, const char* text, int x, int y, int w, int maxLines, int lineH, bool center);
}  // namespace scr
