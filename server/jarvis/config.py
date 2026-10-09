"""Konfiguration laden (YAML) und typisiert bereitstellen.

Aufruf als Modul (im Container als root, vor dem Start der Dienste):
    python -m jarvis.config --init   Beispiele kopieren, Admin-Token erzeugen
    python -m jarvis.config --env    Shell-Exporte für supervisord (Ollama, Autostart)
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_DIR = Path(os.environ.get("JARVIS_CONFIG_DIR", "/config"))
DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", "/data"))
EXAMPLES_DIR = Path(os.environ.get("JARVIS_EXAMPLES_DIR",
                                   Path(__file__).resolve().parents[2] / "config" / "examples"))

_SECRET_RE = re.compile(r"\$\{secret:([A-Za-z0-9_]+)\}")


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="ignore")


class HttpsCfg(_Cfg):
    enabled: bool = True
    port: int = 8443
    certfile: str = ""            # eigenes Zertifikat (z. B. Let's Encrypt), sonst eigene CA
    keyfile: str = ""
    hosts: list[str] = Field(default_factory=list)   # Namen/IPs für das selbst erzeugte Zertifikat


class ServerCfg(_Cfg):
    host: str = "0.0.0.0"
    port: int = 8080
    https: HttpsCfg = HttpsCfg()
    public_url: str = ""          # z. B. https://jarvis.lan:8443 – für Pairing-Links

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "web_port" in data and "port" not in data:
                data["port"] = data["web_port"]
            if data.get("public_base_url") and not data.get("public_url"):
                data["public_url"] = data["public_base_url"]
        return data


class LocationCfg(_Cfg):
    name: str = "Zuhause"
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = "Europe/Berlin"


class GpuCfg(_Cfg):
    comfyui_mode: Literal["off", "on", "auto"] = "off"
    comfyui_container: str = "comfyui"
    unload_after_seconds: int = 60

    @model_validator(mode="before")
    @classmethod
    def _bool_mode(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("comfyui_mode"), bool):
            data = {**data, "comfyui_mode": "on" if data["comfyui_mode"] else "off"}
        return data


class WakeWordCfg(_Cfg):
    enabled: bool = True
    model: str = "hey_jarvis"
    threshold: float = 0.5
    listen_seconds: float = 8.0
    max_listen_seconds: float = 25.0
    follow_up: Literal["off", "question", "always"] = "question"
    follow_up_seconds: float = 6.0


class AudioCfg(_Cfg):
    sample_rate: int = 16000
    wake_word: WakeWordCfg = WakeWordCfg()


STT_TYPES = ("whisper", "openai", "groq", "deepgram", "azure", "google", "elevenlabs", "none")
TTS_TYPES = ("piper", "openai", "elevenlabs", "cartesia", "deepgram", "azure", "google", "none")
CLOUD_LLM_TYPES = ("anthropic", "openai", "google", "mistral", "groq", "openrouter", "deepseek", "openai_compatible")
LOCAL_STT, LOCAL_TTS = {"whisper", "none"}, {"piper", "none"}


class SttCfg(_Cfg):
    type: Literal[STT_TYPES] = "whisper"
    model: str = "large-v3-turbo"     # whisper: large-v3-turbo · openai: gpt-4o-transcribe · groq: whisper-large-v3-turbo · deepgram: nova-3
    device: str = "cuda"              # nur whisper
    compute_type: str = "int8_float16"
    base_url: str = ""                # openai: eigener/kompatibler Endpunkt
    region: str = ""                  # azure
    api_key_secret: str = ""          # abweichender Name in secrets.yaml

    @property
    def cloud(self) -> bool:
        return self.type not in LOCAL_STT and not _is_local(self.base_url)


class TtsCfg(_Cfg):
    type: Literal[TTS_TYPES] = "piper"
    voice: str = "de_DE-thorsten-high"   # piper: Stimme · Cloud: Stimmen-ID des Anbieters
    model: str = ""                      # z. B. eleven_flash_v2_5, sonic-2, gpt-4o-mini-tts
    openai_voice: str = "nova"           # alt (0.2): Stimme für type=openai
    region: str = ""                     # azure
    api_key_secret: str = ""

    @property
    def cloud(self) -> bool:
        return self.type not in LOCAL_TTS


class LocalLlmCfg(_Cfg):
    enabled: bool = True
    type: str = "ollama"
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3:8b"
    keep_alive: str = "10m"
    num_ctx: int = 8192
    think: bool = False           # Denkmodus aus: deutlich schnellere erste Silbe
    temperature: float | None = None


class CloudLlmCfg(_Cfg):
    enabled: bool = False
    type: Literal[CLOUD_LLM_TYPES] = "anthropic"
    model: str = ""
    base_url: str = ""                # openai_compatible (z. B. Together, LM Studio, vLLM) oder eigener Endpunkt
    api_key_secret: str = ""          # abweichender Name in secrets.yaml
    escalation: Literal["manual", "auto"] = "manual"
    auto_min_words: int = 14      # escalation=auto: lange offene Fragen gehen an die Cloud
    failover: bool = True
    budget_eur_day: float = 1.0
    budget_eur_month: float = 15.0
    price_input_eur_per_mtok: float = 3.0
    price_output_eur_per_mtok: float = 15.0
    allowed_tool_risks: list[str] = Field(default_factory=lambda: ["read", "write"])


class LlmCfg(_Cfg):
    primary: Literal["local", "cloud"] = "local"   # wer normale Fragen beantwortet
    local: LocalLlmCfg = LocalLlmCfg()
    cloud: CloudLlmCfg = CloudLlmCfg()
    context_turns: int = 10       # so viele Wechsel bleiben im Gesprächskontext


class ClassifierCfg(_Cfg):
    type: Literal["local", "jev"] = "local"


class ProvidersCfg(_Cfg):
    stt: SttCfg = SttCfg()
    tts: TtsCfg = TtsCfg()
    llm: LlmCfg = LlmCfg()
    classifier: ClassifierCfg = ClassifierCfg()


class ThresholdCfg(_Cfg):
    fast: float = 0.85
    focused: float = 0.5


class RouterCfg(_Cfg):
    enabled: bool = True
    thresholds: ThresholdCfg = ThresholdCfg()
    confirm_threshold: float = 0.9
    slot_boost: float = 0.1           # Pflichtangaben erkannt → Schnellweg schon ab fast - slot_boost
    confirm_timeout: float = 20.0     # Sekunden, danach verfällt eine offene Bestätigung
    dialog_timeout: float = 30.0      # Sekunden für Rückfragen (fehlende Angaben)
    per_intent: dict[str, ThresholdCfg] = Field(default_factory=dict)
    embedding_model: str = "intfloat/multilingual-e5-small"
    similarity_floor: float | None = None   # None = passend zum Modell
    similarity_ref: float | None = None


class McpServerCfg(_Cfg):
    name: str
    enabled: bool = True
    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tools: list[str] | None = None            # Allowlist – None = alle (nicht empfohlen)
    risk: str = "read"
    tool_risks: dict[str, str] = Field(default_factory=dict)
    taint: bool = False


class FeedCfg(_Cfg):
    name: str
    url: str


class NewsCfg(_Cfg):
    feeds: list[FeedCfg] = Field(default_factory=list)
    max_items: int = 5


class SearchCfg(_Cfg):
    provider: Literal["searxng", "brave", "tavily", "none"] = "searxng"   # searxng = MCP-Server (lokal)
    max_results: int = 5
    api_key_secret: str = ""


class MemoryCfg(_Cfg):
    enabled: bool = True
    prompt_items: int = 20


class CalendarCfg(_Cfg):
    enabled: bool = False
    url: str = ""                 # z. B. https://cloud.example.lan/remote.php/dav
    username: str = ""
    password_secret: str = "caldav_password"
    calendars: list[str] = Field(default_factory=list)   # leer = alle
    default_calendar: str = ""
    verify_tls: bool = True


class HomeAssistantCfg(_Cfg):
    enabled: bool = False
    url: str = ""                     # z. B. http://homeassistant.local:8123
    token_secret: str = "homeassistant_token"
    entities: list[str] = Field(default_factory=list)   # Kacheln im Dashboard, z. B. light.wohnzimmer
    verify_tls: bool = True


class NtfyCfg(_Cfg):
    enabled: bool = False
    base_url: str = "https://ntfy.sh"
    topic: str = ""
    token_secret: str = "ntfy_token"
    kinds: list[str] = Field(default_factory=lambda: ["timer", "alarm", "reminder"])
    only_when_offline: bool = True


class PushCfg(_Cfg):
    ntfy: NtfyCfg = NtfyCfg()


class TelegramCfg(_Cfg):
    enabled: bool = False
    allowed_user_ids: list[int] = Field(default_factory=list)


class MatrixCfg(_Cfg):
    enabled: bool = False
    homeserver: str = ""
    user_id: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class AdaptersCfg(_Cfg):
    telegram: TelegramCfg = TelegramCfg()
    matrix: MatrixCfg = MatrixCfg()


class PrivacyCfg(_Cfg):
    retention_days: int = 30      # Router-/Aktionsprotokoll danach löschen (0 = nie)
    log_text: bool = True         # False: Sätze im Router-Log nicht speichern


class FirmwareCfg(_Cfg):
    auto_update: bool = False     # Geräte automatisch per OTA aktualisieren


class JarvisConfig(_Cfg):
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
    search: SearchCfg = SearchCfg()
    memory: MemoryCfg = MemoryCfg()
    calendar: CalendarCfg = CalendarCfg()
    homeassistant: HomeAssistantCfg = HomeAssistantCfg()
    push: PushCfg = PushCfg()
    adapters: AdaptersCfg = AdaptersCfg()
    privacy: PrivacyCfg = PrivacyCfg()
    firmware: FirmwareCfg = FirmwareCfg()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _interpolate(value: Any, secrets_map: dict[str, str]) -> Any:
    """`${secret:name}` in Zeichenketten durch Werte aus secrets.yaml ersetzen."""
    if isinstance(value, str):
        return _SECRET_RE.sub(lambda m: secrets_map.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _interpolate(v, secrets_map) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, secrets_map) for v in value]
    return value


def ensure_config_dir(config_dir: Path = CONFIG_DIR) -> str | None:
    """Beim ersten Start Beispiele kopieren und Admin-Token erzeugen (gibt einen neuen Token zurück).

    Im Container läuft das als root im Entrypoint.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    if EXAMPLES_DIR.exists():
        for example in EXAMPLES_DIR.glob("*.yaml"):
            target = config_dir / example.name
            if not target.exists():
                shutil.copy(example, target)
    secrets_path = config_dir / "secrets.yaml"
    data = _read_yaml(secrets_path)
    if data.get("admin_token", "CHANGE-ME") in ("", "CHANGE-ME", None):
        data["admin_token"] = secrets.token_urlsafe(32)
        with secrets_path.open("w", encoding="utf-8") as f:
            f.write("# Niemals committen! Admin-Token wurde beim ersten Start erzeugt.\n")
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.chmod(secrets_path, 0o600)
        return data["admin_token"]
    return None


