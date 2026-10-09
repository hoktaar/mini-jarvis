// Mini-Jarvis – Verwaltung: alle Einstellungen ohne YAML.
// Abschnitte mit Formularen, Schlüssel direkt am Feld, Speichern mit Prüfung auf dem Server.
import { $, el, icon, toast } from "./ui.js";

const S = {
  data: null,          // Antwort von /api/admin/settings
  draft: {},           // Pfad → neuer Wert
  secrets: {},         // Name → neuer Wert ("" = entfernen)
  whitelist: null,     // geänderte Container-Freigaben (oder null)
  wlRows: null,        // Bearbeitungszeilen der Freigaben
  errors: {},          // Pfad → Meldung
  section: "general",
  advanced: false,
  ha: null,            // Ergebnis des Home-Assistant-Tests
  haFilter: "",
  ollama: null,        // installierte Modelle
  ollamaLoading: false,
  pullTimer: null,
  geo: null,
};
let ctx = null;        // { api, onSaved }

// ---------------------------------------------------------------- Werte
const deep = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const clone = (v) => JSON.parse(JSON.stringify(v ?? null));
const orig = (path) => deep(S.data.values, path);
const get = (path) => (path in S.draft ? S.draft[path] : orig(path));

function set(path, value, rerender = false) {
  if (same(value, orig(path))) delete S.draft[path]; else S.draft[path] = value;
  for (const k of Object.keys(S.errors)) if (k === path || k.startsWith(`${path}.`)) delete S.errors[k];
  updateBar();
  if (rerender) render();
}

const secretInfo = (name) => S.data.secrets[name] || { set: false, source: null, label: name };
const providerSecret = (kind, override = "") => override || S.data.secret_names[kind] || `${kind}_api_key`;
const changes = () => Object.keys(S.draft).length + Object.keys(S.secrets).length + (S.whitelist ? 1 : 0);
export const dirty = () => S.data != null && changes() > 0;

// ---------------------------------------------------------------- Feldbeschreibungen
const T = (path, label, o = {}) => ({ k: "text", path, label, ...o });
const N = (path, label, o = {}) => ({ k: "number", path, label, ...o });
const B = (path, label, o = {}) => ({ k: "toggle", path, label, ...o });
const SEL = (path, label, options, o = {}) => ({ k: "select", path, label, options, ...o });
const CARDS = (path, label, options, o = {}) => ({ k: "cards", path, label, options, ...o });
const AREA = (path, label, o = {}) => ({ k: "area", path, label, ...o });
const LIST = (path, label, o = {}) => ({ k: "list", path, label, ...o });
const MULTI = (path, label, options, o = {}) => ({ k: "multi", path, label, options, ...o });
const SECRET = (name, label, o = {}) => ({ k: "secret", name, label, ...o });
const CUSTOM = (render, o = {}) => ({ k: "custom", render, ...o });
const NOTE = (text, o = {}) => ({ k: "note", text, ...o });

const on = (path) => () => !!get(path);
const is = (path, ...values) => () => values.includes(get(path));

const CLOUD_TYPES = [
  ["anthropic", "Anthropic (Claude)"], ["openai", "OpenAI (GPT)"], ["google", "Google (Gemini)"], ["mistral", "Mistral"],
  ["groq", "Groq"], ["openrouter", "OpenRouter"], ["deepseek", "DeepSeek"], ["openai_compatible", "OpenAI-kompatibel (eigene Adresse)"],
];
const CLOUD_MODELS = {
  anthropic: ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
  openai: ["gpt-5-mini", "gpt-5", "gpt-4.1-mini"], google: ["gemini-2.5-flash", "gemini-2.5-pro"],
  mistral: ["mistral-large-latest", "mistral-small-latest"], groq: ["llama-3.3-70b-versatile", "qwen/qwen3-32b"],
  openrouter: ["anthropic/claude-sonnet-5.5", "openai/gpt-5-mini", "google/gemini-2.5-flash"], deepseek: ["deepseek-chat"],
};
const STT_TYPES = [
  ["whisper", "Whisper – lokal"], ["openai", "OpenAI · Cloud"], ["groq", "Groq · Cloud"], ["deepgram", "Deepgram · Cloud"],
  ["azure", "Azure · Cloud"], ["google", "Google · Cloud"], ["elevenlabs", "ElevenLabs · Cloud"], ["none", "Aus (nur Text)"],
];
const STT_MODELS = {
  whisper: ["large-v3-turbo", "large-v3", "medium", "small"], openai: ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"],
  groq: ["whisper-large-v3-turbo", "whisper-large-v3"], deepgram: ["nova-3", "nova-2"], elevenlabs: ["scribe_v1"],
};
const TTS_TYPES = [
  ["piper", "Piper – lokal"], ["openai", "OpenAI · Cloud"], ["elevenlabs", "ElevenLabs · Cloud"], ["cartesia", "Cartesia · Cloud"],
  ["deepgram", "Deepgram · Cloud"], ["azure", "Azure · Cloud"], ["google", "Google · Cloud"], ["none", "Aus (nur Text)"],
];
const TTS_VOICES = {
  piper: ["de_DE-thorsten-high", "de_DE-thorsten-medium", "de_DE-kerstin-low", "de_DE-eva_k-x_low", "de_DE-ramona-low"],
  openai: ["nova", "alloy", "onyx", "shimmer", "echo", "fable"], azure: ["de-DE-ConradNeural", "de-DE-KatjaNeural"],
  google: ["de-DE-Neural2-B", "de-DE-Neural2-C"],
};
const TTS_MODELS = {
  openai: ["gpt-4o-mini-tts", "tts-1"], elevenlabs: ["eleven_flash_v2_5", "eleven_multilingual_v2"], cartesia: ["sonic-2"],
  deepgram: ["aura-2-julius-de", "aura-2"],
};
const OLLAMA_SUGGEST = ["qwen3:8b", "qwen3:4b", "qwen3:14b", "llama3.1:8b", "gemma3:12b", "mistral-nemo"];
const EMBEDDED_OLLAMA = "http://127.0.0.1:11434/v1";
const RISKS = [["read", "Lesen", "Wetter, Suche, Kalender ansehen"], ["write", "Schreiben", "Timer, Licht, Termine anlegen"],
  ["critical", "Kritisch", "Container steuern, Skripte ausführen"]];

const sttCloud = () => !["whisper", "none"].includes(get("providers.stt.type"));
const ttsCloud = () => !["piper", "none"].includes(get("providers.tts.type"));

