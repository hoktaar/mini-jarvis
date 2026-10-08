// Service Worker: App-Shell offline, Updates ohne Hängenbleiben, API/WebSocket nie aus dem Cache.
const VERSION = "jarvis-v6";
const SHELL = ["/", "/index.html", "/style.css", "/app.js", "/hud.js", "/ui.js", "/vendor/pipecat.js", "/manifest.webmanifest",
  "/icon.svg", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).catch(() => undefined));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== VERSION) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("message", (e) => { if (e.data === "skipWaiting") self.skipWaiting(); });

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/") || url.pathname === "/ca.crt") return;
  if (e.request.mode === "navigate") {
    // Seiten: zuerst Netz (neue Version), sonst Cache (offline)
    e.respondWith(fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(VERSION).then((c) => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request).then((hit) => hit || caches.match("/index.html"))));
    return;
  }
  // Dateien: aus dem Cache, im Hintergrund aktualisieren
  e.respondWith(caches.open(VERSION).then(async (cache) => {
    const hit = await cache.match(e.request);
    const fresh = fetch(e.request).then((res) => { if (res.ok) cache.put(e.request, res.clone()); return res; }).catch(() => hit);
    return hit || fresh;
  }));
});

// Benachrichtigung antippen → Jarvis öffnen
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((list) => (list[0] ? list[0].focus() : self.clients.openWindow("/"))));
});
