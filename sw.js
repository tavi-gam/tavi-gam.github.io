/* Family shopping list: background worker for push notifications */
const CACHE = 'shop-app-v55';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
  await self.clients.claim();
})()));
/* App files: network first so updates arrive, but give up after a short wait on weak signal (e.g. inside a supermarket)
   and serve the cached copy. Videos (range requests) and data calls are never cached. */
const WAIT = 2500;
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET' || r.headers.has('range')) return;
  const u = new URL(r.url);
  if (/\.mp4$/i.test(u.pathname)) return;
  const sameOrigin = u.origin === self.location.origin;
  const cdn = u.hostname === 'cdn.jsdelivr.net' || u.hostname.endsWith('fonts.googleapis.com') || u.hostname.endsWith('fonts.gstatic.com');
  if (!sameOrigin && !cdn) return;
  e.respondWith((async () => {
    const cached = () => caches.match(r, { ignoreSearch: true }).then(h => h || (r.mode === 'navigate' ? caches.match('index.html') : undefined));
    const net = fetch(r).then(async res => {
      if (res && res.status === 200 || (res && res.type === 'opaque')) { try { const c = await caches.open(CACHE); await c.put(r, res.clone()); } catch (_) {} }
      return res;
    });
    // CDN files never change: serve from cache straight away when we have them
    if (cdn) { const h = await caches.match(r); if (h) return h; }
    const timer = new Promise(res => setTimeout(res, WAIT, 'slow'));
    try {
      const first = await Promise.race([net, timer]);
      if (first !== 'slow') return first;
      const h = await cached();
      return h || await net;
    } catch (_) {
      const h = await cached();
      return h || Response.error();
    }
  })());
});
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : '' }; }
  const title = String(d.title || 'תביא גם').slice(0, 80);
  e.waitUntil(self.registration.showNotification(title, {
    body: String(d.body || '').slice(0, 240),
    tag: String(d.tag || 'shop'),
    renotify: true,
    icon: 'icon-192.png',
    badge: 'icon-192.png',
    dir: 'rtl',
    lang: 'he'
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) { if ('focus' in c) { await c.focus(); return; } }
    if (self.clients.openWindow) await self.clients.openWindow('./');
  })());
});
