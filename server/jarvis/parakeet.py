"""Lokale deutsche Spracherkennung mit Parakeet (sherpa-onnx, int8, nur CPU).

Modell: parakeet-primeline (deutsches Fine-Tuning von nvidia/parakeet-tdt-0.6b-v3, CC-BY-4.0, primeline/NVIDIA).
Aufteilen langer Aufnahmen und Anheben leiser Stellen nach dem Vorbild von winidi/dictate (MIT).

Das Modell (~640 MB) wird beim ersten Gebrauch von Hugging Face geladen und einmal pro Prozess
gehalten – alle Geräte und die Transkriptions-Schnittstelle teilen sich einen Erkenner.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from loguru import logger

MODEL_REPO = "flozen1981/parakeet-primeline-onnx"
MODEL_REVISION = "d548e25b9bfe559aa274f361892dc4ed5d64743a"     # fest, damit alle dasselbe Modell bekommen
MODEL_FILES = ("encoder.int8.onnx", "encoder.int8.onnx.data", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
MODEL_BYTES = 670_000_000          # ungefähre Downloadgröße für die Fortschrittsanzeige
RATE = 16000

# Der Encoder scheitert an mehr als 400 s am Stück und sein Speicherbedarf wächst davor quadratisch,
# deshalb werden lange Aufnahmen an einer Pause geteilt.
MAX_CHUNK_S = 90
RETRY_CHUNK_S = 20      # zweiter Versuch in kürzeren Stücken, wenn ein langes Stück leer zurückkommt
SEARCH_S = 15           # Pause im letzten Teil jedes Stücks suchen
WINDOW_S = 0.4
TARGET_PEAK = 0.5       # leise Aufnahmen werden auf diesen Spitzenpegel angehoben …
MAX_GAIN = 30.0         # … aber nie stärker, damit Raumrauschen Rauschen bleibt


def model_dir() -> Path:
    from jarvis.providers import MODELS_DIR

    return MODELS_DIR / "parakeet-primeline"


def installed() -> bool:
    d = model_dir()
    return all((d / f).is_file() for f in MODEL_FILES)


# Zustand für die Verwaltung (Download/Laden)
state: dict = {"downloading": False, "error": "", "loaded": False, "threads": 0}
_lock = threading.Lock()                # Laden/Download
_decode_lock = threading.Lock()         # ein Erkenner, Aufrufe nacheinander
_recognizer = None


def _dir_bytes(d: Path) -> int:
    try:
        return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
    except OSError:
        return 0


def status() -> dict:
    done = installed()
    return {
        "installed": done,
        "downloading": state["downloading"],
        "progress": 1.0 if done else min(0.99, _dir_bytes(model_dir()) / MODEL_BYTES) if state["downloading"] else 0.0,
        "size_mb": MODEL_BYTES // 1_000_000,
        "loaded": state["loaded"],
        "error": state["error"],
    }


def download() -> None:
    """Modell von Hugging Face holen (blockiert). Mehrfachaufrufe warten auf denselben Download."""
    with _lock:
        _download_locked()


def _download_locked() -> None:
    if installed():
        return
    from huggingface_hub import snapshot_download

    state.update(downloading=True, error="")
    d = model_dir()
    d.mkdir(parents=True, exist_ok=True)
    logger.info(f"Lade Parakeet-Modell ({MODEL_BYTES // 1_000_000} MB) nach {d} …")
    try:
        snapshot_download(repo_id=MODEL_REPO, revision=MODEL_REVISION, local_dir=str(d), allow_patterns=list(MODEL_FILES))
        if not installed():
            raise RuntimeError("Download unvollständig")
        logger.info("Parakeet-Modell geladen")
    except Exception as e:
        state["error"] = f"Parakeet-Modell konnte nicht geladen werden: {type(e).__name__}: {e}"
        raise RuntimeError(state["error"]) from e
    finally:
        state["downloading"] = False


def _build(threads: int):
    import sherpa_onnx

    d = model_dir()
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
        model_type="nemo_transducer", num_threads=threads, decoding_method="greedy_search")
    # Aufwärmen: der erste echte Durchlauf wäre sonst etwa doppelt so langsam
    for _ in range(2):
        s = rec.create_stream()
        s.accept_waveform(RATE, np.zeros(RATE, dtype=np.float32))
        rec.decode_stream(s)
    return rec


def get_recognizer(threads: int = 4):
    """Erkenner einmal laden (bei Bedarf vorher herunterladen), danach aus dem Speicher."""
    global _recognizer
    threads = max(1, min(int(threads or 4), 32))
    with _lock:
        if _recognizer is None or state["threads"] != threads:
            _download_locked()
            t = time.monotonic()
            try:
                _recognizer = _build(threads)
            except Exception as e:
                state["error"] = f"Parakeet konnte nicht starten: {type(e).__name__}: {e}"
                raise RuntimeError(state["error"]) from e
            state.update(loaded=True, threads=threads, error="")
            logger.info(f"Parakeet bereit ({threads} Threads, {time.monotonic() - t:.1f} s)")
        return _recognizer


def split(audio: np.ndarray, max_s: float = MAX_CHUNK_S):
    """Stücke von höchstens max_s Sekunden, jeweils an der leisesten Stelle kurz vor dem Ende geschnitten."""
    search_s = min(SEARCH_S, max_s / 2)
    max_n, search_n, win_n = (int(x * RATE) for x in (max_s, search_s, WINDOW_S))
    while len(audio) > max_n:
        tail = audio[max_n - search_n:max_n]
        n_win = len(tail) // win_n
        energy = (tail[:n_win * win_n].reshape(n_win, win_n) ** 2).mean(axis=1)
        cut = max_n - search_n + int(energy.argmin()) * win_n + win_n // 2
        yield audio[:cut]
        audio = audio[cut:]
    yield audio


def _decode(rec, chunk: np.ndarray) -> str:
    # Leise Sprache (Spitze um 0,03) kommt sonst leer zurück; angehoben wird sie vollständig erkannt.
    peak = float(np.abs(chunk).max()) if len(chunk) else 0.0
    if 0.0 < peak < TARGET_PEAK:
        chunk = chunk * min(TARGET_PEAK / peak, MAX_GAIN)
    s = rec.create_stream()
    s.accept_waveform(RATE, chunk.astype(np.float32, copy=False))
    rec.decode_stream(s)
    return s.result.text.strip()


def transcribe(audio: np.ndarray, threads: int = 4) -> str:
    """16-kHz-Mono-Audio (float32 in [-1, 1]) in Text umwandeln."""
    rec = get_recognizer(threads)
    parts = []
    with _decode_lock:
        for chunk in split(audio):
            text = _decode(rec, chunk)
            # Gelegentlich liefert ein langes Stück mit Sprache nichts; kürzere Stücke klappen dann.
            if not text and len(chunk) > RETRY_CHUNK_S * RATE:
                text = " ".join(t for t in (_decode(rec, c) for c in split(chunk, RETRY_CHUNK_S)) if t)
            parts.append(text)
    return " ".join(p for p in parts if p)
