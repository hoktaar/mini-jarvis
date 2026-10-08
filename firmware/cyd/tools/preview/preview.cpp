// Rendert die CYD-Bildschirme auf dem PC (LovyanGFX ohne Display) als PPM – zum Prüfen des Layouts.
//   ./build.sh /pfad/zu/LovyanGFX && ./preview out/          (alle Bildschirme)
//                                    ./preview out/ anim     (Bildfolge für eine Animation)
#include <math.h>
#include <stdio.h>
#include <string.h>

#include <string>

#include "../../src/screens.h"

using namespace scr;

static void save(LGFX_Sprite& s, const std::string& path) {
  FILE* f = fopen(path.c_str(), "wb");
  fprintf(f, "P6\n%d %d\n255\n", s.width(), s.height());
  for (int y = 0; y < s.height(); y++)
    for (int x = 0; x < s.width(); x++) {
      auto c = s.readPixelRGB(x, y);
      fputc(c.R8(), f); fputc(c.G8(), f); fputc(c.B8(), f);
    }
  fclose(f);
}

static void home(LGFX_Sprite& scr, const Layout& L, St st, float level, const char* text, Pg pg, const char* chip) {
  scr.fillScreen(col::bg);
  Header h{"14:26", "So, 27. Apr.", -58, st != St::Offline, false, chip};
  drawHeader(scr, L, h);
  LGFX_Sprite r(&scr);
  r.setColorDepth(16);
  r.createSprite(L.rsize, L.rsize);
  drawReactor(r, L.rsize, 3.2f, st, level);
  r.pushSprite(L.rcx - L.rsize / 2, L.rcy - L.rsize / 2);
  drawTitle(scr, L);
  LGFX_Sprite w(&scr);
  w.setColorDepth(16);
  w.createSprite(L.waveW, L.waveH);
  float smooth[40] = {0};
  for (int i = 0; i < 20; i++) drawWave(w, L.waveW, L.waveH, 2.0f + i * 0.05f, st, level, smooth, 34);
  w.pushSprite(L.waveX, L.waveY);
  drawStatus(scr, L, text, st == St::Speaking ? col::ink : col::ink2);
  drawNav(scr, L, pg);
}

// Bildfolge „Jarvis in Aktion“ (Hochformat): bereit → hört zu → denkt → spricht → bereit
static void anim(const std::string& out) {
  Layout L = layout(240, 320);
  LGFX_Sprite scr;
  scr.setColorDepth(16);
  scr.createSprite(240, 320);
  LGFX_Sprite r(&scr), w(&scr);
  r.setColorDepth(16);
  r.createSprite(L.rsize, L.rsize);
  w.setColorDepth(16);
  w.createSprite(L.waveW, L.waveH);
  float smooth[40] = {0};
  struct Phase { St st; float secs; const char* text; uint16_t color; };
  const Phase phases[] = {
      {St::Idle, 1.6f, "Sag „Hey Jarvis“ oder tippe auf den Kreis", col::muted},
      {St::Listening, 2.4f, "Ich höre dir zu …", col::ink2},
      {St::Thinking, 1.3f, "Einen Moment …", col::ink2},
      {St::Speaking, 3.4f, "Morgen überwiegend klar, 10 bis 21 Grad. Kein Schirm nötig.", col::ink},
      {St::Idle, 1.0f, "Sag „Hey Jarvis“ oder tippe auf den Kreis", col::muted},
  };
  const float fps = 15;
  int n = 0;
  float t = 0;
  for (const Phase& ph : phases) {
    for (int f = 0; f < (int)(ph.secs * fps); f++, n++, t += 1 / fps) {
      float level = ph.st == St::Listening ? 0.12f + 0.16f * fabsf(sinf(t * 7.3f) * sinf(t * 2.1f))
                    : ph.st == St::Speaking ? 0.08f + 0.14f * fabsf(sinf(t * 11.0f) * sinf(t * 3.3f)) : 0;
      scr.fillScreen(col::bg);
      drawHeader(scr, L, Header{"07:42", "Do, 9. Okt.", -57, true, false, "8:59"});
      drawReactor(r, L.rsize, t, ph.st, level);
      r.pushSprite(L.rcx - L.rsize / 2, L.rcy - L.rsize / 2);
      drawTitle(scr, L);
      drawWave(w, L.waveW, L.waveH, t, ph.st, level, smooth, 34);
      w.pushSprite(L.waveX, L.waveY);
      drawStatus(scr, L, ph.text, ph.color);
      drawNav(scr, L, Pg::Home);
      char name[32];
      snprintf(name, sizeof(name), "/anim_%03d.ppm", n);
      save(scr, out + name);
    }
  }
}

