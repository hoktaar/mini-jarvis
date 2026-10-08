// Mini-Jarvis – HUD-Dashboard und Sprachbedienung (Pipecat RTVI, lokal gebündelt).
import { formatMbit, renderMeters, renderNetmap, renderSpark, setRing, startWave } from "./hud.js";
import { $, el, icon, store, toast } from "./ui.js";
import { PipecatClient, WavMediaManager, WebSocketTransport } from "./vendor/pipecat.js";

const STATE_TEXT = {
  idle: "Bereit – tippe zum Sprechen", listening: "Höre zu …", thinking: "Denke nach …", speaking: "Jarvis spricht",
  alarm: "Alarm!", offline: "Nicht verbunden", connecting: "Verbinde …",
};
const KIND_ICON = { timer: "i-timer", alarm: "i-alarm", reminder: "i-bell", event: "i-event" };
const KIND_NAME = { timer: "Timer", alarm: "Wecker", reminder: "Erinnerung", event: "Termin" };
const INTENT_NAME = {
  time_now: "Uhrzeit", timer_set: "Timer", timer_list: "Timer", timer_cancel: "Timer", alarm_set: "Wecker",
  alarm_cancel: "Wecker", reminder_set: "Erinnerung", weather: "Wetter", news: "Nachrichten", web_search: "Websuche",
  docker_status: "Container", docker_action: "Container", run_script: "Skript", memory_remember: "Gedächtnis",
  memory_recall: "Gedächtnis", calendar: "Kalender", smart_home: "Smarthome", private_mode: "Privatmodus",
  volume: "Lautstärke", stop: "Stopp", reset: "Neues Thema", repeat: "Wiederholen", help: "Hilfe", chat: "Gespräch",
};
const WEATHER_ICON = (code) => (code == null ? "i-cloud" : code <= 1 ? "i-sun" : code >= 51 ? "i-rain" : "i-cloud");

// ---------------------------------------------------------------- Speicher
const tokenStore = {
  get() { try { return localStorage.getItem("jarvis-token") || ""; } catch { return ""; } },
  set(t) { try { t ? localStorage.setItem("jarvis-token", t) : localStorage.removeItem("jarvis-token"); } catch { /* privat */ } },
};

const S = {
  token: tokenStore.get(), client: null, conn: "offline", state: "offline", micOn: false, ptt: false,
  handsfree: store.get("handsfree", false), speak: store.get("speak", false), details: store.get("details", false),
  theme: store.get("theme", ""), view: store.get("view", "dashboard"), private: false,
  timers: [], events: [], offset: 0, alarm: null, delay: 1000, level: 0,
  reconnectTimer: null, offTimer: null, holdTimer: null, me: null, info: null, audio: null, beep: null,
  wakeLock: null, armed: false, everConnected: false, dash: null, feed: [], warnings: 0, cloud: false, tz: "",
};