const SECTIONS = [
  {
    id: "general", title: "Allgemein", icon: "i-home", prefixes: ["location", "persona", "providers.llm.context_turns", "memory", "language"],
    intro: "Standort, Zeitzone und wie Jarvis spricht.",
    groups: [
      { title: "Standort", fields: [
        CUSTOM(locationSearch),
        T("location.name", "Name", { placeholder: "z. B. Zuhause", help: "So nennt Jarvis den Ort beim Wetter." }),
        N("location.latitude", "Breitengrad", { step: "any", placeholder: "52.52" }),
        N("location.longitude", "Längengrad", { step: "any", placeholder: "13.40" }),
        T("location.timezone", "Zeitzone", { list: () => S.data.timezones, help: "Für Uhrzeit, Wecker und Erinnerungen." }),
      ] },
      { title: "Persönlichkeit", fields: [
        AREA("persona", "So spricht Jarvis", { rows: 5, help: "Ton und Art der Antworten. Regeln wie „ohne Markdown“ ergänzt Jarvis selbst." }),
        N("providers.llm.context_turns", "Gesprächsgedächtnis", { unit: "Wechsel", min: 1, max: 50, help: "So viele Frage-Antwort-Paare merkt sich Jarvis im laufenden Gespräch." }),
      ] },
      { title: "Gedächtnis", fields: [
        B("memory.enabled", "Fakten merken", { help: "„Merk dir, dass …“ – die Einträge stehen unter „Gedächtnis“." }),
        N("memory.prompt_items", "Fakten im Gespräch", { min: 0, max: 200, advanced: true, help: "So viele gemerkte Fakten bekommt das Sprachmodell mit." }),
      ] },
    ],
  },
  {
    id: "llm", title: "Sprachmodell", icon: "i-brain", prefixes: ["providers.llm"],
    intro: "Wer Fragen beantwortet: ein Modell auf deinem Server, ein Cloud-Anbieter oder beides.",
    groups: [
      { title: "Wer antwortet zuerst?", fields: [
        CARDS("providers.llm.primary", "", [
          ["local", "Lokal zuerst", "Dein Server antwortet. Die Cloud hilft nur auf Wunsch oder bei Ausfall."],
          ["cloud", "Cloud zuerst", "Ein Cloud-Modell antwortet. Das lokale Modell springt bei Ausfall ein."],
        ]),
      ] },
      { title: "Lokales Modell (Ollama)", fields: [
        B("providers.llm.local.enabled", "Lokales Modell nutzen"),
        CUSTOM(ollamaBase, { when: on("providers.llm.local.enabled") }),
        CUSTOM(ollamaModel, { when: on("providers.llm.local.enabled") }),
        B("providers.llm.local.think", "Denkmodus", { when: on("providers.llm.local.enabled"), help: "Gründlicher, aber die erste Antwort kommt deutlich später." }),
        T("providers.llm.local.keep_alive", "Im Speicher halten", { when: on("providers.llm.local.enabled"), advanced: true, placeholder: "10m", help: "z. B. 10m, 1h oder -1 (immer)." }),
        N("providers.llm.local.num_ctx", "Kontextlänge", { when: on("providers.llm.local.enabled"), advanced: true, unit: "Tokens", min: 512, step: 512 }),
        N("providers.llm.local.temperature", "Temperatur", { when: on("providers.llm.local.enabled"), advanced: true, nullable: true, step: 0.1, min: 0, max: 2, placeholder: "Standard des Modells" }),
      ] },
      { title: "Cloud-Modell", fields: [
        B("providers.llm.cloud.enabled", "Cloud-Modell nutzen", { help: "Fragen gehen dann an einen externen Anbieter – im Privatmodus nie." }),
        SEL("providers.llm.cloud.type", "Anbieter", CLOUD_TYPES, { when: on("providers.llm.cloud.enabled") }),
        T("providers.llm.cloud.model", "Modell", { when: on("providers.llm.cloud.enabled"), suggest: () => CLOUD_MODELS[get("providers.llm.cloud.type")] || [], placeholder: "Modellname laut Anbieter" }),
        SECRET(() => providerSecret(get("providers.llm.cloud.type"), get("providers.llm.cloud.api_key_secret")), "API-Schlüssel", { when: on("providers.llm.cloud.enabled") }),
        T("providers.llm.cloud.base_url", "Adresse", { when: () => get("providers.llm.cloud.enabled") && get("providers.llm.cloud.type") === "openai_compatible", placeholder: "https://api.together.xyz/v1", help: "OpenAI-kompatibler Endpunkt (Together, LM Studio, vLLM …)." }),
        SEL("providers.llm.cloud.escalation", "Wann an die Cloud?", [["manual", "Nur auf Wunsch („denk gründlich nach“)"], ["auto", "Automatisch bei langen, offenen Fragen"]], { when: () => get("providers.llm.cloud.enabled") && get("providers.llm.primary") === "local" }),
        N("providers.llm.cloud.auto_min_words", "Ab so vielen Wörtern", { when: () => get("providers.llm.cloud.enabled") && get("providers.llm.cloud.escalation") === "auto", advanced: true, min: 3, max: 100 }),
        B("providers.llm.cloud.failover", "Bei Ausfall einspringen", { when: on("providers.llm.cloud.enabled"), help: "Antwortet das lokale Modell nicht, übernimmt die Cloud." }),
        N("providers.llm.cloud.budget_eur_day", "Budget pro Tag", { when: on("providers.llm.cloud.enabled"), unit: "€", min: 0, step: 0.5, help: "0 = keine Grenze. Danach antwortet nur noch das lokale Modell." }),
        N("providers.llm.cloud.budget_eur_month", "Budget pro Monat", { when: on("providers.llm.cloud.enabled"), unit: "€", min: 0, step: 1 }),
        N("providers.llm.cloud.price_input_eur_per_mtok", "Preis Eingabe", { when: on("providers.llm.cloud.enabled"), advanced: true, unit: "€ / 1 Mio. Tokens", min: 0, step: 0.01 }),
        N("providers.llm.cloud.price_output_eur_per_mtok", "Preis Ausgabe", { when: on("providers.llm.cloud.enabled"), advanced: true, unit: "€ / 1 Mio. Tokens", min: 0, step: 0.01 }),
        MULTI("providers.llm.cloud.allowed_tool_risks", "Werkzeuge für die Cloud", RISKS, { when: on("providers.llm.cloud.enabled"), help: "Welche Werkzeuge das Cloud-Modell benutzen darf." }),
      ] },
    ],
  },
  {
    id: "voice", title: "Sprache", icon: "i-mic", prefixes: ["providers.stt", "providers.tts", "audio"],
    intro: "Hören, sprechen und das Aktivierungswort.",
    groups: [
      { title: "Spracherkennung (hören)", fields: [
        SEL("providers.stt.type", "Dienst", STT_TYPES),
        T("providers.stt.model", "Modell", { when: () => get("providers.stt.type") !== "none", suggest: () => STT_MODELS[get("providers.stt.type")] || [] }),
        SEL("providers.stt.device", "Rechnet auf", [["cuda", "Grafikkarte (CUDA)"], ["cpu", "Prozessor"]], { when: is("providers.stt.type", "whisper") }),
        T("providers.stt.compute_type", "Genauigkeit", { when: is("providers.stt.type", "whisper"), advanced: true, suggest: () => ["int8_float16", "float16", "int8"] }),
        T("providers.stt.base_url", "Eigene Adresse", { when: is("providers.stt.type", "openai"), advanced: true, placeholder: "leer = OpenAI" }),
        T("providers.stt.region", "Region", { when: is("providers.stt.type", "azure"), placeholder: "westeurope" }),
        SECRET(() => providerSecret(get("providers.stt.type") === "google" ? "google_stt" : get("providers.stt.type"), get("providers.stt.api_key_secret")), "API-Schlüssel", { when: sttCloud, multiline: () => get("providers.stt.type") === "google" }),
      ] },
      { title: "Sprachausgabe (sprechen)", fields: [
        SEL("providers.tts.type", "Dienst", TTS_TYPES),
        T("providers.tts.voice", "Stimme", { when: () => get("providers.tts.type") !== "none", suggest: () => TTS_VOICES[get("providers.tts.type")] || [], help: "Piper: Name der Stimme · Cloud: Stimmen-ID des Anbieters." }),
        T("providers.tts.model", "Modell", { when: ttsCloud, suggest: () => TTS_MODELS[get("providers.tts.type")] || [], placeholder: "Standard des Anbieters" }),
        T("providers.tts.region", "Region", { when: is("providers.tts.type", "azure"), placeholder: "westeurope" }),
        SECRET(() => providerSecret(get("providers.tts.type") === "google" ? "google_tts" : get("providers.tts.type"), get("providers.tts.api_key_secret")), "API-Schlüssel", { when: ttsCloud, multiline: () => get("providers.tts.type") === "google" }),
      ] },
      { title: "Aktivierungswort „Hey Jarvis“", fields: [
        B("audio.wake_word.enabled", "Aktivierungswort", { help: "Ohne Aktivierungswort hört Jarvis nur per Knopf (Push-to-Talk)." }),
        N("audio.wake_word.threshold", "Schwelle", { when: on("audio.wake_word.enabled"), min: 0.1, max: 0.95, step: 0.05, help: "Niedriger = reagiert eher, aber auch mal versehentlich." }),
        N("audio.wake_word.listen_seconds", "Zuhören nach dem Wort", { when: on("audio.wake_word.enabled"), unit: "Sekunden", min: 1, max: 60 }),
        N("audio.wake_word.max_listen_seconds", "Höchstens zuhören", { when: on("audio.wake_word.enabled"), unit: "Sekunden", min: 2, max: 120, help: "Obergrenze, auch wenn es laut bleibt (Fernseher)." }),
        SEL("audio.wake_word.follow_up", "Weiter zuhören", [["off", "Nein"], ["question", "Nach Rückfragen"], ["always", "Nach jeder Antwort"]], { when: on("audio.wake_word.enabled") }),
        N("audio.wake_word.follow_up_seconds", "So lange", { when: () => get("audio.wake_word.enabled") && get("audio.wake_word.follow_up") !== "off", unit: "Sekunden", min: 1, max: 60 }),
        T("audio.wake_word.model", "Modell", { when: on("audio.wake_word.enabled"), advanced: true }),
      ] },
    ],
  },
  {
    id: "search", title: "Suche & Nachrichten", icon: "i-search", prefixes: ["search", "news"],
    intro: "Websuche und Nachrichtenquellen für „Was gibt's Neues?“.",
    groups: [
      { title: "Websuche", fields: [
        SEL("search.provider", "Suchdienst", [["searxng", "SearXNG – eingebaut, lokal"], ["brave", "Brave Search · Cloud"], ["tavily", "Tavily · Cloud"], ["none", "Aus"]]),
        SECRET(() => providerSecret(get("search.provider"), get("search.api_key_secret")), "API-Schlüssel", { when: is("search.provider", "brave", "tavily") }),
        N("search.max_results", "Treffer pro Suche", { when: () => get("search.provider") !== "none", min: 1, max: 20 }),
      ] },
      { title: "Nachrichten", fields: [
        CUSTOM(feedsEditor),
        N("news.max_items", "Meldungen pro Abruf", { min: 1, max: 20 }),
      ] },
    ],
  },
  {
    id: "home", title: "Smart Home", icon: "i-bulb", prefixes: ["homeassistant"],
    intro: "Home Assistant für die Kacheln im Dashboard, die Seiten „Licht“ und „Musik“ auf dem CYD und die Sprachsteuerung.",
    groups: [
      { title: "Home Assistant", fields: [
        B("homeassistant.enabled", "Home Assistant verbinden"),
        T("homeassistant.url", "Adresse", { when: on("homeassistant.enabled"), placeholder: "http://homeassistant.local:8123" }),
        SECRET(() => get("homeassistant.token_secret") || "homeassistant_token", "Langzeit-Token", { when: on("homeassistant.enabled"), help: "In Home Assistant: Profil → Sicherheit → Langlebige Zugriffstokens." }),
        B("homeassistant.verify_tls", "Zertifikat prüfen", { when: on("homeassistant.enabled"), advanced: true, help: "Nur ausschalten bei selbst signiertem Zertifikat." }),
        CUSTOM(haConnect, { when: on("homeassistant.enabled") }),
      ] },
      { title: "Geräte", when: on("homeassistant.enabled"), fields: [CUSTOM(haEntities)] },
      { title: "Sprachsteuerung", when: on("homeassistant.enabled"), fields: [CUSTOM(haVoice)] },
    ],
  },
  {
    id: "calendar", title: "Kalender", icon: "i-calendar", prefixes: ["calendar"],
    intro: "Termine über CalDAV, z. B. Nextcloud oder iCloud.",
    groups: [
      { title: "CalDAV", fields: [
        B("calendar.enabled", "Kalender verbinden"),
        T("calendar.url", "Adresse", { when: on("calendar.enabled"), placeholder: "https://cloud.example.lan/remote.php/dav" }),
        T("calendar.username", "Benutzer", { when: on("calendar.enabled"), autocomplete: "username" }),
        SECRET(() => get("calendar.password_secret") || "caldav_password", "Passwort", { when: on("calendar.enabled"), help: "Am besten ein App-Passwort." }),
        LIST("calendar.calendars", "Nur diese Kalender", { when: on("calendar.enabled"), placeholder: "Name + Enter", help: "Leer = alle Kalender." }),
        T("calendar.default_calendar", "Neue Termine in", { when: on("calendar.enabled"), placeholder: "erster Kalender" }),
        B("calendar.verify_tls", "Zertifikat prüfen", { when: on("calendar.enabled"), advanced: true }),
      ] },
    ],
  },
  {
    id: "notify", title: "Benachrichtigungen", icon: "i-bell", prefixes: ["push", "adapters"],
    intro: "Push aufs Handy und Chat mit Jarvis über Telegram oder Matrix.",
    groups: [
      { title: "Push (ntfy)", fields: [
        B("push.ntfy.enabled", "Push-Nachrichten"),
        T("push.ntfy.base_url", "Server", { when: on("push.ntfy.enabled"), placeholder: "https://ntfy.sh" }),
        T("push.ntfy.topic", "Thema", { when: on("push.ntfy.enabled"), placeholder: "z. B. jarvis-7f3k2", help: "Lang und zufällig wählen – wer das Thema kennt, liest mit." }),
        SECRET(() => get("push.ntfy.token_secret") || "ntfy_token", "Zugriffstoken", { when: on("push.ntfy.enabled"), optional: true, help: "Nur für geschützte Themen nötig." }),
        MULTI("push.ntfy.kinds", "Bei", [["timer", "Timer"], ["alarm", "Wecker"], ["reminder", "Erinnerungen"]], { when: on("push.ntfy.enabled") }),
        B("push.ntfy.only_when_offline", "Nur wenn das Gerät offline ist", { when: on("push.ntfy.enabled") }),
      ] },
      { title: "Telegram", fields: [
        B("adapters.telegram.enabled", "Telegram-Bot"),
        SECRET("telegram_bot_token", "Bot-Token", { when: on("adapters.telegram.enabled"), help: "Von @BotFather." }),
        LIST("adapters.telegram.allowed_user_ids", "Erlaubte Nutzer-IDs", { when: on("adapters.telegram.enabled"), numbers: true, placeholder: "ID + Enter", help: "Eigene ID: dem Bot /start schicken – er antwortet mit der ID." }),
      ] },
      { title: "Matrix", fields: [
        B("adapters.matrix.enabled", "Matrix-Bot"),
        T("adapters.matrix.homeserver", "Homeserver", { when: on("adapters.matrix.enabled"), placeholder: "https://matrix.example.org" }),
        T("adapters.matrix.user_id", "Bot-Konto", { when: on("adapters.matrix.enabled"), placeholder: "@jarvis:example.org" }),
        SECRET("matrix_password", "Passwort", { when: on("adapters.matrix.enabled") }),
        LIST("adapters.matrix.allowed_users", "Erlaubte Nutzer", { when: on("adapters.matrix.enabled"), placeholder: "@name:server + Enter" }),
      ] },
    ],
  },
  {
    id: "tools", title: "Werkzeuge", icon: "i-terminal", prefixes: ["gpu", "mcp_servers"],
    intro: "Docker-Container, Grafikkarte und zusätzliche Werkzeuge (MCP).",
    groups: [
      { title: "Docker-Container", intro: "Nur diese Container darf Jarvis sehen und steuern – kritische Aktionen immer mit Rückfrage.", fields: [CUSTOM(whitelistEditor)] },
      { title: "Grafikkarte teilen (ComfyUI)", fields: [
        SEL("gpu.comfyui_mode", "Sparmodus", [["off", "Aus"], ["auto", "Automatisch, solange ComfyUI läuft"], ["on", "Immer"]], { help: "Gibt den Grafikspeicher frei, wenn ein Bildgenerator ihn braucht." }),
        T("gpu.comfyui_container", "ComfyUI-Container", { when: () => get("gpu.comfyui_mode") !== "off" }),
        N("gpu.unload_after_seconds", "Modell entladen nach", { when: () => get("gpu.comfyui_mode") !== "off", advanced: true, unit: "Sekunden", min: 0 }),
      ] },
      { title: "MCP-Server", intro: "Zusätzliche Werkzeuge über das Model Context Protocol.", fields: [CUSTOM(mcpEditor)] },
    ],
  },
  {
    id: "network", title: "Netzwerk & Sicherheit", icon: "i-lock", prefixes: ["server", "privacy", "firmware"],
    intro: "HTTPS, Datenschutz und Updates der Geräte.",
    groups: [
      { title: "HTTPS", fields: [
        B("server.https.enabled", "HTTPS", { help: "Browser erlauben das Mikrofon nur über HTTPS (oder localhost)." }),
        LIST("server.https.hosts", "Namen fürs Zertifikat", { when: on("server.https.enabled"), placeholder: "IP oder Name + Enter", help: "Unter diesen Adressen erreichst du Jarvis, z. B. 192.168.1.10 oder tower.local." }),
        NOTE(() => S.data.env.hosts ? `Zusätzlich aus der Container-Vorlage (JARVIS_HOSTS): ${S.data.env.hosts}` : "", { when: () => !!S.data.env.hosts }),
        T("server.public_url", "Feste Adresse", { placeholder: "https://jarvis.lan:8443", help: "Für Kopplungs-Links und QR-Codes. Leer = Adresse aus dem Browser." }),
        NOTE(() => `Wird überschrieben durch JARVIS_PUBLIC_URL aus der Container-Vorlage: ${S.data.env.public_url}`, { when: () => !!S.data.env.public_url }),
        T("server.https.certfile", "Eigenes Zertifikat", { when: on("server.https.enabled"), advanced: true, placeholder: "/config/tls/fullchain.pem", help: "Leer = eigene Zertifizierungsstelle von Jarvis." }),
        T("server.https.keyfile", "Schlüssel dazu", { when: on("server.https.enabled"), advanced: true, placeholder: "/config/tls/privkey.pem" }),
        NOTE(() => `Ports: HTTP ${orig("server.port")}, HTTPS ${orig("server.https.port")} – festgelegt über die Port-Zuordnung des Containers.`),
      ] },
      { title: "Datenschutz", fields: [
        N("privacy.retention_days", "Protokolle aufbewahren", { unit: "Tage", min: 0, help: "Router- und Aktionsprotokoll danach löschen. 0 = nie." }),
        B("privacy.log_text", "Sätze protokollieren", { help: "Aus: Im Router-Protokoll steht nur, was erkannt wurde – nicht der Satz." }),
      ] },
      { title: "Geräte", fields: [
        B("firmware.auto_update", "Displays automatisch aktualisieren", { help: "Neue Firmware per WLAN (OTA) installieren, sobald sich ein Gerät meldet." }),
      ] },
    ],
  },
  {
    id: "keys", title: "Schlüssel & Zugänge", icon: "i-key", prefixes: [],
    intro: "Alle gespeicherten Schlüssel auf einen Blick. Werte werden nie angezeigt – nur, ob sie gesetzt sind.",
    groups: [{ title: "Schlüssel", fields: [CUSTOM(keysList)] }],
  },
  {
    id: "advanced", title: "Erweitert", icon: "i-settings", prefixes: ["router", "providers.classifier"],
    intro: "Feineinstellungen für das Verstehen von Befehlen. Die Standardwerte passen meistens.",
    groups: [
      { title: "Router", fields: [
        B("router.enabled", "Schnellweg für einfache Befehle", { help: "Aus: Jede Frage geht an das Sprachmodell (langsamer)." }),
        N("router.thresholds.fast", "Sicherheit Schnellweg", { min: 0, max: 1, step: 0.01, help: "Ab dieser Sicherheit führt Jarvis Befehle ohne Sprachmodell aus." }),
        N("router.thresholds.focused", "Sicherheit gezielt", { min: 0, max: 1, step: 0.01, help: "Darunter bekommt das Sprachmodell alle Werkzeuge." }),
        N("router.slot_boost", "Bonus für erkannte Angaben", { min: 0, max: 0.5, step: 0.01 }),
        N("router.confirm_threshold", "Rückfrage ab", { min: 0, max: 1, step: 0.01, help: "Kritische Befehle unter dieser Sicherheit fragt Jarvis nach." }),
        N("router.confirm_timeout", "Bestätigung gilt", { unit: "Sekunden", min: 5, max: 120 }),
        N("router.dialog_timeout", "Rückfragen gelten", { unit: "Sekunden", min: 5, max: 300 }),
        T("router.embedding_model", "Sprachverständnis-Modell", { help: "Leer = einfaches Verfahren ohne Modell (schneller, ungenauer).", suggest: () => ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"] }),
        SEL("providers.classifier.type", "Klassifikator", [["local", "Lokal"], ["jev", "Jev (Cloud)"]], { advanced: true }),
      ] },
    ],
  },
];

// ---------------------------------------------------------------- Bausteine
const fid = (path) => `set-${String(path).replace(/[^a-z0-9]+/gi, "-")}`;

function errorFor(path) {
  if (!path) return null;
  if (S.errors[path]) return S.errors[path];
  const sub = Object.keys(S.errors).find((k) => k.startsWith(`${path}.`));
  return sub ? S.errors[sub] : null;
}

function row(label, help, control, { path = null, wide = false, id = null } = {}) {
  const err = errorFor(path);
  const changed = path != null && path in S.draft;
  return el("div", { class: `set-row${wide ? " wide" : ""}${err ? " has-error" : ""}${changed ? " changed" : ""}`, "data-path": path },
    label || help ? el("div", { class: "set-label" },
      label ? el("label", { for: id || (path ? fid(path) : null) }, label) : null,
      help ? el("small", {}, help) : null) : null,
    el("div", { class: "set-control" }, control, err ? el("p", { class: "set-error", role: "alert" }, err) : null));
}

function datalist(id, values) {
  return el("datalist", { id }, values.map((v) => el("option", { value: v })));
}

function textControl(f) {
  const v = get(f.path);
  const listValues = f.list ? f.list() : f.suggest ? f.suggest() : null;
  const input = el("input", {
    class: "input", id: fid(f.path), type: "text", value: v ?? "", placeholder: f.placeholder || null,
    autocomplete: f.autocomplete || "off", spellcheck: "false", list: listValues?.length ? `${fid(f.path)}-list` : null,
  });
  input.addEventListener("input", () => set(f.path, input.value));
  input.addEventListener("change", () => { if (f.rerender) render(); });
  return [input, listValues?.length ? datalist(`${fid(f.path)}-list`, listValues) : null];
}

function numberControl(f) {
  const v = get(f.path);
  const input = el("input", {
    class: "input", id: fid(f.path), type: "number", value: v ?? "", step: f.step ?? 1, min: f.min ?? null,
    max: f.max ?? null, placeholder: f.placeholder || null, inputmode: "decimal",
  });
  input.addEventListener("input", () => {
    const raw = input.value.trim();
    if (raw === "") set(f.path, f.nullable ? null : "");
    else set(f.path, Number(raw));
  });
  return f.unit ? el("div", { class: "with-unit" }, input, el("span", {}, f.unit)) : input;
}

function toggleControl(f) {
  const input = el("input", { type: "checkbox", role: "switch", id: fid(f.path), checked: !!get(f.path) });
  input.addEventListener("change", () => set(f.path, input.checked, true));
  return el("label", { class: "toggle" }, input, el("span", { "aria-hidden": "true" }));
}

function selectControl(f) {
  const v = get(f.path);
  const options = f.options.map(([value, label]) => el("option", { value, selected: value === v }, label));
  if (v != null && !f.options.some(([value]) => value === v)) options.unshift(el("option", { value: v, selected: true }, `${v} (unbekannt)`));
  const select = el("select", { class: "input", id: fid(f.path) }, options);
  select.addEventListener("change", () => set(f.path, select.value, true));
  return select;
}

function cardsControl(f) {
  const v = get(f.path);
  return el("div", { class: "choice-grid", role: "radiogroup" }, f.options.map(([value, title, text]) => {
    const input = el("input", { type: "radio", name: fid(f.path), value, checked: value === v });
    input.addEventListener("change", () => set(f.path, value, true));
    return el("label", { class: "choice" }, input, el("b", {}, title), el("small", {}, text));
  }));
}

function areaControl(f) {
  const area = el("textarea", { class: "input", id: fid(f.path), rows: f.rows || 4, spellcheck: "true" });
  area.value = get(f.path) ?? "";
  area.addEventListener("input", () => set(f.path, area.value));
  return area;
}

function multiControl(f) {
  const current = new Set(get(f.path) || []);
  return el("div", { class: "checks" }, f.options.map(([value, label, hint]) => {
    const input = el("input", { type: "checkbox", value, checked: current.has(value) });
    input.addEventListener("change", () => {
      const next = f.options.map(([v]) => v).filter((v) => (v === value ? input.checked : current.has(v)));
      current.clear(); next.forEach((x) => current.add(x));
      set(f.path, next);
    });
    return el("label", { class: "check" }, input, el("span", {}, el("b", {}, label), hint ? el("small", {}, hint) : null));
  }));
}

// Liste aus Zeichenketten/Zahlen als Schlagwörter
function tagsControl({ id, values, placeholder, numbers = false, onChange, transform = (x) => x }) {
  const items = [...(values || [])];
  const box = el("div", { class: "tags" });
  const input = el("input", { id, placeholder: placeholder || "Eintrag + Enter", autocomplete: "off", spellcheck: "false" });
  const draw = () => {
    box.replaceChildren(...items.map((v, i) => el("span", { class: "tag" }, String(v),
      el("button", { type: "button", "aria-label": `${v} entfernen`, onclick: () => { items.splice(i, 1); onChange([...items]); draw(); input.focus(); } }, "×"))), input);
  };
  const add = () => {
    for (const part of input.value.split(/[,\n]/)) {
      let v = transform(part.trim());
      if (!v) continue;
      if (numbers) { v = Number(v); if (!Number.isFinite(v)) { toast("Bitte eine Zahl eingeben."); continue; } }
      if (!items.includes(v)) items.push(v);
    }
    input.value = "";
    onChange([...items]);
    draw();
    input.focus();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
    else if (e.key === "Backspace" && !input.value && items.length) { items.pop(); onChange([...items]); draw(); input.focus(); }
  });
  input.addEventListener("blur", () => { if (input.value.trim()) add(); });
  draw();
  return box;
}

function listControl(f) {
  return tagsControl({ id: fid(f.path), values: get(f.path), placeholder: f.placeholder, numbers: f.numbers, onChange: (v) => set(f.path, v) });
}

function secretControl(name, { multiline = false, optional = false } = {}) {
  const info = secretInfo(name);
  const pending = name in S.secrets;
  let state;
  if (info.source === "env") state = el("span", { class: "st ok" }, "aus Container-Vorlage");
  else if (pending) state = el("span", { class: "st warn" }, S.secrets[name] ? "wird gespeichert" : "wird entfernt");
  else if (info.set) state = el("span", { class: "st ok" }, "gesetzt");
  else state = el("span", { class: `st${optional ? "" : " error"}` }, optional ? "nicht gesetzt" : "fehlt");
  if (info.source === "env") {
    return el("div", { class: "secret-field" }, state, el("small", { class: "muted" }, `JARVIS_${name.toUpperCase()} – nur in der Container-Vorlage änderbar`));
  }
  const attrs = { id: fid(`secret-${name}`), autocomplete: "new-password", spellcheck: "false", placeholder: info.set ? "gesetzt – zum Ändern neu eingeben" : "hier einfügen" };
  const input = multiline ? el("textarea", { class: "input mono", rows: 4, ...attrs }) : el("input", { class: "input", type: "password", ...attrs });
  if (pending && S.secrets[name]) input.value = S.secrets[name];
  input.addEventListener("input", () => {
    if (input.value.trim()) S.secrets[name] = input.value; else delete S.secrets[name];
    updateBar();
  });
  const show = multiline ? null : el("button", {
    type: "button", class: "icon-btn", title: "Eingabe zeigen", "aria-label": "Eingabe zeigen",
    onclick: () => { input.type = input.type === "password" ? "text" : "password"; },
  }, icon("i-eye"));
  const remove = info.set && !pending ? el("button", {
    type: "button", class: "btn small ghost", onclick: () => { S.secrets[name] = ""; updateBar(); render(); },
  }, "Entfernen") : pending ? el("button", { type: "button", class: "btn small ghost", onclick: () => { delete S.secrets[name]; updateBar(); render(); } }, "Rückgängig") : null;
  return el("div", { class: "secret-box" }, el("div", { class: "secret-field" }, input, show), el("div", { class: "secret-meta" }, state, el("code", {}, name), remove));
}

function renderField(f) {
  if (f.advanced && !S.advanced) return null;
  if (f.when && !f.when()) return null;
  const help = typeof f.help === "function" ? f.help() : f.help;
  switch (f.k) {
    case "text": return row(f.label, help, textControl(f), { path: f.path });
    case "number": return row(f.label, help, numberControl(f), { path: f.path });
    case "toggle": return row(f.label, help, toggleControl(f), { path: f.path });
    case "select": return row(f.label, help, selectControl(f), { path: f.path });
    case "cards": return row(f.label, help, cardsControl(f), { path: f.path, wide: true });
    case "area": return row(f.label, help, areaControl(f), { path: f.path, wide: true });
    case "list": return row(f.label, help, listControl(f), { path: f.path });
    case "multi": return row(f.label, help, multiControl(f), { path: f.path });
    case "secret": {
      const name = typeof f.name === "function" ? f.name() : f.name;
      const multiline = typeof f.multiline === "function" ? f.multiline() : !!f.multiline;
      return row(f.label, help || secretInfo(name).label, secretControl(name, { multiline, optional: !!f.optional }), { id: fid(`secret-${name}`) });
    }
    case "note": {
      const text = typeof f.text === "function" ? f.text() : f.text;
      return text ? el("p", { class: "set-note" }, icon("i-help"), text) : null;
    }
    case "custom": return f.render();
    default: return null;
  }
}

// ---------------------------------------------------------------- Eigene Bausteine
function locationSearch() {
  const q = el("input", { class: "input", type: "search", id: "set-geo", placeholder: "Ort suchen, z. B. Leipzig", autocomplete: "off" });
  const results = el("div", { class: "geo-results" });
  const draw = () => {
    if (!S.geo) { results.replaceChildren(); return; }
    if (S.geo.error) { results.replaceChildren(el("p", { class: "set-error" }, S.geo.error)); return; }
    if (S.geo.busy) { results.replaceChildren(el("p", { class: "muted small" }, "Suche …")); return; }
    results.replaceChildren(...(S.geo.hits.length ? S.geo.hits.map((h) => el("button", {
      type: "button", class: "geo-hit", onclick: () => {
        set("location.name", h.name);
        set("location.latitude", Math.round(h.latitude * 10000) / 10000);
        set("location.longitude", Math.round(h.longitude * 10000) / 10000);
        if (h.timezone) set("location.timezone", h.timezone);
        S.geo = null;
        render();
        toast(`Standort übernommen: ${h.name}`);
      },
    }, el("b", {}, h.name), el("small", {}, [h.region, h.timezone].filter(Boolean).join(" · ")))) : [el("p", { class: "muted small" }, "Nichts gefunden – Koordinaten bitte von Hand eintragen.")]));
  };
  const go = async () => {
    const text = q.value.trim();
    if (text.length < 2) return;
    S.geo = { busy: true, hits: [] }; draw();
    try { S.geo = { hits: await ctx.api(`/api/admin/geocode?q=${encodeURIComponent(text)}`) }; } catch (e) { S.geo = { error: e.message, hits: [] }; }
    draw();
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  draw();
  return row("Ort suchen", "Füllt Name, Koordinaten und Zeitzone aus (Open-Meteo).",
    el("div", { class: "geo" }, el("div", { class: "inline-row" }, q, el("button", { type: "button", class: "btn small", onclick: go }, icon("i-search"), "Suchen")), results), { id: "set-geo" });
}

function ollamaBase() {
  const path = "providers.llm.local.base_url";
  const cur = get(path) || "";
  const embedded = cur === EMBEDDED_OLLAMA || cur === "http://localhost:11434/v1";
  const pick = (mode) => {
    if (mode === "embedded") set(path, EMBEDDED_OLLAMA, true);
    else set(path, S.extOllama || (embedded ? "http://192.168.1.10:11434/v1" : cur), true);
    S.ollama = null;
  };
  const cards = el("div", { class: "choice-grid" }, [["embedded", "Eingebaut", "Ollama läuft mit im Container (Vorlage mit GPU)."], ["external", "Eigener Ollama-Server", "z. B. auf einem anderen Rechner im Netz."]].map(([value, title, text]) => {
    const input = el("input", { type: "radio", name: "ollama-mode", value, checked: (value === "embedded") === embedded });
    input.addEventListener("change", () => pick(value));
    return el("label", { class: "choice" }, input, el("b", {}, title), el("small", {}, text));
  }));
  const parts = [row("Wo läuft Ollama?", null, cards, { path, wide: true })];
  if (!embedded) {
    const input = el("input", { class: "input", id: fid(path), value: cur, placeholder: "http://192.168.1.10:11434/v1", spellcheck: "false" });
    input.addEventListener("input", () => { S.extOllama = input.value; set(path, input.value); });
    input.addEventListener("change", () => { S.ollama = null; render(); });
    parts.push(row("Adresse", "Mit /v1 am Ende.", input, { path }));
  }
  return parts;
}

async function loadOllama() {
  if (S.ollamaLoading) return;
  S.ollamaLoading = true;
  try { S.ollama = await ctx.api(`/api/admin/ollama?base_url=${encodeURIComponent(get("providers.llm.local.base_url") || "")}`); } catch (e) { S.ollama = { ok: false, error: e.message, models: [] }; }
  S.ollamaLoading = false;
  if (S.ollama.pull && !S.ollama.pull.done) pollPull();
  if (S.section === "llm") render();
}

function pollPull() {
  clearTimeout(S.pullTimer);
  S.pullTimer = setTimeout(async () => {
    try {
      const p = await ctx.api("/api/admin/ollama/pull");
      if (S.ollama) S.ollama.pull = p;
      if (p.done) { S.ollama = null; toast(p.error ? `Download fehlgeschlagen: ${p.error}` : `Modell ${p.model} ist bereit.`); }
      else pollPull();
    } catch { pollPull(); }
    if (S.section === "llm") render();
  }, 1500);
}

function ollamaModel() {
  const path = "providers.llm.local.model";
  if (!S.ollama) loadOllama();
  const o = S.ollama;
  const installed = o?.models?.map((m) => m.name) || [];
  const model = get(path) || "";
  const input = el("input", { class: "input", id: fid(path), value: model, list: `${fid(path)}-list`, placeholder: "z. B. qwen3:8b", spellcheck: "false" });
  input.addEventListener("input", () => set(path, input.value.trim()));
  input.addEventListener("change", () => render());
  const info = [];
  if (!o) info.push(el("p", { class: "muted small" }, "Frage Ollama nach den geladenen Modellen …"));
  else if (!o.ok) info.push(el("p", { class: "set-note warn" }, icon("i-warn"), o.error || "Ollama nicht erreichbar."));
  else {
    const has = installed.some((n) => n === model || n === `${model}:latest`);
    if (installed.length) {
      info.push(el("div", { class: "chips" }, o.models.map((m) => el("button", {
        type: "button", class: `chip-s pick${m.name === model ? " on" : ""}`, title: "Dieses Modell verwenden",
        onclick: () => set(path, m.name, true),
      }, el("b", {}, m.name), m.size ? ` ${(m.size / 1e9).toFixed(1).replace(".", ",")} GB` : ""))));
    }
    const pull = o.pull && !o.pull.done ? o.pull : null;
    if (pull) {
      const pct = pull.total ? Math.round((pull.completed / pull.total) * 100) : 0;
      info.push(el("div", { class: "progress" }, el("div", { class: "label" }, el("span", {}, `${pull.model}: ${pull.status}`), el("span", {}, pull.total ? `${pct} %` : "")),
        el("div", { class: "track" }, el("div", { class: "fill", style: `width:${pct}%` }))));
    } else if (model && !has) {
      info.push(el("p", { class: "set-note warn" }, icon("i-warn"), `„${model}“ ist auf diesem Ollama noch nicht vorhanden.`,
        el("button", {
          type: "button", class: "btn small primary", onclick: async () => {
            try {
              const p = await ctx.api("/api/admin/ollama/pull", { method: "POST", body: { model, base_url: get("providers.llm.local.base_url") || "" } });
              S.ollama.pull = p; pollPull(); render();
            } catch (e) { toast(e.message); }
          },
        }, icon("i-download"), "Jetzt herunterladen")));
    }
  }
  return row("Modell", "Größere Modelle antworten besser, brauchen aber mehr Grafikspeicher (8B ≈ 6 GB).",
    el("div", { class: "stack-s" }, input, datalist(`${fid(path)}-list`, [...new Set([...installed, ...OLLAMA_SUGGEST])]), ...info), { path });
}

function feedsEditor() {
  const path = "news.feeds";
  const feeds = clone(get(path)) || [];
  const update = (rerender) => set(path, feeds, rerender);
  const rows = feeds.map((f, i) => {
    const name = el("input", { class: "input", value: f.name, placeholder: "Name", "aria-label": "Name der Quelle" });
    const url = el("input", { class: "input", value: f.url, placeholder: "https://…/rss.xml", "aria-label": "Adresse des Feeds", spellcheck: "false" });
    name.addEventListener("input", () => { feeds[i].name = name.value; update(false); });
    url.addEventListener("input", () => { feeds[i].url = url.value; update(false); });
    const err = S.errors[`${path}.${i}.url`] || S.errors[`${path}.${i}.name`];
    return el("div", { class: `obj-line${err ? " has-error" : ""}` }, name, url,
      el("button", { type: "button", class: "icon-btn", title: "Entfernen", "aria-label": `${f.name || "Quelle"} entfernen`, onclick: () => { feeds.splice(i, 1); update(true); } }, icon("i-trash")),
      err ? el("p", { class: "set-error" }, err) : null);
  });
  return row("Quellen (RSS)", "„Was gibt's Neues?“ liest die neuesten Meldungen dieser Feeds vor.",
    el("div", { class: "obj-list" }, rows.length ? rows : el("p", { class: "muted small" }, "Noch keine Quellen."),
      el("button", { type: "button", class: "btn small", onclick: () => { feeds.push({ name: "", url: "" }); update(true); } }, icon("i-new"), "Quelle hinzufügen")),
    { path, wide: true });
}

function haConnect() {
  const tokenName = get("homeassistant.token_secret") || "homeassistant_token";
  const btn = el("button", { type: "button", class: "btn small" }, icon("i-refresh"), "Verbindung testen & Geräte laden");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      S.ha = await ctx.api("/api/admin/homeassistant/test", { method: "POST", body: { url: get("homeassistant.url") || "", token: S.secrets[tokenName] || "", verify_tls: !!get("homeassistant.verify_tls") } });
    } catch (e) { S.ha = { ok: false, error: e.message }; }
    btn.disabled = false;
    render();
  });
  const status = !S.ha ? null : S.ha.ok
    ? el("span", { class: "st ok" }, `Verbunden – Home Assistant ${S.ha.version}, ${S.ha.entities.length} Entitäten`)
    : el("span", { class: "st error" }, S.ha.error);
  return row("Verbindung", null, el("div", { class: "inline-row" }, btn, status));
}