def secrets_with_env(data: dict[str, Any]) -> dict[str, str]:
    """Umgebungsvariablen (z. B. aus dem Unraid-Template) haben Vorrang: JARVIS_<NAME>."""
    data = dict(data)
    names = set(data) | {"admin_token", "telegram_bot_token", "matrix_password", "homeassistant_token",
                         "caldav_password", "ntfy_token", "typesafe_api_key", *SECRET_NAMES.values()}
    for key in names:
        env = os.environ.get(f"JARVIS_{key.upper()}")
        if env:
            data[key] = env
    return {k: str(v) for k, v in data.items() if v not in (None, "")}


def load_secrets(config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    return secrets_with_env(_read_yaml(config_dir / "secrets.yaml"))


def load_config(config_dir: Path = CONFIG_DIR, secrets_map: dict[str, str] | None = None) -> JarvisConfig:
    raw = _read_yaml(config_dir / "config.yaml")
    if secrets_map is None:
        secrets_map = load_secrets(config_dir)
    cfg = JarvisConfig.model_validate(_interpolate(raw, secrets_map))
    hosts = os.environ.get("JARVIS_HOSTS", "")
    if hosts:
        cfg.server.https.hosts = [*cfg.server.https.hosts, *[h.strip() for h in hosts.split(",") if h.strip()]]
    if os.environ.get("JARVIS_PUBLIC_URL"):
        cfg.server.public_url = os.environ["JARVIS_PUBLIC_URL"]
    return cfg


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    return _read_yaml(config_dir / name)


def _is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1")


# Standardnamen der API-Schlüssel in secrets.yaml (bzw. JARVIS_<NAME> als Umgebungsvariable)
SECRET_NAMES = {
    "anthropic": "anthropic_api_key", "openai": "openai_api_key", "openai_compatible": "openai_api_key",
    "google": "google_api_key", "mistral": "mistral_api_key", "groq": "groq_api_key",
    "openrouter": "openrouter_api_key", "deepseek": "deepseek_api_key", "deepgram": "deepgram_api_key",
    "elevenlabs": "elevenlabs_api_key", "cartesia": "cartesia_api_key", "azure": "azure_speech_key",
    "google_tts": "google_credentials", "google_stt": "google_credentials",
    "brave": "brave_api_key", "tavily": "tavily_api_key",
}


def secret_name(kind: str, override: str = "") -> str:
    return override or SECRET_NAMES.get(kind, f"{kind}_api_key")


def cloud_services(cfg: JarvisConfig) -> list[str]:
    """Welche Rollen laufen über externe Dienste? (für Hinweise in den Clients)"""
    p = cfg.providers
    out = []
    if p.stt.cloud:
        out.append(f"Spracherkennung: {p.stt.type}")
    if p.tts.cloud:
        out.append(f"Sprachausgabe: {p.tts.type}")
    if p.llm.cloud.enabled:
        role = "Standard" if p.llm.primary == "cloud" else "auf Wunsch/Ausfall"
        out.append(f"Sprachmodell: {p.llm.cloud.type} ({role})")
    if cfg.search.provider in ("brave", "tavily"):
        out.append(f"Websuche: {cfg.search.provider}")
    return out


PROVIDER_LABELS = {
    "anthropic": "Anthropic", "openai": "OpenAI", "google": "Google", "mistral": "Mistral", "groq": "Groq",
    "openrouter": "OpenRouter", "deepseek": "DeepSeek", "openai_compatible": "OpenAI-kompatibel",
    "deepgram": "Deepgram", "elevenlabs": "ElevenLabs", "cartesia": "Cartesia", "azure": "Azure",
    "brave": "Brave", "tavily": "Tavily",
}


def config_warnings(cfg: JarvisConfig, secrets_map: dict[str, str]) -> list[str]:
    """Hinweise für die Verwaltung: was fehlt oder nicht zusammenpasst – mit dem Ort in den Einstellungen."""
    w: list[str] = []
    label = PROVIDER_LABELS.get
    if cfg.location.latitude == 0 and cfg.location.longitude == 0:
        w.append("Standort ist nicht gesetzt – Wetter stimmt nicht (Einstellungen → Allgemein).")
    p = cfg.providers
    cloud = p.llm.cloud
    llm = "(Einstellungen → Sprachmodell)"
    if cloud.enabled and not cloud.model:
        w.append(f"Cloud-Sprachmodell ist eingeschaltet, aber kein Modell gewählt {llm}.")
    key = secret_name(cloud.type, cloud.api_key_secret)
    if cloud.enabled and key not in secrets_map and not (cloud.type == "openai_compatible" and cloud.base_url):
        w.append(f"Cloud-Sprachmodell {label(cloud.type, cloud.type)}: API-Schlüssel fehlt {llm}.")
    if cloud.type == "openai_compatible" and cloud.enabled and not cloud.base_url:
        w.append(f"OpenAI-kompatibler Anbieter braucht eine Adresse {llm}.")
    if p.llm.primary == "cloud" and not cloud.enabled:
        w.append(f"„Cloud zuerst“ ist gewählt, aber kein Cloud-Modell eingeschaltet – Jarvis nutzt das lokale {llm}.")
    if not p.llm.local.enabled and not cloud.enabled:
        w.append(f"Weder lokales noch Cloud-Sprachmodell aktiv – nur einfache Befehle funktionieren {llm}.")
    for role, c in (("Spracherkennung", p.stt), ("Sprachausgabe", p.tts)):
        if c.cloud:
            key = secret_name(f"google_{'stt' if c is p.stt else 'tts'}" if c.type == "google" else c.type,
                              c.api_key_secret)
            if key not in secrets_map and not (c.type == "openai" and c.base_url):
                w.append(f"{role} über {label(c.type, c.type)}: API-Schlüssel fehlt (Einstellungen → Sprache).")
            if c.type == "azure" and not c.region:
                w.append(f"{role} über Azure braucht eine Region (Einstellungen → Sprache).")
    if cfg.search.provider in ("brave", "tavily"):
        key = secret_name(cfg.search.provider, cfg.search.api_key_secret)
        if key not in secrets_map:
            w.append(f"Websuche über {label(cfg.search.provider)}: API-Schlüssel fehlt (Einstellungen → Suche).")
    for m in cfg.mcp_servers:
        if m.enabled and m.name != "docker" and m.tools is None:
            w.append(f"MCP-Server {m.name}: alle Werkzeuge freigegeben – besser eine Auswahl festlegen "
                     "(Einstellungen → Werkzeuge).")
        if m.enabled and m.transport != "stdio" and not m.url:
            w.append(f"MCP-Server {m.name}: Adresse fehlt (Einstellungen → Werkzeuge).")
    if cfg.calendar.enabled and (not cfg.calendar.url or cfg.calendar.password_secret not in secrets_map):
        w.append("Kalender ist eingeschaltet, aber Adresse oder Passwort fehlen (Einstellungen → Kalender).")
    ha = cfg.homeassistant
    if ha.enabled and (not ha.url or ha.token_secret not in secrets_map):
        w.append("Home Assistant ist eingeschaltet, aber Adresse oder Token fehlen (Einstellungen → Smart Home).")
    if ha.enabled and not ha.entities:
        w.append("Home Assistant: noch keine Geräte ausgewählt – Dashboard und CYD zeigen nichts "
                 "(Einstellungen → Smart Home).")
    if cfg.push.ntfy.enabled and not cfg.push.ntfy.topic:
        w.append("ntfy ist eingeschaltet, aber das Thema fehlt (Einstellungen → Benachrichtigungen).")
    if cfg.adapters.telegram.enabled and "telegram_bot_token" not in secrets_map:
        w.append("Telegram ist eingeschaltet, aber der Bot-Token fehlt (Einstellungen → Benachrichtigungen).")
    if cfg.adapters.telegram.enabled and not cfg.adapters.telegram.allowed_user_ids:
        w.append("Telegram ist eingeschaltet, aber niemand ist freigegeben (Einstellungen → Benachrichtigungen).")
    if cfg.adapters.matrix.enabled and "matrix_password" not in secrets_map:
        w.append("Matrix ist eingeschaltet, aber das Passwort fehlt (Einstellungen → Benachrichtigungen).")
    if not cfg.server.https.enabled:
        w.append("HTTPS ist aus – Browser erlauben das Mikrofon dann nur über localhost "
                 "(Einstellungen → Netzwerk & Sicherheit).")
    return w


def shell_env(cfg: JarvisConfig) -> dict[str, str]:
    """Werte für supervisord: Ollama-Parameter und welche eingebetteten Dienste starten."""
    local = cfg.providers.llm.local
    embedded = os.environ.get("JARVIS_EMBEDDED_OLLAMA", "auto").lower()
    ollama = local.enabled and (_is_local(local.base_url) if embedded == "auto" else embedded in ("1", "true", "yes"))
    searx_urls = [m.env.get("SEARXNG_URL", "") for m in cfg.mcp_servers
                  if m.enabled and m.name == "searxng" and cfg.search.provider == "searxng"]
    embedded_s = os.environ.get("JARVIS_EMBEDDED_SEARXNG", "auto").lower()
    searx = any(_is_local(u) for u in searx_urls) if embedded_s == "auto" else embedded_s in ("1", "true", "yes")
    keep_alive = "1m" if cfg.gpu.comfyui_mode == "on" else local.keep_alive
    return {
        "OLLAMA_KEEP_ALIVE": keep_alive,
        "OLLAMA_CONTEXT_LENGTH": str(local.num_ctx),
        "OLLAMA_MODEL": local.model,
        "JARVIS_OLLAMA_AUTOSTART": "true" if ollama else "false",
        "JARVIS_SEARXNG_AUTOSTART": "true" if searx else "false",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Mini-Jarvis Konfiguration")
    ap.add_argument("--init", action="store_true", help="Beispiele kopieren, Admin-Token erzeugen")
    ap.add_argument("--env", action="store_true", help="Shell-Exporte für supervisord ausgeben")
    ap.add_argument("--config-dir", default=str(CONFIG_DIR))
    a = ap.parse_args()
    config_dir = Path(a.config_dir)
    if a.init:
        token = ensure_config_dir(config_dir)
        if token and not os.environ.get("JARVIS_ADMIN_TOKEN"):
            line = "=" * 72
            print(f"{line}\n Mini-Jarvis: Admin-Token für die Verwaltung (erscheint nur beim ersten Start)\n\n"
                  f"   {token}\n\n Anmelden unter https://<server>:8443/admin.html – später unter „System“ neu erzeugbar.\n{line}",
                  flush=True)
    if a.env:
        try:
            cfg = load_config(config_dir)
        except Exception as e:  # noqa: BLE001 – kaputte Config darf den Start nicht verhindern
            print(f"echo 'Warnung: config.yaml ungültig ({e}) – Standardwerte'", file=sys.stdout)
            cfg = JarvisConfig()
        for k, v in shell_env(cfg).items():
            safe = re.sub(r"[^A-Za-z0-9_.:/-]", "", v)
            print(f"export {k}='{safe}'")


if __name__ == "__main__":
    main()
