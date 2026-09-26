#pragma once
// Pinbelegung ESP32-2432S028 (CYD). Vor dem Löten mit der eigenen Revision abgleichen!

// Display (HSPI)
#define TFT_SCLK 14
#define TFT_MOSI 13
#define TFT_MISO 12
#define TFT_DC    2
#define TFT_CS   15
#define TFT_BL   21

// Touch XPT2046 (eigener SPI-Bus)
#define TOUCH_CLK  25
#define TOUCH_MOSI 32
#define TOUCH_MISO 39
#define TOUCH_CS   33
#define TOUCH_IRQ  36

// RGB-LED (aktiv LOW)
#define LED_R 4
#define LED_G 16
#define LED_B 17

// Mikrofon INMP441 (I2S)
#define MIC_SCK 22
#define MIC_WS  27
#define MIC_SD  35

// Lautsprecher: interner DAC, Kanal 2 = GPIO 26
#define SPEAKER_DAC_GPIO 26
