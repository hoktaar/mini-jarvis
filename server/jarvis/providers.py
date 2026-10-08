"""Fabriken für STT, TTS und LLM – lokal zuerst, Cloud optional.

Modelle (Whisper, Piper) werden einmal pro Prozess geladen und von allen Geräten
geteilt. Vorher hatte jede Verbindung ihr eigenes Whisper im VRAM, und das Laden
blockierte alle anderen Sitzungen.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
from loguru import logger

from jarvis.config import JarvisConfig

MODELS_DIR = Path(os.environ.get("JARVIS_MODELS_DIR", "/models"))

_whisper_cache: dict[tuple[str, str, str], object] = {}
_whisper_lock = threading.Lock()
_piper_lock = threading.Lock()          # espeak-ng (Phonemisierung) ist nicht threadsicher


def whisper_device(cfg: JarvisConfig, gpu_busy: bool = False) -> tuple[str, str]:
    s = cfg.providers.stt
    device = "cpu" if (gpu_busy or cfg.gpu.comfyui_mode == "on") else s.device
    compute = "int8" if device == "cpu" else s.compute_type
    return device, compute


def get_whisper_model(model: str, device: str, compute: str):
    """WhisperModel einmal laden, danach aus dem Cache (threadsicher)."""
    key = (model, device, compute)
    with _whisper_lock:
        if key not in _whisper_cache:
            from faster_whisper import WhisperModel

            logger.info(f"Lade Whisper {model} ({device}/{compute}) …")
            _whisper_cache[key] = WhisperModel(model, device=device, compute_type=compute)
            logger.info("Whisper geladen")
        return _whisper_cache[key]


def preload(cfg: JarvisConfig) -> None:
    """Beim Start im Hintergrund-Thread aufrufen – die erste Verbindung wartet dann nicht."""
    try:
        if cfg.providers.stt.type == "whisper":
            device, compute = whisper_device(cfg)
            get_whisper_model(cfg.providers.stt.model, device, compute)
        if cfg.providers.tts.type == "piper":
            _patch_piper_cache()
            make_tts(cfg, {})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Modelle konnten nicht vorgeladen werden: {e}")


def transcribe_pcm(cfg: JarvisConfig, pcm16: bytes) -> str:
    """Sprachnachricht (16 kHz PCM16 mono) mit dem geteilten Whisper transkribieren."""
    device, compute = whisper_device(cfg)
    model = get_whisper_model(cfg.providers.stt.model, device, compute)
    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(audio, language="de")
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe_audio(cfg: JarvisConfig, secrets: dict, data: bytes, filename: str = "audio.ogg") -> str:
    """Sprachnachricht (z. B. Telegram-OGG) transkribieren: lokal mit Whisper oder über OpenAI/Groq."""
    import asyncio
    import io

    s = cfg.providers.stt
    if s.type in ("openai", "groq"):
        import httpx

        base = s.base_url or ("https://api.groq.com/openai/v1" if s.type == "groq" else "https://api.openai.com/v1")
        model = s.model or ("whisper-large-v3-turbo" if s.type == "groq" else "gpt-4o-transcribe")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{base.rstrip('/')}/audio/transcriptions",
                                  headers={"Authorization": f"Bearer {_key(secrets, s.type, s.api_key_secret)}"},
                                  data={"model": model, "language": "de"}, files={"file": (filename, data)})
            r.raise_for_status()
            return (r.json().get("text") or "").strip()
    if s.type not in ("whisper", "none"):
        raise RuntimeError("Sprachnachrichten brauchen Whisper, OpenAI oder Groq als Spracherkennung.")

    def _decode() -> bytes:
        import soundfile as sf
        import soxr

        audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        if rate != 16000:
            mono = soxr.resample(mono, rate, 16000)
        return (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()

    pcm = await asyncio.to_thread(_decode)
    return await asyncio.to_thread(transcribe_pcm, cfg, pcm)


def _patch_piper_cache() -> None:
    import pipecat.services.piper.tts as mod

    if getattr(mod, "_jarvis_cached", False):
        return
    original = mod.PiperVoice
    cache: dict[tuple[str, bool], object] = {}

    class _Locked:
        def __init__(self, voice):
            self._voice = voice

        def __getattr__(self, name):
            return getattr(self._voice, name)

        def synthesize(self, text, *args, **kwargs):
            gen = self._voice.synthesize(text, *args, **kwargs)
            while True:
                with _piper_lock:
                    try:
                        item = next(gen)
                    except StopIteration:
                        return
                yield item

    class _CachedPiperVoice:
        @staticmethod
        def load(path, use_cuda: bool = False, **kwargs):
            key = (str(path), use_cuda)
            if key not in cache:
                cache[key] = _Locked(original.load(path, use_cuda=use_cuda, **kwargs))
            return cache[key]

    mod.PiperVoice = _CachedPiperVoice
    mod._jarvis_cached = True


def _settings(cls, **values):
    """Settings-Objekt eines Pipecat-Dienstes nur mit den Feldern füllen, die es kennt."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(cls.Settings)}
    return cls.Settings(**{k: v for k, v in values.items() if k in names and v not in (None, "")})


