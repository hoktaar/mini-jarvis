// USB-Einrichtung für CYD/ESP32: Firmware per esptool-js (Web Serial) flashen, danach WLAN, Server und Token
// über die serielle Konsole übergeben. Die WLAN-Daten gehen nur über USB an das Gerät, nie an den Server.
//
// Serielles Protokoll (115200 Baud, Zeilen mit \n), umgesetzt in firmware/cyd/src/provision.cpp:
//   → JARVIS?                       ← JARVIS-READY fw=<version> board=<variante>
//   → JARVIS-CONFIG {json}          ← JARVIS-OK | JARVIS-ERR <grund>
//                                   ← JARVIS-WIFI OK <ip> | JARVIS-WIFI FAIL <grund>
import { $, el, icon } from "./ui.js";

const VARIANT_INFO = {
  cyd: { title: "CYD (ILI9341)", hint: "ESP32-2432S028R mit einem Micro-USB-Anschluss – die häufigste Version." },
  "cyd-st7789": { title: "CYD2USB (ST7789)", hint: "Version mit USB-C und Micro-USB. Zeigt die normale Firmware vertauschte Farben, ist es diese." },
};

class SerialLines {
  constructor(port, onLine) { this.port = port; this.onLine = onLine; this.waiters = []; this.buffer = ""; }

  async open() {
    await this.port.open({ baudRate: 115200 });
    try { await this.port.setSignals({ dataTerminalReady: false, requestToSend: false }); } catch { /* nicht jeder Adapter */ }
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this.loop();
  }

  async loop() {
    const decoder = new TextDecoder();
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        this.buffer += decoder.decode(value, { stream: true });
        let i;
        while ((i = this.buffer.indexOf("\n")) >= 0) {
          const line = this.buffer.slice(0, i).replace(/\r$/, "");
          this.buffer = this.buffer.slice(i + 1);
          this.onLine(line);
          for (const w of [...this.waiters]) if (w.re.test(line)) w.done(line);
        }
        if (this.buffer.length > 4096) this.buffer = "";
      }
    } catch { /* Port geschlossen */ }
  }

  wait(re, ms) {
    return new Promise((resolve, reject) => {
      const w = { re };
      const timer = setTimeout(() => { this.waiters.splice(this.waiters.indexOf(w), 1); reject(new Error("timeout")); }, ms);
      w.done = (line) => { clearTimeout(timer); this.waiters.splice(this.waiters.indexOf(w), 1); resolve(line); };
      this.waiters.push(w);
    });
  }

  async send(text) { await this.writer.write(new TextEncoder().encode(`${text}\n`)); }

  async close() {
    try { await this.reader.cancel(); } catch { /* egal */ }
    try { this.reader.releaseLock(); } catch { /* egal */ }
    try { await this.writer.close(); } catch { /* egal */ }
    try { this.writer.releaseLock(); } catch { /* egal */ }
    try { await this.port.close(); } catch { /* egal */ }
  }
}

function friendlyError(e) {
  const msg = String(e?.message || e);
  if (e?.name === "NotFoundError") return "Kein Gerät ausgewählt.";
  if (e?.name === "SecurityError") return "Der Browser hat den USB-Zugriff blockiert.";
  if (/Failed to open|already open|InvalidStateError|NetworkError/i.test(msg) || e?.name === "InvalidStateError" || e?.name === "NetworkError") {
    return "Der USB-Port ist belegt. Schließe andere Programme (Arduino IDE, PlatformIO-Monitor, andere Browser-Tabs) und versuche es erneut.";
  }
  if (/Failed to connect|Timed out|timeout|No serial data/i.test(msg)) {
    return "Keine Verbindung zum ESP32. Halte die BOOT-Taste gedrückt, tippe kurz auf RST und versuche es erneut. Nutze ein Datenkabel (kein reines Ladekabel).";
  }
  return msg;
}

