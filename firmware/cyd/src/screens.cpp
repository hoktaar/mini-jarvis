#include "screens.h"

#include <math.h>
#include <string.h>

#include <string>

#include "fonts.h"

namespace scr {
using G = lgfx::LovyanGFX;

lgfx::VLWfont fClock, fTitle, fLarge, fText, fSmall;
static lgfx::PointerWrapper wClock, wTitle, wLarge, wText, wSmall;

void initFonts() {
  wClock.set(font_clock, sizeof(font_clock));
  wTitle.set(font_title, sizeof(font_title));
  wLarge.set(font_large, sizeof(font_large));
  wText.set(font_text, sizeof(font_text));
  wSmall.set(font_small, sizeof(font_small));
  fClock.loadFont(&wClock);
  fTitle.loadFont(&wTitle);
  fLarge.loadFont(&wLarge);
  fText.loadFont(&wText);
  fSmall.loadFont(&wSmall);
}

uint16_t blend(uint16_t a, uint16_t b, float t) {
  if (t <= 0) return a;
  if (t >= 1) return b;
  int ar = (a >> 11) & 31, ag = (a >> 5) & 63, ab = a & 31;
  int br = (b >> 11) & 31, bgc = (b >> 5) & 63, bb = b & 31;
  int r = ar + (int)((br - ar) * t + 0.5f), g = ag + (int)((bgc - ag) * t + 0.5f), bl = ab + (int)((bb - ab) * t + 0.5f);
  return (uint16_t)((r << 11) | (g << 5) | bl);
}

static const float PI_F = 3.14159265f;

// ---------------------------------------------------------------- Layout
Layout layout(int w, int h) {
  Layout L{};
  L.w = w;
  L.h = h;
  L.land = w > h;
  if (!L.land) {                      // Hochformat 240 × 320
    L.headerH = 60;
    L.navH = 48;
    L.navY = h - L.navH;
    L.rsize = 128;
    L.rcx = w / 2;
    L.rcy = 126;
    L.titleX = w / 2;
    L.titleY = 199;
    L.waveX = 26;
    L.waveY = 211;
    L.waveW = w - 52;
    L.waveH = 22;
    L.textX = 10;
    L.textY = 232;
    L.textW = w - 20;
    L.textLines = 2;
  } else {                            // Querformat 320 × 240
    L.headerH = 34;
    L.navH = 44;
    L.navY = h - L.navH;
    L.rsize = 124;
    L.rcx = 76;
    L.rcy = 115;
    L.titleX = 230;
    L.titleY = 58;
    L.waveX = 152;
    L.waveY = 76;
    L.waveW = 156;
    L.waveH = 22;
    L.textX = 146;
    L.textY = 104;
    L.textW = 168;
    L.textLines = 4;
  }
  L.contentY = L.headerH;
  L.contentH = L.navY - L.headerH;
  return L;
}

// ---------------------------------------------------------------- Text
static bool supported(uint32_t cp) {
  if ((cp >= 0x20 && cp < 0x7F) || (cp >= 0xA1 && cp <= 0xFF)) return true;
  switch (cp) {
    case 0x2013: case 0x2014: case 0x2018: case 0x2019: case 0x201A:
    case 0x201C: case 0x201D: case 0x201E: case 0x2022: case 0x2026: case 0x20AC:
      return true;
    default:
      return false;
  }
}

static size_t put(char* out, size_t pos, size_t len, uint32_t cp) {
  char buf[4];
  size_t n;
  if (cp < 0x80) { buf[0] = (char)cp; n = 1; }
  else if (cp < 0x800) { buf[0] = (char)(0xC0 | (cp >> 6)); buf[1] = (char)(0x80 | (cp & 0x3F)); n = 2; }
  else { buf[0] = (char)(0xE0 | (cp >> 12)); buf[1] = (char)(0x80 | ((cp >> 6) & 0x3F)); buf[2] = (char)(0x80 | (cp & 0x3F)); n = 3; }
  if (pos + n >= len) return pos;
  memcpy(out + pos, buf, n);
  return pos + n;
}

size_t sanitize(const char* in, char* out, size_t len) {
  size_t pos = 0;
  bool space = true;                  // führende Leerzeichen weglassen
  const unsigned char* p = (const unsigned char*)in;
  while (*p && pos + 1 < len) {
    uint32_t cp;
    int extra;
    if (*p < 0x80) { cp = *p; extra = 0; }
    else if ((*p & 0xE0) == 0xC0) { cp = *p & 0x1F; extra = 1; }
    else if ((*p & 0xF0) == 0xE0) { cp = *p & 0x0F; extra = 2; }
    else if ((*p & 0xF8) == 0xF0) { cp = *p & 0x07; extra = 3; }
    else { p++; continue; }
    p++;
    bool bad = false;
    for (int i = 0; i < extra; i++) {
      if ((*p & 0xC0) != 0x80) { bad = true; break; }
      cp = (cp << 6) | (*p & 0x3F);
      p++;
    }
    if (bad) continue;
    if (cp == '\n' || cp == '\t' || cp == '\r' || cp == 0xA0 || cp == 0x2009 || cp == 0x202F) cp = ' ';
    if (cp == 0x2212) cp = '-';
    if (cp == 0x2192) cp = 0xBB;      // → als »
    if (cp == ' ') {
      if (space) continue;
      space = true;
    } else if (!supported(cp)) {
      continue;                       // Emojis u. Ä. weglassen
    } else {
      space = false;
    }
    pos = put(out, pos, len, cp);
  }
  while (pos && out[pos - 1] == ' ') pos--;
  out[pos] = 0;
  return pos;
}

static void popChar(std::string& s) {
  while (!s.empty()) {
    unsigned char c = (unsigned char)s.back();
    s.pop_back();
    if ((c & 0xC0) != 0x80) break;
  }
}

static std::string ellipsize(G& g, std::string s, int w) {
  if (g.textWidth(s.c_str()) <= w) return s;
  const char* dots = "\xE2\x80\xA6";
  while (!s.empty() && g.textWidth((s + dots).c_str()) > w) popChar(s);
  while (!s.empty() && s.back() == ' ') s.pop_back();
  return s + dots;
}

int drawWrapped(G& g, const char* text, int x, int y, int w, int maxLines, int lineH, bool center) {
  std::string rest(text ? text : "");
  int lines = 0;
  g.setTextDatum(center ? textdatum_t::top_center : textdatum_t::top_left);
  while (!rest.empty() && lines < maxLines) {
    std::string line;
    size_t pos = 0;
    while (pos < rest.size()) {
      size_t next = rest.find(' ', pos);
      std::string word = rest.substr(pos, next == std::string::npos ? std::string::npos : next - pos);
      std::string cand = line.empty() ? word : line + " " + word;
      if (g.textWidth(cand.c_str()) <= w) {
        line = cand;
        pos = next == std::string::npos ? rest.size() : next + 1;
      } else {
        if (line.empty()) {           // einzelnes zu langes Wort hart umbrechen
          std::string cut = word;
          while (!cut.empty() && g.textWidth(cut.c_str()) > w) popChar(cut);
          line = cut;
          pos += cut.size();
        }
        break;
      }
    }
    rest = pos < rest.size() ? rest.substr(pos) : std::string();
    if (lines == maxLines - 1 && !rest.empty()) line = ellipsize(g, line + " " + rest, w);
    g.drawString(line.c_str(), center ? x + w / 2 : x, y + lines * lineH);
    lines++;
  }
  return lines;
}

// ---------------------------------------------------------------- Symbole
static void iconWifi(G& g, int x, int y, int rssi) {
  int cx = x + 10, cy = y + 16;
  int bars = rssi == 0 ? 0 : rssi >= -60 ? 3 : rssi >= -72 ? 2 : 1;
  const int radii[3] = {5, 10, 15};
  for (int i = 0; i < 3; i++) {
    uint16_t c = i < bars ? col::ink : col::line;
    g.fillArc(cx, cy, radii[i], radii[i] - 2, 225, 315, c);
  }
  g.fillCircle(cx, cy - 1, 2, bars ? col::ink : col::line);
  if (!bars) {
    g.drawWideLine(x + 3, y + 3, x + 17, y + 17, 1.2f, col::danger);
  }
}

static void iconLock(G& g, int x, int y, uint16_t c) {
  g.drawRoundRect(x, y + 6, 12, 9, 2, c);
  g.drawArc(x + 6, y + 6, 4, 3, 180, 360, c);
}

static void iconTimer(G& g, int x, int y, uint16_t c) {
  g.drawCircle(x + 6, y + 7, 6, c);
  g.drawLine(x + 6, y + 7, x + 6, y + 3, c);
  g.drawLine(x + 6, y + 7, x + 9, y + 9, c);
  g.drawLine(x + 4, y, x + 8, y, c);
}

static void iconHome(G& g, int cx, int cy, uint16_t c) {
  g.drawWideLine(cx - 9, cy, cx, cy - 8, 1.1f, c);
  g.drawWideLine(cx, cy - 8, cx + 9, cy, 1.1f, c);
  g.drawWideLine(cx - 6, cy - 2, cx - 6, cy + 8, 1.1f, c);
  g.drawWideLine(cx + 6, cy - 2, cx + 6, cy + 8, 1.1f, c);
  g.drawWideLine(cx - 6, cy + 8, cx + 6, cy + 8, 1.1f, c);
  g.drawWideLine(cx - 2, cy + 8, cx - 2, cy + 3, 1.0f, c);
  g.drawWideLine(cx + 2, cy + 8, cx + 2, cy + 3, 1.0f, c);
}

static void iconBulb(G& g, int cx, int cy, uint16_t c, bool filled = false) {
  if (filled) g.fillSmoothCircle(cx, cy - 3, 6, c);
  g.drawCircle(cx, cy - 3, 7, c);
  g.drawWideLine(cx - 3, cy + 4, cx - 3, cy + 7, 1.0f, c);
  g.drawWideLine(cx + 3, cy + 4, cx + 3, cy + 7, 1.0f, c);
  g.drawWideLine(cx - 3, cy + 7, cx + 3, cy + 7, 1.0f, c);
  g.drawWideLine(cx - 2, cy + 10, cx + 2, cy + 10, 1.0f, c);
}

static void iconMusic(G& g, int cx, int cy, uint16_t c) {
  g.fillSmoothCircle(cx - 6, cy + 6, 3, c);
  g.fillSmoothCircle(cx + 5, cy + 4, 3, c);
  g.drawWideLine(cx - 3, cy + 6, cx - 3, cy - 7, 1.0f, c);
  g.drawWideLine(cx + 8, cy + 4, cx + 8, cy - 9, 1.0f, c);
  g.drawWideLine(cx - 3, cy - 7, cx + 8, cy - 9, 1.6f, c);
}

static void iconGear(G& g, int cx, int cy, uint16_t c) {
  for (int i = 0; i < 8; i++) {
    float a = i * PI_F / 4;
    g.drawWideLine(cx + (int)(cosf(a) * 6), cy + (int)(sinf(a) * 6), cx + (int)(cosf(a) * 9.5f), cy + (int)(sinf(a) * 9.5f), 1.6f, c);
  }
  g.drawCircle(cx, cy, 6, c);
  g.drawCircle(cx, cy, 7, c);
  g.drawCircle(cx, cy, 3, c);
}

static void iconPlay(G& g, int cx, int cy, int s, uint16_t c) { g.fillTriangle(cx - s / 2, cy - s, cx - s / 2, cy + s, cx + s, cy, c); }

static void iconPause(G& g, int cx, int cy, int s, uint16_t c) {
  g.fillRect(cx - s, cy - s, s * 2 / 3, s * 2, c);
  g.fillRect(cx + s / 3, cy - s, s * 2 / 3, s * 2, c);
}

static void iconSkip(G& g, int cx, int cy, int s, uint16_t c, bool forward) {
  int d = forward ? 1 : -1;
  g.fillTriangle(cx - d * s, cy - s, cx - d * s, cy + s, cx, cy, c);
  g.fillTriangle(cx, cy - s, cx, cy + s, cx + d * s, cy, c);
  g.fillRect(forward ? cx + s : cx - s - 2, cy - s, 2, s * 2, c);
}

static void iconGauge(G& g, int cx, int cy, uint16_t c) {
  g.drawArc(cx, cy + 4, 9, 8, 180, 360, c);
  g.drawWideLine(cx, cy + 4, cx + 5, cy - 2, 1.2f, c);
}

// ---------------------------------------------------------------- Kopfzeile
void drawHeader(G& g, const Layout& L, const Header& h) {
  g.fillRect(0, 0, L.w, L.headerH, col::bg);
  g.setTextDatum(textdatum_t::top_left);
  if (!L.land) {
    g.setFont(&fClock);
    g.setTextColor(col::ink, col::bg);
    g.drawString(h.time, 12, -1);
    g.setFont(&fSmall);
    g.setTextColor(col::ink2, col::bg);
    g.drawString(h.date, 14, 45);
  } else {
    g.setFont(&fLarge);
    g.setTextColor(col::ink, col::bg);
    g.drawString(h.time, 10, 6);
    int tw = g.textWidth(h.time);
    g.setFont(&fSmall);
    g.setTextColor(col::ink2, col::bg);
    g.drawString(h.date, 18 + tw, 11);
  }
  // rechts: WLAN, Verbindung zu Jarvis, Privatmodus, nächster Timer
  int x = L.w - 30;
  iconWifi(g, x, 6, h.rssi);
  g.fillCircle(L.w - 7, 8, 3, h.online ? col::ok : h.rssi ? col::warn : col::danger);
  if (h.priv) iconLock(g, x - 20, 6, col::warn);
  if (h.chip && *h.chip) {
    int cx, cy;
    chipPos(L, h.priv, cx, cy);
    g.setClipRect(cx, cy, kChipW, kChipH);
    g.setFont(&fSmall);
    g.setTextColor(col::accent, col::bg);
    g.setTextDatum(textdatum_t::top_right);
    g.drawString(h.chip, cx + kChipW - 1, cy + 1);
    iconTimer(g, cx + kChipW - 1 - g.textWidth(h.chip) - 17, cy + 2, col::accent);
    g.clearClipRect();
  }
  g.drawFastHLine(0, L.headerH - 1, L.w, L.land ? col::line : col::bg);
}

void chipPos(const Layout& L, bool priv, int& x, int& y) {
  if (L.land) {
    x = L.w - 30 - (priv ? 26 : 8) - kChipW;
    y = 10;
  } else {
    x = L.w - 10 - kChipW;
    y = 35;
  }
}

void drawChip(G& sp, const char* chip) {
  sp.fillScreen(col::bg);
  if (!chip || !*chip) return;
  sp.setFont(&fSmall);
  sp.setTextColor(col::accent, col::bg);
  sp.setTextDatum(textdatum_t::top_right);
  sp.drawString(chip, kChipW - 1, 1);
  iconTimer(sp, kChipW - 1 - sp.textWidth(chip) - 17, 2, col::accent);
}

// ---------------------------------------------------------------- Navigation
static const char* const NAV_LABELS[4] = {"Start", "Licht", "Musik", "Einstellungen"};

void drawNav(G& g, const Layout& L, Pg active) {
  g.fillRect(0, L.navY, L.w, L.navH, col::bg);
  g.drawFastHLine(0, L.navY, L.w, col::line);
  int bw = L.w / 4;
  g.setFont(&fSmall);
  for (int i = 0; i < 4; i++) {
    bool on = (int)active == i;
    int bx = i * bw;
    uint16_t c = on ? col::accent : col::muted;
    uint16_t fill = on ? col::panel2 : col::bg;
    if (on) g.fillRoundRect(bx + 3, L.navY + 4, bw - 6, L.navH - 7, 7, fill);
    int cx = bx + bw / 2, cy = L.navY + (L.land ? 13 : 15);
    switch (i) {
      case 0: iconHome(g, cx, cy, c); break;
      case 1: iconBulb(g, cx, cy, c); break;
      case 2: iconMusic(g, cx, cy, c); break;
      default: iconGear(g, cx, cy, c); break;
    }
    const char* label = NAV_LABELS[i];
    if (i == 3 && g.textWidth(label) > bw - 6) label = "Einstell.";
    g.setTextColor(c, fill);
    g.setTextDatum(textdatum_t::top_center);
    int ly = L.navY + (L.land ? 24 : 27);
    g.drawString(label, cx, ly);
    if (on) {
      int lw = g.textWidth(label);
      g.fillRect(cx - lw / 2, L.navY + L.navH - 4, lw, 2, col::accent);
    }
  }
}

int navHit(const Layout& L, int x, int y) {
  if (y < L.navY || y >= L.h) return -1;
  int i = x / (L.w / 4);
  return i > 3 ? 3 : i;
}

// ---------------------------------------------------------------- Reaktor
static void stateColors(St st, uint16_t& c1, uint16_t& c2) {
  switch (st) {
    case St::Offline: c1 = rgb(72, 97, 127); c2 = rgb(44, 66, 96); break;
    case St::Alarm: c1 = col::warn; c2 = rgb(196, 106, 0); break;
    default: c1 = col::accent; c2 = col::accent2; break;
  }
}

static uint16_t coreColor(St st, float f) {   // f = 0 Mitte … 1 Rand
  uint16_t a, b, c, d;
  if (st == St::Alarm) { a = rgb(255, 246, 220); b = rgb(255, 214, 128); c = col::warn; d = rgb(143, 90, 10); }
  else if (st == St::Offline) { a = rgb(170, 186, 204); b = rgb(110, 132, 160); c = rgb(62, 84, 112); d = rgb(30, 44, 66); }
  else { a = rgb(232, 251, 255); b = rgb(127, 228, 255); c = col::accent2; d = rgb(10, 59, 143); }
  if (f < 0.35f) return blend(a, b, f / 0.35f);
  if (f < 0.75f) return blend(b, c, (f - 0.35f) / 0.4f);
  return blend(c, d, (f - 0.75f) / 0.25f);
}

void drawReactor(G& sp, int size, float t, St st, float level) {
  uint16_t c1, c2;
  stateColors(st, c1, c2);
  float k = size / 128.0f;
  int c = size / 2;
  sp.fillScreen(col::bg);

  float speed = st == St::Offline ? 0 : st == St::Listening ? 45 : st == St::Thinking ? 120 : st == St::Speaking ? 36 : st == St::Alarm ? 60 : 15;
  float rot = fmodf(t * speed, 360.0f);

  // weicher Lichthof
  for (int r = (int)(60 * k); r > (int)(24 * k); r -= 2) {
    float a = 0.16f * (1.0f - (r - 24 * k) / (36 * k));
    sp.fillCircle(c, c, r, blend(col::bg, c2, a));
  }
  // Punktring außen
  for (int i = 0; i < 72; i++) {
    float a = (i * 5 + rot * 0.25f) * PI_F / 180;
    sp.fillCircle(c + (int)lroundf(cosf(a) * 61 * k), c + (int)lroundf(sinf(a) * 61 * k), 1, blend(col::bg, c1, i % 6 == 0 ? 0.9f : 0.45f));
  }
  // Skala
  for (int i = 0; i < 120; i++) {
    float a = i * 3 * PI_F / 180;
    float r0 = (i % 10 == 0 ? 52 : 54) * k, r1 = 57 * k;
    sp.drawLine(c + (int)(cosf(a) * r0), c + (int)(sinf(a) * r0), c + (int)(cosf(a) * r1), c + (int)(sinf(a) * r1), blend(col::bg, c1, 0.28f));
  }
  // drei leuchtende Bögen (drehen sich)
  const float arcs[3][2] = {{0, 82}, {118, 168}, {205, 300}};
  for (auto& a : arcs) {
    sp.fillArc(c, c, (int)(41 * k), (int)(51 * k), a[0] + rot, a[1] + rot, blend(col::bg, c1, 0.22f));
  }
  for (auto& a : arcs) {
    sp.fillArc(c, c, (int)(44 * k), (int)(48 * k), a[0] + rot, a[1] + rot, c1);
  }
  // gestrichelter Ring (gegenläufig)
  for (int i = 0; i < 10; i++) {
    float a0 = i * 36 - rot * 1.4f;
    sp.fillArc(c, c, (int)(35 * k), (int)(38 * k), a0, a0 + 24, blend(col::bg, c2, 0.9f));
  }
  sp.drawCircle(c, c, (int)(31 * k), blend(col::bg, c2, 0.55f));

  // Kern mit Leuchten
  float breathe = st == St::Idle ? 0.04f * sinf(t * 1.6f) : 0;
  float rc = 21 * k * (0.92f + level * 0.35f + breathe);
  if (rc > 28 * k) rc = 28 * k;
  for (int i = 8; i >= 1; i--) sp.fillCircle(c, c, (int)(rc + i), blend(col::bg, c1, 0.06f * (9 - i)));
  sp.fillArc(c, c, (int)(rc + 2), (int)(rc + 4), 0, 360, st == St::Listening ? c1 : blend(col::bg, c1, 0.7f));
  sp.fillSmoothCircle(c, c, (int)rc, coreColor(st, 1.0f));
  for (int r = (int)rc - 1; r >= 1; r--) sp.fillCircle(c, c, r, coreColor(st, (float)r / rc));
}

void drawWave(G& sp, int w, int h, float t, St st, float level, float* smooth, int bars) {
  uint16_t c1, c2;
  stateColors(st, c1, c2);
  sp.fillScreen(col::bg);
  bool active = st == St::Listening || st == St::Speaking;
  float base = st == St::Thinking ? 0.22f : active ? 0.12f : st == St::Offline ? 0.02f : 0.05f;
  float amp = base + (active ? level * 2.6f : 0);
  if (amp > 1) amp = 1;
  float gap = (float)w / bars;
  int mid = h / 2;
  for (int i = 0; i < bars; i++) {
    float d = fabsf(i - (bars - 1) / 2.0f) / (bars / 2.0f);
    float env = powf(1 - d, 1.6f);
    float noise = 0.55f + 0.45f * sinf(t * 7.8f + i * 0.9f) * sinf(t * 4.2f + i * 0.37f);
    float target = amp * env * noise;
    if (target < 0.03f) target = 0.03f;
    smooth[i] += (target - smooth[i]) * 0.3f;
    int bh = (int)(smooth[i] * h * 0.95f);
    int x = (int)(i * gap + gap / 2);
    uint16_t c = blend(col::bg, c1, 0.35f + 0.65f * env);
    if (bh <= 3) {
      sp.fillCircle(x, mid, 1, c);
    } else {
      int bw = gap * 0.42f < 2 ? 2 : (int)(gap * 0.42f);
      sp.fillRect(x - bw / 2, mid - bh / 2, bw, bh, c);
    }
  }
}

void drawTitle(G& g, const Layout& L) {
  const char* letters = "JARVIS";
  g.setFont(&fTitle);
  g.setTextDatum(textdatum_t::middle_center);
  int spacing = L.land ? 20 : 22;
  int x0 = L.titleX - spacing * 5 / 2;
  g.fillRect(L.titleX - spacing * 3 - 4, L.titleY - 16, spacing * 6 + 8, 32, col::bg);
  for (int i = 0; i < 6; i++) {
    char s[2] = {letters[i], 0};
    // leichter Schein: Kopie in Akzentfarbe, darüber die helle Schrift
    g.setTextColor(blend(col::bg, col::accent2, 0.55f));
    g.drawString(s, x0 + i * spacing, L.titleY + 1);
    g.setTextColor(col::ink);
    g.drawString(s, x0 + i * spacing, L.titleY);
  }
}

void drawStatus(G& g, const Layout& L, const char* text, uint16_t color) {
  g.fillRect(L.textX, L.textY, L.textW, L.textLines * 19, col::bg);
  g.setFont(&fText);
  g.setTextColor(color, col::bg);
  drawWrapped(g, text, L.textX, L.textY, L.textW, L.textLines, 19, true);
}

bool reactorHit(const Layout& L, int x, int y) {
  int dx = x - L.rcx, dy = y - L.rcy;
  return dx * dx + dy * dy <= (L.rsize / 2 + 8) * (L.rsize / 2 + 8);
}

// ---------------------------------------------------------------- Seiten
void drawPageHead(G& g, const Layout& L, const char* title, const char* sub) {
  g.fillRect(0, L.contentY, L.w, kPageHead, col::bg);
  g.setFont(&fLarge);
  g.setTextColor(col::ink, col::bg);
  g.setTextDatum(textdatum_t::middle_left);
  g.drawString(title, 12, L.contentY + kPageHead / 2);
  if (sub && *sub) {
    g.setFont(&fSmall);
    g.setTextColor(col::muted, col::bg);
    g.setTextDatum(textdatum_t::middle_right);
    g.drawString(sub, L.w - 12, L.contentY + kPageHead / 2 + 1);
  }
  g.fillRect(12, L.contentY + kPageHead - 2, 26, 2, col::accent);
}

void drawMessage(G& g, const Layout& L, const char* title, const char* text) {
  int y = L.contentY + kPageHead + 14;
  g.fillRect(0, L.contentY + kPageHead, L.w, L.contentH - kPageHead, col::bg);
  g.setFont(&fText);
  g.setTextColor(col::ink, col::bg);
  int n = drawWrapped(g, title, 16, y, L.w - 32, 2, 20, true);
  g.setFont(&fSmall);
  g.setTextColor(col::muted, col::bg);
  drawWrapped(g, text, 16, y + n * 20 + 8, L.w - 32, 5, 16, true);
}

static void toggleSwitch(G& g, int x, int y, bool on, bool enabled) {
  uint16_t track = !enabled ? col::line : on ? col::accent2 : rgb(46, 66, 96);
  g.fillSmoothRoundRect(x, y, 40, 22, 11, track);
  g.fillSmoothCircle(on ? x + 29 : x + 11, y + 11, 8, enabled ? col::ink : col::muted);
}

void drawTileRow(G& g, int w, const Tile& t, bool pressed) {
  g.fillScreen(col::bg);
  uint16_t fill = pressed ? col::panel2 : col::panel;
  g.fillSmoothRoundRect(6, 3, w - 12, kTileH - 6, 8, fill);
  g.drawRoundRect(6, 3, w - 12, kTileH - 6, 8, t.on ? blend(col::line, col::accent, 0.5f) : col::line);
  uint16_t ic = !t.available ? col::muted : t.on ? rgb(255, 215, 106) : col::ink2;
  int cy = kTileH / 2;
  switch (t.kind) {
    case 0: iconBulb(g, 26, cy, ic, t.on && t.available); break;
    case 1: iconPlay(g, 26, cy, 7, ic); break;
    case 2: iconMusic(g, 26, cy, ic); break;
    default: iconGauge(g, 26, cy, ic); break;
  }
  int right = t.kind == 0 ? 56 : t.kind == 1 ? 34 : 14;
  g.setTextDatum(textdatum_t::top_left);
  g.setFont(&fText);
  g.setTextColor(t.available ? col::ink : col::muted, fill);
  g.drawString(ellipsize(g, t.name, w - 48 - right).c_str(), 46, 7);
  g.setFont(&fSmall);
  g.setTextColor(t.on ? col::ink2 : col::muted, fill);
  g.drawString(ellipsize(g, t.display, w - 48 - right).c_str(), 46, 27);
  if (t.kind == 0) toggleSwitch(g, w - 54, cy - 11, t.on, t.available);
  else if (t.kind == 1) iconPlay(g, w - 24, cy, 6, t.available ? col::accent : col::muted);
}

// ---------------------------------------------------------------- Musik
struct MusicGeo {
  int cy, cxPrev, cxPlay, cxNext, r;
  int volY, volH, minusX, plusX, volW;
};

static MusicGeo musicGeo(const Layout& L) {
  MusicGeo m{};
  m.r = L.land ? 22 : 25;
  m.cy = L.contentY + (L.land ? 104 : 136);
  int d = L.land ? 64 : 72;
  m.cxPlay = L.w / 2;
  m.cxPrev = m.cxPlay - d;
  m.cxNext = m.cxPlay + d;
  m.volH = 32;
  m.volY = L.navY - m.volH - (L.land ? 4 : 8);
  m.volW = 62;
  m.minusX = 14;
  m.plusX = L.w - 14 - m.volW;
  if (L.land) m.volY = m.cy - m.volH / 2;  // im Querformat neben den Tasten
  return m;
}

void drawMusic(G& g, const Layout& L, const Player& p) {
  g.fillRect(0, L.contentY + kPageHead, L.w, L.contentH - kPageHead, col::bg);
  MusicGeo m = musicGeo(L);
  int y = L.contentY + kPageHead + 6;
  g.setFont(&fText);
  g.setTextColor(col::ink, col::bg);
  g.setTextDatum(textdatum_t::top_center);
  g.drawString(ellipsize(g, p.name, L.w - 70).c_str(), L.w / 2, y);
  if (p.count > 1) {
    g.fillTriangle(16, y + 9, 24, y + 3, 24, y + 15, col::accent);
    g.fillTriangle(L.w - 16, y + 9, L.w - 24, y + 3, L.w - 24, y + 15, col::accent);
  }
  g.setFont(&fSmall);
  g.setTextColor(p.playing ? col::accent : col::muted, col::bg);
  drawWrapped(g, p.display, 20, y + 22, L.w - 40, L.land ? 1 : 2, 16, true);

  uint16_t en = p.available ? col::ink : col::muted;
  g.drawCircle(m.cxPrev, m.cy, m.r - 4, col::line);
  iconSkip(g, m.cxPrev, m.cy, 7, en, false);
  g.fillSmoothCircle(m.cxPlay, m.cy, m.r, p.available ? col::accent2 : col::line);
  if (p.playing) iconPause(g, m.cxPlay, m.cy, 8, col::ink);
  else iconPlay(g, m.cxPlay + 2, m.cy, 9, col::ink);
  g.drawCircle(m.cxNext, m.cy, m.r - 4, col::line);
  iconSkip(g, m.cxNext, m.cy, 7, en, true);

  if (!L.land) {
    g.fillSmoothRoundRect(m.minusX, m.volY, m.volW, m.volH, 8, col::panel);
    g.fillSmoothRoundRect(m.plusX, m.volY, m.volW, m.volH, 8, col::panel);
    g.setFont(&fSmall);
    g.setTextColor(col::muted, col::bg);
    g.setTextDatum(textdatum_t::middle_center);
    g.drawString("Lautstärke", L.w / 2, m.volY + m.volH / 2);
  } else {
    g.fillSmoothRoundRect(m.minusX, m.volY, 40, m.volH, 8, col::panel);
    g.fillSmoothRoundRect(L.w - 54, m.volY, 40, m.volH, 8, col::panel);
  }
  int mx = L.land ? m.minusX + 20 : m.minusX + m.volW / 2;
  int px = L.land ? L.w - 34 : m.plusX + m.volW / 2;
  int vy = m.volY + m.volH / 2;
  g.fillRect(mx - 7, vy - 1, 14, 3, en);
  g.fillRect(px - 7, vy - 1, 14, 3, en);
  g.fillRect(px - 1, vy - 7, 3, 14, en);
}

int musicHit(const Layout& L, int x, int y) {
  MusicGeo m = musicGeo(L);
  int head = L.contentY + kPageHead;
  if (y >= head && y < head + 24) {
    if (x < 50 || x > L.w - 50) return 5;
  }
  auto inCircle = [&](int cx) { return (x - cx) * (x - cx) + (y - m.cy) * (y - m.cy) <= (m.r + 8) * (m.r + 8); };
  if (inCircle(m.cxPrev)) return 0;
  if (inCircle(m.cxPlay)) return 1;
  if (inCircle(m.cxNext)) return 2;
  if (y >= m.volY - 4 && y <= m.volY + m.volH + 4) {
    if (L.land) {
      if (x >= m.minusX && x <= m.minusX + 44) return 3;
      if (x >= L.w - 58) return 4;
    } else {
      if (x >= m.minusX && x <= m.minusX + m.volW) return 3;
      if (x >= m.plusX && x <= m.plusX + m.volW) return 4;
    }
  }
  return -1;
}

// ---------------------------------------------------------------- Einstellungen
void drawSettingRow(G& g, int w, const SetRow& r) {
  g.fillScreen(col::bg);
  g.drawFastHLine(10, kSetH - 1, w - 20, col::line);
  g.setTextDatum(textdatum_t::top_left);
  g.setFont(&fText);
  g.setTextColor(col::ink, col::bg);
  int right = r.stepper ? 100 : r.action ? 26 : 12;
  g.drawString(ellipsize(g, r.label, w - 24 - right).c_str(), 12, 4);
  if (r.value && *r.value) {
    g.setFont(&fSmall);
    g.setTextColor(r.action && !r.stepper ? col::accent : col::muted, col::bg);
    g.drawString(ellipsize(g, r.value, w - 24 - right).c_str(), 12, 24);
  }
  if (r.bar >= 0) {
    int bx = 12 + 54, bw = w - 24 - right - 54;
    if (bw > 20) {
      g.fillRoundRect(bx, 30, bw, 4, 2, col::line);
      g.fillRoundRect(bx, 30, bw * r.bar / 100, 4, 2, col::accent);
    }
  }
  if (r.stepper) {
    g.fillSmoothRoundRect(w - 92, 7, 38, 32, 8, col::panel2);
    g.fillSmoothRoundRect(w - 48, 7, 38, 32, 8, col::panel2);
    g.fillRect(w - 79, 22, 12, 3, col::ink);
    g.fillRect(w - 35, 22, 12, 3, col::ink);
    g.fillRect(w - 30, 17, 3, 12, col::ink);
  } else if (r.action) {
    g.drawWideLine(w - 20, 17, w - 14, 23, 1.2f, col::muted);
    g.drawWideLine(w - 14, 23, w - 20, 29, 1.2f, col::muted);
  }
}

int stepperHit(int w, int x) {
  if (x >= w - 96 && x < w - 51) return -1;
  if (x >= w - 51) return 1;
  return 0;
}

// ---------------------------------------------------------------- Überlagerungen
struct Btn { int x, y, w, h; };
static void alarmButtons(const Layout& L, Btn& off, Btn& snooze) {
  if (!L.land) {
    off = {14, L.textY - 6, L.w - 28, 40};
    snooze = {14, L.navY + 6, L.w - 28, L.navH - 10};
  } else {
    off = {L.textX + 4, L.textY - 4, L.textW - 10, 42};
    snooze = {L.textX + 4, L.textY + 46, L.textW - 10, 34};
  }
}

void drawAlarm(G& g, const Layout& L, const char* label, float t) {
  (void)t;
  Btn off, snooze;
  alarmButtons(L, off, snooze);
  g.setFont(&fLarge);
  g.setTextColor(col::warn, col::bg);
  g.setTextDatum(textdatum_t::middle_center);
  g.fillRect(L.land ? L.textX : 0, L.titleY - 16, L.land ? L.textW : L.w, 32, col::bg);
  g.drawString(ellipsize(g, label, L.land ? L.textW - 8 : L.w - 20).c_str(), L.titleX, L.titleY);
  g.fillSmoothRoundRect(off.x, off.y, off.w, off.h, 10, col::warn);
  g.setFont(&fLarge);
  g.setTextColor(col::bg, col::warn);
  g.drawString("Ausschalten", off.x + off.w / 2, off.y + off.h / 2);
  g.fillRect(snooze.x - 2, snooze.y - 2, snooze.w + 4, snooze.h + 4, col::bg);
  g.drawRoundRect(snooze.x, snooze.y, snooze.w, snooze.h, 10, col::warn);
  g.setFont(&fSmall);
  g.setTextColor(col::warn, col::bg);
  g.drawString("5 Minuten schlummern", snooze.x + snooze.w / 2, snooze.y + snooze.h / 2);
}

int alarmHit(const Layout& L, int x, int y) {
  Btn off, snooze;
  alarmButtons(L, off, snooze);
  if (x >= off.x && x < off.x + off.w && y >= off.y - 6 && y < off.y + off.h + 6) return 0;
  if (x >= snooze.x && x < snooze.x + snooze.w && y >= snooze.y - 4 && y < snooze.y + snooze.h + 4) return 1;
  return -1;
}

void drawOta(G& g, const Layout& L, int pct, const char* version, const char* status, bool error) {
  g.fillScreen(col::bg);
  int cy = L.h / 2;
  g.setTextDatum(textdatum_t::middle_center);
  g.setFont(&fLarge);
  g.setTextColor(error ? col::danger : col::ink, col::bg);
  g.drawString(error ? "Update fehlgeschlagen" : "Update wird installiert", L.w / 2, cy - 54);
  g.setFont(&fSmall);
  g.setTextColor(col::muted, col::bg);
  if (version && *version) {
    char v[40];
    snprintf(v, sizeof(v), "Version %s", version);
    g.drawString(v, L.w / 2, cy - 30);
  }
  int bw = L.w - 48, bx = 24;
  g.fillSmoothRoundRect(bx, cy - 6, bw, 12, 6, col::line);
  if (pct > 0) g.fillSmoothRoundRect(bx, cy - 6, bw * (pct > 100 ? 100 : pct) / 100, 12, 6, error ? col::danger : col::accent);
  char p[8];
  snprintf(p, sizeof(p), "%d %%", pct);
  g.setFont(&fText);
  g.setTextColor(col::ink, col::bg);
  g.drawString(p, L.w / 2, cy + 24);
  g.setFont(&fSmall);
  g.setTextColor(error ? col::danger : col::muted, col::bg);
  drawWrapped(g, status, 16, cy + 42, L.w - 32, 3, 16, true);
}

static Btn setupButton(const Layout& L) { return L.land ? Btn{60, L.navY - 50, L.w - 120, 32} : Btn{24, L.navY - 58, L.w - 48, 36}; }

void drawSetup(G& g, const Layout& L, bool portal, const char* apName, const char* fw) {
  g.fillRect(0, L.contentY, L.w, L.contentH, col::bg);
  int y = L.contentY + 8;
  g.setFont(&fLarge);
  g.setTextColor(col::accent, col::bg);
  g.setTextDatum(textdatum_t::top_center);
  g.drawString("Einrichtung", L.w / 2, y);
  g.setFont(&fSmall);
  g.setTextColor(col::ink2, col::bg);
  char buf[160];
  int lines = 0;
  if (portal) {
    snprintf(buf, sizeof(buf), "Verbinde dein Handy mit dem WLAN „%s“. Die Einrichtungsseite öffnet sich dann von selbst.", apName);
    lines = drawWrapped(g, buf, 14, y + 32, L.w - 28, 4, 16, true);
    g.setTextColor(col::muted, col::bg);
    drawWrapped(g, "Dort WLAN, Jarvis-Server und Geräte-Token eintragen.", 14, y + 40 + lines * 16, L.w - 28, 3, 16, true);
  } else {
    lines = drawWrapped(g, "Am Computer: Jarvis-Verwaltung » Firmware » „CYD per USB einrichten“ und dieses Display per USB anschließen.", 14, y + 32, L.w - 28, 5, 16, true);
    g.setTextColor(col::muted, col::bg);
    if (!L.land) drawWrapped(g, "Ohne Computer: Hotspot starten und mit dem Handy verbinden.", 14, y + 40 + lines * 16, L.w - 28, 3, 16, true);
    Btn b = setupButton(L);
    g.fillSmoothRoundRect(b.x, b.y, b.w, b.h, 10, col::accent2);
    g.setFont(&fText);
    g.setTextColor(col::ink, col::accent2);
    g.setTextDatum(textdatum_t::middle_center);
    g.drawString("Hotspot starten", b.x + b.w / 2, b.y + b.h / 2);
  }
  g.setFont(&fSmall);
  g.setTextColor(col::line, col::bg);
  g.setTextDatum(textdatum_t::bottom_center);
  snprintf(buf, sizeof(buf), "Firmware %s", fw);
  g.drawString(buf, L.w / 2, L.navY - 3);
}

bool setupHit(const Layout& L, int x, int y) {
  Btn b = setupButton(L);
  return x >= b.x && x < b.x + b.w && y >= b.y - 6 && y < b.y + b.h + 6;
}

void drawToast(G& g, const Layout& L, const char* text, bool home) {
  // Startseite: deckt den Statustext ab; andere Seiten: unten über der Navigation
  int x = home ? L.textX : 10, w = home ? L.textW : L.w - 20;
  int h = home ? L.textLines * 19 + 2 : 34;
  int y = home ? L.textY - 1 : L.navY - h - 6;
  g.fillRect(x, y, w, h, col::bg);
  g.fillSmoothRoundRect(x, y, w, h, 9, col::panel2);
  g.drawRoundRect(x, y, w, h, 9, col::accent);
  g.setFont(&fSmall);
  g.setTextColor(col::ink, col::panel2);
  int lines = h >= 34 ? 2 : 1;
  int ty = y + (h - lines * 16) / 2;
  drawWrapped(g, text, x + 8, ty, w - 16, lines, 16, true);
}

void drawSplash(G& g, const Layout& L, const char* fw) {
  g.fillScreen(col::bg);
  Layout l = L;
  l.titleY = L.h / 2 - 6;
  l.titleX = L.w / 2;
  drawTitle(g, l);
  g.setFont(&fSmall);
  g.setTextColor(col::muted, col::bg);
  g.setTextDatum(textdatum_t::top_center);
  char v[32];
  snprintf(v, sizeof(v), "Firmware %s", fw);
  g.drawString(v, L.w / 2, L.h / 2 + 18);
}
}  // namespace scr
