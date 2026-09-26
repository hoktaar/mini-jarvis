#include "audio.h"

#include <ESP_I2S.h>
#include <driver/dac_continuous.h>

#include "board_cyd.h"
#include "config.h"

namespace audio {
static I2SClass micI2S;
static dac_continuous_handle_t dac = nullptr;
static uint8_t ring[PLAYBACK_BUFFER];
static volatile size_t head = 0, tail = 0;
static uint32_t lastAudioMs = 0;

bool beginSpeaker() {
  dac_continuous_config_t cfg = {
      .chan_mask = DAC_CHANNEL_MASK_CH1,  // CH1 = GPIO 26
      .desc_num = 4,
      .buf_size = 1024,
      .freq_hz = SAMPLE_RATE,
      .offset = 0,
      .clk_src = DAC_DIGI_CLK_SRC_APLL,
      .chan_mode = DAC_CHANNEL_MODE_SIMUL,
  };
  if (dac_continuous_new_channels(&cfg, &dac) != ESP_OK) return false;
  return dac_continuous_enable(dac) == ESP_OK;
}

bool beginMic() {
  micI2S.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);
  // INMP441 liefert 24 Bit in 32-Bit-Slots, linker Kanal (L/R an GND)
  return micI2S.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO,
                      I2S_STD_SLOT_LEFT);
}

size_t readMic(int16_t* out, size_t samples) {
  static int32_t raw[MIC_FRAME_SAMPLES];
  size_t want = min(samples, (size_t)MIC_FRAME_SAMPLES);
  size_t got = micI2S.readBytes((char*)raw, want * sizeof(int32_t)) / sizeof(int32_t);
  for (size_t i = 0; i < got; i++) out[i] = (int16_t)(raw[i] >> 14);  // 24→16 Bit + etwas Gain
  return got * sizeof(int16_t);
}

void queuePlayback(const uint8_t* pcm16, size_t len) {
  const int16_t* s = (const int16_t*)pcm16;
  for (size_t i = 0; i < len / 2; i++) {
    size_t next = (head + 1) % PLAYBACK_BUFFER;
    if (next == tail) break;                      // Puffer voll → verwerfen
    ring[head] = (uint8_t)((s[i] >> 8) + 128);    // PCM16 → unsigned 8 Bit für den DAC
    head = next;
  }
  lastAudioMs = millis();
}

void clearPlayback() { tail = head; }

bool isPlaying() { return head != tail || millis() - lastAudioMs < 300; }

void loop() {
  if (!dac || head == tail) return;
  static uint8_t chunk[512];
  size_t n = 0;
  while (tail != head && n < sizeof(chunk)) {
    chunk[n++] = ring[tail];
    tail = (tail + 1) % PLAYBACK_BUFFER;
  }
  size_t loaded = 0;
  dac_continuous_write(dac, chunk, n, &loaded, 20);
}
}  // namespace audio