export function initFlasher({ api, adminToken, toast, kindName }) {
  const F = {
    step: 0, variants: [], variant: "", target: "new", deviceId: "", name: "", room: "", ssid: "", pass: "",
    host: "", port: 8080, hosts: [], tz: "", erase: true, skipFlash: false, provision: null, serial: null, busy: false,
    devices: [], prepared: null, chip: "",
  };
  const body = $("fl-body");
  const logBox = $("fl-log");
  const supported = "serial" in navigator;

  const log = (line) => {
    logBox.textContent += `${line}\n`;
    if (logBox.textContent.length > 60000) logBox.textContent = logBox.textContent.slice(-40000);
    logBox.scrollTop = logBox.scrollHeight;
  };
  const terminal = { clean() {}, writeLine: (d) => log(d), write: (d) => log(String(d).replace(/\n$/, "")) };

  function setSupportTag() {
    const tag = $("fl-support");
    tag.replaceChildren(el("span", { class: `st ${supported ? "ok" : "warn"}` }, supported ? "USB bereit" : "USB nicht verfügbar"));
  }

  function steps() {
    document.querySelectorAll("#fl-steps li").forEach((li, i) => {
      li.classList.toggle("active", i === F.step);
      li.classList.toggle("done", i < F.step);
      if (i === F.step) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
  }

  function go(step) { F.step = step; steps(); render(); }

  function actions(...buttons) { return el("div", { class: "fl-actions" }, buttons); }

  // ------------------------------------------------------------ Schritt 1: Gerät
  function renderDevice() {
    if (!supported) {
      const https = !window.isSecureContext;
      return [
        el("h3", {}, "USB-Zugriff ist in diesem Browser nicht möglich"),
        el("p", {}, https
          ? "Der Browser erlaubt USB nur über HTTPS. Öffne die Verwaltung über die HTTPS-Adresse (Port 8443) und installiere einmal das CA-Zertifikat aus der Übersicht."
          : "Nutze Chrome, Edge oder Opera am Computer. Firefox, Safari und Handys können keine USB-Geräte ansprechen."),
        https ? el("a", { class: "btn primary", href: `https://${location.hostname}:8443/admin.html#firmware` }, "Über HTTPS öffnen") : null,
        el("p", { class: "muted small" }, "Alternativ: Firmware mit PlatformIO flashen (siehe docs/HARDWARE.md) und hier nur den Token anlegen."),
      ];
    }
    const flashable = F.variants.filter((v) => v.flashable);
    if (!F.variant && flashable.length) F.variant = flashable[0].variant;
    const variantChoices = flashable.length ? el("div", { class: "choice-grid", role: "radiogroup", "aria-label": "Variante" }, flashable.map((v) => {
      const info = VARIANT_INFO[v.variant] || { title: v.title, hint: "" };
      const input = el("input", { type: "radio", name: "fl-variant", value: v.variant, checked: F.variant === v.variant });
      input.addEventListener("change", () => { F.variant = v.variant; });
      return el("label", { class: "choice" }, input, el("b", {}, `${info.title} · ${v.version}`), el("small", {}, info.hint));
    })) : el("p", { class: "form-error" }, "Keine flashbare Firmware gefunden. Das Docker-Image enthält sie normalerweise – oder lade einen kompletten Build hoch.");

    const sats = F.devices.filter((d) => !d.revoked && (d.kind === "cyd" || d.kind === "esp32"));
    const targetChoices = [
      ["new", "Neues Gerät anlegen", "Jarvis legt das Gerät beim Einrichten an."],
      ...(sats.length ? [["existing", "Vorhandenes Gerät neu einrichten", "Bekommt einen neuen Token, Name und Raum bleiben."]] : []),
      ...(F.prepared ? [["prepared", `Gerade angelegt: ${F.prepared.name}`, "Den eben erzeugten Token verwenden."]] : []),
    ];
    const targetGrid = el("div", { class: "choice-grid", role: "radiogroup", "aria-label": "Gerät" }, targetChoices.map(([value, title, hint]) => {
      const input = el("input", { type: "radio", name: "fl-target", value, checked: F.target === value });
      input.addEventListener("change", () => { F.target = value; render(); });
      return el("label", { class: "choice" }, input, el("b", {}, title), el("small", {}, hint));
    }));

    const fields = [];
    if (F.target === "new") {
      const name = el("input", { id: "fl-name", required: true, maxlength: 60, value: F.name, placeholder: "z. B. Küche" });
      const room = el("input", { id: "fl-room", maxlength: 40, value: F.room, placeholder: "optional" });
      name.addEventListener("input", () => { F.name = name.value; });
      room.addEventListener("input", () => { F.room = room.value; });
      fields.push(el("div", { class: "form-row" }, el("label", { class: "field" }, "Name", name), el("label", { class: "field" }, "Raum", room)));
    } else if (F.target === "existing") {
      if (!F.deviceId && sats.length) F.deviceId = String(sats[0].id);
      const sel = el("select", { id: "fl-device" }, sats.map((d) => el("option", { value: d.id, selected: String(d.id) === F.deviceId }, `${d.name}${d.room ? ` · ${d.room}` : ""} (${kindName[d.kind] || d.kind})`)));
      sel.addEventListener("change", () => { F.deviceId = sel.value; });
      fields.push(el("label", { class: "field" }, "Gerät", sel));
    }

    const skip = el("input", { type: "checkbox", checked: F.skipFlash });
    skip.addEventListener("change", () => { F.skipFlash = skip.checked; });
    const erase = el("input", { type: "checkbox", checked: F.erase });
    erase.addEventListener("change", () => { F.erase = erase.checked; });

    const next = el("button", { class: "btn primary" }, "Weiter");
    next.addEventListener("click", () => {
      if (F.target === "new" && !F.name.trim()) { $("fl-name").focus(); toast("Bitte einen Namen eingeben."); return; }
      if (!F.skipFlash && !F.variant) { toast("Keine Firmware zum Flashen vorhanden."); return; }
      go(1);
    });
    return [
      el("h3", {}, "Welches Display?"), variantChoices,
      el("h3", {}, "Welches Gerät?"), targetGrid, ...fields,
      el("label", { class: "switch" }, erase, el("span", {}, "Flash vorher komplett löschen", el("small", {}, "Empfohlen bei der ersten Installation oder wenn vorher andere Firmware drauf war."))),
      el("label", { class: "switch" }, skip, el("span", {}, "Nur einrichten, nicht flashen", el("small", {}, "Die Jarvis-Firmware ist schon drauf – nur WLAN, Server und Token übertragen."))),
      actions(next),
    ];
  }

  // ------------------------------------------------------------ Schritt 2: WLAN & Server
  function renderWifi() {
    const ssid = el("input", { id: "fl-ssid", required: true, maxlength: 32, value: F.ssid, autocomplete: "off", spellcheck: "false" });
    const pass = el("input", { id: "fl-pass", type: "password", maxlength: 64, value: F.pass, autocomplete: "new-password" });
    const show = el("button", { type: "button", class: "btn small ghost" }, "Zeigen");
    show.addEventListener("click", () => { pass.type = pass.type === "password" ? "text" : "password"; show.textContent = pass.type === "password" ? "Zeigen" : "Verbergen"; });
    ssid.addEventListener("input", () => { F.ssid = ssid.value; });
    pass.addEventListener("input", () => { F.pass = pass.value; });
    if (!F.host) F.host = F.hosts[0] || location.hostname;
    const host = el("input", { id: "fl-host", required: true, value: F.host, list: "fl-hosts", spellcheck: "false" });
    host.addEventListener("input", () => { F.host = host.value.trim(); });
    const port = el("input", { id: "fl-port", type: "number", min: 1, max: 65535, value: F.port });
    port.addEventListener("input", () => { F.port = Number(port.value) || 8080; });
    const back = el("button", { class: "btn ghost" }, "Zurück");
    back.addEventListener("click", () => go(0));
    const next = el("button", { class: "btn primary" }, F.skipFlash ? "Weiter zum Einrichten" : "Weiter zum Flashen");
    next.addEventListener("click", () => {
      if (!F.ssid.trim()) { ssid.focus(); toast("Bitte den WLAN-Namen eingeben."); return; }
      if (!F.host) { host.focus(); toast("Bitte die Server-Adresse eingeben."); return; }
      go(F.skipFlash ? 3 : 2);
    });
    const local = /\.local$/i.test(F.host);
    return [
      el("h3", {}, "WLAN für das Display"),
      el("p", { class: "muted small" }, "Der ESP32 kann nur 2,4-GHz-WLAN. Die Zugangsdaten gehen nur per USB an das Gerät und werden nicht auf dem Server gespeichert."),
      el("div", { class: "form-row" }, el("label", { class: "field" }, "WLAN-Name (SSID)", ssid),
        el("label", { class: "field" }, "Passwort", el("div", { class: "pw-row" }, pass, show))),
      el("h3", {}, "Jarvis-Server"),
      el("div", { class: "form-row" }, el("label", { class: "field grow" }, "Adresse (IP oder Name)", host), el("label", { class: "field" }, "Port", port)),
      el("datalist", { id: "fl-hosts" }, F.hosts.map((h) => el("option", { value: h }))),
      el("p", { class: "muted small" }, local
        ? "Hinweis: „.local“-Namen löst der ESP32 nicht immer auf. Sicherer ist die feste IP des Servers."
        : "Das Display verbindet sich unverschlüsselt im Heimnetz (HTTP-Port, Standard 8080)."),
      actions(back, next),
    ];
  }

  // ------------------------------------------------------------ Schritt 3: Flashen
  function renderFlash() {
    const back = el("button", { class: "btn ghost", disabled: F.busy }, "Zurück");
    back.addEventListener("click", () => go(1));
    const start = el("button", { class: "btn primary big", disabled: F.busy }, icon("i-usb"), "USB-Gerät wählen und flashen");
    start.addEventListener("click", flash);
    const v = F.variants.find((x) => x.variant === F.variant);
    return [
      el("h3", {}, `Firmware ${VARIANT_INFO[F.variant]?.title || F.variant} ${v ? v.version : ""} flashen`),
      el("ol", { class: "steps small" },
        el("li", {}, "Display mit einem Datenkabel an diesen Computer anschließen."),
        el("li", {}, "Auf den Knopf unten klicken und den Eintrag „USB-SERIAL CH340“ (oder CP210x) wählen."),
        el("li", {}, "Warten – das dauert etwa eine Minute. Das Display bleibt dabei dunkel.")),
      el("div", { class: "progress", id: "fl-progress", hidden: !F.busy },
        el("div", { class: "label" }, el("span", { id: "fl-phase" }, "Bereite vor …"), el("span", { id: "fl-pct" }, "0 %")),
        el("div", { class: "track", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, id: "fl-bar" }, el("div", { class: "fill", id: "fl-fill" }))),
      el("p", { class: "form-error", id: "fl-error", role: "alert", hidden: true }),
      actions(back, start),
    ];
  }

  function progress(phase, pct) {
    const fill = $("fl-fill");
    if (!fill) return;
    $("fl-progress").hidden = false;
    $("fl-phase").textContent = phase;
    $("fl-pct").textContent = `${Math.round(pct)} %`;
    fill.style.width = `${pct}%`;
    $("fl-bar").setAttribute("aria-valuenow", String(Math.round(pct)));
  }

  function showError(id, e) {
    const box = $(id);
    if (!box) { toast(friendlyError(e)); return; }
    box.hidden = false;
    box.textContent = friendlyError(e);
    log(`Fehler: ${e?.message || e}`);
  }

  async function fetchPart(path) {
    const res = await fetch(`/api/firmware/${encodeURIComponent(F.variant)}/${encodeURIComponent(path)}`, { headers: { "X-Admin-Token": adminToken() } });
    if (!res.ok) throw new Error(`${path} nicht ladbar (HTTP ${res.status})`);
    return new Uint8Array(await res.arrayBuffer());
  }

  async function flash() {
    let port;
    try {
      port = await navigator.serial.requestPort();
    } catch (e) { if (e?.name !== "NotFoundError") showError("fl-error", e); return; }
    F.busy = true; render(); $("fl-error").hidden = true;
    let transport = null;
    try {
      progress("Lade Firmware vom Server …", 1);
      const manifest = await api(`/api/admin/firmware/${encodeURIComponent(F.variant)}/manifest`);
      const files = [];
      for (const part of manifest.parts) files.push({ data: await fetchPart(part.path), address: Number(part.offset) });
      log(`Firmware ${manifest.variant} ${manifest.version}: ${files.map((f, i) => `${manifest.parts[i].path}@0x${f.address.toString(16)}`).join(", ")}`);
      progress("Verbinde mit dem ESP32 …", 3);
      const { ESPLoader, Transport } = await import("./vendor/esptool.js");
      transport = new Transport(port, false);
      const loader = new ESPLoader({ transport, baudrate: 921600, romBaudrate: 115200, terminal });
      F.chip = await loader.main();
      log(`Chip: ${F.chip}`);
      const total = files.reduce((s, f) => s + f.data.length, 0);
      const done = files.map(() => 0);
      progress(F.erase ? "Lösche Flash …" : "Schreibe …", 5);
      await loader.writeFlash({
        fileArray: files, flashMode: "keep", flashFreq: "keep", flashSize: "keep", eraseAll: F.erase, compress: true,
        reportProgress: (i, written, size) => {
          done[i] = size ? (written / size) * files[i].data.length : 0;
          progress(`Schreibe ${manifest.parts[i].path} …`, 5 + (done.reduce((a, b) => a + b, 0) / total) * 93);
        },
      });
      progress("Starte neu …", 99);
      await loader.after("hard_reset");
      await transport.disconnect();
      transport = null;
      F.serialPort = port;
      progress("Fertig geflasht", 100);
      log("Flashen abgeschlossen.");
      F.busy = false;
      go(3);
    } catch (e) {
      F.busy = false;
      render();
      showError("fl-error", e);
      try { if (transport) await transport.disconnect(); } catch { /* egal */ }
    }
  }

  // ------------------------------------------------------------ Schritt 4: Einrichten
  function renderProvision() {
    const items = [
      ["token", F.target === "new" ? "Gerät in Jarvis anlegen" : "Neuen Token erzeugen"],
      ["ready", "Verbindung zum Display"],
      ["config", "WLAN und Server übertragen"],
      ["wifi", "Display verbindet sich mit dem WLAN"],
    ];
    const start = el("button", { class: "btn primary big", disabled: F.busy }, icon("i-usb"), F.serialPort ? "Einrichten" : "USB-Gerät wählen und einrichten");
    start.addEventListener("click", provision);
    const back = el("button", { class: "btn ghost", disabled: F.busy }, "Zurück");
    back.addEventListener("click", () => go(F.skipFlash ? 1 : 2));
    return [
      el("h3", {}, "Display einrichten"),
      el("p", { class: "muted small" }, "Das Display muss per USB verbunden bleiben. Danach kann es an jedes USB-Netzteil."),
      el("ul", { class: "checklist", id: "fl-check" }, items.map(([key, text]) => el("li", { "data-key": key }, text))),
      el("p", { class: "form-error", id: "fl-perror", role: "alert", hidden: true }),
      actions(back, start),
    ];
  }

  function check(key, state, text) {
    const li = document.querySelector(`#fl-check [data-key="${key}"]`);
    if (!li) return;
    li.className = state;
    if (text) li.textContent = text;
  }

  async function getProvision() {
    if (F.target === "prepared" && F.prepared?.provision) return F.prepared;
    if (F.provision) return F.provision.__data;
    let data;
    if (F.target === "existing") {
      data = await api(`/api/admin/devices/${F.deviceId}/rotate`, { method: "POST" });
    } else {
      data = await api("/api/admin/devices", { method: "POST", body: { name: F.name.trim(), kind: "cyd", room: F.room.trim() } });
      F.target = "prepared";
      F.prepared = data;
    }
    F.provision = { __data: data };
    return data;
  }

  async function provision() {
    let port = F.serialPort;
    if (!port) {
      try { port = await navigator.serial.requestPort(); } catch (e) { if (e?.name !== "NotFoundError") showError("fl-perror", e); return; }
    }
    F.busy = true; render();
    let serial = null;
    let stage = "token";
    try {
      check("token", "run");
      const data = await getProvision();
      F.deviceId = String(data.id);
      check("token", "ok", `Gerät „${data.name}“ angelegt`);

      stage = "ready";
      check("ready", "run");
      serial = new SerialLines(port, (line) => log(`< ${line}`));
      await serial.open();
      const ready = serial.wait(/^JARVIS-READY/, 30000);
      const poll = setInterval(() => serial.send("JARVIS?").catch(() => undefined), 900);
      let hello;
      try { hello = await ready; } finally { clearInterval(poll); }
      check("ready", "ok", `Display antwortet (${hello.replace("JARVIS-READY", "").trim() || "Jarvis-Firmware"})`);

      stage = "config";
      check("config", "run");
      const pv = data.provision;
      const config = { ssid: F.ssid, pass: F.pass, host: F.host || pv.host, port: F.port || pv.port, token: pv.token, name: data.name, tz: pv.tz };
      log("> JARVIS-CONFIG {… WLAN, Server und Token …}");
      const answer = serial.wait(/^JARVIS-(OK|ERR)/, 15000);
      await serial.send(`JARVIS-CONFIG ${JSON.stringify(config)}`);
      const reply = await answer;
      if (reply.startsWith("JARVIS-ERR")) throw new Error(`Das Display meldet: ${reply.slice(11) || "Fehler"}`);
      check("config", "ok", "Einstellungen gespeichert");

      stage = "wifi";
      check("wifi", "run");
      const wifi = await serial.wait(/^JARVIS-WIFI/, 40000);
      if (!/^JARVIS-WIFI OK/.test(wifi)) throw new Error(`WLAN-Verbindung fehlgeschlagen: ${wifi.replace(/^JARVIS-WIFI FAIL\s*/, "") || "unbekannt"}. Name und Passwort prüfen (nur 2,4 GHz).`);
      const ip = wifi.replace(/^JARVIS-WIFI OK\s*/, "");
      check("wifi", "ok", `Im WLAN${ip ? ` als ${ip}` : ""}`);
      await serial.close();
      serial = null;
      F.serialPort = null;
      F.busy = false;
      go(4);
    } catch (e) {
      F.busy = false;
      if (serial) await serial.close();
      F.serialPort = null;
      check(stage, "fail");
      const err = e?.message === "timeout" && stage === "ready"
        ? new Error("Das Display antwortet nicht. Läuft die Jarvis-Firmware (ab 0.3)? Sonst zuerst flashen. Ein kurzer Druck auf RST hilft manchmal.")
        : e?.message === "timeout" && stage === "wifi" ? new Error("Keine Rückmeldung vom WLAN. Name und Passwort prüfen – der ESP32 kann nur 2,4 GHz.") : e;
      showError("fl-perror", err);
      document.querySelectorAll("#fl-body .fl-actions button").forEach((b) => { b.disabled = false; });
    }
  }

  // ------------------------------------------------------------ Schritt 5: Fertig
  function renderDone() {
    const status = el("p", { id: "fl-online", class: "small" }, "Warte, bis sich das Display bei Jarvis meldet …");
    const again = el("button", { class: "btn" }, "Weiteres Gerät einrichten");
    again.addEventListener("click", () => {
      Object.assign(F, { target: "new", name: "", room: "", deviceId: "", provision: null, prepared: null, serialPort: null });
      go(0);
    });
    const devices = el("a", { class: "btn primary", href: "#devices" }, "Zu den Geräten");
    waitOnline();
    return [el("h3", {}, "Fast geschafft"), status, actions(again, devices)];
  }

  async function waitOnline() {
    const id = F.deviceId;
    for (let i = 0; i < 45 && F.step === 4 && id === F.deviceId; i++) {
      try {
        const list = await api("/api/admin/devices");
        const d = list.find((x) => String(x.id) === id);
        if (d?.online) {
          const box = $("fl-online");
          if (box) box.replaceChildren(el("span", { class: "st ok" }, "ONLINE"), ` ${d.name} ist mit Jarvis verbunden${d.fw ? ` (Firmware ${d.fw})` : ""}. Künftige Updates kommen per WLAN.`);
          return;
        }
      } catch { /* weiter versuchen */ }
      await new Promise((r) => setTimeout(r, 2000));
    }
    const box = $("fl-online");
    if (box && F.step === 4) {
      box.replaceChildren(el("span", { class: "st warn" }, "NOCH NICHT ONLINE"),
        " Das Display ist im WLAN, erreicht Jarvis aber nicht. Prüfe Server-Adresse und Port (Standard 8080, im Container freigegeben?) und ob eine Firewall blockiert.");
    }
  }

  function render() {
    const view = [renderDevice, renderWifi, renderFlash, renderProvision, renderDone][F.step]();
    body.replaceChildren(...view.filter(Boolean));
  }

  async function refreshContext() {
    try {
      const [devices, info] = await Promise.all([api("/api/admin/devices"), api("/api/admin/provision-info")]);
      F.devices = devices;
      F.hosts = info.hosts;
      if (info.port) F.port = info.port;
      if (!F.busy && F.step <= 1) render();
    } catch { /* Seite bleibt nutzbar */ }
  }

  setSupportTag();
  steps();
  render();
  return {
    setVariants(variants) {
      F.variants = variants;
      refreshContext();
      if (!F.busy && F.step === 0) render();
    },
    // Aus „Geräte → Neues Gerät“: den gerade erzeugten Token direkt verwenden
    prepare(data) {
      if (F.busy) return;
      F.prepared = data; F.target = "prepared"; F.deviceId = String(data.id); F.provision = null;
      if (data.provision?.hosts?.length) F.hosts = data.provision.hosts;
      go(0);
      $("flasher").scrollIntoView({ behavior: "smooth", block: "start" });
    },
  };
}
