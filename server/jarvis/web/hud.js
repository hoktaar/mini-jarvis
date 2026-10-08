// HUD-Grafik: Wellenform, Geräte-Netzkarte, Meter, Sparklines (mit Tooltip), Ringanzeige.
const NS = "http://www.w3.org/2000/svg";
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function svgEl(tag, attrs = {}) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

// ---------------------------------------------------------------- Wellenform
// Symmetrische Balken links/rechts der Mitte, Höhe folgt dem Audiopegel.
export function startWave(canvas, getState) {
  const ctx = canvas.getContext("2d");
  const bars = 56;
  const smooth = new Float32Array(bars);
  let t = 0;
  function frame() {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const { level, state, color } = getState();
    const active = state === "listening" || state === "speaking";
    const base = state === "thinking" ? 0.18 : active ? 0.12 : 0.04;
    const amp = Math.min(1, base + (active ? level * 2.4 : 0));
    const gap = w / bars;
    const mid = h / 2;
    for (let i = 0; i < bars; i++) {
      const d = Math.abs(i - (bars - 1) / 2) / (bars / 2);          // 0 Mitte … 1 Rand
      const envelope = Math.pow(1 - d, 1.6);
      const noise = 0.55 + 0.45 * Math.sin(t * 0.13 + i * 0.9) * Math.sin(t * 0.07 + i * 0.37);
      const target = Math.max(0.02, amp * envelope * noise);
      smooth[i] += (target - smooth[i]) * 0.25;
      const bh = Math.max(2, smooth[i] * h * 0.95);
      const x = i * gap + gap / 2;
      ctx.globalAlpha = 0.35 + 0.65 * envelope;
      ctx.fillStyle = color;
      if (bh <= 3) {
        ctx.beginPath(); ctx.arc(x, mid, 1.4, 0, Math.PI * 2); ctx.fill();
      } else {
        const bw = Math.max(1.5, gap * 0.38);
        ctx.fillRect(x - bw / 2, mid - bh / 2, bw, bh);
      }
    }
    ctx.globalAlpha = 1;
    t += 1;
    if (!reduced) requestAnimationFrame(frame);
  }
  frame();
}

// ---------------------------------------------------------------- Geräte-Netzkarte
export function renderNetmap(svg, devices) {
  const W = 320, H = 170, cx = W / 2, cy = H / 2;
  svg.replaceChildren();
  svg.append(svgEl("ellipse", { class: "orbit", cx, cy, rx: 110, ry: 62 }));
  svg.append(svgEl("ellipse", { class: "orbit", cx, cy, rx: 62, ry: 36 }));
  const list = devices.slice(0, 12);
  list.forEach((d, i) => {
    const a = (i / Math.max(1, list.length)) * Math.PI * 2 - Math.PI / 2;
    const ring = i % 2 ? { rx: 62, ry: 36 } : { rx: 110, ry: 62 };
    const x = cx + Math.cos(a) * ring.rx, y = cy + Math.sin(a) * ring.ry;
    svg.append(svgEl("line", { class: `link${d.online ? "" : " off"}`, x1: cx, y1: cy, x2: x, y2: y }));
    const node = svgEl("circle", { class: `node${d.online ? " on" : ""}`, cx: x, cy: y, r: d.online ? 4.5 : 3.5 });
    const title = svgEl("title"); title.textContent = `${d.name}${d.room ? ` · ${d.room}` : ""} – ${d.online ? "online" : "offline"}`;
    node.append(title);
    svg.append(node);
    const label = svgEl("text", { x: x + (Math.cos(a) >= 0 ? 7 : -7), y: y + 3, "text-anchor": Math.cos(a) >= 0 ? "start" : "end" });
    label.textContent = d.name.length > 12 ? `${d.name.slice(0, 11)}…` : d.name;
    svg.append(label);
  });
  svg.append(svgEl("circle", { class: "hub", cx, cy, r: 11 }));
  if (!list.length) {
    const t = svgEl("text", { x: cx, y: cy + 30, "text-anchor": "middle" });
    t.textContent = "Noch keine Geräte";
    svg.append(t);
  }
}

// ---------------------------------------------------------------- Meter
export function renderMeters(box, rows) {
  box.replaceChildren(...rows.map((r) => {
    const pct = r.value == null ? null : Math.max(0, Math.min(100, r.value));
    const row = document.createElement("div");
    row.className = `meter${pct != null && pct >= 90 ? " high" : ""}`;
    row.setAttribute("role", "meter");
    row.setAttribute("aria-label", r.label);
    row.setAttribute("aria-valuemin", "0"); row.setAttribute("aria-valuemax", "100");
    if (pct != null) row.setAttribute("aria-valuenow", String(Math.round(pct)));
    if (r.detail) row.title = r.detail;
    const label = document.createElement("span"); label.textContent = r.label;
    const track = document.createElement("div"); track.className = "track";
    const fill = document.createElement("div"); fill.className = "fill"; fill.style.width = `${pct ?? 0}%`;
    track.append(fill);
    const out = document.createElement("output");
    out.textContent = pct == null ? "–" : `${Math.round(pct)} %${pct >= 90 ? " hoch" : ""}`;
    row.append(label, track, out);
    return row;
  }));
}

// ---------------------------------------------------------------- Sparkline (Balken, eine Reihe, mit Tooltip)
const tooltip = () => document.getElementById("tooltip");

export function renderSpark(svg, values, format) {
  const W = 120, H = 36, n = Math.max(values.length, 1);
  const max = Math.max(0.001, ...values);
  const gap = 1;
  const bw = Math.max(1, W / n - gap);
  svg.replaceChildren();
  values.forEach((v, i) => {
    const bh = Math.max(1.5, (v / max) * (H - 2));
    const rect = svgEl("rect", { x: i * (bw + gap), y: H - bh, width: bw, height: bh, rx: Math.min(2, bw / 2) });
    rect.dataset.v = v;
    rect.dataset.ago = String((values.length - 1 - i) * 3);
    svg.append(rect);
  });
  // Trefferfläche größer als die Balken: ganzer Bereich, nächster Balken zählt
  svg.onpointermove = (e) => {
    const box = svg.getBoundingClientRect();
    const idx = Math.min(values.length - 1, Math.max(0, Math.floor(((e.clientX - box.left) / box.width) * values.length)));
    svg.querySelectorAll("rect.hover").forEach((r) => r.classList.remove("hover"));
    const rect = svg.children[idx];
    if (!rect) return;
    rect.classList.add("hover");
    const tip = tooltip();
    tip.hidden = false;
    tip.textContent = `${format(Number(rect.dataset.v))} · vor ${rect.dataset.ago} s`;
    tip.style.left = `${e.clientX + 12}px`;
    tip.style.top = `${e.clientY - 30}px`;
  };
  svg.onpointerleave = () => {
    tooltip().hidden = true;
    svg.querySelectorAll("rect.hover").forEach((r) => r.classList.remove("hover"));
  };
}

// ---------------------------------------------------------------- Ringanzeige (Speicher)
export function setRing(circle, pct) {
  circle.setAttribute("stroke-dasharray", `${Math.max(0, Math.min(100, pct))} 100`);
}

export function formatMbit(v) {
  if (v >= 100) return `${Math.round(v)} Mbit/s`;
  if (v >= 1) return `${v.toFixed(1).replace(".", ",")} Mbit/s`;
  return `${Math.round(v * 1000)} kbit/s`;
}
