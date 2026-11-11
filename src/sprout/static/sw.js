// Caches only the app shell (static files). Family data is never cached.
const CACHE = "sprout-static-v1";
const SHELL = ["/static/style.css", "/static/app.js", "/static/icon.svg", "/offline"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  } else if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => caches.match("/offline")));
  }
});
