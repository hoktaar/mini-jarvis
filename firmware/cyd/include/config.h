#pragma once
// Mini-Jarvis CYD-Firmware – zentrale Konstanten

#define FW_VERSION "0.3.0"
#ifdef PANEL_ST7789
#define FW_BOARD "cyd-st7789"
#else
#define FW_BOARD "cyd"
#endif

#define SAMPLE_RATE        16000
#define MIC_FRAME_MS       20
#define MIC_FRAME_SAMPLES  (SAMPLE_RATE * MIC_FRAME_MS / 1000)   // 320 Samples = 640 Bytes
#define PLAYBACK_BYTES     (32 * 1024)                           // 1 s PCM16 Antwort-Audio
#define MIC_QUEUE_BYTES    (8 * MIC_FRAME_SAMPLES * 2)            // 160 ms Mikrofon-Puffer
#define WS_PATH            "/ws/cyd"
#define DEFAULT_PORT       8080
#define WIFI_TIMEOUT_MS    20000
#define SETUP_AP_NAME      "Jarvis-Setup"
#define NTP_SERVER_1       "pool.ntp.org"
#define NTP_SERVER_2       "time.cloudflare.com"
#define DEFAULT_TZ         "CET-1CEST,M3.5.0,M10.5.0/3"
