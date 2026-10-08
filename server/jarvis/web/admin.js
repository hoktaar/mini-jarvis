// Mini-Jarvis – Verwaltung: Übersicht, Geräte, Firmware (USB-Flasher), Router, Gedächtnis, Skripte, Timer, Protokoll, System.
import { initFlasher } from "./flasher.js";
import { renderMeters } from "./hud.js";
import { $, applyTheme, el, icon, store, toast } from "./ui.js";

const TOKEN_KEY = "jarvis-admin-token";
const PAGES = {
  overview: ["Übersicht", "Zustand von Server, Diensten und KI-Anbietern"],
  devices: ["Geräte", "Koppeln, einstellen, sperren und aktualisieren"],
  firmware: ["Firmware", "CYD per USB einrichten, Updates per WLAN (OTA)"],
  router: ["Router", "Wie Jarvis Sätze versteht – testen und korrigieren"],
  memory: ["Gedächtnis", "Fakten, die Jarvis sich gemerkt hat"],
  scripts: ["Skripte", "Freigegebene Skripte im Runner"],
  timers: ["Timer & Wecker", "Laufende und klingelnde Einträge"],
  audit: ["Protokoll", "Wer hat wann was ausgelöst"],
  system: ["System", "Konfiguration, Geheimnisse, neu einlesen"],
};
export const KIND_NAME = {
  pwa: "Browser / PWA", cyd: "CYD-Display", esp32: "ESP32-Satellit", android: "Android", android_auto: "Android Auto",
  desktop: "Desktop", telegram: "Telegram", matrix: "Matrix",
};
const KIND_HINT = {
  pwa: "Danach erscheint ein QR-Code: mit dem Handy scannen, fertig.",
  cyd: "Danach kannst du das Display direkt per USB flashen und einrichten (Seite „Firmware“).",
  esp32: "Danach bekommst du Server, Port und Token für die Firmware.",
  android: "Danach erscheint ein QR-Code zum Koppeln.", android_auto: "Danach erscheint ein QR-Code zum Koppeln.",
  desktop: "Danach erscheint ein Link zum Koppeln.",
  telegram: "Für Telegram-Nutzer: Token mit /pair <token> an den Bot schicken.",
  matrix: "Für Matrix-Nutzer: Token mit !pair <token> an den Bot schicken.",
};
const ROUTE_NAME = { fast: "Schnell", ask_slot: "Rückfrage", focused: "LLM gezielt", full: "LLM", escalate: "Cloud" };
const LAT_NAME = {
  stt: "Spracherkennung", router: "Router", llm_local_ttfb: "Lokales LLM · erstes Wort",
  llm_cloud_ttfb: "Cloud-LLM · erstes Wort", tts_ttfb: "Sprachausgabe · erster Ton", turn_total: "Gesamt · Frage → Antwort",
};
const TIMER_KIND = { timer: "Timer", alarm: "Wecker", reminder: "Erinnerung" };
const OTA_STATE = {
  offered: "Update angeboten", queued: "Update beim nächsten Verbinden", downloading: "Lädt herunter",
  writing: "Schreibt", done: "Aktualisiert", ok: "Aktualisiert", error: "Update fehlgeschlagen", failed: "Update fehlgeschlagen",
};

const S = {
  token: "", page: "overview", ov: null, devices: [], intents: [], rtOffset: 0, auOffset: 0,
  refreshTimer: null, theme: store.get("theme", ""), pendingProvision: null,
};

// ---------------------------------------------------------------- API & Anmeldung
class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = { "X-Admin-Token": S.token };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  let data = null;
  try { data = await res.json(); } catch { /* leer */ }
  if (res.status === 401) {
    logout("Sitzung abgelaufen – bitte neu anmelden.");
    throw new ApiError(401, "Nicht angemeldet");
  }
  if (!res.ok) throw new ApiError(res.status, (data && data.detail) || `Fehler ${res.status}`);
  return data;
}
export const adminToken = () => S.token;

function readToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
function saveToken(token, remember) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
    if (remember) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY);
  } catch { /* privat */ }
}

function showLogin(message = "") {
  $("app").hidden = true;
  $("login").hidden = false;
  $("login-error").hidden = !message;
  $("login-error").textContent = message;
  $("login-token").focus();
}

function logout(message = "") {
  S.token = "";
  try { sessionStorage.removeItem(TOKEN_KEY); localStorage.removeItem(TOKEN_KEY); } catch { /* privat */ }
  clearInterval(S.refreshTimer);
  showLogin(message);
}

async function login(token, remember) {
  const res = await fetch("/api/admin/overview", { headers: { "X-Admin-Token": token } });
  if (res.status === 401) throw new Error("Der Token stimmt nicht.");
  if (!res.ok) throw new Error(`Server antwortet mit Fehler ${res.status}.`);
  S.token = token;
  saveToken(token, remember);
  S.ov = await res.json();
  renderServerCard();
  $("login").hidden = true;
  $("app").hidden = false;
  start();
}

