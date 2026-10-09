"""Einstellungen aus der Verwaltung: config.yaml, secrets.yaml, scripts.yaml und whitelist.yaml
lesen und schreiben – niemand muss dafür YAML anfassen.

- ruamel.yaml schreibt rund: Kommentare, Reihenfolge und Anführungszeichen bleiben erhalten.
- Jede Änderung wird vor dem Schreiben gegen das Konfigurationsmodell geprüft (deutsche Meldungen).
- Geheimnisse verlassen den Server nie; die Verwaltung sieht nur, ob sie gesetzt sind.
- Vor jedem Schreiben landet die alte Datei unter backups/ (die letzten 20 je Datei).
"""

from __future__ import annotations

import io
import os
import re
import time
import zoneinfo
from functools import lru_cache
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, LiteralScalarString, SingleQuotedScalarString

from jarvis.config import SECRET_NAMES, JarvisConfig, _interpolate, shell_env

READONLY_ENV = "JARVIS_CONFIG_READONLY"
BACKUPS_KEEP = 20
SECRET_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SCRIPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
MCP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
CONTAINER_ACTIONS = ("status", "start", "stop", "restart")

# Ports legt die Port-Zuordnung des Containers fest – aus der Verwaltung heraus nicht änderbar.
LOCKED_PATHS = {
    "server.host": "Die Adresse legt der Container fest.",
    "server.port": "Den Port legt die Port-Zuordnung des Containers fest.",
    "server.https.port": "Den HTTPS-Port legt die Port-Zuordnung des Containers fest.",
}

# Bekannte Geheimnisse mit Beschriftung (weitere Namen sind erlaubt, z. B. für eigene MCP-Server)
SECRET_LABELS = {
    "anthropic_api_key": "Anthropic (Claude)", "openai_api_key": "OpenAI", "google_api_key": "Google Gemini",
    "mistral_api_key": "Mistral", "groq_api_key": "Groq", "openrouter_api_key": "OpenRouter",
    "deepseek_api_key": "DeepSeek", "deepgram_api_key": "Deepgram", "elevenlabs_api_key": "ElevenLabs",
    "cartesia_api_key": "Cartesia", "azure_speech_key": "Azure Speech",
    "google_credentials": "Google Cloud (Dienstkonto-JSON)", "brave_api_key": "Brave Search",
    "tavily_api_key": "Tavily", "homeassistant_token": "Home Assistant (Langzeit-Token)",
    "caldav_password": "Kalender (CalDAV-Passwort)", "ntfy_token": "ntfy (Zugriffstoken)",
    "telegram_bot_token": "Telegram-Bot", "matrix_password": "Matrix-Passwort", "typesafe_api_key": "Jev (Klassifikator)",
}

# Was eine Änderung braucht, die über einen Neustart von Jarvis hinausgeht (supervisord-Umgebung)
CONTAINER_ENV = {
    "JARVIS_OLLAMA_AUTOSTART": "eingebautes Ollama an/aus",
    "JARVIS_SEARXNG_AUTOSTART": "eingebaute Websuche (SearXNG) an/aus",
    "OLLAMA_KEEP_ALIVE": "Ollama: Modell im Speicher halten",
    "OLLAMA_CONTEXT_LENGTH": "Ollama: Kontextlänge",
}


class SettingsError(Exception):
    """Fehler mit Meldung für die Verwaltung; errors = [{path, message}] für einzelne Felder."""

    def __init__(self, message: str, errors: list[dict] | None = None, status: int = 400):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.status = status


