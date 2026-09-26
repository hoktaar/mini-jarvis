#include "ui.h"

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

#include "board_cyd.h"

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
    { auto c = bus.config();
      c.spi_host = HSPI_HOST; c.spi_mode = 0; c.freq_write = 40000000; c.freq_read = 16000000;
      c.pin_sclk = TFT_SCLK; c.pin_mosi = TFT_MOSI; c.pin_miso = TFT_MISO; c.pin_dc = TFT_DC;
      bus.config(c); panel.setBus(&bus); }
    { auto c = panel.config();
      c.pin_cs = TFT_CS; c.pin_rst = -1; c.panel_width = 240; c.panel_height = 320;
      c.readable = true; c.bus_shared = false;
      panel.config(c); }
    { auto c = light.config(); c.pin_bl = TFT_BL; c.freq = 12000; c.pwm_channel = 7;
      light.config(c); panel.setLight(&light); }
    { auto c = touch.config();
      c.spi_host = VSPI_HOST; c.freq = 1000000;
      c.pin_sclk = TOUCH_CLK; c.pin_mosi = TOUCH_MOSI; c.pin_miso = TOUCH_MISO; c.pin_cs = TOUCH_CS;
      c.pin_int = TOUCH_IRQ; c.bus_shared = false;
      c.x_min = 300; c.x_max = 3900; c.y_min = 200; c.y_max = 3700;   // TODO: kalibrieren
      touch.config(c); panel.setTouch(&touch); }
    setPanel(&panel);
  }
};

namespace ui {
static LGFX tft;
static JState current = JState::Offline;
static uint32_t frame = 0;
static const uint16_t CYAN = 0x2E9A, AMBER = 0xD4A3, DIM = 0x18E3;

static void led(bool r, bool g, bool b) {       // aktiv LOW
  digitalWrite(LED_R, !r); digitalWrite(LED_G, !g); digitalWrite(LED_B, !b);
}

void begin() {
  pinMode(LED_R, OUTPUT); pinMode(LED_G, OUTPUT); pinMode(LED_B, OUTPUT);
  tft.init();
  tft.setRotation(1);
  tft.setBrightness(180);
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFont(&fonts::FreeSans9pt7b);
  setState(JState::Offline);
}

JState state() { return current; }

void setState(JState s) {
  current = s;
  switch (s) {
    case JState::Offline:   led(1, 0, 0); break;
    case JState::Idle:      led(0, 0, 0); break;
    case JState::Listening: led(0, 0, 1); break;
    case JState::Thinking:  led(0, 1, 1); break;
    case JState::Speaking:  led(0, 1, 0); break;
    case JState::Alarm:     led(1, 1, 0); break;
  }
  tft.fillRect(0, 0, 320, 20, TFT_BLACK);
  static const char* names[] = {"Offline", "Bereit", "Hoert zu", "Denkt nach", "Spricht", "Alarm"};
  tft.drawString(names[(int)s], 6, 2);
}

void showText(const char* role, const char* text) {
  tft.fillRect(0, 180, 320, 60, TFT_BLACK);
  tft.setTextColor(strcmp(role, "user") == 0 ? TFT_LIGHTGREY : TFT_WHITE, TFT_BLACK);
  tft.setCursor(6, 186);
  tft.setTextWrap(true);
  tft.print(text);          // TODO: Umlaute über eigene Schrift (u8g2-Fonts in LovyanGFX)
}

bool touched() {
  int32_t x, y;
  return tft.getTouch(&x, &y);
}

void loop() {
  if (++frame % 3) return;                        // ~ alle 3 Durchläufe zeichnen
  const int cx = 160, cy = 100;
  uint16_t color = current == JState::Alarm ? AMBER : current == JState::Offline ? DIM : CYAN;
  float phase = (frame % 60) / 60.0f;
  int pulse = (current == JState::Speaking || current == JState::Alarm) ? (int)(6 * sinf(phase * 12.56f))
            : (current == JState::Idle) ? (int)(3 * sinf(phase * 6.28f)) : 0;
  tft.fillCircle(cx, cy, 58, TFT_BLACK);
  tft.drawCircle(cx, cy, 56, current == JState::Listening ? color : DIM);
  if (current == JState::Thinking) {
    float a = phase * 6.283f;
    tft.fillArc(cx, cy, 44, 40, (int)(a * 57.3f), (int)(a * 57.3f) + 90, color);
  } else {
    tft.drawCircle(cx, cy, 42, color);
  }
  tft.fillCircle(cx, cy, 18 + pulse, color);
}
}  // namespace ui
