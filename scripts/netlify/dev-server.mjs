// Local preview of the Netlify cloud edition without the Netlify CLI: serves dist/ and runs the
// /cloud function in-process with an in-memory store. Keys come from this shell's environment.
//
//   node scripts/netlify/build.mjs && GROQ_API_KEY=... node scripts/netlify/dev-server.mjs
//
// ATLAS_FAKE_MODEL=1 swaps every provider for a FAKE model that echoes the last message. It exists
// for automated tests only; its replies are labelled FAKE and are never real AI output.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHandler, memoryStore } from '../../netlify/lib/cloud.mjs';

const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const port = Number(process.env.PORT || 8888);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };

export function fakeModelFetch(url, init) {
  const sse = (chunks) => new Response(new ReadableStream({
    start(c) { for (const x of chunks) c.enqueue(new TextEncoder().encode('data: ' + x + '\n\n')); c.close(); },
  }), { headers: { 'Content-Type': 'text/event-stream' } });
  if (String(url).endsWith('/models')) return Promise.resolve(Response.json({ data: [{ id: 'fake-small' }, { id: 'fake-large' }] }));
  const body = JSON.parse(init.body);
  const last = body.messages.filter((m) => m.role === 'user').pop().content;
  if (body.model === 'fake-broken') return Promise.resolve(new Response('{"error":{"message":"model not found"}}', { status: 404 }));
  const system = body.messages.find((m) => m.role === 'system');
  const text = system && system.content.includes('planner')
    ? JSON.stringify({ steps: [{ title: 'FAKE step one', detail: 'for ' + last }, { title: 'FAKE step two', detail: 'checked' }], risks: [] })
    : 'FAKE reply to: ' + last;
  const words = text.match(/.{1,12}/gs);
  return Promise.resolve(sse([...words.map((w) => JSON.stringify({ choices: [{ delta: { content: w } }] })),
    JSON.stringify({ choices: [{ delta: {}, finish_reason: 'stop' }], usage: { total_tokens: 42 } }), '[DONE]']));
}

const fake = process.env.ATLAS_FAKE_MODEL === '1';
const env = { ...process.env, ...(fake ? { GROQ_API_KEY: 'fake-key-for-tests' } : {}) }; // pragma: allowlist secret (not a key)
const handle = createHandler({ store: memoryStore(), env, fetchImpl: fake ? fakeModelFetch : fetch });

createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost:' + port);
  if (url.pathname.startsWith('/cloud/')) {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const request = new Request(url, { method: req.method, headers: req.headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks) });
    const response = await handle(request);
    res.writeHead(response.status, Object.fromEntries(response.headers));
    if (response.body) for await (const c of response.body) res.write(c);
    res.end();
    return;
  }
  const file = normalize(join(dist, url.pathname === '/' ? 'index.html' : url.pathname));
  if (!file.startsWith(dist)) { res.writeHead(403).end(); return; }
  try {
    const data = await readFile(file);
    res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" });
    res.end(data);
  } catch {
    res.writeHead(404).end('Not found');
  }
}).listen(port, () => console.log('ATLAS cloud preview on http://localhost:' + port + (fake ? ' (FAKE model)' : '')));