int main(int argc, char** argv) {
  std::string out = argc > 1 ? argv[1] : ".";
  initFonts();
  if (argc > 2 && std::string(argv[2]) == "anim") {
    anim(out);
    puts("ok");
    return 0;
  }
  for (int land = 0; land < 2; land++) {
    int W = land ? 320 : 240, H = land ? 240 : 320;
    Layout L = layout(W, H);
    std::string sfx = land ? "-quer" : "-hoch";
    LGFX_Sprite scr;
    scr.setColorDepth(16);
    scr.createSprite(W, H);

    home(scr, L, St::Listening, 0.25f, "Ich höre dir zu …", Pg::Home, nullptr);
    save(scr, out + "/home-listening" + sfx + ".ppm");
    home(scr, L, St::Speaking, 0.2f, "Morgen wird es in Berlin sonnig bei bis zu 19 Grad. Regen ist nicht in Sicht – kein Schirm nötig.", Pg::Home, "4:59");
    save(scr, out + "/home-speaking" + sfx + ".ppm");
    home(scr, L, St::Offline, 0, "Jarvis-Server nicht erreichbar (192.168.1.144:8080)", Pg::Home, nullptr);
    save(scr, out + "/home-offline" + sfx + ".ppm");

    // Licht
    scr.fillScreen(col::bg);
    drawHeader(scr, L, Header{"14:26", "So, 27. Apr.", -66, true, true, nullptr});
    drawPageHead(scr, L, "Licht", "3 von 5 an");
    Tile tiles[] = {{"Licht Wohnzimmer", "an", true, 0, true}, {"Stehlampe Leseecke", "aus", false, 0, true},
                    {"Filmabend", "Szene starten", false, 1, true}, {"Kaffeemaschine", "nicht erreichbar", false, 0, false},
                    {"Außentemperatur", "12,4 °C", false, 3, true}};
    LGFX_Sprite row(&scr);
    row.setColorDepth(16);
    row.createSprite(W, kTileH);
    int y = L.contentY + kPageHead;
    scr.setClipRect(0, y, W, L.navY - y);
    for (auto& t : tiles) {
      drawTileRow(row, W, t, &t == &tiles[1]);
      row.pushSprite(0, y);
      y += kTileH;
    }
    scr.clearClipRect();
    drawNav(scr, L, Pg::Light);
    save(scr, out + "/licht" + sfx + ".ppm");

    // Musik
    scr.fillScreen(col::bg);
    drawHeader(scr, L, Header{"14:26", "So, 27. Apr.", -66, true, false, nullptr});
    drawPageHead(scr, L, "Musik", "Spotify");
    drawMusic(scr, L, Player{"Musik Wohnzimmer", "Daft Punk – Get Lucky (feat. Pharrell Williams)", true, true, 0, 2});
    drawNav(scr, L, Pg::Music);
    save(scr, out + "/musik" + sfx + ".ppm");

    // Einstellungen
    scr.fillScreen(col::bg);
    drawHeader(scr, L, Header{"14:26", "So, 27. Apr.", -66, true, false, nullptr});
    drawPageHead(scr, L, "Einstellungen", "Küche");
    SetRow rows[] = {{"Lautstärke", "70 %", 70, true, false}, {"Helligkeit", "180", 70, true, false},
                     {"Ausrichtung", "Hochformat", -1, false, true}, {"Touch kalibrieren", "", -1, false, true},
                     {"WLAN neu einrichten", "Hotspot „Jarvis-Setup“", -1, false, true}};
    LGFX_Sprite srow(&scr);
    srow.setColorDepth(16);
    srow.createSprite(W, kSetH);
    y = L.contentY + kPageHead;
    scr.setClipRect(0, y, W, L.navY - y);
    for (auto& r : rows) {
      drawSettingRow(srow, W, r);
      srow.pushSprite(0, y);
      y += kSetH;
    }
    scr.clearClipRect();
    drawNav(scr, L, Pg::Settings);
    save(scr, out + "/einstellungen" + sfx + ".ppm");

    // Wecker
    scr.fillScreen(col::bg);
    drawHeader(scr, L, Header{"06:30", "Mo, 28. Apr.", -60, true, false, nullptr});
    LGFX_Sprite r(&scr);
    r.setColorDepth(16);
    r.createSprite(L.rsize, L.rsize);
    drawReactor(r, L.rsize, 1.0f, St::Alarm, 0.4f);
    r.pushSprite(L.rcx - L.rsize / 2, L.rcy - L.rsize / 2);
    drawAlarm(scr, L, "Wecker", 0);
    save(scr, out + "/wecker" + sfx + ".ppm");

    // Einrichtung, Update, Start
    scr.fillScreen(col::bg);
    drawHeader(scr, L, Header{"--:--", "", 0, false, false, nullptr});
    drawSetup(scr, L, false, "Jarvis-Setup", "0.3.0");
    drawNav(scr, L, Pg::Home);
    save(scr, out + "/einrichtung" + sfx + ".ppm");
    drawOta(scr, L, 62, "0.3.1", "Lade Firmware vom Jarvis-Server …", false);
    save(scr, out + "/update" + sfx + ".ppm");
    drawSplash(scr, L, "0.3.0");
    save(scr, out + "/start" + sfx + ".ppm");
    scr.fillScreen(col::bg);
    home(scr, L, St::Idle, 0, "Sag „Hey Jarvis“ oder tippe auf den Kreis", Pg::Home, nullptr);
    drawToast(scr, L, "Licht Wohnzimmer geschaltet", true);
    save(scr, out + "/toast" + sfx + ".ppm");
  }
  puts("ok");
  return 0;
}
