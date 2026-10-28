// Size budget for the online app, so it stays quick to open on a phone over mobile data.
// Run after the build: node scripts/netlify/build.mjs && node --test netlify/tests/budget.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { gzipSync } from 'node:zlib';

const dist = new URL('../../dist/', import.meta.url);
const gz = (path) => gzipSync(readFileSync(new URL(path, dist))).length;

test('code needed to open the app stays under 80 KB compressed', () => {
  const files = ['index.html', 'static/theme.js', 'static/app.js', 'static/app.css', 'static/cloud.js', 'static/icon.svg'];
  const total = files.reduce((sum, f) => sum + gz(f), 0);
  assert.ok(total < 80_000, 'first load is ' + total + ' bytes gzipped');
});

test('scripts load without blocking the first paint', () => {
  const html = readFileSync(new URL('index.html', dist), 'utf8');
  const scripts = html.match(/<script\b[^>]*>/gi) || [];
  assert.ok(scripts.length >= 2);
  // theme.js runs first on purpose, so the saved theme applies before paint; it must stay tiny.
  for (const s of scripts) if (!s.includes('/static/theme.js')) assert.match(s, /\bdefer\b/, s);
  assert.ok(readFileSync(new URL('static/theme.js', dist)).length < 400, 'theme.js grew');
});

test('the service worker always asks the server for fresh pages and code, even when the browser asks for a cached copy', async () => {
  // Android Chrome restores tabs with "use any cached copy"; passed on, that kept the owner's phone on 0.18.0.
  const { runInNewContext } = await import('node:vm');
  const listeners = {};
  const sent = [];
  const cache = { put: async () => {}, addAll: async () => {} };
  const sandbox = {
    self: { addEventListener: (type, fn) => { listeners[type] = fn; }, location: { origin: 'https://atlas.test' }, skipWaiting: () => {}, clients: { claim: () => {} } },
    caches: { open: async () => cache, keys: async () => [], match: async () => null, delete: async () => true },
    fetch: async (req) => { sent.push(req); return new Response('ok', { status: 200 }); },
    Request, Response, URL,
  };
  runInNewContext(readFileSync(new URL('sw.js', dist), 'utf8'), sandbox);
  const respond = async (request) => { let p; listeners.fetch({ request, respondWith: (x) => { p = x; } }); return p; };
  // A restored tab: a navigation that would accept a stale cached copy.
  await respond({ method: 'GET', url: 'https://atlas.test/', mode: 'navigate', cache: 'force-cache' });
  await respond(new Request('https://atlas.test/static/app.js?v=1', { cache: 'force-cache' }));
  await respond(new Request('https://atlas.test/static/theme.js', { cache: 'only-if-cached', mode: 'same-origin' }));
  assert.deepEqual(sent.map((r) => [new URL(r.url).pathname, r.cache]), [['/', 'no-cache'], ['/static/app.js', 'no-cache'], ['/static/theme.js', 'no-cache']]);
  // Function calls, other sites and non-GET requests are left alone (never cached).
  for (const request of [new Request('https://atlas.test/cloud/chat', { method: 'POST', body: '{}' }), new Request('https://atlas.test/cloud/status'), new Request('https://evil.example/x')]) {
    assert.equal(await respond(request), undefined, request.url);
  }
  assert.match(readFileSync(new URL('sw.js', dist), 'utf8'), /CACHE = 'atlas-shell-v5'/, 'a new cache name removes the old cached page');
});

test('store-ready app manifest: icons, screenshots with their real sizes, shortcuts, and a privacy policy', () => {
  const m = JSON.parse(readFileSync(new URL('static/manifest.webmanifest', dist), 'utf8'));
  for (const k of ['name', 'short_name', 'description', 'id', 'start_url', 'display', 'background_color', 'theme_color', 'categories', 'lang']) assert.ok(m[k], 'manifest needs ' + k);
  const pngSize = (path) => { const b = readFileSync(new URL(path.slice(1), dist)); return b.readUInt32BE(16) + 'x' + b.readUInt32BE(20); };
  for (const icon of m.icons.filter((i) => i.type === 'image/png')) assert.equal(pngSize(icon.src), icon.sizes, icon.src);
  assert.ok(m.icons.some((i) => i.sizes === '512x512' && i.purpose === 'maskable'), 'a maskable 512 icon');
  assert.ok(m.screenshots.some((s) => s.form_factor === 'wide') && m.screenshots.some((s) => s.form_factor === 'narrow'));
  for (const s of m.screenshots) assert.equal(pngSize(s.src), s.sizes, s.src);
  for (const s of m.shortcuts) assert.match(s.url, /^\/\?section=[a-z]+$/);
  const privacy = readFileSync(new URL('privacy.html', dist), 'utf8');
  for (const words of ['no ATLAS account', 'stores nothing', 'ATLAS PC helper', 'Phone actions', 'Deleting your data', 'Contact']) assert.ok(privacy.includes(words), 'privacy policy covers: ' + words);
  assert.ok(!/<script/i.test(privacy), 'the privacy page runs no script');
  assert.match(readFileSync(new URL('index.html', dist), 'utf8'), /href="\/privacy\.html"/);
});