// ---------------------------------------------------------------- Formatierung
// Zeiten in der Zeitzone des Servers – so wie Jarvis sie auch ansagt.
function fmt(ts, opts) {
  try { return new Intl.DateTimeFormat("de-DE", { timeZone: S.ov?.timezone || undefined, ...opts }).format(new Date(ts * 1000)); } catch {
    return new Intl.DateTimeFormat("de-DE", opts).format(new Date(ts * 1000));
  }
}
function fmtTime(ts, withDate = true) {
  if (!ts) return "–";
  const time = fmt(ts, { hour: "2-digit", minute: "2-digit" });
  const day = (t) => fmt(t, { year: "numeric", month: "2-digit", day: "2-digit" });
  return withDate && day(ts) !== day(Date.now() / 1000) ? `${fmt(ts, { day: "2-digit", month: "2-digit" })} ${time}` : time;
}
function fmtSlot(v) {
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v)) {
    const ts = Date.parse(v) / 1000;
    return `${fmt(ts, { weekday: "short", day: "2-digit", month: "2-digit" })}, ${fmt(ts, { hour: "2-digit", minute: "2-digit" })} Uhr`;
  }
  return String(v);
}
function relTime(ts) {
  if (!ts) return "nie";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.round(s / 60)} min`;
  if (s < 86400) return `vor ${Math.round(s / 3600)} h`;
  return `vor ${Math.round(s / 86400)} Tagen`;
}
function untilText(ts) {
  const s = ts - Date.now() / 1000;
  if (s <= 0) return "jetzt";
  if (s < 3600) return `in ${Math.ceil(s / 60)} min`;
  if (s < 86400) return `um ${fmtTime(ts, false)} Uhr`;
  return `${fmtTime(ts)} Uhr`;
}
function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} T ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}
const fmtKB = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1).replace(".", ",")} MB` : `${Math.round(b / 1024)} KB`);
const fmtEuro = (v) => `${Number(v || 0).toFixed(2).replace(".", ",")} €`;
const st = (level, text) => el("span", { class: `st ${level}` }, text);
const empty = (text) => el("li", { class: "empty" }, text);

export function confirmDialog(title, text, okLabel = "Ja") {
  const dlg = $("confirm-dialog");
  $("confirm-title").textContent = title;
  $("confirm-text").textContent = text;
  $("confirm-ok").textContent = okLabel;
  dlg.showModal();
  return new Promise((resolve) => dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true }));
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Kopiert"); } catch { toast("Kopieren nicht möglich – bitte markieren."); }
}

