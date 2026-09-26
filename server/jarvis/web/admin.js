const $ = (id) => document.getElementById(id);
$("admin-token").value = sessionStorage.getItem("jarvis-admin") || "";

function notice(text) { $("notice").hidden = false; $("notice").textContent = text; }

async function api(path, opts = {}) {
  const token = $("admin-token").value.trim();
  sessionStorage.setItem("jarvis-admin", token);
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token, ...(opts.headers || {}) } });
  if (res.status === 401) throw new Error("Admin-Token fehlt oder ist falsch.");
  return res.json();
}

function row(...cells) {
  const tr = document.createElement("tr");
  for (const c of cells) {
    const td = document.createElement("td");
    if (c instanceof Node) td.append(c); else td.textContent = c ?? "";
    tr.append(td);
  }
  return tr;
}

async function load() {
  if (!$("admin-token").value.trim()) return;
  try {
    const devices = await api("/api/admin/devices");
    $("devices").replaceChildren(...devices.map((d) => {
      let action = "";
      if (!d.revoked) {
        action = Object.assign(document.createElement("button"), { className: "ghost", textContent: "Sperren" });
        action.onclick = async () => { await api(`/api/admin/devices/${d.id}`, { method: "DELETE" }); load(); };
      }
      return row(d.name, d.kind, d.room, d.revoked ? "gesperrt" : "aktiv", action);
    }));
    const log = await api("/api/admin/router-log?limit=30");
    $("router").replaceChildren(...log.map((r) => row(r.text, r.intent, `${Math.round(r.confidence * 100)} %`, r.route)));
    const audit = await api("/api/admin/audit?limit=30");
    $("audit").replaceChildren(...audit.map((a) => row(new Date(a.ts * 1000).toLocaleString("de-DE"), a.actor, `${a.action} ${a.detail || ""}`, a.result)));
  } catch (err) { notice(err.message); }
}

$("new-device").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const name = $("dev-name").value;
    const r = await api("/api/admin/devices", { method: "POST", body: JSON.stringify({ name, kind: $("dev-kind").value, room: $("dev-room").value }) });
    notice(`Token für „${name}“ (nur jetzt sichtbar): ${r.token}`);
    e.target.reset(); load();
  } catch (err) { notice(err.message); }
});
$("admin-token").addEventListener("change", load);
load();
