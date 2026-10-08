// Gemeinsame Bausteine für Dashboard und Verwaltung.
export const $ = (id) => document.getElementById(id);

export const store = {
  get(k, d) { try { const v = localStorage.getItem(`jarvis-${k}`); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`jarvis-${k}`, JSON.stringify(v)); } catch { /* privat */ } },
};

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) { if (v) node.addEventListener(k.slice(2), v); }
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) node.append(c instanceof Node ? c : document.createTextNode(c));
  return node;
}

export const icon = (id) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#${id}`); s.append(u); return s;
};

let toastTimer;
export function toast(text, ms = 3200) {
  const t = $("toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

export function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
}