// ---------------------------------------------------------------- Navigation
function setPage(page) {
  if (!PAGES[page]) page = "overview";
  S.page = page;
  document.body.dataset.page = page;
  document.querySelectorAll(".page").forEach((p) => { p.hidden = p.dataset.page !== page; });
  document.querySelectorAll("#nav [data-page]").forEach((b) => {
    if (b.dataset.page === page) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  $("page-title").textContent = PAGES[page][0];
  $("page-sub").textContent = PAGES[page][1];
  document.title = `Jarvis – ${PAGES[page][0]}`;
  if (location.hash.slice(1) !== page) history.replaceState(null, "", `#${page}`);
  load(page);
}

async function load(page = S.page) {
  try {
    await ({ overview: loadOverview, devices: loadDevices, firmware: loadFirmware, router: loadRouter, memory: loadMemory,
      scripts: loadScripts, timers: loadTimers, audit: () => loadAudit(true), system: loadSystem })[page]();
  } catch (e) {
    if (e.status !== 401) toast(e.message);
  }
}

function start() {
  setPage((location.hash || "#overview").slice(1));
  clearInterval(S.refreshTimer);
  S.refreshTimer = setInterval(() => {
    if (document.hidden) return;
    if (["overview", "devices", "timers"].includes(S.page)) load();
    else refreshServerCard();
  }, 10000);
}

// ---------------------------------------------------------------- Übersicht
async function refreshServerCard() {
  try { S.ov = await api("/api/admin/overview"); renderServerCard(); } catch { /* still */ }
}

function renderServerCard() {
  const ov = S.ov;
  const card = $("srv-card");
  if (!ov) { card.dataset.state = "offline"; return; }
  const bad = Object.values(ov.checks).filter((c) => !c.ok).length + ov.mcp.filter((m) => !m.ok).length;
  card.dataset.state = bad || ov.warnings.length ? "warn" : "ok";
  $("srv-title").textContent = `Jarvis ${ov.version}`;
  $("srv-detail").textContent = bad ? `${bad} Dienst(e) gestört` : ov.warnings.length ? `${ov.warnings.length} Hinweis(e)` : "Alles in Ordnung";
  card.title = `${$("srv-title").textContent} – ${$("srv-detail").textContent}`;
}

async function loadOverview() {
  const [ov, devices] = await Promise.all([api("/api/admin/overview"), api("/api/admin/devices")]);
  S.ov = ov; S.devices = devices;
  renderServerCard();
  const active = devices.filter((d) => !d.revoked);
  const kpi = (label, value, sub) => el("div", { class: "kpi" }, el("span", {}, label), el("b", {}, value), el("small", {}, sub));
  $("ov-kpis").replaceChildren(
    kpi("Version", ov.version, `läuft seit ${fmtUptime(ov.uptime_s)}`),
    kpi("Geräte online", `${active.filter((d) => d.online).length} / ${active.length}`, `${ov.sessions.length} Sitzung(en)`),
    kpi("Timer & Wecker", String(ov.timers), ov.ringing ? `${ov.ringing} klingelt gerade` : "nichts klingelt"),
    kpi("Werkzeuge", String(ov.tools.length), `${ov.mcp.filter((m) => m.ok).length} von ${ov.mcp.length} MCP-Servern`),
    kpi("Hinweise", String(ov.warnings.length), ov.warnings.length ? "siehe unten" : "keine"),
  );

  // Dienste
  const CHECK_NAME = { ollama: "Ollama (lokales LLM)", docker: "Docker-Proxy", runner: "Skript-Runner" };
  const rows = Object.entries(ov.checks).map(([name, c]) => el("li", {},
    el("span", { class: "main" }, el("b", {}, CHECK_NAME[name] || name), el("small", {}, c.detail)),
    el("span", { class: "side" }, st(c.ok ? "ok" : "error", c.ok ? "OK" : "FEHLER"))));
  for (const m of ov.mcp) {
    rows.push(el("li", {},
      el("span", { class: "main" }, el("b", {}, `MCP: ${m.name}`), el("small", {}, m.ok ? `${m.tools.length} Werkzeuge` : m.error || "nicht verbunden")),
      el("span", { class: "side" }, st(m.ok ? "ok" : "error", m.ok ? "OK" : "FEHLER"))));
  }
  rows.push(el("li", {},
    el("span", { class: "main" }, el("b", {}, "GPU-Verwaltung"), el("small", {}, `Modus ${ov.gpu.mode}${ov.gpu.comfyui_running ? " · ComfyUI läuft" : ""}`)),
    el("span", { class: "side" }, st(ov.gpu.busy ? "warn" : "ok", ov.gpu.busy ? "BELEGT" : "FREI"))));
  $("ov-checks").replaceChildren(...(rows.length ? rows : [empty("Keine Dienste konfiguriert.")]));

  // Anbieter
  const p = ov.providers;
  const def = (k, v, cloud = false) => [el("dt", {}, k), el("dd", {}, cloud ? el("span", { class: "chip-s cloud" }, icon("i-cloud"), v) : v)];
  const isCloud = (type) => !["whisper", "piper", "none", "searxng", "aus"].includes(String(type).split(" ")[0]);
  $("ov-providers").replaceChildren(
    ...def("Sprachmodell", p.llm_primary === "cloud" ? "Cloud zuerst, lokal als Ausfall" : "Lokal zuerst"),
    ...def("Lokal", p.llm_local),
    ...def("Cloud", p.llm_cloud, p.llm_cloud !== "aus"),
    ...def("Spracherkennung", p.stt, isCloud(p.stt)),
    ...def("Sprachausgabe", p.tts, isCloud(p.tts)),
    ...def("Websuche", p.search, isCloud(p.search)),
  );
  const tag = $("ov-cloud-tag");
  tag.replaceChildren(st(p.cloud_services.length ? "cloud" : "ok", p.cloud_services.length ? `${p.cloud_services.length} Cloud-Dienst(e)` : "Alles lokal"));
  tag.title = p.cloud_services.join("\n") || "Keine Daten verlassen das Haus.";

  // Latenzen (Tabelle; Balken relativ zum langsamsten Median)
  const lat = ov.metrics.latency_ms;
  const keys = Object.keys(LAT_NAME).filter((k) => lat[k]).concat(Object.keys(lat).filter((k) => !LAT_NAME[k]));
  if (!keys.length) {
    $("ov-latency").replaceChildren(el("p", { class: "muted small" }, "Noch keine Messwerte – sprich ein paar Sätze mit Jarvis."));
  } else {
    const max = Math.max(...keys.map((k) => lat[k].p50), 1);
    $("ov-latency").replaceChildren(el("table", { class: "table lat-table" },
      el("thead", {}, el("tr", {}, el("th", {}, "Stufe"), el("th", { class: "bar-cell" }, ""), el("th", { class: "num" }, "Median"), el("th", { class: "num" }, "90 %"), el("th", { class: "num" }, "zuletzt"))),
      el("tbody", {}, keys.map((k) => el("tr", { title: `${lat[k].n} Messungen` },
        el("td", {}, LAT_NAME[k] || k),
        el("td", { class: "bar-cell" }, el("div", { class: "bar" }, el("i", { style: `width:${Math.round((lat[k].p50 / max) * 100)}%` }))),
        el("td", { class: "num" }, `${lat[k].p50} ms`), el("td", { class: "num" }, `${lat[k].p90} ms`), el("td", { class: "num" }, `${lat[k].last} ms`))))));
  }

  // Budget
  const b = ov.budget;
  const cloudOn = p.llm_cloud !== "aus";
  $("ov-budget-panel").hidden = !cloudOn;
  if (cloudOn) {
    renderMeters($("ov-budget"), [
      { label: `Heute · ${fmtEuro(b.today)}`, value: b.limit_day ? (b.today / b.limit_day) * 100 : null, detail: b.limit_day ? `Grenze ${fmtEuro(b.limit_day)} pro Tag` : "keine Tagesgrenze" },
      { label: `Monat · ${fmtEuro(b.month)}`, value: b.limit_month ? (b.month / b.limit_month) * 100 : null, detail: b.limit_month ? `Grenze ${fmtEuro(b.limit_month)} pro Monat` : "keine Monatsgrenze" },
    ]);
    if (!b.allowed) $("ov-budget").append(el("p", { class: "form-error" }, "Budget erreicht – Jarvis nutzt bis zum Ende des Zeitraums nur das lokale Modell."));
  }

  // Hinweise
  $("ov-warnings").replaceChildren(...(ov.warnings.length
    ? ov.warnings.map((w) => el("li", { class: "warn" }, el("span", { class: "ic" }, icon("i-warn")), el("span", { class: "main" }, w)))
    : [empty("Keine Hinweise – alles eingerichtet.")]));

  // HTTPS
  const h = ov.https;
  const box = [];
  if (!h.enabled) {
    box.push(el("p", { class: "small" }, "HTTPS ist aus. Mikrofon im Browser und der USB-Flasher funktionieren dann nur über localhost."));
  } else {
    box.push(el("dl", { class: "defs" },
      el("dt", {}, "Adresse"), el("dd", {}, el("a", { href: h.url }, h.url)),
      el("dt", {}, "Gültig für"), el("dd", {}, (h.cert.names || []).join(", ") || "–"),
      el("dt", {}, "Läuft ab"), el("dd", {}, h.cert.expires ? new Date(h.cert.expires).toLocaleDateString("de-DE") : "–"),
      el("dt", {}, "Fingerabdruck"), el("dd", {}, el("code", {}, (h.cert.fingerprint || "–").slice(0, 47) + "…"))));
    box.push(el("div", { class: "btn-row" },
      el("a", { class: "btn small", href: "/ca.crt", download: "jarvis-ca.crt" }, icon("i-download"), "CA-Zertifikat laden"),
      el("span", { class: "muted small" }, "Einmal auf jedem Gerät installieren, dann gibt es keine Warnungen mehr.")));
  }
  $("ov-https").replaceChildren(...box);

  // Sitzungen
  $("ov-sessions").replaceChildren(...(ov.sessions.length ? ov.sessions.map((s) => el("li", {},
    el("span", { class: "main" }, el("b", {}, s.device), el("small", {}, [KIND_NAME[s.kind] || s.kind, s.room].filter(Boolean).join(" · "))),
    el("span", { class: "side" }, s.private ? st("warn", "PRIVAT") : null,
      st("ok", s.transport === "voice" ? `Sprache · ${relTime(s.since).replace("vor ", "seit ")}` : "Chat")))) : [empty("Gerade ist niemand verbunden.")]));
}

// ---------------------------------------------------------------- Geräte
function pairingDialog(data) {
  const body = $("pair-body");
  const parts = [el("h2", {}, `${data.name} gekoppelt`)];
  if (data.pair_url) {
    parts.push(el("p", {}, "Mit dem Gerät scannen – oder den Link dort öffnen:"));
    const qr = el("div", { class: "qr", "aria-label": "QR-Code zum Koppeln" });
    qr.innerHTML = data.qr_svg;                       // vom Server erzeugt (segno), keine Nutzereingabe
    parts.push(qr, el("div", { class: "secret" }, el("span", {}, data.pair_url),
      el("button", { type: "button", class: "btn small", onclick: () => copy(data.pair_url) }, "Kopieren")));
  } else if (data.provision) {
    const pv = data.provision;
    parts.push(el("p", {}, "Für ESP32-Geräte: per USB einrichten (empfohlen) oder die Werte in der Firmware eintragen."));
    parts.push(el("dl", { class: "defs" }, el("dt", {}, "Server"), el("dd", {}, pv.host), el("dt", {}, "Port"), el("dd", {}, String(pv.port))));
    parts.push(el("div", { class: "secret" }, el("span", {}, pv.token),
      el("button", { type: "button", class: "btn small", onclick: () => copy(pv.token) }, "Token kopieren")));
    if (data.kind === "cyd" || data.kind === "esp32") {
      parts.push(el("button", {
        type: "button", class: "btn primary", onclick: () => {
          $("pair-dialog").close();
          S.pendingProvision = data;
          setPage("firmware");
        },
      }, icon("i-usb"), "Jetzt per USB einrichten"));
    }
  } else {
    parts.push(el("div", { class: "secret" }, el("span", {}, data.token),
      el("button", { type: "button", class: "btn small", onclick: () => copy(data.token) }, "Kopieren")));
  }
  parts.push(el("p", { class: "muted small" }, "Der Token wird nur jetzt angezeigt. Verloren? Einfach „Neu koppeln“."));
  parts.push(el("menu", { class: "sheet-actions" }, el("button", { class: "btn", value: "close" }, "Fertig")));
  body.replaceChildren(...parts);
  $("pair-dialog").showModal();
}

async function loadDevices() {
  S.devices = await api("/api/admin/devices");
  const box = $("dev-list");
  if (!S.devices.length) {
    box.replaceChildren(el("section", { class: "panel" }, el("p", { class: "muted" }, "Noch keine Geräte. Lege oben das erste an – zum Beispiel dein Handy.")));
    return;
  }
  box.replaceChildren(...S.devices.map(deviceCard));
}

function deviceCard(d) {
  const satellite = d.kind === "cyd" || d.kind === "esp32";
  const status = d.revoked ? st("", "GESPERRT") : d.online ? st("ok", "ONLINE") : st("", "OFFLINE");
  const meta = [el("dt", {}, "Raum"), el("dd", {}, d.room || "–"), el("dt", {}, "Zuletzt"), el("dd", {}, d.online ? "jetzt verbunden" : relTime(d.last_seen))];
  if (satellite) meta.push(el("dt", {}, "Firmware"), el("dd", {}, d.fw ? `${d.fw}${d.settings.fw_variant ? ` (${d.settings.fw_variant})` : ""}` : "unbekannt"));
  if (d.settings.private) meta.push(el("dt", {}, "Privatmodus"), el("dd", {}, "an – nur lokale Dienste"));
  const card = el("article", { class: `panel device${d.revoked ? " revoked" : ""}` },
    el("header", {}, el("div", {}, el("h3", {}, d.name), el("span", { class: "kind" }, KIND_NAME[d.kind] || d.kind)), status),
    el("dl", { class: "meta" }, meta));
  if (d.ota) {
    const level = /error|fail/.test(d.ota.state) ? "error" : /done|ok/.test(d.ota.state) ? "ok" : "warn";
    card.append(el("div", { class: "ota" }, st(level, `${OTA_STATE[d.ota.state] || d.ota.state}${d.ota.version ? ` · ${d.ota.version}` : ""}${d.ota.progress != null ? ` · ${d.ota.progress} %` : ""}`),
      d.ota.error ? el("small", { class: "muted" }, ` ${d.ota.error}`) : null));
  }
  if (d.revoked) return card;
  if (satellite) {
    const out = el("output", {}, `${d.settings.volume ?? 70} %`);
    const range = el("input", { type: "range", min: 5, max: 100, step: 5, value: d.settings.volume ?? 70, "aria-label": `Lautstärke ${d.name}` });
    range.addEventListener("input", () => { out.textContent = `${range.value} %`; });
    range.addEventListener("change", () => patchDevice(d, { volume: Number(range.value) }));
    card.append(el("label", { class: "vol" }, "Lautstärke", range, out));
  }
  const actions = el("div", { class: "actions" },
    el("button", { class: "btn small", onclick: () => editDevice(d) }, icon("i-edit"), "Bearbeiten"),
    el("button", { class: "btn small", onclick: () => patchDevice(d, { private: !d.settings.private }) }, icon("i-lock"), d.settings.private ? "Privat aus" : "Privat an"),
    el("button", { class: "btn small", onclick: () => rotateDevice(d) }, icon("i-key"), "Neu koppeln"));
  if (satellite) actions.append(el("button", { class: "btn small", onclick: () => otaDevice(d) }, icon("i-download"), "Update"));
  actions.append(el("button", { class: "btn small ghost", onclick: () => revokeDevice(d) }, icon("i-trash"), "Sperren"));
  card.append(actions);
  return card;
}

async function patchDevice(d, patch) {
  try { await api(`/api/admin/devices/${d.id}`, { method: "PATCH", body: patch }); toast("Gespeichert"); loadDevices(); } catch (e) { toast(e.message); }
}

function editDevice(d) {
  const body = $("pair-body");
  const name = el("input", { value: d.name, maxlength: 60, required: true });
  const room = el("input", { value: d.room || "", maxlength: 40 });
  body.replaceChildren(el("h2", {}, "Gerät bearbeiten"), el("label", { class: "field" }, "Name", name), el("label", { class: "field" }, "Raum", room),
    el("menu", { class: "sheet-actions" }, el("button", { class: "btn ghost", value: "cancel", formnovalidate: true }, "Abbrechen"), el("button", { class: "btn primary", value: "save" }, "Speichern")));
  const dlg = $("pair-dialog");
  dlg.showModal();
  dlg.addEventListener("close", () => {
    if (dlg.returnValue === "save" && name.value.trim()) patchDevice(d, { name: name.value.trim(), room: room.value.trim() });
  }, { once: true });
}

async function rotateDevice(d) {
  if (!await confirmDialog("Neu koppeln?", `${d.name} wird getrennt und braucht danach den neuen Token.`, "Neu koppeln")) return;
  try { pairingDialog(await api(`/api/admin/devices/${d.id}/rotate`, { method: "POST" })); loadDevices(); } catch (e) { toast(e.message); }
}

async function revokeDevice(d) {
  if (!await confirmDialog("Gerät sperren?", `${d.name} kann sich danach nicht mehr verbinden. Das lässt sich nicht rückgängig machen.`, "Sperren")) return;
  try { await api(`/api/admin/devices/${d.id}`, { method: "DELETE" }); toast(`${d.name} gesperrt`); loadDevices(); } catch (e) { toast(e.message); }
}

async function otaDevice(d) {
  try {
    const r = await api(`/api/admin/devices/${d.id}/ota`, { method: "POST" });
    toast(r.state === "offered" ? `Update ${r.version} wird installiert …` : `Update ${r.version} startet beim nächsten Verbinden.`);
    setTimeout(loadDevices, 1500);
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- Firmware
let flasher = null;
async function loadFirmware() {
  const data = await api("/api/admin/firmware");
  $("fw-auto").replaceChildren(st(data.auto_update ? "ok" : "", data.auto_update ? "Auto-Update an" : "Auto-Update aus"));
  $("fw-auto").title = "firmware.auto_update in config.yaml";
  $("fw-variants").replaceChildren(...(data.variants.length ? data.variants.map((v) => el("li", {},
    el("span", { class: "ic" }, icon("i-chip")),
    el("span", { class: "main" }, el("b", {}, `${v.title} · ${v.version}`),
      el("small", {}, [v.source === "builtin" ? "im Image gebaut" : "hochgeladen", v.size ? fmtKB(v.size) : "", v.built ? `gebaut ${v.built.slice(0, 10)}` : ""].filter(Boolean).join(" · "))),
    el("span", { class: "side" }, st(v.flashable ? "ok" : "warn", v.flashable ? "USB + OTA" : "nur OTA")))) : [empty("Keine Firmware gefunden – das Image wurde ohne Firmware gebaut.")]));
  if (!flasher) flasher = initFlasher({ api, adminToken, toast, kindName: KIND_NAME });
  flasher.setVariants(data.variants);
  if (S.pendingProvision) { flasher.prepare(S.pendingProvision); S.pendingProvision = null; }
}

// ---------------------------------------------------------------- Router
async function loadRouter() {
  S.intents = await api("/api/admin/intents");
  $("rt-intents").replaceChildren(...S.intents.map((i) => el("span", { class: `chip-s${i.available ? "" : " off"}`, title: i.tool ? `Werkzeug: ${i.tool}${i.available ? "" : " (nicht verfügbar)"}` : "ohne Werkzeug" },
    el("b", {}, i.name), `${i.examples}`, i.fast ? " · schnell" : "")));
  await loadRouterLog(true);
}

async function loadRouterLog(reset = false) {
  if (reset) S.rtOffset = 0;
  const rows = await api(`/api/admin/router-log?limit=40&offset=${S.rtOffset}&route=${encodeURIComponent($("rt-filter").value)}`);
  S.rtOffset += rows.length;
  const tbody = $("rt-log").tBodies[0];
  if (reset) tbody.replaceChildren();
  for (const r of rows) tbody.append(routerRow(r));
  if (reset && !rows.length) tbody.append(el("tr", {}, el("td", { colspan: 8, class: "muted" }, "Noch keine Einträge.")));
  $("rt-more").hidden = rows.length < 40;
}

function routerRow(r) {
  const select = el("select", { "aria-label": "Richtige Absicht" }, el("option", { value: "" }, "–"),
    S.intents.map((i) => el("option", { value: i.name, selected: (r.corrected_intent || "") === i.name }, i.name)));
  const save = el("button", { class: "btn small", title: "Korrektur speichern und als Beispiel lernen" }, icon("i-check"));
  save.addEventListener("click", async () => {
    if (!select.value) return;
    try {
      await api(`/api/admin/router-log/${r.id}/correct`, { method: "POST", body: { intent: select.value, add_example: true } });
      toast(`Gelernt: „${r.text.slice(0, 40)}“ → ${select.value}`);
      tr.classList.add("corrected");
    } catch (e) { toast(e.message); }
  });
  const tr = el("tr", { class: r.corrected_intent ? "corrected" : "" },
    el("td", { class: "time" }, fmtTime(r.ts)), el("td", {}, r.device || "–"), el("td", { class: "text" }, r.text),
    el("td", {}, r.intent || "–"), el("td", { class: "num" }, r.confidence != null ? `${Math.round(r.confidence * 100)} %` : "–"),
    el("td", {}, el("span", { class: `route ${r.route}` }, ROUTE_NAME[r.route] || r.route || "–")),
    el("td", { class: "num" }, r.latency_ms != null ? String(Math.round(r.latency_ms)) : "–"),
    el("td", {}, el("div", { class: "correct" }, select, save)));
  return tr;
}

async function testSentence(text) {
  const r = await api("/api/admin/router/test", { method: "POST", body: { text } });
  const conf = Math.round(r.confidence * 100);
  const slots = Object.entries(r.slots);
  $("rt-result").replaceChildren(el("div", { class: "result" },
    el("div", { class: "head" }, el("b", {}, r.intent || "keine Absicht"), el("span", { class: `chip-s${r.route === "escalate" ? " cloud" : ""}` }, ROUTE_NAME[r.route] || r.route),
      el("span", { class: "muted small" }, `${r.latency_ms} ms`)),
    el("div", { class: "conf" }, el("span", {}, "Sicherheit"), el("div", { class: "bar" }, el("i", { style: `width:${conf}%` })), el("output", {}, `${conf} %`)),
    slots.length ? el("dl", { class: "defs" }, slots.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, fmtSlot(v))])) : el("p", { class: "muted small" }, "Keine Angaben erkannt."),
    r.ask ? el("p", { class: "small" }, `Rückfrage: „${r.ask}“`) : null,
    r.candidates?.length ? el("p", { class: "muted small" }, `Werkzeuge fürs LLM: ${r.candidates.join(", ")}`) : null));
}

async function runEval() {
  $("rt-eval").disabled = true;
  $("rt-eval-out").replaceChildren(el("p", { class: "muted small" }, "Prüfe …"));
  try {
    const r = await api("/api/admin/router/eval");
    const worst = Object.entries(r.per_intent).map(([k, v]) => [k, v.correct / Math.max(1, v.total), v]).sort((a, b) => a[1] - b[1]).slice(0, 5);
    $("rt-eval-out").replaceChildren(
      el("div", { class: "kpi-row" },
        el("div", { class: "kpi" }, el("span", {}, "Treffer"), el("b", {}, `${Math.round(r.accuracy * 100)} %`), el("small", {}, `${r.correct} von ${r.total} Sätzen`)),
        el("div", { class: "kpi" }, el("span", {}, "Schnellweg"), el("b", {}, `${Math.round(r.fast_share * 100)} %`), el("small", {}, "ohne LLM beantwortet"))),
      el("h3", { class: "sub-h" }, "Schwächste Absichten"),
      el("ul", { class: "rows" }, worst.map(([k, share, v]) => el("li", {}, el("span", { class: "main" }, el("b", {}, k)), el("span", { class: "side" }, `${v.correct}/${v.total}`, st(share >= 0.9 ? "ok" : share >= 0.7 ? "warn" : "error", `${Math.round(share * 100)} %`))))),
      r.errors.length ? el("details", { class: "log-box" }, el("summary", {}, `${r.errors.length} Fehler ansehen`),
        el("ul", { class: "rows" }, r.errors.slice(0, 60).map((e) => el("li", {}, el("span", { class: "main" }, el("b", {}, e.text), el("small", {}, `erwartet ${e.expected}, erkannt ${e.got || "–"} (${Math.round(e.confidence * 100)} %)`)))))) : null);
  } catch (e) { $("rt-eval-out").replaceChildren(el("p", { class: "form-error" }, e.message)); }
  $("rt-eval").disabled = false;
}

// ---------------------------------------------------------------- Gedächtnis
async function loadMemory() {
  const items = await api("/api/admin/memory");
  $("mem-count").textContent = `${items.length} Einträge`;
  $("mem-list").replaceChildren(...(items.length ? items.map((m) => el("li", {},
    el("span", { class: "ic" }, icon("i-brain")),
    el("span", { class: "main" }, el("b", {}, m.text), el("small", {}, `gemerkt ${relTime(m.created)}`)),
    el("span", { class: "side" }, el("button", {
      class: "icon-btn", title: "Vergessen", "aria-label": `Vergessen: ${m.text}`,
      onclick: async () => {
        if (!await confirmDialog("Vergessen?", `„${m.text}“ wird gelöscht.`, "Vergessen")) return;
        await api(`/api/admin/memory/${m.id}`, { method: "DELETE" }); loadMemory();
      },
    }, icon("i-trash"))))) : [empty("Jarvis hat sich noch nichts gemerkt. Sag zum Beispiel: „Merk dir, dass …“")]));
}

// ---------------------------------------------------------------- Skripte
async function loadScripts() {
  const scripts = await api("/api/admin/scripts");
  if (!scripts.length) {
    $("sc-list").replaceChildren(el("section", { class: "panel" }, el("p", { class: "muted" }, "Keine Skripte freigegeben. Trage sie in /config/scripts.yaml ein und lies sie unter „System“ neu ein.")));
    return;
  }
  $("sc-list").replaceChildren(...scripts.map((s) => {
    const inputs = Object.entries(s.params).map(([name, p]) => {
      let input;
      if (p.type === "bool") input = el("input", { type: "checkbox", name });
      else if (p.type === "enum" || p.choices?.length) input = el("select", { name }, (p.required ? [] : [el("option", { value: "" }, "–")]).concat(p.choices.map((c) => el("option", { value: c }, c))));
      else input = el("input", { name, type: p.type === "int" ? "number" : "text", min: p.min, max: p.max, pattern: p.pattern, required: p.required });
      return el("label", { class: "field" }, `${name}${p.required ? " *" : ""}`, input);
    });
    const out = el("pre", { class: "script-out", hidden: true });
    const form = el("form", { class: "stack" }, inputs, el("button", { class: "btn primary" }, icon("i-play"), "Ausführen"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const args = {};
      for (const [name, p] of Object.entries(s.params)) {
        const f = form.elements[name];
        if (p.type === "bool") args[name] = f.checked;
        else if (f.value !== "") args[name] = p.type === "int" ? Number(f.value) : f.value;
      }
      if (s.confirm && !await confirmDialog("Skript ausführen?", `${s.id} wird jetzt ausgeführt.`, "Ausführen")) return;
      out.hidden = false; out.textContent = "Läuft …";
      try {
        const r = await api(`/api/admin/scripts/${encodeURIComponent(s.id)}/run`, { method: "POST", body: { args } });
        out.textContent = r.ok ? (r.output || "Erledigt (keine Ausgabe).") : `Fehler: ${r.error || "unbekannt"}${r.output ? `\n${r.output}` : ""}`;
      } catch (err) { out.textContent = `Fehler: ${err.message}`; }
    });
    return el("section", { class: "panel" },
      el("header", {}, el("h2", {}, icon("i-terminal"), s.id), el("span", {}, s.confirm ? st("warn", "MIT RÜCKFRAGE") : null, s.car_allowed ? st("ok", "IM AUTO") : null)),
      el("p", { class: "small" }, s.description || "–"), el("p", { class: "muted small" }, `Zeitlimit ${s.timeout} s`), form, el("div", { class: "log-box" }, out));
  }));
}

// ---------------------------------------------------------------- Timer
async function loadTimers() {
  const data = await api("/api/admin/timers");
  const items = data.items.sort((a, b) => a.due - b.due);
  $("tm-list").replaceChildren(...(items.length ? items.map((t) => el("li", { class: t.ringing ? "warn" : "" },
    el("span", { class: "ic" }, icon("i-timer")),
    el("span", { class: "main" }, el("b", {}, t.label || TIMER_KIND[t.kind] || t.kind),
      el("small", {}, [TIMER_KIND[t.kind], t.device ? `von ${t.device}` : "alle Geräte"].filter(Boolean).join(" · "))),
    el("span", { class: "side" }, t.ringing ? st("warn", "KLINGELT") : el("span", { class: "small" }, untilText(t.due)),
      el("button", {
        class: "icon-btn", title: t.ringing ? "Ausschalten" : "Löschen", "aria-label": `${t.label || TIMER_KIND[t.kind]} löschen`,
        onclick: async () => { await api(`/api/admin/timers/${t.id}`, { method: "DELETE" }); loadTimers(); },
      }, icon("i-x"))))) : [empty("Keine Timer oder Wecker aktiv.")]));
}

// ---------------------------------------------------------------- Protokoll
async function loadAudit(reset = false) {
  if (reset) S.auOffset = 0;
  const rows = await api(`/api/admin/audit?limit=50&offset=${S.auOffset}`);
  S.auOffset += rows.length;
  const tbody = $("au-table").tBodies[0];
  if (reset) tbody.replaceChildren();
  for (const r of rows) {
    const bad = r.result && !/^(ok|ja|erledigt|bestätigt)/i.test(r.result);
    tbody.append(el("tr", {}, el("td", { class: "time" }, fmtTime(r.ts)), el("td", {}, r.actor || "–"), el("td", {}, r.action),
      el("td", { class: "text" }, r.detail || ""), el("td", {}, r.result ? st(bad ? "warn" : "ok", r.result.slice(0, 40)) : "–")));
  }
  if (reset && !rows.length) tbody.append(el("tr", {}, el("td", { colspan: 5, class: "muted" }, "Noch keine Einträge.")));
  $("au-more").hidden = rows.length < 50;
}

// ---------------------------------------------------------------- System
function configNode(key, value, depth = 0) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value);
    const scalars = entries.filter(([, v]) => !(v && typeof v === "object" && !Array.isArray(v)) && !(Array.isArray(v) && v.some((x) => x && typeof x === "object")));
    const nested = entries.filter((e) => !scalars.includes(e));
    return el("details", { open: depth === 0 ? false : null }, el("summary", {}, key),
      scalars.length ? el("div", { class: "kv" }, scalars.flatMap(([k, v]) => [el("span", {}, k), formatValue(v)])) : null,
      nested.length ? el("div", { class: "inner" }, nested.map(([k, v]) => configNode(k, v, depth + 1))) : null);
  }
  if (Array.isArray(value)) {
    return el("details", {}, el("summary", {}, `${key} (${value.length})`),
      el("div", { class: "inner" }, value.map((v, i) => configNode(v?.name || v?.id || `#${i + 1}`, v, depth + 1))));
  }
  return el("div", { class: "kv" }, el("span", {}, key), formatValue(value));
}

