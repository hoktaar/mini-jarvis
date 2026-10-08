#include "audio.h"

#include <ESP_I2S.h>
#include <driver/dac_continuous.h>
#include <freertos/stream_buffer.h>
#include <math.h>

#include "board_cyd.h"
#include "config.h"

namespace audio {
static I2SClass micI2S(I2S_NUM_1);               // I2S0 gehört dem DAC
static dac_continuous_handle_t dac = nullptr;
static StreamBufferHandle_t micBuf = nullptr;
static StreamBufferHandle_t playBuf = nullptr;
static bool micReady = false;
static volatile bool streaming = false;
static volatile bool dropIncoming = false;
static volatile bool clearRequest = false;
static volatile bool alarmOn = false;
static volatile uint32_t beepUntil = 0;
static volatile uint8_t volume = 70;
static volatile float micLevel = 0, playLevel = 0;
static volatile uint32_t lastPlayMs = 0;

static inline uint8_t toDac(int32_t s16) {
  int32_t v = (s16 >> 8) + 128;
  return (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
}

static float gain() {
  float v = volume / 100.0f;
  return 1.3f * v * v;                           // annähernd gehörrichtig
}

// ---------------------------------------------------------------- Mikrofon
static void micTask(void*) {
  static int32_t raw[MIC_FRAME_SAMPLES];
  static int16_t pcm[MIC_FRAME_SAMPLES];
  float prevIn = 0, prevOut = 0;
  for (;;) {
    size_t got = 0;
    if (i2s_channel_read(micI2S.rxChan(), raw, sizeof(raw), &got, portMAX_DELAY) != ESP_OK || !got) {
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }
    size_t n = got / sizeof(int32_t);
    float sum = 0;
    for (size_t i = 0; i < n; i++) {
      float x = (float)(raw[i] >> 8);            // INMP441: 24 Bit linksbündig im 32-Bit-Slot
      float y = x - prevIn + 0.995f * prevOut;   // Gleichanteil entfernen (Hochpass ~13 Hz)
      prevIn = x;
      prevOut = y;
      float s = y / 64.0f;                       // 24 → 16 Bit mit etwas Verstärkung
      if (s > 32767.0f) s = 32767.0f;
      if (s < -32768.0f) s = -32768.0f;
      pcm[i] = (int16_t)s;
      sum += s * s;
    }
    float rms = sqrtf(sum / (float)n) / 32768.0f;
    micLevel = micLevel * 0.6f + rms * 0.4f;
    if (streaming) xStreamBufferSend(micBuf, pcm, n * sizeof(int16_t), 0);   // voll → Block verwerfen
  }
}

// ---------------------------------------------------------------- Wiedergabe
static size_t alarmChunk(uint8_t* out, size_t n, uint32_t& t) {
  // Zwei Töne (880 Hz / 1175 Hz), dann Pause – wiederholt alle 1,2 s
  float g = fmaxf(gain(), 0.45f);
  for (size_t i = 0; i < n; i++, t++) {
    uint32_t ms = (t / (SAMPLE_RATE / 1000)) % 1200;
    float f = ms < 180 ? 880.0f : (ms >= 300 && ms < 480) ? 1175.0f : 0.0f;
    float s = f > 0 ? sinf(2.0f * (float)M_PI * f * (float)t / SAMPLE_RATE) : 0.0f;
    out[i] = toDac((int32_t)(s * 26000.0f * g));
  }
  return n;
}

static void playTask(void*) {
  static int16_t in[256];
  static uint8_t out[256];
  uint32_t toneT = 0;
  for (;;) {
    size_t n = 0;
    if (clearRequest) {
      xStreamBufferReset(playBuf);
      clearRequest = false;
    }
    if (alarmOn) {
      n = alarmChunk(out, sizeof(out), toneT);
      playLevel = 0.5f;
    } else if (millis() < beepUntil) {
      float g = fmaxf(gain(), 0.3f);
      for (size_t i = 0; i < 128; i++, toneT++)
        out[i] = toDac((int32_t)(sinf(2.0f * (float)M_PI * 1320.0f * (float)toneT / SAMPLE_RATE) * 14000.0f * g));
      n = 128;
    } else {
      size_t bytes = xStreamBufferReceive(playBuf, in, sizeof(in), pdMS_TO_TICKS(20));
      n = bytes / 2;
      if (n) {
        float g = gain(), sum = 0;
        for (size_t i = 0; i < n; i++) {
          int32_t s = (int32_t)(in[i] * g);
          out[i] = toDac(s);
          sum += (float)in[i] * (float)in[i];
        }
        playLevel = playLevel * 0.5f + 0.5f * sqrtf(sum / (float)n) / 32768.0f;
        lastPlayMs = millis();
      } else {
        memset(out, 128, 128);                   // Stille halten, sonst wiederholt der DMA den letzten Block
        n = 128;
        playLevel *= 0.8f;
      }
    }
    size_t loaded = 0;
    dac_continuous_write(dac, out, n, &loaded, -1);
  }
}

bool begin() {
  dac_continuous_config_t cfg = {
      .chan_mask = DAC_CHANNEL_MASK_CH1,         // CH1 = GPIO 26
      .desc_num = 4,
      .buf_size = 512,
      .freq_hz = SAMPLE_RATE,
      .offset = 0,
      .clk_src = DAC_DIGI_CLK_SRC_APLL,
      .chan_mode = DAC_CHANNEL_MODE_SIMUL,
  };
  bool dacOk = dac_continuous_new_channels(&cfg, &dac) == ESP_OK && dac_continuous_enable(dac) == ESP_OK;

  micI2S.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);
  micReady = micI2S.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT);

  micBuf = xStreamBufferCreate(MIC_QUEUE_BYTES, MIC_FRAME_SAMPLES * 2);
  playBuf = xStreamBufferCreate(PLAYBACK_BYTES, 2);
  if (dacOk) xTaskCreatePinnedToCore(playTask, "play", 4096, nullptr, 6, nullptr, 0);
  if (micReady) xTaskCreatePinnedToCore(micTask, "mic", 4096, nullptr, 5, nullptr, 0);
  return dacOk && micReady;
}

bool micOk() { return micReady; }

void setMicStreaming(bool on) {
  if (on && !streaming) xStreamBufferReset(micBuf);
  streaming = on;
}

size_t readFrame(int16_t* out) {
  if (!micBuf || xStreamBufferBytesAvailable(micBuf) < MIC_FRAME_SAMPLES * 2) return 0;
  return xStreamBufferReceive(micBuf, out, MIC_FRAME_SAMPLES * 2, 0);
}

void play(const uint8_t* pcm16, size_t len) {
  if (dropIncoming || alarmOn || !playBuf) return;
  size_t space = xStreamBufferSpacesAvailable(playBuf);
  len = (len < space ? len : space) & ~(size_t)1;
  if (len) xStreamBufferSend(playBuf, pcm16, len, 0);
  lastPlayMs = millis();
}

void clear() { clearRequest = true; }
void setDropIncoming(bool drop) { dropIncoming = drop; if (drop) clearRequest = true; }

bool playing() {
  return alarmOn || (playBuf && xStreamBufferBytesAvailable(playBuf) > 0) || millis() - lastPlayMs < 250;
}

void setVolume(uint8_t v) { volume = v > 100 ? 100 : v; }
void alarm(bool on) { alarmOn = on; if (on) clearRequest = true; }
bool alarmActive() { return alarmOn; }
void beep() { beepUntil = millis() + 70; }
float level() { return streaming ? micLevel : playLevel; }
}  // namespace audio