function haEntities() {
  const path = "homeassistant.entities";
  const selected = [...(get(path) || [])];
  const parts = [tagsControl({
    id: fid(path), values: selected, placeholder: "z. B. light.wohnzimmer + Enter",
    transform: (x) => x.toLowerCase(), onChange: (v) => set(path, v, !!S.ha?.ok),
  })];
  if (S.ha?.ok) {
    const domains = [...new Set(S.ha.entities.map((e) => e.domain))];
    const filter = el("input", { class: "input", type: "search", placeholder: "Filtern, z. B. Wohnzimmer", value: S.haFilter });
    const grid = el("div", { class: "check-grid" });
    const draw = () => {
      const q = S.haFilter.toLowerCase();
      const hits = S.ha.entities.filter((e) => !q || e.name.toLowerCase().includes(q) || e.id.includes(q)).slice(0, 400);
      grid.replaceChildren(...hits.map((e) => {
        const box = el("input", { type: "checkbox", checked: selected.includes(e.id) });
        box.addEventListener("change", () => {
          const next = box.checked ? [...selected, e.id] : selected.filter((x) => x !== e.id);
          selected.splice(0, selected.length, ...next);
          set(path, [...selected], true);
        });
        return el("label", { class: "entity" }, box, el("span", {}, el("b", {}, e.name), el("small", {}, `${e.id} · ${e.state}`)));
      }));
      if (!hits.length) grid.append(el("p", { class: "muted small" }, "Keine Treffer."));
    };
    filter.addEventListener("input", () => { S.haFilter = filter.value; draw(); });
    draw();
    parts.push(el("div", { class: "inline-row" }, filter, el("small", { class: "muted" }, `${domains.length} Bereiche`)), grid);
  } else {
    parts.push(el("p", { class: "muted small" }, "Tipp: „Verbindung testen“ lädt alle Geräte aus Home Assistant zum Ankreuzen."));
  }
  return row("Sichtbar und schaltbar", "Nur diese Entitäten erscheinen im Dashboard und auf dem CYD.", el("div", { class: "stack-s" }, parts), { path, wide: true });
}