function formatValue(v) {
  if (v === true) return el("span", { class: "v-true" }, "ja");
  if (v === false) return el("span", { class: "v-false" }, "nein");
  if (v === "***") return el("span", { class: "v-secret" }, "••• (geheim)");
  if (v == null || v === "") return el("span", { class: "v-false" }, "–");
  if (Array.isArray(v)) return el("span", {}, v.length ? v.join(", ") : "–");
  return el("span", {}, String(v));
}

async function loadSystem() {
  const data = await api("/api/admin/config");
  $("sys-secrets").replaceChildren(...(data.secrets.length ? data.secrets.map((s) => el("span", { class: "chip-s" }, icon("i-key"), s)) : [el("span", { class: "muted small" }, "Keine weiteren Geheimnisse gesetzt.")]));
  const general = {};
  const sections = [];
  for (const [k, v] of Object.entries(data.config)) {
    if (v && typeof v === "object") sections.push([k, v]); else general[k] = v;
  }
  $("sys-config").replaceChildren(configNode("allgemein", general), ...sections.map(([k, v]) => configNode(k, v)));
}

// ---------------------------------------------------------------- Ereignisse
function bind() {
  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.submitter; if (btn) btn.disabled = true;
    try { await login($("login-token").value.trim(), $("login-remember").checked); $("login-token").value = ""; } catch (err) { showLogin(err.message); }
    if (btn) btn.disabled = false;
  });
  $("nav").addEventListener("click", (e) => { const b = e.target.closest("[data-page]"); if (b) setPage(b.dataset.page); });
  window.addEventListener("hashchange", () => { if (S.token) setPage(location.hash.slice(1)); });
  $("refresh").addEventListener("click", () => load());
  $("logout").addEventListener("click", () => logout());
  $("theme").addEventListener("click", () => {
    const dark = S.theme === "light" ? false : S.theme === "dark" ? true : !window.matchMedia("(prefers-color-scheme: light)").matches;
    S.theme = dark ? "light" : "dark"; store.set("theme", S.theme); applyTheme(S.theme);
  });
  $("dev-kind").addEventListener("change", () => { $("dev-kind-hint").textContent = KIND_HINT[$("dev-kind").value] || ""; });
  $("dev-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const data = await api("/api/admin/devices", { method: "POST", body: { name: $("dev-name").value.trim(), kind: $("dev-kind").value, room: $("dev-room").value.trim() } });
      $("dev-name").value = ""; $("dev-room").value = "";
      pairingDialog(data);
      loadDevices();
    } catch (err) { toast(err.message); }
  });
  $("rt-form").addEventListener("submit", async (e) => { e.preventDefault(); try { await testSentence($("rt-text").value); } catch (err) { toast(err.message); } });
  $("rt-eval").addEventListener("click", runEval);
  $("rt-retrain").addEventListener("click", async () => {
    try { const r = await api("/api/admin/router/retrain", { method: "POST" }); toast(`Neu gelernt (${r.examples} eigene Beispiele)`); } catch (err) { toast(err.message); }
  });
  $("rt-filter").addEventListener("change", () => loadRouterLog(true));
  $("rt-more").addEventListener("click", () => loadRouterLog());
  $("au-more").addEventListener("click", () => loadAudit());
  $("mem-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/api/admin/memory", { method: "POST", body: { text: $("mem-text").value.trim() } }); $("mem-text").value = ""; loadMemory(); } catch (err) { toast(err.message); }
  });
  $("sys-reload").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/reload", { method: "POST" });
      $("sys-reload-out").textContent = `Neu eingelesen: ${r.intents} Absichten. ${r.hint}`;
    } catch (err) { $("sys-reload-out").textContent = err.message; }
  });
  $("fw-upload").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData();
    form.append("variant", $("fw-up-variant").value);
    form.append("version", $("fw-up-version").value.trim());
    form.append("file", $("fw-up-file").files[0]);
    try {
      const m = await api("/api/admin/firmware/upload", { method: "POST", form });
      toast(`Firmware ${m.variant} ${m.version} hochgeladen`);
      e.target.reset();
      loadFirmware();
    } catch (err) { toast(err.message); }
  });
  $("dev-kind-hint").textContent = KIND_HINT[$("dev-kind").value];
}

applyTheme(S.theme);
bind();
const saved = readToken();
if (saved) {
  login(saved, (() => { try { return !!localStorage.getItem(TOKEN_KEY); } catch { return false; } })()).catch(() => logout());
} else {
  showLogin();
}