# --------------------------------------------------------------------------- YAML rundschreiben
def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    y.representer.add_representer(type(None), lambda r, _d: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def plain(node: Any) -> Any:
    """ruamel-Knoten → einfache Python-Werte (für Prüfung und JSON)."""
    if isinstance(node, dict):
        return {str(k): plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [plain(v) for v in node]
    if isinstance(node, bool) or node is None:
        return node
    if isinstance(node, int):
        return int(node)
    if isinstance(node, float):
        return float(node)
    if isinstance(node, str):
        return str(node)
    return node


def _scalar_list(value: list) -> bool:
    return all(isinstance(v, (str, int, float, bool)) for v in value) and len(repr(value)) <= 100


def to_node(value: Any, old: Any = None) -> Any:
    """Einfache Werte → ruamel-Knoten; kurze Listen in Zeilenform, mehrzeilige Texte als Block.

    Unveränderte Werte behalten ihre Schreibweise in der Datei."""
    if old is not None and plain(old) == value and type(plain(old)) is type(value):
        return old
    if isinstance(value, dict):
        m = CommentedMap()
        for k, v in value.items():
            m[k] = to_node(v, old.get(k) if isinstance(old, dict) else None)
        return m
    if isinstance(value, list):
        seq = CommentedSeq(to_node(v) for v in value)
        if _scalar_list(value):
            seq.fa.set_flow_style()
        return seq
    if isinstance(value, str):
        if "\n" in value.strip("\n"):
            return LiteralScalarString(value if value.endswith("\n") else value + "\n")
        if isinstance(old, (DoubleQuotedScalarString, SingleQuotedScalarString)) and str(old):
            return type(old)(value)              # Stil der Datei beibehalten
        if value != value.strip() or not _reads_back(value):
            return DoubleQuotedScalarString(value)
    return value


def _reads_back(value: str) -> bool:
    """Liest PyYAML (YAML 1.1, wie der Kern) den Text ohne Anführungszeichen unverändert zurück?"""
    try:
        return yaml.safe_load(value) == value
    except yaml.YAMLError:
        return False


_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):")


def _header_start(lines: list[str], i: int) -> int:
    while i > 0 and lines[i - 1].startswith("#"):
        i -= 1
    return i


def _keep_section_gaps(old_text: str, new_text: str) -> str:
    """Leerzeilen vor Abschnitten wie vorher – ruamel verliert sie, wenn die Liste davor ersetzt wurde."""
    old = old_text.splitlines()
    gap = {}
    for i, line in enumerate(old):
        m = _TOP_KEY.match(line)
        if m:
            j = _header_start(old, i)
            gap[m.group(1)] = j > 0 and old[j - 1].strip() == ""
    new = new_text.splitlines()
    inserts = []
    for i, line in enumerate(new):
        m = _TOP_KEY.match(line)
        if m and gap.get(m.group(1)):
            j = _header_start(new, i)
            if j > 0 and new[j - 1].strip() != "":
                inserts.append(j)
    for j in reversed(inserts):
        new.insert(j, "")
    return "\n".join(new) + ("\n" if new_text.endswith("\n") else "")


class ConfigFiles:
    """Lesen/Schreiben der Dateien in /config mit Sicherung und atomarem Ersetzen."""

    def __init__(self, config_dir: Path):
        self.dir = Path(config_dir)

    def path(self, name: str) -> Path:
        return self.dir / name

    def readonly_reason(self) -> str | None:
        if os.environ.get(READONLY_ENV, "").lower() in ("1", "true", "yes"):
            return f"Die Einstellungen sind gesperrt ({READONLY_ENV}=true in der Container-Vorlage)."
        if not os.access(self.dir, os.W_OK):
            return "Jarvis darf den Konfigurationsordner nicht beschreiben (Rechte von /config prüfen)."
        for name in ("config.yaml", "secrets.yaml"):
            p = self.path(name)
            if p.exists() and not os.access(p, os.W_OK):
                return f"Jarvis darf {name} nicht beschreiben (Rechte prüfen)."
        return None

    def load(self, name: str) -> CommentedMap:
        p = self.path(name)
        if not p.exists():
            return CommentedMap()
        try:
            data = _yaml().load(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 – Syntaxfehler verständlich melden
            raise SettingsError(f"{name} lässt sich nicht lesen: {e}") from e
        if data is None:
            return CommentedMap()
        if not isinstance(data, CommentedMap):
            raise SettingsError(f"{name} hat ein unerwartetes Format.")
        return data

    def save(self, name: str, data: CommentedMap) -> None:
        reason = self.readonly_reason()
        if reason:
            raise SettingsError(reason, status=409)
        target = self.path(name)
        buf = io.StringIO()
        _yaml().dump(data, buf)
        text = buf.getvalue()
        mode = 0o600 if name == "secrets.yaml" else 0o644
        if target.exists():
            mode = target.stat().st_mode & 0o777
            before = target.read_text(encoding="utf-8")
            text = _keep_section_gaps(before, text)
            if before == text:
                return
            self._backup(target)
        tmp = target.with_name(f".{name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, mode)
        os.replace(tmp, target)

    def _backup(self, target: Path) -> None:
        folder = self.dir / "backups"
        try:
            folder.mkdir(mode=0o770, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            dst = folder / f"{target.name}.{stamp}"
            dst.write_bytes(target.read_bytes())
            os.chmod(dst, target.stat().st_mode & 0o777)
            old = sorted(folder.glob(f"{target.name}.*"))
            for p in old[:-BACKUPS_KEEP]:
                p.unlink(missing_ok=True)
        except OSError:
            pass                             # Sicherung ist nett, aber kein Grund, nicht zu speichern


# --------------------------------------------------------------------------- config.yaml
def check_path(path: str) -> None:
    """Nur Pfade erlauben, die es im Konfigurationsmodell gibt (Listen/Dicts nur als Ganzes)."""
    cls: Any = JarvisConfig
    parts = path.split(".")
    for i, part in enumerate(parts):
        fields = cls.model_fields if isinstance(cls, type) and issubclass(cls, BaseModel) else None
        if not fields or part not in fields:
            raise SettingsError(f"Unbekannte Einstellung: {path}", [{"path": path, "message": "Unbekannte Einstellung"}])
        ann = fields[part].annotation
        cls = ann if isinstance(ann, type) and issubclass(ann, BaseModel) else None
        if cls is None and i < len(parts) - 1:
            raise SettingsError(f"Unbekannte Einstellung: {path}", [{"path": path, "message": "Unbekannte Einstellung"}])


MASK = "***"
_PLACEHOLDER_RE = re.compile(r"^\$\{secret:[A-Za-z0-9_]+\}$|^Bearer \$\{secret:[A-Za-z0-9_]+\}$")
_SECRETISH = ("key", "token", "secret", "pass", "auth")


def _maskable(section: str, key: str, value: Any) -> bool:
    if not isinstance(value, str) or not value or _PLACEHOLDER_RE.match(value):
        return False
    return section == "headers" or any(w in key.lower() for w in _SECRETISH)


def config_values(files: ConfigFiles) -> dict:
    """Werte so, wie sie in config.yaml stehen (Platzhalter ${secret:…} bleiben stehen), ergänzt um Standards.

    Wörtlich eingetragene Zugangsdaten in MCP-Headern/-Umgebung werden maskiert."""
    raw = files.load("config.yaml")
    try:
        values = JarvisConfig.model_validate(plain(raw)).model_dump(mode="json")
    except ValidationError as e:
        raise SettingsError("config.yaml enthält ungültige Werte.", _errors(e)) from e
    for m in values.get("mcp_servers", []):
        for section in ("headers", "env"):
            m[section] = {k: MASK if _maskable(section, k, v) else v for k, v in (m.get(section) or {}).items()}
    return values


def _unmask_mcp(raw: CommentedMap, servers: list) -> list:
    """Unveränderte, maskierte Werte („***“) durch die gespeicherten ersetzen."""
    old = {str(m.get("name")): m for m in raw.get("mcp_servers") or [] if isinstance(m, dict)}
    out = []
    for m in servers:
        m = dict(m)
        prev = old.get(str(m.get("name")), {})
        for section in ("headers", "env"):
            if isinstance(m.get(section), dict):
                m[section] = {k: (plain((prev.get(section) or {}).get(k, "")) if v == MASK else v)
                              for k, v in m[section].items()}
        out.append(m)
    return out


def _list_model(path: str) -> type[BaseModel] | None:
    """Modell der Listeneinträge (z. B. mcp_servers → McpServerCfg), sonst None."""
    cls: Any = JarvisConfig
    ann: Any = None
    for part in path.split("."):
        ann = cls.model_fields[part].annotation
        cls = ann if isinstance(ann, type) and issubclass(ann, BaseModel) else None
    if get_origin(ann) is list:
        (item,) = get_args(ann)
        if isinstance(item, type) and issubclass(item, BaseModel):
            return item
    return None


def _merge_items(old: Any, items: list, model: type[BaseModel]) -> CommentedSeq:
    """Listen aus Objekten (MCP-Server, Feeds): vorhandene Einträge (gleicher Name) samt Kommentaren
    weiterverwenden und Standardwerte nicht unnötig ausschreiben."""
    defaults = {k: f.get_default(call_default_factory=True) for k, f in model.model_fields.items() if not f.is_required()}
    previous = {str(m.get("name")): m for m in old if isinstance(m, CommentedMap)} if isinstance(old, list) else {}
    out = CommentedSeq()
    for item in items:
        prev = previous.get(str(item.get("name")))
        node = prev if prev is not None else CommentedMap()
        for k, v in item.items():
            if k not in node and k in defaults and plain(v) == defaults[k]:
                continue
            node[k] = to_node(v, node.get(k))
        out.append(node)
    return out


def apply_changes(raw: CommentedMap, changes: dict[str, Any]) -> None:
    for path, value in changes.items():
        check_path(path)
        if path in LOCKED_PATHS:
            raise SettingsError(LOCKED_PATHS[path], [{"path": path, "message": LOCKED_PATHS[path]}])
        parts = path.split(".")
        node = raw
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = CommentedMap()
            node = node[part]
        key = parts[-1]
        if path == "mcp_servers" and isinstance(value, list):
            value = _unmask_mcp(raw, value)
        model = _list_model(path)
        if value is None:
            node.pop(key, None)             # zurück auf den Standard
        elif model is not None and isinstance(value, list) and all(isinstance(v, dict) for v in value):
            node[key] = _merge_items(node.get(key), value, model)
        else:
            node[key] = to_node(value, node.get(key))


def _german(err: dict) -> str:
    t = err.get("type", "")
    ctx = err.get("ctx") or {}
    if t == "literal_error":
        return f"Ungültige Auswahl – erlaubt: {ctx.get('expected', '')}".rstrip(" –:")
    if t in ("int_parsing", "int_type", "int_from_float"):
        return "Bitte eine ganze Zahl eingeben."
    if t in ("float_parsing", "float_type"):
        return "Bitte eine Zahl eingeben."
    if t in ("bool_parsing", "bool_type"):
        return "Bitte ja oder nein wählen."
    if t == "string_type":
        return "Bitte Text eingeben."
    if t in ("list_type", "dict_type"):
        return "Ungültiges Format."
    if t == "missing":
        return "Pflichtangabe fehlt."
    return err.get("msg", "Ungültiger Wert.")


def _errors(e: ValidationError) -> list[dict]:
    return [{"path": ".".join(str(x) for x in err["loc"]), "message": _german(err)} for err in e.errors()]


@lru_cache(maxsize=1)
def timezones() -> list[str]:
    return sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/")))


def _url_ok(url: str) -> bool:
    return not url or bool(re.match(r"^https?://[^\s/]+", url))


def semantic_errors(cfg: JarvisConfig) -> list[dict]:
    """Was das Modell nicht prüft, aber sicher falsch ist."""
    out: list[dict] = []

    def bad(path: str, message: str) -> None:
        out.append({"path": path, "message": message})

    loc = cfg.location
    if loc.timezone not in timezones() and loc.timezone != "UTC":
        bad("location.timezone", "Unbekannte Zeitzone – bitte aus der Liste wählen.")
    if not -90 <= loc.latitude <= 90:
        bad("location.latitude", "Breitengrad liegt zwischen -90 und 90.")
    if not -180 <= loc.longitude <= 180:
        bad("location.longitude", "Längengrad liegt zwischen -180 und 180.")
    unit = {"router.thresholds.fast": cfg.router.thresholds.fast,
            "router.thresholds.focused": cfg.router.thresholds.focused,
            "router.confirm_threshold": cfg.router.confirm_threshold,
            "audio.wake_word.threshold": cfg.audio.wake_word.threshold}
    for path, v in unit.items():
        if not 0 <= v <= 1:
            bad(path, "Wert zwischen 0 und 1.")
    ranges = {
        "providers.llm.context_turns": (cfg.providers.llm.context_turns, 1, 50),
        "providers.llm.local.num_ctx": (cfg.providers.llm.local.num_ctx, 512, 262144),
        "search.max_results": (cfg.search.max_results, 1, 20),
        "news.max_items": (cfg.news.max_items, 1, 20),
        "memory.prompt_items": (cfg.memory.prompt_items, 0, 200),
        "privacy.retention_days": (cfg.privacy.retention_days, 0, 3650),
        "audio.wake_word.listen_seconds": (cfg.audio.wake_word.listen_seconds, 1, 60),
        "audio.wake_word.max_listen_seconds": (cfg.audio.wake_word.max_listen_seconds, 2, 120),
        "audio.wake_word.follow_up_seconds": (cfg.audio.wake_word.follow_up_seconds, 1, 60),
        "providers.llm.cloud.budget_eur_day": (cfg.providers.llm.cloud.budget_eur_day, 0, 10000),
        "providers.llm.cloud.budget_eur_month": (cfg.providers.llm.cloud.budget_eur_month, 0, 100000),
        "providers.llm.cloud.price_input_eur_per_mtok": (cfg.providers.llm.cloud.price_input_eur_per_mtok, 0, 10000),
        "providers.llm.cloud.price_output_eur_per_mtok": (cfg.providers.llm.cloud.price_output_eur_per_mtok, 0, 10000),
        "gpu.unload_after_seconds": (cfg.gpu.unload_after_seconds, 0, 86400),
    }
    for path, (v, lo, hi) in ranges.items():
        if not lo <= v <= hi:
            bad(path, f"Erlaubt sind {lo} bis {hi}.")
    urls = {
        "providers.llm.local.base_url": cfg.providers.llm.local.base_url,
        "providers.llm.cloud.base_url": cfg.providers.llm.cloud.base_url,
        "providers.stt.base_url": cfg.providers.stt.base_url,
        "homeassistant.url": cfg.homeassistant.url, "calendar.url": cfg.calendar.url,
        "push.ntfy.base_url": cfg.push.ntfy.base_url, "adapters.matrix.homeserver": cfg.adapters.matrix.homeserver,
        "server.public_url": cfg.server.public_url,
    }
    for path, url in urls.items():
        if not _url_ok(url):
            bad(path, "Adresse muss mit http:// oder https:// beginnen.")
    for i, f in enumerate(cfg.news.feeds):
        if not f.name.strip():
            bad(f"news.feeds.{i}.name", "Name fehlt.")
        if not _url_ok(f.url) or not f.url:
            bad(f"news.feeds.{i}.url", "Adresse muss mit http:// oder https:// beginnen.")
    for e in cfg.homeassistant.entities:
        if not ENTITY_RE.match(e):
            bad("homeassistant.entities", f"„{e}“ ist keine Entitäts-ID (z. B. light.wohnzimmer).")
    seen: set[str] = set()
    for i, m in enumerate(cfg.mcp_servers):
        if not MCP_NAME_RE.match(m.name):
            bad(f"mcp_servers.{i}.name", "Name: Kleinbuchstaben, Ziffern, - und _.")
        if m.name in seen:
            bad(f"mcp_servers.{i}.name", "Name ist doppelt.")
        seen.add(m.name)
        if m.enabled and m.transport == "stdio" and not m.command:
            bad(f"mcp_servers.{i}.command", "Befehl fehlt.")
        if m.enabled and m.transport != "stdio" and (not m.url or not _url_ok(m.url)):
            bad(f"mcp_servers.{i}.url", "Adresse muss mit http:// oder https:// beginnen.")
        if m.risk not in ("read", "write", "critical", "mixed"):
            bad(f"mcp_servers.{i}.risk", "Risiko: read, write, critical oder mixed.")
    for r in cfg.providers.llm.cloud.allowed_tool_risks:
        if r not in ("read", "write", "critical"):
            bad("providers.llm.cloud.allowed_tool_risks", "Erlaubt sind read, write und critical.")
    return out


def validate(raw: CommentedMap, secrets_map: dict[str, str]) -> JarvisConfig:
    try:
        cfg = JarvisConfig.model_validate(_interpolate(plain(raw), secrets_map))
    except ValidationError as e:
        raise SettingsError("Bitte die markierten Eingaben prüfen.", _errors(e), status=422) from e
    errors = semantic_errors(cfg)
    if errors:
        raise SettingsError("Bitte die markierten Eingaben prüfen.", errors, status=422)
    return cfg


def container_restart_reasons(cfg: JarvisConfig) -> list[str]:
    """Was erst nach einem Neustart des ganzen Containers wirkt (eingebettete Dienste)."""
    if "JARVIS_OLLAMA_AUTOSTART" not in os.environ:
        return []                           # nicht im Container (Entwicklung)
    new = shell_env(cfg)
    return [label for key, label in CONTAINER_ENV.items() if os.environ.get(key, "") != new.get(key, "")]


# --------------------------------------------------------------------------- secrets.yaml
def env_secret(name: str) -> str:
    return os.environ.get(f"JARVIS_{name.upper()}", "")


def secret_status(files: ConfigFiles) -> dict[str, dict]:
    data = files.load("secrets.yaml")
    names = (set(SECRET_LABELS) | {str(k) for k in data}) - {"admin_token"}
    out = {}
    for name in sorted(names):
        source = "env" if env_secret(name) else "file" if data.get(name) not in (None, "") else None
        out[name] = {"set": source is not None, "source": source, "label": SECRET_LABELS.get(name, name)}
    return out


def apply_secrets(raw: CommentedMap, updates: dict[str, str | None]) -> None:
    for name, value in updates.items():
        if name == "admin_token":
            raise SettingsError("Den Admin-Token bitte unter „System“ neu erzeugen.")
        if not SECRET_RE.match(name):
            raise SettingsError(f"Ungültiger Name für ein Geheimnis: {name}")
        if env_secret(name):
            raise SettingsError(f"{SECRET_LABELS.get(name, name)} kommt aus der Umgebungsvariable "
                                f"JARVIS_{name.upper()} (Container-Vorlage) und lässt sich nur dort ändern.")
        value = (value or "").strip()
        if len(value) > 20000:
            raise SettingsError(f"{SECRET_LABELS.get(name, name)}: Wert ist zu lang.")
        raw[name] = LiteralScalarString(value + "\n") if "\n" in value else DoubleQuotedScalarString(value)


# --------------------------------------------------------------------------- whitelist.yaml
def whitelist_values(files: ConfigFiles) -> dict[str, list[str]]:
    data = plain(files.load("whitelist.yaml")).get("containers") or {}
    return {str(k): [a for a in CONTAINER_ACTIONS if a in (v or [])] for k, v in data.items()}


def apply_whitelist(raw: CommentedMap, containers: dict[str, list[str]]) -> None:
    out = CommentedMap()
    for name, actions in containers.items():
        name = name.strip()
        if not CONTAINER_RE.match(name):
            raise SettingsError(f"„{name}“ ist kein gültiger Containername.")
        bad = set(actions) - set(CONTAINER_ACTIONS)
        if bad:
            raise SettingsError(f"Unbekannte Aktion für {name}: {', '.join(sorted(bad))}")
        seq = CommentedSeq(a for a in CONTAINER_ACTIONS if a in actions)
        seq.fa.set_flow_style()
        out[name] = seq
    raw["containers"] = out


# --------------------------------------------------------------------------- scripts.yaml
def scripts_root() -> str:
    return os.environ.get("JARVIS_SCRIPTS_ROOT", "/scripts")


def script_values(files: ConfigFiles) -> dict[str, dict]:
    return plain(files.load("scripts.yaml")).get("scripts") or {}


def _clean_params(params: dict) -> dict:
    out = {}
    for name, p in (params or {}).items():
        if not PARAM_RE.match(name):
            raise SettingsError(f"Parametername „{name}“: Kleinbuchstaben, Ziffern und _.")
        ptype = p.get("type", "str")
        if ptype not in ("str", "int", "bool", "enum"):
            raise SettingsError(f"Parameter {name}: unbekannter Typ {ptype}.")
        clean: dict[str, Any] = {"type": ptype, "required": bool(p.get("required", False))}
        if ptype == "str" and p.get("pattern"):
            try:
                re.compile(p["pattern"])
            except re.error as e:
                raise SettingsError(f"Parameter {name}: Muster ist kein gültiger regulärer Ausdruck ({e}).") from e
            clean["pattern"] = str(p["pattern"])
        if ptype == "int":
            for k in ("min", "max"):
                if p.get(k) not in (None, ""):
                    clean[k] = int(p[k])
        if ptype == "enum":
            choices = [str(c).strip() for c in p.get("choices") or [] if str(c).strip()]
            if not choices:
                raise SettingsError(f"Parameter {name}: Auswahl braucht mindestens einen Wert.")
            clean["choices"] = choices
        out[name] = clean
    return out


def apply_script(raw: CommentedMap, sid: str, spec: dict | None) -> None:
    from jarvis.runner.registry import ValidationError as RegistryError
    from jarvis.runner.registry import load_registry

    if not SCRIPT_ID_RE.match(sid):
        raise SettingsError("Name des Skripts: Kleinbuchstaben, Ziffern und _ (max. 40 Zeichen).")
    scripts = raw.get("scripts")
    if not isinstance(scripts, dict):
        scripts = raw["scripts"] = CommentedMap()
    if spec is None:
        scripts.pop(sid, None)
        return
    path = str(spec.get("path", "")).strip()
    if not path:
        raise SettingsError("Pfad zum Skript fehlt.")
    timeout = int(spec.get("timeout", 60))
    if not 1 <= timeout <= 3600:
        raise SettingsError("Zeitlimit: 1 bis 3600 Sekunden.")
    clean = {
        "path": path, "description": str(spec.get("description", "")).strip()[:300],
        "confirm": bool(spec.get("confirm", True)), "car_allowed": bool(spec.get("car_allowed", False)),
        "timeout": timeout, "params": _clean_params(spec.get("params") or {}),
    }
    old = scripts.get(sid)
    node = old if isinstance(old, CommentedMap) else CommentedMap()
    for k, v in clean.items():
        node[k] = to_node(v, node.get(k))
    if not clean["params"]:
        node["params"] = CommentedMap()
        node["params"].fa.set_flow_style()
    scripts[sid] = node
    try:                                     # nur dieses Skript prüfen – andere Einträge stören nicht
        load_registry({"scripts": {sid: plain(node)}}, scripts_root())
    except (RegistryError, TypeError, ValueError) as e:
        raise SettingsError(str(e) if str(e).startswith("Skript") else f"Skript {sid}: {e}") from e


def script_files() -> list[dict]:
    root = Path(scripts_root())
    try:
        return [{"path": str(p), "executable": os.access(p, os.X_OK)}
                for p in sorted(root.iterdir()) if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return []


def secret_names() -> dict[str, str]:
    """Standardnamen der API-Schlüssel je Anbieter – damit die Verwaltung das passende Feld zeigt."""
    return dict(SECRET_NAMES)