function haVoice() {
  const list = clone(get("mcp_servers")) || [];
  const i = list.findIndex((m) => m.name === "homeassistant");
  const enabled = i >= 0 && list[i].enabled;
  const url = `${String(get("homeassistant.url") || "").replace(/\/+$/, "")}/api/mcp`;
  const input = el("input", { type: "checkbox", role: "switch", id: "set-ha-voice", checked: enabled });
  input.addEventListener("change", () => {
    if (i < 0) {
      list.push({ name: "homeassistant", enabled: input.checked, transport: "http", command: "", args: [], env: {}, url,
        headers: { Authorization: "Bearer ${secret:homeassistant_token}" },
        tools: ["HassTurnOn", "HassTurnOff", "HassLightSet", "HassClimateSetTemperature", "GetLiveContext"], risk: "write", tool_risks: {}, taint: false });
    } else {
      list[i].enabled = input.checked;
      if (input.checked) list[i].url = url;
    }
    set("mcp_servers", list, true);
  });
  const parts = [row("Geräte per Sprache steuern", "„Mach das Licht im Wohnzimmer an“ – über den MCP-Server von Home Assistant.",
    el("label", { class: "toggle" }, input, el("span", { "aria-hidden": "true" })), { id: "set-ha-voice" })];
  if (enabled && list[i].url !== url && get("homeassistant.url")) {
    parts.push(el("p", { class: "set-note warn" }, icon("i-warn"), `Der MCP-Server zeigt auf ${list[i].url}.`,
      el("button", { type: "button", class: "btn small", onclick: () => { list[i].url = url; set("mcp_servers", list, true); } }, "Adresse übernehmen")));
  }
  parts.push(el("p", { class: "set-note" }, icon("i-help"), "In Home Assistant die Integration „Model Context Protocol Server“ hinzufügen und die Geräte für Sprachassistenten freigeben."));
  return parts;
}

