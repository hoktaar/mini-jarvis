"""Konfiguration laden (YAML) und typisiert bereitstellen."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(os.environ.get("JARVIS_CONFIG_DIR", "/config"))
DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", "/data"))
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "config" / "examples"


class ServerCfg(BaseModel):
    host: str = "0.0.0.0"
    web_port: int = 8080
    ws_port: int = 8080
    public_base_url: str = ""


class LocationCfg(BaseModel):
    name: str = "Zuhause"
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = "Europe/Berlin"


class GpuCfg(BaseModel):
    comfyui_mode: bool = False


class WakeWordCfg(BaseModel):
    enabled: bool = True
    model: str = "hey_jarvis"
    threshold: float = 0.5
    listen_seconds: float = 8.0


class AudioCfg(BaseModel):
    sample_rate: int = 16000
    wake_word: WakeWordCfg = WakeWordCfg()


class SttCfg(BaseModel):
    type: str = "whisper"
    model: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "int8_float16"


class TtsCfg(BaseModel):
    type: str = "piper"
    voice: str = "de_DE-thorsten-high"


class LocalLlmCfg(BaseModel):
    type: str = "ollama"
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3:8b"
    keep_alive: str = "10m"


class CloudLlmCfg(BaseModel):
    enabled: bool = False
    type: str = "anthropic"
    model: str = ""
    base_url: str = ""
    escalation: Literal["manual", "auto"] = "manual"
    failover: bool = True
    budget_eur_day: float = 1.0
    budget_eur_month: float = 15.0
    allowed_tool_risks: list[str] = Field(default_factory=lambda: ["read", "write"])


class LlmCfg(BaseModel):
    local: LocalLlmCfg = LocalLlmCfg()
    cloud: CloudLlmCfg = CloudLlmCfg()


class ClassifierCfg(BaseModel):
    type: Literal["local", "jev", "llm"] = "local"


class ProvidersCfg(BaseModel):
    stt: SttCfg = SttCfg()
    tts: TtsCfg = TtsCfg()
    llm: LlmCfg = LlmCfg()
    classifier: ClassifierCfg = ClassifierCfg()


class ThresholdCfg(BaseModel):
    fast: float = 0.85
    focused: float = 0.5


class RouterCfg(BaseModel):
    enabled: bool = True
    thresholds: ThresholdCfg = ThresholdCfg()
    confirm_threshold: float = 0.9
    per_intent: dict[str, ThresholdCfg] = Field(default_factory=dict)
    embedding_model: str = "intfloat/multilingual-e5-small"


class McpServerCfg(BaseModel):
    name: str
    enabled: bool = True
    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    risk: str = "read"
    taint: bool = False


class FeedCfg(BaseModel):
    name: str
    url: str


class NewsCfg(BaseModel):
    feeds: list[FeedCfg] = Field(default_factory=list)
    max_items: int = 5


class JarvisConfig(BaseModel):
    server: ServerCfg = ServerCfg()
    language: str = "de"
    location: LocationCfg = LocationCfg()
    persona: str = "Du bist Jarvis. Antworte kurz auf Deutsch."
    gpu: GpuCfg = GpuCfg()
    audio: AudioCfg = AudioCfg()
    providers: ProvidersCfg = ProvidersCfg()
    router: RouterCfg = RouterCfg()
    mcp_servers: list[McpServerCfg] = Field(default_factory=list)
    news: NewsCfg = NewsCfg()
    push: dict[str, Any] = Field(default_factory=dict)
    adapters: dict[str, Any] = Field(default_factory=dict)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ensure_config_dir(config_dir: Path = CONFIG_DIR) -> None:
    """Beim ersten Start Beispiele kopieren und Admin-Token erzeugen."""
    config_dir.mkdir(parents=True, exist_ok=True)
    if EXAMPLES_DIR.exists():
        for example in EXAMPLES_DIR.glob("*.yaml"):
            target = config_dir / example.name
            if not target.exists():
                shutil.copy(example, target)
    secrets_path = config_dir / "secrets.yaml"
    data = _read_yaml(secrets_path)
    if data.get("admin_token", "CHANGE-ME") in ("", "CHANGE-ME"):
        data["admin_token"] = secrets.token_urlsafe(32)
        with secrets_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        os.chmod(secrets_path, 0o600)


def load_config(config_dir: Path = CONFIG_DIR) -> JarvisConfig:
    return JarvisConfig.model_validate(_read_yaml(config_dir / "config.yaml"))


def load_secrets(config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    data = _read_yaml(config_dir / "secrets.yaml")
    # Umgebungsvariablen (z. B. aus dem Unraid-Template) haben Vorrang.
    for key in list(data) + ["admin_token", "anthropic_api_key", "openai_api_key"]:
        env = os.environ.get(f"JARVIS_{key.upper()}")
        if env:
            data[key] = env
    return {k: str(v) for k, v in data.items() if v is not None}


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    return _read_yaml(config_dir / name)