// ---------------------------------------------------------------- Hilfen
class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(S.token ? { Authorization: `Bearer ${S.token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* leer */ }
  if (!res.ok) throw new ApiError(res.status, (data && data.detail) || `Fehler ${res.status}`);
  return data;
}


function banner(id, text, actions = [], kind = "") {
  let b = document.querySelector(`[data-banner="${id}"]`);
  if (!text) { b?.remove(); return; }
  if (!b) { b = el("div", { class: `banner ${kind}`, "data-banner": id }); $("banners").append(b); }
  b.replaceChildren(el("span", {}, text), el("div", { class: "actions" }, actions));
}

const serverNow = () => Date.now() / 1000 + S.offset;
const pad = (n) => String(n).padStart(2, "0");
// Alle Zeiten in der Zeitzone des Jarvis-Servers (ein Wandtablet soll dieselbe Uhrzeit zeigen wie der CYD).
const tzOpt = () => (S.tz ? { timeZone: S.tz } : {});
const fmtTime = (d) => d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", ...tzOpt() });
const dayKey = (d) => d.toLocaleDateString("en-CA", tzOpt());

function formatWhen(ts) {
  const d = new Date(ts * 1000);
  const now = new Date(serverNow() * 1000);
  const tomorrow = new Date(now.getTime() + 86400000);
  const time = `${fmtTime(d)} Uhr`;
  if (dayKey(d) === dayKey(now)) return `Heute, ${time}`;
  if (dayKey(d) === dayKey(tomorrow)) return `Morgen, ${time}`;
  return `${d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric", ...tzOpt() })}, ${time}`;
}

function formatCountdown(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec >= 3600) return `${Math.floor(sec / 3600)}:${pad(Math.floor(sec % 3600 / 60))}:${pad(sec % 60)}`;
  return `${Math.floor(sec / 60)}:${pad(sec % 60)}`;
}

function relTime(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  if (dayKey(d) === dayKey(now)) return `${fmtTime(d)} Uhr`;
  if (dayKey(d) === dayKey(new Date(now.getTime() - 86400000))) return "Gestern";
  return d.toLocaleDateString("de-DE", { day: "numeric", month: "numeric", ...tzOpt() });
}

// ---------------------------------------------------------------- Ansicht & Zustand
function applyTheme() {
  if (S.theme) document.documentElement.dataset.theme = S.theme; else delete document.documentElement.dataset.theme;
}

function setView(view) {
  S.view = view; store.set("view", view);
  document.body.dataset.view = view;
  document.querySelectorAll("button[data-view]").forEach((b) => {
    if (b.dataset.view === view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  renderTasks();
  if (S.dash) renderHome(S.dash.home);
  if (view === "chat") $("input").focus({ preventScroll: true });
}

function setConn(state) {
  S.conn = state;
  const av = $("avatar");
  av.dataset.state = state;
  av.title = { connected: "Verbunden", connecting: "Verbinde …", offline: "Getrennt" }[state];
  if (state !== "connected") setState(state === "connecting" ? "connecting" : "offline");
  else if (S.state === "offline" || S.state === "connecting") setState("idle");
  updateOnline();
  updateHint();
}

function updateOnline() {
  const card = $("online-card");
  const reachable = S.conn === "connected" || !!S.dash;
  card.dataset.state = reachable ? (S.warnings > 0 ? "warn" : "ok") : "offline";
  $("online-word").textContent = reachable ? "online" : "offline";
  $("online-detail").textContent = !reachable ? "Nicht verbunden"
    : S.warnings ? `${S.warnings} Hinweis${S.warnings > 1 ? "e" : ""} in der Verwaltung` : "Alle Systeme betriebsbereit";
  card.title = `JARVIS ${$("online-word").textContent} – ${$("online-detail").textContent}`;
}

function setState(state) {
  S.state = state;
  $("orb").dataset.state = state === "connecting" ? "offline" : state;
  $("state-label").textContent = STATE_TEXT[state] || state;
  document.querySelectorAll("#states li").forEach((li) => li.classList.toggle("active", li.dataset.s === state));
  if (state !== "speaking" && state !== "listening") setLevel(0);
}

function updateHint() {
  const hint = $("hint");
  if (!S.token) hint.textContent = "Verbinde zuerst dieses Gerät.";
  else if (!window.isSecureContext && !isLocalhost()) hint.textContent = "Für das Mikrofon brauchst du die HTTPS-Adresse.";
  else if (S.conn === "connected") hint.textContent = S.handsfree ? "Freisprechen: einfach losreden." : "Halten = Push-to-Talk · Leertaste · Esc stoppt";
  else hint.textContent = "Tippe zum Sprechen – oder schreib einfach.";
}

function setLevel(level) {
  S.level = level;
  $("orb").style.setProperty("--level", Math.min(1, level * 2.2).toFixed(3));
}

function tickClock() {
  const now = new Date(serverNow() * 1000);
  const time = `${fmtTime(now)} Uhr`;
  $("clock-date").textContent = now.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short", year: "numeric", ...tzOpt() });
  $("clock-time").textContent = time;
  $("hero-date").textContent = now.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", ...tzOpt() });
  $("hero-time").textContent = time;
  const h = Number(now.toLocaleTimeString("de-DE", { hour: "2-digit", hour12: false, ...tzOpt() }).slice(0, 2));
  $("greeting").textContent = h < 5 ? "Gute Nacht" : h < 11 ? "Guten Morgen" : h < 17 ? "Guten Tag" : h < 22 ? "Guten Abend" : "Gute Nacht";
  renderTasks();
}

// ---------------------------------------------------------------- Gespräch
function hideSuggestions() { $("suggestions").hidden = true; }

function addMessage(role, text, meta = {}) {
  if (!text) return null;
  hideSuggestions();
  removeTyping();
  const li = el("li", { class: `msg ${role}` }, text);
  const tags = [];
  if (meta.provider === "cloud" || meta.cloud) tags.push(el("span", { class: "tag cloud" }, icon("i-cloud"), "Cloud"));
  if (S.details && role === "assistant" && (meta.route || meta.intent)) {
    const route = { fast: "Schnellweg", ask: "Rückfrage", confirm: "Bestätigung", focused: "LLM", full: "LLM", escalate: "Cloud" }[meta.route] || meta.route;
    tags.push(el("span", { class: "tag" }, [route, INTENT_NAME[meta.intent] || meta.intent].filter(Boolean).join(" · ")));
  }
  if (tags.length) li.append(el("span", { class: "meta" }, tags));
  if (role === "assistant" && meta.confirm) {
    li.append(el("span", { class: "meta" },
      el("button", { class: "btn small primary", onclick: () => quickReply("Ja") }, "Ja"),
      el("button", { class: "btn small ghost", onclick: () => quickReply("Nein") }, "Nein")));
  }
  const log = $("log");
  log.append(li);
  while (log.children.length > 80) log.firstElementChild.remove();
  log.scrollTop = log.scrollHeight;
  return li;
}

function showTyping() { removeTyping(); $("log").append(el("li", { class: "msg assistant typing", id: "typing" }, "Jarvis denkt nach")); }
function removeTyping() { $("typing")?.remove(); }

function quickReply(text) {
  document.querySelectorAll(".msg .meta .btn").forEach((b) => b.closest(".meta")?.remove());
  sendText(text);
}

// ---------------------------------------------------------------- Aufgaben (Timer, Wecker, Termine)
function renderTasks() {
  const box = $("tasks");
  const now = serverNow();
  const items = [...S.timers.filter((t) => t.ringing || t.due > now - 1), ...S.events.filter((e) => e.due > now - 3600)]
    .sort((a, b) => a.due - b.due);
  if (!items.length) { box.replaceChildren(el("li", { class: "empty" }, "Keine Timer, Wecker oder Termine.")); return; }
  const limit = S.view === "tasks" ? 50 : 3;
  box.replaceChildren(...items.slice(0, limit).map((t) => {
    const label = t.label || KIND_NAME[t.kind] || "Timer";
    const when = t.ringing ? "klingelt" : t.kind === "timer" ? `noch ${formatCountdown(t.due - now)}` : t.all_day ? "ganztägig" : formatWhen(t.due);
    const li = el("li", { class: t.ringing ? "ringing" : "" },
      el("span", { class: "ic" }, icon(KIND_ICON[t.kind] || "i-timer")),
      el("span", { class: "txt" }, el("b", {}, label), el("small", {}, KIND_NAME[t.kind] || "")),
      el("span", { class: "time" }, when));
    if (t.id != null && t.kind !== "event") {
      li.append(el("button", { class: "ghost-x", "aria-label": `${label} löschen`, title: t.ringing ? "Ausschalten" : "Löschen", onclick: () => cancelTimer(t) }, icon("i-x")));
    }
    return li;
  }));
}

async function cancelTimer(t) {
  try {
    if (t.ringing) await api(`/api/alarms/${t.id}/ack`, { method: "POST" });
    else await api(`/api/timers/${t.id}`, { method: "DELETE" });
    S.timers = S.timers.filter((x) => x.id !== t.id);
    renderTasks();
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- Dashboard
async function loadDashboard() {
  if (!S.token || document.hidden) return;
  let d;
  try { d = await api("/api/dashboard"); } catch (e) { if (e.status === 401) tokenInvalid(); return; }
  S.dash = d;
  S.tz = d.timezone;
  S.offset = d.now - Date.now() / 1000;
  S.warnings = d.warnings;
  S.timers = d.upcoming.filter((u) => u.kind !== "event");
  S.events = d.upcoming.filter((u) => u.kind === "event");
  renderTasks();
  updateOnline();

  if (d.weather) {
    $("weather").hidden = false;
    $("weather-temp").textContent = `${d.weather.temp} °C`;
    $("weather-desc").textContent = d.weather.desc;
    $("weather-place").textContent = d.weather.place;
    $("weather-icon").querySelector("use").setAttribute("href", `#${WEATHER_ICON(d.weather.code)}`);
  }

  renderNetmap($("netmap"), d.devices.list);
  $("kpi-online").textContent = d.devices.online;
  $("kpi-rooms").textContent = d.devices.rooms.length;
  $("kpi-warn").textContent = d.warnings;
  const tag = $("status-tag");
  tag.dataset.level = d.warnings ? "warn" : "ok";
  tag.lastElementChild.textContent = d.warnings ? `${d.warnings} Hinweis${d.warnings > 1 ? "e" : ""}` : "Alle Systeme online";

  const s = d.system || {};
  const disk = s.disks ? (s.disks.Modelle || s.disks.Daten) : null;
  renderMeters($("meters"), [
    { label: "CPU", value: s.cpu, detail: s.cores ? `${s.cores} Kerne · Last ${s.load?.[0] ?? "–"}` : "" },
    { label: "GPU", value: s.gpu ? s.gpu.util : null, detail: s.gpu ? `${s.gpu.name} · ${(s.gpu.mem_used_mb / 1024).toFixed(1).replace(".", ",")} von ${Math.round(s.gpu.mem_total_mb / 1024)} GB · ${s.gpu.temp} °C` : "keine NVIDIA-GPU erkannt" },
    { label: "Arbeitsspeicher", value: s.ram, detail: s.ram_total_gb ? `${s.ram_used_gb} von ${s.ram_total_gb} GB` : "" },
    { label: "Speicher", value: disk?.percent, detail: disk ? `${disk.used_gb} von ${disk.total_gb} GB` : "" },
  ]);
  if (disk) {
    $("disk").hidden = false;
    setRing($("disk-fill"), disk.percent);
    $("disk-pct").textContent = `${Math.round(disk.percent)} %`;
    $("disk-detail").textContent = `${Math.round(disk.used_gb)} von ${Math.round(disk.total_gb)} GB`;
    $("disk").title = `Speicher ${Math.round(disk.percent)} % · ${$("disk-detail").textContent}`;
  }
  const hist = s.history || { down: [], up: [] };
  $("net-down").textContent = formatMbit(s.net_down || 0);
  $("net-up").textContent = formatMbit(s.net_up || 0);
  renderSpark($("spark-down"), hist.down, formatMbit);
  renderSpark($("spark-up"), hist.up, formatMbit);

  $("caps").replaceChildren(...d.capabilities.map((c) => el("li", { class: c.ok ? "ok" : "off", title: c.ok ? "verfügbar" : "nicht eingerichtet" }, c.name)));

  $("recent").replaceChildren(...(d.recent.length ? d.recent.map((r) => el("li", {
    title: "Antippen, um die Frage zu übernehmen", onclick: () => { $("input").value = r.text; $("input").focus(); },
  }, el("span", { class: "ic" }, icon("i-chat")),
  el("span", { class: "txt" }, el("b", {}, r.text), el("small", {}, INTENT_NAME[r.intent] || r.intent || "")),
  el("span", { class: "time" }, relTime(r.ts)))) : [el("li", { class: "empty" }, "Noch keine Anfragen.")]));

  renderHome(d.home);
  S.feed = d.feed;
  renderFeed();

  $("devices").replaceChildren(...d.devices.list.map((dv) => el("li", {},
    el("span", { class: `dot${dv.online ? " on" : ""}` }),
    el("span", { class: "txt" }, el("b", {}, dv.name), el("small", {}, [dv.room, dv.kind].filter(Boolean).join(" · "))),
    el("span", { class: "time" }, dv.online ? "online" : "offline"))));
  renderBell();
}

const TILE_ICON = { bulb: "i-bulb", power: "i-power", lock: "i-lock", garage: "i-garage", thermo: "i-thermo", gauge: "i-gauge",
  camera: "i-camera", music: "i-music", film: "i-film", fan: "i-fan", shield: "i-shield", play: "i-play", robot: "i-robot",
  auto: "i-auto", dot: "i-dot" };

function renderHome(home) {
  const box = $("tiles");
  const tag = $("home-tag");
  if (!home.configured) {
    tag.hidden = true;
    box.replaceChildren(el("div", { class: "empty-state" },
      el("span", {}, "Verbinde Home Assistant, um Licht, Heizung und mehr hier zu steuern."),
      el("code", {}, "config.yaml → homeassistant: enabled, url, entities"),
      el("a", { href: "admin.html#system" }, "Zur Verwaltung")));
    return;
  }
  const available = home.tiles.filter((t) => t.available).length;
  tag.hidden = false; tag.dataset.level = available ? "ok" : "warn";
  tag.lastElementChild.textContent = `${available} Geräte online`;
  // Dashboard: 6 Kacheln, der Rest in der Ansicht „Smarthome“
  const limit = S.view === "dashboard" ? 6 : home.tiles.length;
  $("home-more").hidden = home.tiles.length <= limit;
  $("home-more").textContent = `Alle ${home.tiles.length} anzeigen`;
  box.replaceChildren(...home.tiles.slice(0, limit).map((t) => {
    const can = (t.toggle || t.activate) && t.available;
    const tile = el(can ? "button" : "div", {
      class: `tile${t.on ? " on" : ""}${can ? " can" : ""}${t.available ? "" : " unavailable"}`,
      "aria-pressed": t.toggle ? String(t.on) : null, title: `${t.name} · ${t.display}`,
    }, el("span", {}, icon(TILE_ICON[t.icon] || "i-dot")), el("div", {}, el("b", {}, t.name), el("small", {}, t.display)),
    t.toggle ? el("span", { class: "toggle", "aria-hidden": "true" }) : t.activate ? icon("i-play") : el("span"));
    tile.querySelector("svg")?.classList.add("tic");
    if (can) tile.addEventListener("click", () => toggleTile(t, tile));
    return tile;
  }));
}

async function toggleTile(t, tile) {
  tile.classList.toggle("on");
  try {
    await api(`/api/home/${encodeURIComponent(t.entity_id)}/toggle`, { method: "POST" });
    setTimeout(loadDashboard, 800);
  } catch (e) { tile.classList.toggle("on"); toast(e.message); }
}

function renderFeed() {
  const box = $("feed");
  if (!S.feed.length) { box.replaceChildren(el("li", { class: "empty" }, "Noch keine Ereignisse.")); return; }
  const label = { ok: "OK", warn: "WARN", error: "FEHLER", info: "INFO" };
  box.replaceChildren(...S.feed.slice(0, 30).map((f) => {
    return el("li", {}, el("time", {}, fmtTime(new Date(f.ts * 1000))), el("span", {}, f.text),
      el("span", { class: `lvl ${f.level}` }, label[f.level] || f.level.toUpperCase()));
  }));
}

function renderBell() {
  const ringing = S.timers.filter((t) => t.ringing);
  const warnFeed = S.feed.filter((f) => f.level === "warn" || f.level === "error").slice(0, 5);
  const count = ringing.length + (S.warnings ? 1 : 0);
  $("bell-badge").hidden = count === 0;
  $("bell-badge").textContent = String(count);
  const items = [
    ...ringing.map((t) => el("li", {}, `${t.label || KIND_NAME[t.kind]} klingelt`)),
    ...(S.warnings ? [el("li", {}, `${S.warnings} Konfigurationshinweis(e) – `, el("a", { href: "admin.html" }, "Verwaltung"))] : []),
    ...warnFeed.map((f) => el("li", {}, f.text)),
  ];
  $("bell-pop").replaceChildren(el("ul", {}, items.length ? items : [el("li", {}, "Keine Benachrichtigungen.")]));
}

// ---------------------------------------------------------------- Wecker
function unlockAudio() {
  if (S.audio) return;
  try { S.audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { /* ohne Ton */ }
}

function startBeep() {
  stopBeep();
  const tick = () => {
    if (S.audio) {
      const t = S.audio.currentTime;
      for (const [offset, freq] of [[0, 880], [0.18, 1175]]) {
        const o = S.audio.createOscillator(); const g = S.audio.createGain();
        o.frequency.value = freq; o.type = "sine";
        g.gain.setValueAtTime(0.0001, t + offset); g.gain.exponentialRampToValueAtTime(0.4, t + offset + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + offset + 0.15);
        o.connect(g).connect(S.audio.destination); o.start(t + offset); o.stop(t + offset + 0.16);
      }
    }
    navigator.vibrate?.([200, 100, 200]);
  };
  tick();
  S.beep = setInterval(tick, 1200);
}
function stopBeep() { clearInterval(S.beep); S.beep = null; navigator.vibrate?.(0); }

function showAlarm(ev) {
  S.alarm = ev;
  $("alarm-title").textContent = KIND_NAME[ev.kind] || "Alarm";
  $("alarm-text").textContent = ev.text || ev.label || "";
  $("alarm").hidden = false;
  $("alarm-stop").focus();
  setState("alarm");
  startBeep();
  if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    new Notification(`Jarvis – ${KIND_NAME[ev.kind] || "Alarm"}`, { body: ev.text || ev.label, tag: `alarm-${ev.id}`, renotify: true });
  }
}
function hideAlarm(id) {
  if (S.alarm && (id === undefined || S.alarm.id === id)) {
    S.alarm = null; $("alarm").hidden = true; stopBeep();
    setState(S.conn === "connected" ? "idle" : "offline");
  }
}
async function alarmAction(kind) {
  const ev = S.alarm; if (!ev) return;
  hideAlarm();
  try {
    if (S.client) S.client.sendClientMessage("jarvis", kind === "ack" ? { type: "alarm_ack", id: ev.id } : { type: "alarm_snooze", id: ev.id, minutes: 5 });
    else await api(`/api/alarms/${ev.id}/${kind === "ack" ? "ack" : "snooze"}`, { method: "POST", body: kind === "ack" ? undefined : { minutes: 5 } });
    if (kind !== "ack") toast("Schlummern: 5 Minuten");
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- Ereignisse vom Server
function onJarvis(ev) {
  switch (ev.type) {
    case "state":
      if (!S.alarm) setState(ev.value);
      if (ev.value === "idle" && S.micOn && !S.handsfree && !S.ptt) scheduleMicOff(400);
      break;
    case "text":
      if (ev.role === "user") addMessage("user", ev.content);
      else addMessage("assistant", ev.content, ev.meta || {});
      break;
    case "alarm": showAlarm(ev); break;
    case "alarm_stop": hideAlarm(ev.id); break;
    case "timers": S.offset = (ev.now || Date.now() / 1000) - Date.now() / 1000; S.timers = ev.items || []; renderTasks(); renderBell(); break;
    case "private": setPrivate(!!ev.value); break;
    case "cloud": S.cloud = !!ev.value; $("orb").classList.toggle("cloud", S.cloud); break;
    case "notice": addMessage("notice", ev.text); break;
    case "feed": S.feed.unshift(ev.item); S.feed = S.feed.slice(0, 60); renderFeed(); break;
    case "turn_done": S.cloud = false; $("orb").classList.remove("cloud"); break;
    default: break;
  }
}

function setPrivate(value) {
  S.private = value;
  const btn = $("private-btn");
  btn.setAttribute("aria-pressed", String(value));
  btn.querySelector("use").setAttribute("href", value ? "#i-lock" : "#i-unlock");
  btn.title = value ? "Privatmodus an – nur lokale Verarbeitung" : "Privatmodus aus";
}

// ---------------------------------------------------------------- Verbindung
function scheduleReconnect() {
  clearTimeout(S.reconnectTimer);
  if (!S.token || document.hidden) return;
  if (!S.everConnected) { armConnect(); return; }
  S.reconnectTimer = setTimeout(connect, S.delay);
  S.delay = Math.min(30000, S.delay * 2);
}

async function connect() {
  if (!S.token || S.client || S.conn === "connecting") return;
  setConn("connecting");
  let ticket;
  try {
    ticket = (await api("/api/ws-ticket", { method: "POST" })).ticket;
  } catch (e) {
    setConn("offline");
    if (e.status === 401) { tokenInvalid(); return; }
    scheduleReconnect();
    return;
  }
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const client = new PipecatClient({
    // Lokaler Media-Manager: der Standard (Daily) lädt Code von c.daily.co nach – Jarvis soll ohne Internet laufen.
    transport: new WebSocketTransport({ mediaManager: new WavMediaManager(undefined, 16000), recorderSampleRate: 16000 }),
    enableMic: false,
    enableCam: false,
    callbacks: {
      onConnected: () => { S.delay = 1000; S.everConnected = true; banner("gesture", ""); setConn("connected"); },
      onDisconnected: () => { if (S.client === client) { S.client = null; micUi(false); setConn("offline"); scheduleReconnect(); } },
      onServerMessage: (data) => data && data.jarvis && onJarvis(data.jarvis),
      onUserStartedSpeaking: () => { clearTimeout(S.offTimer); if (!S.alarm) setState("listening"); },
      onUserStoppedSpeaking: () => { if (!S.handsfree && !S.ptt) scheduleMicOff(900); },
      onBotStartedSpeaking: () => { if (!S.alarm) setState("speaking"); if (!S.handsfree && !S.ptt && S.micOn) micOff(); },
      onBotStoppedSpeaking: () => { if (!S.alarm && S.state === "speaking") setState("idle"); },
      onLocalAudioLevel: (level) => { if (S.micOn) setLevel(level); },
      onRemoteAudioLevel: (level) => { if (S.state === "speaking") setLevel(level); },
      onError: (msg) => console.warn("Pipecat:", msg),
    },
  });
  S.client = client;
  try {
    await client.connect({ wsUrl: `${scheme}://${location.host}/ws/client?ticket=${encodeURIComponent(ticket)}` });
    if (S.handsfree && window.isSecureContext) micOn();
  } catch (e) {
    console.warn(e);
    if (S.client === client) { S.client = null; setConn("offline"); scheduleReconnect(); }
  }
}

async function disconnect() {
  clearTimeout(S.reconnectTimer);
  const c = S.client; S.client = null;
  if (c) { try { await c.disconnect(); } catch { /* egal */ } }
  micUi(false);
  setConn("offline");
}

function tokenInvalid() {
  banner("token", "Dieses Gerät ist nicht mehr verbunden (Code ungültig oder gesperrt).",
    [el("button", { class: "btn small primary", onclick: () => showOnboarding() }, "Neu koppeln")]);
  updateHint();
}

// Browser geben Audio erst nach einer Nutzergeste frei – vorher läuft alles über REST.
function armConnect() {
  if (S.armed || !S.token) return;
  if (navigator.userActivation?.hasBeenActive) { connect(); return; }
  S.armed = true;
  const go = () => {
    document.removeEventListener("pointerdown", go, true);
    document.removeEventListener("keydown", go, true);
    S.armed = false;
    unlockAudio();
    connect();
  };
  document.addEventListener("pointerdown", go, true);
  document.addEventListener("keydown", go, true);
  if (S.handsfree) banner("gesture", "Tippe einmal irgendwo, um das Freisprechen zu starten.", [], "info");
}

async function pollRinging() {
  if (!S.token || S.client || document.hidden) return;
  try {
    const r = await api("/api/timers");
    S.offset = r.now - Date.now() / 1000; S.timers = r.items || []; renderTasks();
    const ringing = S.timers.find((t) => t.ringing);
    if (ringing && !S.alarm) showAlarm({ id: ringing.id, kind: ringing.kind, label: ringing.label, text: ringing.label || KIND_NAME[ringing.kind] });
    if (!ringing && S.alarm) hideAlarm();
  } catch (e) { if (e.status === 401) tokenInvalid(); }
}

// ---------------------------------------------------------------- Mikrofon
function isLocalhost() { return ["localhost", "127.0.0.1", "::1"].includes(location.hostname); }

function micUi(on) {
  S.micOn = on;
  for (const id of ["talk", "listen"]) $(id).setAttribute("aria-pressed", String(on));
  $("talk").setAttribute("aria-label", on ? "Zuhören beenden" : "Sprechen");
  if (!on && S.state === "listening") setState(S.conn === "connected" ? "idle" : "offline");
}

async function micOn() {
  unlockAudio();
  if (!S.token) { showOnboarding(); return; }
  if (!window.isSecureContext && !isLocalhost()) { showHttpsHelp(true); return; }
  if (!S.client) { await connect(); if (!S.client) { toast("Keine Verbindung zu Jarvis."); return; } }
  clearTimeout(S.offTimer);
  try {
    if (typeof S.client.needsInit === "function" && S.client.needsInit()) await S.client.initDevices();
    S.client.enableMic(true);
  } catch (e) {
    toast(`Mikrofon nicht verfügbar: ${e.message || e}`);
    return;
  }
  micUi(true);
  S.client.sendClientMessage("jarvis", { type: "ptt", value: "start" });
  setState("listening");
  if (!S.handsfree) S.offTimer = setTimeout(micOff, 20000);           // Sicherheitsnetz
  requestWakeLock();
}

function micOff() {
  clearTimeout(S.offTimer);
  if (!S.micOn) return;
  try { S.client?.enableMic(false); S.client?.sendClientMessage("jarvis", { type: "ptt", value: "stop" }); } catch { /* getrennt */ }
  micUi(false);
}

function scheduleMicOff(ms) { clearTimeout(S.offTimer); S.offTimer = setTimeout(micOff, ms); }

function stopAll() {
  if (S.alarm) { alarmAction("ack"); return; }
  try { S.client?.sendClientMessage("jarvis", { type: "stop" }); } catch { /* egal */ }
  if (!S.handsfree) micOff();
}

async function requestWakeLock() {
  if (!S.handsfree || !("wakeLock" in navigator) || S.wakeLock) return;
  try { S.wakeLock = await navigator.wakeLock.request("screen"); S.wakeLock.addEventListener("release", () => { S.wakeLock = null; }); } catch { /* nicht erlaubt */ }
}

// ---------------------------------------------------------------- Text
async function sendText(text) {
  unlockAudio();
  if (!S.token) { showOnboarding(); return; }
  hideSuggestions();
  if (S.view !== "dashboard" && S.view !== "chat") setView("chat");
  const viaSocket = !!S.client && S.conn === "connected";
  if (!viaSocket) { addMessage("user", text); showTyping(); }
  try {
    const r = await api("/api/chat", { method: "POST", body: { text, speak: S.speak } });
    if (r.queued) return;
    removeTyping();
    addMessage("assistant", r.reply || "…", { route: r.route, intent: r.intent, cloud: r.cloud, confirm: r.needs_confirmation });
    setTimeout(loadDashboard, 600);
  } catch (e) {
    removeTyping();
    if (e.status === 401) tokenInvalid();
    addMessage("notice", e.message);
  }
}

// ---------------------------------------------------------------- HTTPS-Hinweis
async function loadInfo() {
  try { S.info = await (await fetch("/api/info")).json(); } catch { S.info = null; }
}

function showHttpsHelp(fromMic = false) {
  if (window.isSecureContext || isLocalhost()) return;
  const actions = [];
  if (S.info?.https_url) {
    const url = new URL(S.info.https_url); url.hash = S.token ? `pair=${S.token}` : "";
    actions.push(el("a", { class: "btn small primary", href: url.toString() }, "Zur sicheren Adresse"));
  }
  if (S.info?.ca) actions.push(el("a", { class: "btn small ghost", href: "/ca.crt", download: "mini-jarvis-ca.crt" }, "Zertifikat (CA) laden"));
  banner("https", "Das Mikrofon funktioniert im Browser nur über HTTPS. Installiere einmalig das Jarvis-Zertifikat und öffne die sichere Adresse.", actions);
  if (fromMic) toast("Mikrofon braucht HTTPS – siehe Hinweis oben.");
}

// ---------------------------------------------------------------- Dialoge
function showOnboarding() { $("ob-token").value = ""; $("onboarding").showModal(); }

function showSettings() {
  $("opt-handsfree").checked = S.handsfree;
  $("opt-speak").checked = S.speak;
  $("opt-details").checked = S.details;
  $("opt-theme").value = S.theme;
  $("st-token").value = S.token;
  $("st-device").textContent = S.me ? `${S.me.name}${S.me.room ? ` · ${S.me.room}` : ""} (${S.me.kind})` : "Noch nicht verbunden";
  const cloud = S.me?.cloud_services || [];
  $("st-cloud").hidden = cloud.length === 0;
  $("st-cloud").textContent = cloud.length ? `Externe Dienste: ${cloud.join(" · ")}. Der Privatmodus hält das Sprachmodell lokal.` : "";
  $("st-version").textContent = S.me ? `Jarvis ${S.me.version}` : "";
  $("opt-notify").hidden = !("Notification" in window) || Notification.permission === "granted";
  $("settings").showModal();
}

async function saveToken(token) {
  token = token.trim();
  if (token === S.token) return;
  await disconnect();
  S.token = token; tokenStore.set(token);
  banner("token", "");
  await refreshMe();
  loadDashboard();
  if (navigator.userActivation?.hasBeenActive) connect(); else armConnect();
}

async function refreshMe() {
  if (!S.token) { S.me = null; updateHint(); return; }
  try {
    S.me = await api("/api/me");
    S.tz = S.me.timezone || S.tz;
    setPrivate(S.me.private);
    S.offset = S.me.now - Date.now() / 1000; S.timers = S.me.timers || []; renderTasks();
    banner("token", "");
  } catch (e) {
    if (e.status === 401) tokenInvalid();
  }
  updateHint();
}

// ---------------------------------------------------------------- Service Worker
function registerSw() {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  navigator.serviceWorker.register("sw.js").then((reg) => {
    const offer = (worker) => banner("update", "Eine neue Version von Jarvis ist da.",
      [el("button", { class: "btn small primary", onclick: () => worker.postMessage("skipWaiting") }, "Neu laden")], "info");
    if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const nw = reg.installing;
      nw?.addEventListener("statechange", () => { if (nw.state === "installed" && navigator.serviceWorker.controller) offer(nw); });
    });
  }).catch(() => { /* ohne Offline-Modus */ });
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!reloading) { reloading = true; location.reload(); } });
}

// ---------------------------------------------------------------- Bedienung
function bindTalkButton(button) {
  button.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    unlockAudio();
    clearTimeout(S.holdTimer);
    S.holdTimer = setTimeout(() => { S.ptt = true; if (!S.micOn) micOn(); }, 300);
  });
  const release = (e) => {
    if (S.holdTimer === null) return;
    clearTimeout(S.holdTimer); S.holdTimer = null;
    if (S.ptt) { S.ptt = false; setTimeout(micOff, 450); return; }
    if (e.type !== "pointerup") return;
    if (S.state === "speaking" && !S.micOn) { stopAll(); micOn(); return; }      // unterbrechen und sprechen
    S.micOn ? micOff() : micOn();
  };
  button.addEventListener("pointerup", release);
  button.addEventListener("pointercancel", release);
  button.addEventListener("pointerleave", (e) => { if (S.ptt) release(e); });
  button.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); S.micOn ? micOff() : micOn(); } });
  button.addEventListener("contextmenu", (e) => e.preventDefault());
}

