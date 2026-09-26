// Minimaler Service Worker: App-Shell cachen, API nie cachen.
const CACHE = "jarvis-v2";
const SHELL = ["/", "/index.html", "/style.css", "/app.js", "/vendor/pipecat.js", "/manifest.webmanifest", "/icon.svg"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL))));
self.addEventListener("fetch", (e) => {
  if (new URL(e.request.url).pathname.startsWith("/api/")) return;
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
// Phase 1: Web Push ('push'-Event) für Timer und Erinnerungen.
