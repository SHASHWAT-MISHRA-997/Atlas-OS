// Size budget for the online app, so it stays quick to open on a phone over mobile data.
// Run after the build: node scripts/netlify/build.mjs && node --test netlify/tests/budget.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { gzipSync } from 'node:zlib';

const dist = new URL('../../dist/', import.meta.url);
const gz = (path) => gzipSync(readFileSync(new URL(path, dist))).length;

test('code needed to open the app stays under 80 KB compressed', () => {
  const files = ['index.html', 'static/app.js', 'static/app.css', 'static/cloud.js', 'static/cloud.css', 'static/icon.svg'];
  const total = files.reduce((sum, f) => sum + gz(f), 0);
  assert.ok(total < 80_000, 'first load is ' + total + ' bytes gzipped');
});

test('scripts load without blocking the first paint', () => {
  const html = readFileSync(new URL('index.html', dist), 'utf8');
  const scripts = html.match(/<script\b[^>]*>/g) || [];
  assert.ok(scripts.length >= 2);
  for (const s of scripts) assert.match(s, /\bdefer\b/, s);
});