function whitelistEditor() {
  if (!S.wlRows) S.wlRows = Object.entries(S.whitelist || S.data.whitelist).map(([name, actions]) => ({ name, actions: [...actions] }));
  const sync = () => {
    const obj = {};
    for (const r of S.wlRows) if (r.name.trim()) obj[r.name.trim()] = r.actions;
    S.whitelist = same(obj, S.data.whitelist) ? null : obj;
    updateBar();
  };
  const ACTIONS = [["status", "Status"], ["start", "Starten"], ["stop", "Stoppen"], ["restart", "Neu starten"]];
  const rows = S.wlRows.map((r) => {
    const name = el("input", { class: "input", value: r.name, placeholder: "Containername", "aria-label": "Containername", spellcheck: "false" });
    name.addEventListener("input", () => { r.name = name.value; sync(); });
    return el("div", { class: "obj-line wl" }, name,
      el("div", { class: "checks inline" }, ACTIONS.map(([a, label]) => {
        const box = el("input", { type: "checkbox", checked: r.actions.includes(a) });
        box.addEventListener("change", () => { r.actions = ACTIONS.map(([x]) => x).filter((x) => (x === a ? box.checked : r.actions.includes(x))); sync(); });
        return el("label", { class: "check" }, box, el("span", {}, label));
      })),
      el("button", { type: "button", class: "icon-btn", title: "Entfernen", "aria-label": `${r.name || "Container"} entfernen`, onclick: () => { S.wlRows.splice(S.wlRows.indexOf(r), 1); sync(); render(); } }, icon("i-trash")));
  });
  return row(null, null, el("div", { class: "obj-list" }, rows.length ? rows : el("p", { class: "muted small" }, "Noch keine Container freigegeben."),
    el("button", { type: "button", class: "btn small", onclick: () => { S.wlRows.push({ name: "", actions: ["status"] }); render(); } }, icon("i-new"), "Container freigeben"),
    el("p", { class: "muted small" }, "Der Name muss genau so lauten wie in Docker (Unraid: Docker-Seite).")), { wide: true });
}