function bindKeys() {
  const typing = () => ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) || document.querySelector("dialog[open]");
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("cmd-input").focus(); return; }
    if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
      if (!$("bell-pop").hidden) { $("bell-pop").hidden = true; return; }
      stopAll(); return;
    }
    if (e.code !== "Space" || e.repeat || typing() || document.activeElement?.tagName === "BUTTON") return;
    e.preventDefault();
    S.ptt = true; micOn();
  });
  document.addEventListener("keyup", (e) => {
    if (e.code !== "Space" || !S.ptt) return;
    e.preventDefault();
    S.ptt = false; setTimeout(micOff, 450);
  });
}

function init() {
  applyTheme();
  setView(S.view);
  setConn("offline");
  for (const id of ["talk", "orb", "listen"]) bindTalkButton($(id));
  bindKeys();
  tickClock();
  setInterval(tickClock, 1000);
  startWave($("wave"), () => ({
    level: S.level, state: S.state,
    color: S.state === "alarm" ? "#ffb547" : S.cloud ? "#b49cff" : S.state === "offline" ? "#48617f" : "#3fd0ff",
  }));

  document.querySelectorAll("button[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.goto)));
  document.querySelectorAll("[data-say]").forEach((b) => b.addEventListener("click", () => sendText(b.dataset.say)));
  document.querySelectorAll("[data-prefill]").forEach((b) => b.addEventListener("click", () => {
    $("input").value = b.dataset.prefill; $("input").focus(); $("input").setSelectionRange(9999, 9999);
  }));
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("input").value.trim();
    if (text) { $("input").value = ""; sendText(text); }
  });
  $("cmd").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("cmd-input").value.trim();
    if (text) { $("cmd-input").value = ""; $("cmd-input").blur(); sendText(text); }
  });
  $("suggestions").addEventListener("click", (e) => { if (e.target.matches(".chip")) sendText(e.target.textContent); });
  for (const id of ["nav-settings", "tab-settings", "avatar"]) $(id).addEventListener("click", showSettings);
  $("bell").addEventListener("click", () => {
    const pop = $("bell-pop"); pop.hidden = !pop.hidden; $("bell").setAttribute("aria-expanded", String(!pop.hidden));
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".bell-wrap")) $("bell-pop").hidden = true; });
  $("private-btn").addEventListener("click", async () => {
    if (!S.token) { showOnboarding(); return; }
    try { const r = await api("/api/me", { method: "PATCH", body: { private: !S.private } }); setPrivate(r.private); toast(r.private ? "Privatmodus an – nur lokale Verarbeitung" : "Privatmodus aus"); }
    catch (e) { toast(e.message); }
  });
  $("alarm-stop").addEventListener("click", () => alarmAction("ack"));
  $("alarm-snooze").addEventListener("click", () => alarmAction("snooze"));
  $("ob-save").addEventListener("click", (e) => {
    const t = $("ob-token").value.trim();
    if (!t) { e.preventDefault(); $("ob-token").focus(); return; }
    saveToken(t);
  });
  $("settings").addEventListener("close", () => {
    if ($("settings").returnValue !== "save") return;
    S.handsfree = $("opt-handsfree").checked; store.set("handsfree", S.handsfree);
    S.speak = $("opt-speak").checked; store.set("speak", S.speak);
    S.details = $("opt-details").checked; store.set("details", S.details);
    S.theme = $("opt-theme").value; store.set("theme", S.theme); applyTheme();
    saveToken($("st-token").value);
    if (S.handsfree && S.conn === "connected" && !S.micOn) micOn();
    if (!S.handsfree && S.micOn && !S.ptt) micOff();
    updateHint();
  });
  $("opt-notify").addEventListener("click", async () => {
    const p = await Notification.requestPermission();
    toast(p === "granted" ? "Benachrichtigungen sind an." : "Benachrichtigungen wurden nicht erlaubt.");
    $("opt-notify").hidden = p === "granted";
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    if (S.token && !S.client && S.everConnected) { S.delay = 1000; connect(); }
    loadDashboard();
    if (S.handsfree) requestWakeLock();
  });
  window.addEventListener("online", () => { banner("offline", ""); if (!S.client && S.everConnected) connect(); });
  window.addEventListener("offline", () => banner("offline", "Keine Netzwerkverbindung."));
  setInterval(loadDashboard, 5000);
  setInterval(pollRinging, 15000);

  // Pairing-Link: …/#pair=<code>
  const m = location.hash.match(/pair=([^&]+)/);
  if (m) {
    history.replaceState(null, "", location.pathname + location.search);
    saveToken(decodeURIComponent(m[1])).then(() => toast("Gerät gekoppelt – tippe auf den Kern und sprich!"));
  }

  registerSw();
  loadInfo().then(() => showHttpsHelp());
  if (!S.token && !m) showOnboarding();
  else if (!m) { refreshMe(); loadDashboard(); armConnect(); }
  updateHint();
}

init();
