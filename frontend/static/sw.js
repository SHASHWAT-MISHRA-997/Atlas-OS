// ATLAS OS service worker: lets the app open (read-only shell) when the
// computer running ATLAS is unreachable. It never caches /api responses,
// so chat, memory and tasks are never stored here.
const CACHE = 'atlas-shell-v1';
const SHELL = ['/', '/static/app.css', '/static/app.js', '/static/icon.svg', '/static/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/cloud/') || url.pathname === '/health' || url.search.includes('pair=')) return;
  // Network first, so a running ATLAS always serves the newest code; the cache is only a fallback.
  event.respondWith(fetch(request).then((response) => {
    if (response.ok && (request.mode === 'navigate' || SHELL.includes(url.pathname) || url.pathname.startsWith('/static/'))) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request.mode === 'navigate' ? '/' : request, copy));
    }
    return response;
  }).catch(() => caches.match(request.mode === 'navigate' ? '/' : request)
    .then((hit) => hit || new Response('ATLAS is offline.', { status: 503, headers: { 'Content-Type': 'text/plain' } }))));
});