function kvEditor(obj, onChange, { keyLabel = "Name", valueLabel = "Wert" } = {}) {
  const rows = Object.entries(obj || {});
  const emit = () => onChange(Object.fromEntries(rows.filter(([k]) => k.trim())));
  const box = el("div", { class: "obj-list" });
  const draw = () => {
    box.replaceChildren(...rows.map((r, i) => {
      const k = el("input", { class: "input", value: r[0], placeholder: keyLabel, "aria-label": keyLabel, spellcheck: "false" });
      const masked = r[1] === "***";
      const v = el("input", { class: "input", value: masked ? "" : r[1], placeholder: masked ? "••• gespeichert (unverändert)" : valueLabel, "aria-label": valueLabel, spellcheck: "false" });
      k.addEventListener("input", () => { r[0] = k.value; emit(); });
      v.addEventListener("input", () => { r[1] = v.value || (masked ? "***" : ""); emit(); });
      return el("div", { class: "obj-line" }, k, v, el("button", { type: "button", class: "icon-btn", "aria-label": "Entfernen", onclick: () => { rows.splice(i, 1); emit(); draw(); } }, icon("i-trash")));
    }), el("button", { type: "button", class: "btn small ghost", onclick: () => { rows.push(["", ""]); draw(); } }, icon("i-new"), "Eintrag"));
  };
  draw();
  return box;
}