_aiohttp_session = None


def _http_session():
    """Eine geteilte aiohttp-Sitzung für Dienste, die eine verlangen (statt einer pro Verbindung)."""
    global _aiohttp_session
    import aiohttp

    if _aiohttp_session is None or _aiohttp_session.closed:
        _aiohttp_session = aiohttp.ClientSession()
    return _aiohttp_session


def _key(secrets: dict, kind: str, override: str = "") -> str:
    from jarvis.config import secret_name

    return secrets.get(secret_name(kind, override), "")


def make_stt(cfg: JarvisConfig, secrets: dict, hotwords: list[str] | None = None, gpu_busy: bool = False):
    from pipecat.transcriptions.language import Language

    s = cfg.providers.stt
    if s.type == "none":
        return None
    if s.type == "whisper":
        from pipecat.services.whisper.stt import WhisperSTTService

        device, compute = whisper_device(cfg, gpu_busy)

        class SharedWhisperSTTService(WhisperSTTService):
            def _load(self):
                self._model = get_whisper_model(s.model, device, compute)

        return SharedWhisperSTTService(
            settings=WhisperSTTService.Settings(
                model=s.model, language=Language.DE,
                # Eigennamen (Container, Skripte) besser erkennen
                hotwords=" ".join(["Jarvis", *(hotwords or [])]),
            ),
            device=device, compute_type=compute,
        )
    prompt = "Jarvis, " + ", ".join(hotwords or [])
    key = _key(secrets, "google_stt" if s.type == "google" else s.type, s.api_key_secret)
    if s.type == "openai":
        from pipecat.services.openai.stt import OpenAISTTService

        kwargs = {"base_url": s.base_url} if s.base_url else {}
        return OpenAISTTService(api_key=key or "none",
                                settings=_settings(OpenAISTTService, model=s.model or "gpt-4o-transcribe",
                                                   language=Language.DE, prompt=prompt), **kwargs)
    if s.type == "groq":
        from pipecat.services.groq.stt import GroqSTTService

        return GroqSTTService(api_key=key, settings=_settings(GroqSTTService, model=s.model or "whisper-large-v3-turbo",
                                                              language=Language.DE, prompt=prompt))
    if s.type == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService

        return DeepgramSTTService(api_key=key, settings=_settings(DeepgramSTTService, model=s.model or "nova-3",
                                                                  language=Language.DE))
    if s.type == "azure":
        from pipecat.services.azure.stt import AzureSTTService

        return AzureSTTService(api_key=key, region=s.region,
                               settings=_settings(AzureSTTService, language=Language.DE_DE))
    if s.type == "google":
        from pipecat.services.google.stt import GoogleSTTService

        return GoogleSTTService(credentials=key or None,
                                settings=_settings(GoogleSTTService, model=s.model or None, language=Language.DE_DE,
                                                   languages=[Language.DE_DE]))
    if s.type == "elevenlabs":
        from pipecat.services.elevenlabs.stt import ElevenLabsSTTService

        return ElevenLabsSTTService(api_key=key, aiohttp_session=_http_session(),
                                    settings=_settings(ElevenLabsSTTService, model=s.model or None,
                                                       language=Language.DE))
    raise ValueError(f"STT-Typ nicht unterstützt: {s.type}")


