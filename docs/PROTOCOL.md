# Protokolle

## 1. RTVI (PWA, Android, Desktop)

Diese Clients nutzen die offiziellen Pipecat-Client-SDKs und das RTVI-Protokoll
über `ws://<server>:8080/ws/client?token=<gerätetoken>` (Protobuf-Serializer)
bzw. später WebRTC (SmallWebRTC). Jarvis-spezifische Ereignisse kommen als
Server-Messages mit `{"jarvis": {...}}` (siehe unten).

## 2. CYD-Protokoll (schlanke ESP32 ohne PSRAM)

Endpoint: `ws://<server>:8080/ws/cyd?token=<gerätetoken>`

### Client → Server

| Typ | Inhalt |
|---|---|
| Binär | PCM 16 Bit, mono, 16 kHz, little-endian, beliebige Blockgröße (empfohlen 20 ms = 640 Bytes) |
| Text | `{"type":"hello","fw":"0.1.0","board":"cyd","caps":["mic","speaker","display","touch"]}` |
| Text | `{"type":"ptt","value":"start"}` / `{"type":"ptt","value":"stop"}` |
| Text | `{"type":"alarm_ack","id":42}` |

### Server → Client

| Typ | Inhalt |
|---|---|
| Binär | PCM 16 Bit, mono, 16 kHz (Firmware wandelt für den 8-Bit-DAC) |
| Text | `{"type":"state","value":"idle|listening|thinking|speaking|alarm|offline"}` |
| Text | `{"type":"text","role":"user|assistant","content":"…"}` |
| Text | `{"type":"alarm","id":42,"label":"Pizza"}` |
| Text | `{"type":"cloud","value":true}` – Antwort lief über externen Dienst |

## 3. Jarvis-Ereignisse (alle Clients)

`state`, `text`, `alarm`, `cloud` wie oben – bei RTVI-Clients verpackt als
Server-Message.
