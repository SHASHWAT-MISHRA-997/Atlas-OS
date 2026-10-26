// ATLAS OS service worker: lets the app open (read-only shell) without a connection.
// It never caches /cloud responses, so chats and keys are never stored here.
const CACHE = 'atlas-shell-v4';
const SHELL = ['/', '/static/theme.js', '/static/app.css', '/static/cloud.js', '/static/app.js', '/static/realtime.js', '/static/live-worklet.js', '/static/icon.svg', '/static/manifest.webmanifest'];

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
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/cloud/') || url.pathname === '/version.json') return;
  // Network first, so the newest code is always used online; the cache is only a fallback.
  event.respondWith(fetch(request).then((response) => {
    if (response.ok && (request.mode === 'navigate' || SHELL.includes(url.pathname) || url.pathname.startsWith('/static/'))) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request.mode === 'navigate' ? '/' : request, copy));
    }
    return response;
  }).catch(() => caches.match(request.mode === 'navigate' ? '/' : request)
    .then((hit) => hit || new Response('ATLAS is offline.', { status: 503, headers: { 'Content-Type': 'text/plain' } }))));
});
