#pragma once
#define FW_VERSION      "0.1.0"
#define SAMPLE_RATE     16000
#define MIC_FRAME_MS    20
#define MIC_FRAME_SAMPLES (SAMPLE_RATE * MIC_FRAME_MS / 1000)   // 320 Samples = 640 Bytes
#define PLAYBACK_BUFFER (16 * 1024)                            // Ringpuffer für Antwort-Audio
#define WS_PATH         "/ws/cyd"
#define DEFAULT_PORT    8080