def make_tts(cfg: JarvisConfig, secrets: dict):
    from pipecat.transcriptions.language import Language

    t = cfg.providers.tts
    if t.type == "none":
        return None
    if t.type == "piper":
        _patch_piper_cache()
        from pipecat.services.piper.tts import PiperTTSService

        return PiperTTSService(
            settings=PiperTTSService.Settings(voice=t.voice),
            download_dir=MODELS_DIR / "piper",
        )
    key = _key(secrets, "google_tts" if t.type == "google" else t.type, t.api_key_secret)
    voice = t.voice if t.voice and not t.voice.startswith("de_DE-") else ""
    if t.type == "openai":
        from pipecat.services.openai.tts import OpenAITTSService

        return OpenAITTSService(api_key=key, settings=_settings(OpenAITTSService, voice=voice or t.openai_voice,
                                                                model=t.model or "gpt-4o-mini-tts"))
    if t.type == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(api_key=key, settings=_settings(ElevenLabsTTSService, voice=voice or None,
                                                                    model=t.model or "eleven_flash_v2_5",
                                                                    language=Language.DE))
    if t.type == "cartesia":
        from pipecat.services.cartesia.tts import CartesiaTTSService

        return CartesiaTTSService(api_key=key, settings=_settings(CartesiaTTSService, voice=voice or None,
                                                                  model=t.model or "sonic-2", language=Language.DE))
    if t.type == "deepgram":
        from pipecat.services.deepgram.tts import DeepgramTTSService

        return DeepgramTTSService(api_key=key, settings=_settings(DeepgramTTSService, voice=voice or None,
                                                                  model=t.model or None))
    if t.type == "azure":
        from pipecat.services.azure.tts import AzureTTSService

        return AzureTTSService(api_key=key, region=t.region,
                               settings=_settings(AzureTTSService, voice=voice or "de-DE-ConradNeural",
                                                  language=Language.DE_DE))
    if t.type == "google":
        from pipecat.services.google.tts import GoogleTTSService

        return GoogleTTSService(credentials=key or None,
                                settings=_settings(GoogleTTSService, voice=voice or "de-DE-Chirp3-HD-Charon",
                                                   language=Language.DE_DE))
    raise ValueError(f"TTS-Typ nicht unterstützt: {t.type}")


def make_local_llm(cfg: JarvisConfig):
    lc = cfg.providers.llm.local
    if not lc.enabled:
        return None
    from pipecat.services.ollama.llm import OLLamaLLMService

    settings = OLLamaLLMService.Settings(model=lc.model)
    if lc.temperature is not None:
        settings.temperature = lc.temperature
    return OLLamaLLMService(settings=settings, base_url=lc.base_url)


def system_suffix(cfg: JarvisConfig) -> str:
    """Modell-spezifische Schalter für den Systemprompt (qwen3: Denkmodus aus)."""
    lc = cfg.providers.llm.local
    if not lc.think and lc.model.lower().startswith("qwen3") and "instruct" not in lc.model.lower():
        return "\n/no_think"
    return ""


# Cloud-LLM-Anbieter: (Modul, Klasse, Standard-base_url-Parameter)
_CLOUD_LLMS = {
    "anthropic": ("pipecat.services.anthropic.llm", "AnthropicLLMService"),
    "openai": ("pipecat.services.openai.llm", "OpenAILLMService"),
    "openai_compatible": ("pipecat.services.openai.llm", "OpenAILLMService"),
    "google": ("pipecat.services.google.llm", "GoogleLLMService"),
    "mistral": ("pipecat.services.mistral.llm", "MistralLLMService"),
    "groq": ("pipecat.services.groq.llm", "GroqLLMService"),
    "openrouter": ("pipecat.services.openrouter.llm", "OpenRouterLLMService"),
    "deepseek": ("pipecat.services.deepseek.llm", "DeepSeekLLMService"),
}


def make_cloud_llm(cfg: JarvisConfig, secrets: dict):
    import importlib

    cc = cfg.providers.llm.cloud
    if not cc.enabled or not cc.model:
        return None
    try:
        module, cls_name = _CLOUD_LLMS[cc.type]
        cls = getattr(importlib.import_module(module), cls_name)
        kwargs = {"api_key": _key(secrets, cc.type, cc.api_key_secret) or "none",
                  "settings": _settings(cls, model=cc.model)}
        if cc.base_url and cc.type not in ("anthropic", "google"):
            kwargs["base_url"] = cc.base_url
        return cls(**kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Cloud-LLM ({cc.type}) konnte nicht erstellt werden: {e}")
        return None