const MCP_BUILTIN = { docker: "Docker-Steuerung (eingebaut) – Container aus der Liste oben.", searxng: "Websuche über das eingebaute SearXNG." };

function mcpEditor() {
  const list = clone(get("mcp_servers")) || [];
  const update = (rerender) => set("mcp_servers", list, rerender);
  const cards = list.map((m, i) => {
    const builtin = m.name in MCP_BUILTIN;
    const err = (k) => S.errors[`mcp_servers.${i}.${k}`];
    const enabled = el("input", { type: "checkbox", role: "switch", checked: m.enabled, "aria-label": `${m.name} aktiv` });
    enabled.addEventListener("change", () => { m.enabled = enabled.checked; update(true); });
    const head = el("div", { class: "obj-head" }, el("b", {}, m.name || "Neuer Server"),
      el("label", { class: "toggle small" }, enabled, el("span", { "aria-hidden": "true" })),
      builtin || m.name === "homeassistant" ? null : el("button", { type: "button", class: "icon-btn", title: "Entfernen", "aria-label": `${m.name} entfernen`, onclick: () => { list.splice(i, 1); update(true); } }, icon("i-trash")));
    const body = [];
    if (builtin) body.push(el("p", { class: "muted small" }, MCP_BUILTIN[m.name]));
    else {
      const mini = (label, control, key) => el("label", { class: `mini${err(key) ? " has-error" : ""}` }, label, control, err(key) ? el("span", { class: "set-error" }, err(key)) : null);
      const name = el("input", { class: "input", value: m.name, spellcheck: "false" });
      name.addEventListener("input", () => { m.name = name.value.trim(); update(false); });
      const transport = el("select", { class: "input" }, [["stdio", "Programm (stdio)"], ["http", "HTTP"], ["sse", "SSE"]].map(([v, l]) => el("option", { value: v, selected: m.transport === v }, l)));
      transport.addEventListener("change", () => { m.transport = transport.value; update(true); });
      const risk = el("select", { class: "input" }, [["read", "Lesen"], ["write", "Schreiben"], ["critical", "Kritisch"], ["mixed", "Gemischt"]].map(([v, l]) => el("option", { value: v, selected: m.risk === v }, l)));
      risk.addEventListener("change", () => { m.risk = risk.value; update(false); });
      const line = [mini("Name", name, "name"), mini("Verbindung", transport, "transport"), mini("Risiko", risk, "risk")];
      if (m.transport === "stdio") {
        const cmd = el("input", { class: "input", value: m.command, placeholder: "z. B. npx", spellcheck: "false" });
        cmd.addEventListener("input", () => { m.command = cmd.value; update(false); });
        line.push(mini("Befehl", cmd, "command"));
      } else {
        const url = el("input", { class: "input", value: m.url, placeholder: "https://…/mcp", spellcheck: "false" });
        url.addEventListener("input", () => { m.url = url.value; update(false); });
        line.push(mini("Adresse", url, "url"));
      }
      body.push(el("div", { class: "obj-row" }, line));
      if (m.transport === "stdio") body.push(el("div", { class: "mini" }, "Argumente", tagsControl({ id: `mcp-args-${i}`, values: m.args, placeholder: "Argument + Enter", onChange: (v) => { m.args = v; update(false); } })));
      const taint = el("input", { type: "checkbox", checked: m.taint });
      taint.addEventListener("change", () => { m.taint = taint.checked; update(false); });
      body.push(el("label", { class: "check" }, taint, el("span", {}, el("b", {}, "Ergebnisse sind fremde Inhalte"), el("small", {}, "z. B. Websuche: danach keine kritischen Aktionen ohne Rückfrage."))));
    }
    if (m.name !== "docker") {
      body.push(el("div", { class: "mini" }, "Freigegebene Werkzeuge",
        tagsControl({ id: `mcp-tools-${i}`, values: m.tools || [], placeholder: "Werkzeugname + Enter", onChange: (v) => { m.tools = v.length ? v : null; update(false); } }),
        el("small", { class: "muted" }, m.tools?.length ? "Nur diese Werkzeuge sind erlaubt." : "Leer = alle Werkzeuge des Servers (nicht empfohlen).")));
    }
    if (S.advanced && !builtin) {
      body.push(el("details", { class: "obj-more" }, el("summary", {}, "Umgebung und Header"),
        el("div", { class: "mini" }, "Umgebungsvariablen", kvEditor(m.env, (v) => { m.env = v; update(false); })),
        el("div", { class: "mini" }, "HTTP-Header", kvEditor(m.headers, (v) => { m.headers = v; update(false); }, { keyLabel: "Header", valueLabel: "z. B. Bearer ${secret:name}" })),
        el("p", { class: "muted small" }, "Zugangsdaten als ${secret:name} eintragen und den Schlüssel unter „Schlüssel & Zugänge“ anlegen.")));
    }
    return el("div", { class: `obj${m.enabled ? "" : " off"}` }, head, body);
  });
  return row(null, null, el("div", { class: "obj-list" }, cards,
    el("button", {
      type: "button", class: "btn small", onclick: () => {
        list.push({ name: `server${list.length + 1}`, enabled: true, transport: "http", command: "", args: [], env: {}, url: "", headers: {}, tools: [], risk: "read", tool_risks: {}, taint: false });
        update(true);
      },
    }, icon("i-new"), "MCP-Server hinzufügen"),
    S.advanced ? null : el("p", { class: "muted small" }, "Umgebungsvariablen und Header: oben „Erweitert anzeigen“.")), { wide: true });
}

