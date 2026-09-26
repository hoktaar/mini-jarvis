"""End-to-End-Selbsttest wie ein CYD: WAV hinschicken, Antwort-Audio empfangen.

    python -m jarvis.selftest --url ws://192.168.1.144:8080/ws/cyd --token <cyd-token> frage.wav

Schickt Push-to-Talk, streamt die Aufnahme in Echtzeit (16 kHz PCM16),
sammelt Zustände/Texte und speichert die gesprochene Antwort als antwort.wav.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import numpy as np
import soundfile as sf
import soxr
import websockets

RATE = 16000
CHUNK = 320  # 20 ms


def load_pcm16(path: str) -> bytes:
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if rate != RATE:
        mono = soxr.resample(mono, rate, RATE)
    return (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()


async def run(url: str, token: str, wav: str, out: str, timeout: float) -> int:
    pcm = load_pcm16(wav)
    silence = bytes(CHUNK * 2)
    answer = bytearray()
    events: list[dict] = []
    async with websockets.connect(f"{url}?token={token}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "fw": "selftest", "board": "cyd", "caps": ["mic", "speaker"]}))
        await ws.send(json.dumps({"type": "ptt", "value": "start"}))

        async def sender():
            for _ in range(15):                     # 300 ms Vorlauf
                await ws.send(silence); await asyncio.sleep(0.02)
            for i in range(0, len(pcm), CHUNK * 2):
                await ws.send(pcm[i : i + CHUNK * 2]); await asyncio.sleep(0.02)
            for _ in range(75):                     # 1,5 s Stille → Satzende
                await ws.send(silence); await asyncio.sleep(0.02)
            await ws.send(json.dumps({"type": "ptt", "value": "stop"}))

        send_task = asyncio.create_task(sender())
        start, spoke, last_audio = time.monotonic(), False, None
        while time.monotonic() - start < timeout:
            try:
                msg = await asyncio.wait_for(ws.recv(), 0.5)
            except asyncio.TimeoutError:
                if spoke and last_audio and time.monotonic() - last_audio > 1.5:
                    break
                continue
            if isinstance(msg, bytes):
                answer += msg
                spoke, last_audio = True, time.monotonic()
            else:
                ev = json.loads(msg)
                events.append(ev)
                print("←", ev)
        send_task.cancel()
    if answer:
        sf.write(out, np.frombuffer(bytes(answer), dtype="<i2"), RATE)
        print(f"Antwort: {len(answer) / 2 / RATE:.1f} s Audio → {out}")
    ok = bool(answer) and any(e.get("type") == "text" and e.get("role") == "assistant" for e in events)
    print("✅ Selbsttest bestanden" if ok else "❌ Keine gesprochene Antwort erhalten")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--url", default="ws://127.0.0.1:8080/ws/cyd")
    ap.add_argument("--token", required=True)
    ap.add_argument("--out", default="antwort.wav")
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(run(a.url, a.token, a.wav, a.out, a.timeout)))


if __name__ == "__main__":
    main()
