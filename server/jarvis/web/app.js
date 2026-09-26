// Mini-Jarvis PWA: Sprachmodus über Pipecat (RTVI, lokal gebündelt) + Text-Test des Routers.
import { PipecatClient, WebSocketTransport } from "./vendor/pipecat.js";

const $ = (id) => document.getElementById(id);
const STATE_TEXT = { idle: "Bereit", listening: "Hört zu", thinking: "Denkt nach", speaking: "Spricht", alarm: "Alarm", offline: "Nicht verbunden" };
let token = localStorage.getItem("jarvis-token") || "";
let client = null;
let lastCloud = false;

function setState(state) {
  $("ring").dataset.state = state;
  $("state").textContent = STATE_TEXT[state] || state;
}

function addMessage(role, text, meta) {
  if (!text) return;
  const li = document.createElement("li");
  li.className = role + (role === "assistant" && lastCloud ? " cloud" : "");
  li.textContent = text;
  if (meta || li.classList.contains("cloud")) {
    const small = document.createElement("small");
    small.textContent = meta || "";
    li.append(small);
  }
  $("log").append(li);
  li.scrollIntoView({ behavior: "smooth", block: "end" });
}

// Ereignisse vom Jarvis-Core (state, text, alarm, cloud)
function onJarvis(ev) {
  if (ev.type === "state") setState(ev.value);
  else if (ev.type === "text") { addMessage(ev.role, ev.content); if (ev.role === "assistant") lastCloud = false; }
  else if (ev.type === "cloud") lastCloud = !!ev.value;
  else if (ev.type === "alarm") { setState("alarm"); addMessage("assistant", ev.label); notify(ev.label); }
}

function notify(text) {
  if ("Notification" in window && Notification.permission === "granted") new Notification("Jarvis", { body: text });
}

async function startVoice() {
  if (!token) { $("settings").showModal(); return; }
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  client = new PipecatClient({
    transport: new WebSocketTransport({ recorderSampleRate: 16000, playerSampleRate: 16000 }),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onConnected: () => setState("idle"),
      onDisconnected: () => { setState("offline"); stopVoiceUi(); client = null; },
      onServerMessage: (data) => data && data.jarvis && onJarvis(data.jarvis),
      onUserStartedSpeaking: () => setState("listening"),
      onBotStartedSpeaking: () => setState("speaking"),
      onBotStoppedSpeaking: () => setState("idle"),
      onError: (msg) => addMessage("assistant", `Fehler: ${msg?.data?.message || "Verbindung gestört"}`),
    },
  });
  try {
    $("talk").setAttribute("aria-pressed", "true");
    $("talk").textContent = "Beenden";
    await client.connect({ wsUrl: `${scheme}://${location.host}/ws/client?token=${encodeURIComponent(token)}` });
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  } catch (err) {
    const insecure = !window.isSecureContext ? " Das Mikrofon braucht HTTPS (siehe docs/UNRAID.md)." : "";
    addMessage("assistant", `Sprachmodus nicht verfügbar: ${err.message || err}.${insecure}`);
    client = null;
    stopVoiceUi();
  }
}

function stopVoiceUi() {
  $("talk").setAttribute("aria-pressed", "false");
  $("talk").textContent = "Sprechen";
}

async function stopVoice() {
  if (client) { await client.disconnect(); client = null; }
  stopVoiceUi();
  setState("idle");
}

async function sendText(text) {
  if (!token) { $("settings").showModal(); return; }
  addMessage("user", text);
  setState("thinking");
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ text }),
    });
    if (res.status === 401) throw new Error("Token ungültig – bitte unter „Gerät“ neu eintragen.");
    const data = await res.json();
    addMessage("assistant", data.reply, `${data.intent}, ${data.route}, ${Math.round(data.confidence * 100)} %`);
  } catch (err) {
    addMessage("assistant", err.message);
  } finally {
    setState("idle");
  }
}

$("talk").addEventListener("click", () => (client ? stopVoice() : startVoice()));
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("input").value.trim();
  if (text) { $("input").value = ""; sendText(text); }
});
$("settings-btn").addEventListener("click", () => { $("token").value = token; $("settings").showModal(); });
$("save").addEventListener("click", () => { token = $("token").value.trim(); localStorage.setItem("jarvis-token", token); });

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
if (!token) addMessage("assistant", "Verbinde zuerst dieses Gerät über „Gerät“.");