function keysList() {
  const names = Object.keys(S.data.secrets).sort((a, b) => secretInfo(a).label.localeCompare(secretInfo(b).label, "de"));
  const rows = names.map((name) => row(secretInfo(name).label, null, secretControl(name, { multiline: name === "google_credentials", optional: true }), { id: fid(`secret-${name}`) }));
  const nameIn = el("input", { class: "input", placeholder: "eigener_name", spellcheck: "false", pattern: "[a-z][a-z0-9_]{1,63}" });
  const add = el("button", {
    type: "button", class: "btn small", onclick: () => {
      const n = nameIn.value.trim().toLowerCase();
      if (!/^[a-z][a-z0-9_]{1,63}$/.test(n)) { toast("Name: Kleinbuchstaben, Ziffern und _ (mind. 2 Zeichen)."); return; }
      if (!S.data.secrets[n]) S.data.secrets[n] = { set: false, source: null, label: n };
      render();
      setTimeout(() => $(fid(`secret-${n}`))?.focus(), 0);
    },
  }, icon("i-new"), "Anlegen");
  rows.push(row("Eigener Schlüssel", "Für eigene MCP-Server: in Headern als ${secret:name} verwenden.", el("div", { class: "inline-row" }, nameIn, add)));
  return rows;
}

// ---------------------------------------------------------------- Abschnitte & Leiste
function sectionOf(path) {
  let best = null; let len = -1;
  for (const s of SECTIONS) {
    for (const p of s.prefixes) {
      if ((path === p || path.startsWith(`${p}.`)) && p.length > len) { best = s.id; len = p.length; }
    }
  }
  return best;
}

function renderNav() {
  const counts = {}; const errs = {};
  for (const p of Object.keys(S.draft)) { const s = sectionOf(p); if (s) counts[s] = (counts[s] || 0) + 1; }
  if (S.whitelist) counts.tools = (counts.tools || 0) + 1;
  if (Object.keys(S.secrets).length) counts.keys = Object.keys(S.secrets).length;
  for (const p of Object.keys(S.errors)) { const s = sectionOf(p); if (s) errs[s] = true; }
  $("set-nav").replaceChildren(...SECTIONS.map((s) => el("button", {
    type: "button", "aria-current": s.id === S.section ? "true" : null, onclick: () => showSection(s.id),
  }, icon(s.icon), el("span", {}, s.title),
  errs[s.id] ? el("i", { class: "badge err", title: "Eingaben prüfen" }, "!") : counts[s.id] ? el("i", { class: "badge", title: "Ungespeicherte Änderungen" }, String(counts[s.id])) : null)));
}

export function render() {
  if (!S.data) return;
  const sec = SECTIONS.find((s) => s.id === S.section) || SECTIONS[0];
  const parts = [el("div", { class: "set-head" },
    el("div", {}, el("h2", {}, icon(sec.icon), sec.title), el("p", { class: "muted small" }, sec.intro)),
    el("label", { class: "inline-field adv" }, el("input", {
      type: "checkbox", checked: S.advanced,
      onchange: (e) => { S.advanced = e.target.checked; render(); },
    }), "Erweitert anzeigen"))];
  if (S.data.readonly) parts.push(el("p", { class: "form-error" }, `${S.data.readonly} Werte lassen sich ansehen, aber nicht ändern.`));
  for (const g of sec.groups) {
    if (g.when && !g.when()) continue;
    const rows = g.fields.map(renderField).flat().filter(Boolean);
    if (!rows.length) continue;
    parts.push(el("section", { class: "panel set-group" }, el("header", {}, el("h3", {}, g.title)),
      g.intro ? el("p", { class: "muted small group-intro" }, g.intro) : null, el("div", { class: "set-rows" }, rows)));
  }
  const fs = el("fieldset", { class: "set-fieldset", disabled: !!S.data.readonly }, parts);
  const scroll = $("main").scrollTop;
  const focusId = document.activeElement?.id;
  $("set-body").replaceChildren(fs);
  $("main").scrollTop = scroll;
  if (focusId && $(focusId) && $("set-body").contains($(focusId))) $(focusId).focus();
  renderNav();
  updateBar();
}

function updateBar() {
  const n = changes();
  const bar = $("set-bar");
  bar.hidden = n === 0;
  $("set-bar-text").textContent = n === 1 ? "1 ungespeicherte Änderung" : `${n} ungespeicherte Änderungen`;
  renderNavCounts();
}

let navTimer = null;
function renderNavCounts() { clearTimeout(navTimer); navTimer = setTimeout(renderNav, 150); }

export function showSection(id) {
  if (!SECTIONS.some((s) => s.id === id)) id = "general";
  S.section = id;
  S.geo = null;
  if (location.hash !== `#settings:${id}`) history.replaceState(null, "", `#settings:${id}`);
  render();
  $("main").scrollTop = 0;
}

// Titel aus Hinweisen („Einstellungen → Smart Home“) → Abschnitt
export function sectionByTitle(title) {
  const t = title.trim().toLowerCase();
  return SECTIONS.find((s) => s.title.toLowerCase() === t || s.title.toLowerCase().startsWith(t))?.id || null;
}

export async function loadSettings(section) {
  S.data = await ctx.api("/api/admin/settings");
  S.wlRows = null;
  if (section) S.section = section;
  render();
}

async function save() {
  const btn = $("set-save");
  const body = { changes: S.draft, secrets: S.secrets };
  if (S.whitelist) body.whitelist = S.whitelist;
  btn.disabled = true;
  try {
    const r = await ctx.api("/api/admin/settings", { method: "PUT", body });
    S.data.values = r.values; S.data.secrets = r.secrets; S.data.warnings = r.warnings;
    if (S.whitelist) S.data.whitelist = S.whitelist;
    S.draft = {}; S.secrets = {}; S.whitelist = null; S.wlRows = null; S.errors = {}; S.ollama = null;
    ctx.onSaved(r.restart_pending);
    toast(r.restart_pending.core ? "Gespeichert – wirkt nach einem Neustart von Jarvis." : "Gespeichert.");
    render();
  } catch (e) {
    S.errors = Object.fromEntries((e.errors || []).map((x) => [x.path, x.message]));
    const first = Object.keys(S.errors).map(sectionOf).find(Boolean);
    if (first && first !== S.section) S.section = first;
    toast(e.message, 5000);
    render();
    setTimeout(() => document.querySelector(".set-row.has-error, .obj-line.has-error, .mini.has-error")?.scrollIntoView({ block: "center", behavior: "smooth" }), 50);
  }
  btn.disabled = false;
}

function discard() {
  S.draft = {}; S.secrets = {}; S.whitelist = null; S.wlRows = null; S.errors = {};
  render();
  toast("Änderungen verworfen.");
}

export function initSettings(options) {
  ctx = options;
  $("set-save").addEventListener("click", save);
  $("set-discard").addEventListener("click", discard);
  window.addEventListener("beforeunload", (e) => { if (dirty()) { e.preventDefault(); e.returnValue = ""; } });
}
