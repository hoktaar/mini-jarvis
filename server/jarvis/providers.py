"""Fabriken für STT, TTS und LLM – lokal zuerst, Cloud optional."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from jarvis.config import JarvisConfig

import os

MODELS_DIR = Path(os.environ.get("JARVIS_MODELS_DIR", "/models"))


def make_stt(cfg: JarvisConfig, secrets: dict, hotwords: list[str] | None = None):
    s = cfg.providers.stt
    if s.type == "whisper":
        from pipecat.services.whisper.stt import WhisperSTTService
        from pipecat.transcriptions.language import Language

        device = "cpu" if cfg.gpu.comfyui_mode else s.device
        compute = "int8" if device == "cpu" else s.compute_type
        return WhisperSTTService(
            settings=WhisperSTTService.Settings(
                model=s.model, language=Language.DE,
                # Eigennamen (Container, Skripte) besser erkennen
                hotwords=" ".join(["Jarvis", *(hotwords or [])]),
            ),
            device=device, compute_type=compute,
        )
    if s.type == "openai":
        from pipecat.services.openai.stt import OpenAISTTService

        return OpenAISTTService(api_key=secrets.get("openai_api_key", ""))
    raise ValueError(f"STT-Typ nicht unterstützt: {s.type}")


def make_tts(cfg: JarvisConfig, secrets: dict):
    t = cfg.providers.tts
    if t.type == "piper":
        from pipecat.services.piper.tts import PiperTTSService

        return PiperTTSService(
            settings=PiperTTSService.Settings(voice=t.voice),
            download_dir=MODELS_DIR / "piper",
        )
    if t.type == "openai":
        from pipecat.services.openai.tts import OpenAITTSService

        return OpenAITTSService(api_key=secrets.get("openai_api_key", ""))
    raise ValueError(f"TTS-Typ nicht unterstützt: {t.type}")


def make_local_llm(cfg: JarvisConfig):
    from pipecat.services.ollama.llm import OLLamaLLMService

    lc = cfg.providers.llm.local
    return OLLamaLLMService(settings=OLLamaLLMService.Settings(model=lc.model), base_url=lc.base_url)


def make_cloud_llm(cfg: JarvisConfig, secrets: dict):
    cc = cfg.providers.llm.cloud
    if not cc.enabled:
        return None
    try:
        if cc.type == "anthropic":
            from pipecat.services.anthropic.llm import AnthropicLLMService

            return AnthropicLLMService(
                api_key=secrets["anthropic_api_key"],
                settings=AnthropicLLMService.Settings(model=cc.model),
            )
        from pipecat.services.openai.llm import OpenAILLMService

        key = secrets.get("openrouter_api_key") if cc.type == "openrouter" else secrets.get("openai_api_key")
        base = cc.base_url or ("https://openrouter.ai/api/v1" if cc.type == "openrouter" else None)
        return OpenAILLMService(api_key=key or "", base_url=base, settings=OpenAILLMService.Settings(model=cc.model))
    except Exception as e:  # noqa: BLE001
        logger.error(f"Cloud-LLM konnte nicht erstellt werden: {e}")
        return None
