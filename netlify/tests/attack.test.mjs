// Attacks on the ATLAS online function, run as tests so they keep passing after every change.
// Providers are FAKE fetch stubs that record where the function tried to connect.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHandler } from '../lib/cloud.mjs';

const KEY = 'visitor-key-not-real-123';
const OFFICIAL_HOSTS = new Set(['api.groq.com', 'generativelanguage.googleapis.com', 'openrouter.ai', 'api.openai.com']);

function setup() {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: new URL(String(url)), init });
    return new Response('data: ' + JSON.stringify({ choices: [{ delta: { content: 'ok' }, finish_reason: 'stop' }] }) + '\n\ndata: [DONE]\n\n',
      { headers: { 'Content-Type': 'text/event-stream' } });
  };
  const handle = createHandler({ fetchImpl });
  const call = (path, body, headers = {}) => handle(new Request('https://atlas.example/cloud/' + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: typeof body === 'string' ? body : JSON.stringify(body),
  }));
  return { call, calls };
}
const chat = (extra) => ({ provider: 'groq', api_key: KEY, model: 'llama-3.1-8b-instant', messages: [{ role: 'user', content: 'hi' }], ...extra });

test('header injection through the key is refused (CR/LF, spaces, control and non-ASCII characters)', async () => {
  const t = setup();
  for (const api_key of [KEY + '\r\nX-Evil: 1', KEY + '\nHost: evil.example', 'abc def ghi jkl', KEY + '\u0000', 'ключ-ключ-ключ', 'x'.repeat(401)]) {
    const r = await t.call('chat', chat({ api_key }));
    assert.equal(r.status, 422, JSON.stringify(api_key));
  }
  assert.equal(t.calls.length, 0, 'nothing reached a provider');
});

test('the function cannot be turned into a proxy to other hosts or paths', async () => {
  const t = setup();
  const models = ['../../../v1/files', 'x/../../admin', '..', 'a?key=stolen', 'a#frag', 'http://evil.example/x', '//evil.example', 'm\r\nHost: evil', 'a b', 'a%2F..'];
  for (const provider of ['groq', 'gemini', 'openrouter', 'openai']) {
    for (const model of models) {
      const r = await t.call('chat', chat({ provider, model }));
      await r.text();
    }
    for (const extra of [{ base: 'https://evil.example' }, { url: 'https://evil.example' }, { endpoint: 'https://evil.example' }]) await (await t.call('chat', chat({ provider, ...extra }))).text();
  }
  for (const c of t.calls) {
    assert.ok(OFFICIAL_HOSTS.has(c.url.hostname), 'called ' + c.url);
    assert.equal(c.url.protocol, 'https:');
    assert.ok(/^\/(openai\/v1\/chat\/completions|api\/v1\/chat\/completions|v1\/chat\/completions|v1beta\/models\/[^/]+:streamGenerateContent)$/.test(c.url.pathname), 'path ' + c.url.pathname);
  }
});

test('prototype tricks in the provider name are refused', async () => {
  const t = setup();
  for (const provider of ['__proto__', 'constructor', 'toString', 'hasOwnProperty', 'valueOf', ['groq'], { id: 'groq' }, null]) {
    const r = await t.call('chat', chat({ provider }));
    assert.equal(r.status, 422, JSON.stringify(provider));
  }
  const r = await t.call('chat', '{"provider":"groq","api_key":"' + KEY + '","model":"m","messages":[{"role":"user","content":"x"}],"__proto__":{"key":"evil"}}');
  await r.text();
  assert.equal(t.calls.at(-1).init.headers.Authorization, 'Bearer ' + KEY);
});

test('messages cannot smuggle extra fields (tools, roles, functions) to the provider', async () => {
  const t = setup();
  const r = await t.call('chat', chat({
    messages: [{ role: 'user', content: 'hi', tool_calls: [{ id: 'x' }], name: 'admin' }],
    tools: [{ type: 'function', function: { name: 'shell' } }], tool_choice: 'auto', response_format: { type: 'json_object' }, temperature: 9, max_tokens: 999999,
  }));
  await r.text();
  const sent = JSON.parse(t.calls[0].init.body);
  assert.deepEqual(Object.keys(sent).sort(), ['max_tokens', 'messages', 'model', 'stream']);
  assert.deepEqual(sent.messages, [{ role: 'user', content: 'hi' }]);
  assert.equal(sent.max_tokens, 2048);
  for (const role of ['tool', 'function', 'developer', 'System ']) assert.equal((await t.call('chat', chat({ messages: [{ role, content: 'x' }] }))).status, 422, role);
});

test('requests from other websites are refused', async () => {
  const t = setup();
  for (const origin of ['https://evil.example', 'null', 'https://atlas.example.evil.example', 'https://evil.example/atlas.example']) {
    const r = await t.call('chat', chat(), { Origin: origin });
    assert.equal(r.status, 403, origin);
  }
  for (const site of ['cross-site', 'same-site']) assert.equal((await t.call('chat', chat(), { 'Sec-Fetch-Site': site })).status, 403, site);
  // Without CORS headers a browser on another site could not read a reply anyway.
  const ok = await t.call('chat', chat(), { Origin: 'https://atlas.example' });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get('Access-Control-Allow-Origin'), null);
  await ok.text();
  assert.equal(t.calls.length, 1, 'only the same-site request reached a provider');
});

test('form posts and other non-JSON bodies are refused (no cross-site form submission)', async () => {
  const t = setup();
  for (const type of ['text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data; boundary=x']) {
    const r = await t.call('chat', JSON.stringify(chat()), { 'Content-Type': type });
    assert.equal(r.status, 415, type);
  }
  assert.equal(t.calls.length, 0);
});

test('huge bodies are refused before they are read', async () => {
  const t = setup();
  const r = await t.call('chat', '{"x":"' + 'a'.repeat(5_100_000) + '"}');
  assert.equal(r.status, 413, 'chat: over 5 MB');
  const m = await t.call('models', '{"x":"' + 'a'.repeat(30_000) + '"}');
  assert.equal(m.status, 413, 'model listing: over 20 KB');
  const deep = await t.call('chat', '['.repeat(100_000));
  assert.ok([400, 413].includes(deep.status), 'deeply nested JSON is refused, status ' + deep.status);
});

test('error messages never echo the key back, even partly encoded', async () => {
  const handle = createHandler({ fetchImpl: async () => new Response(JSON.stringify({ error: { message: 'Invalid key ' + KEY + ' / ' + encodeURIComponent(KEY) } }), { status: 401 }) });
  const r = await handle(new Request('https://atlas.example/cloud/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: 'groq', api_key: KEY }) }));
  const text = await r.text();
  assert.ok(!text.includes(KEY), text);
});

test('replies are JSON or SSE with nosniff, so a browser never renders them as a page', async () => {
  const t = setup();
  const r = await t.call('models', { provider: 'groq', api_key: KEY });
  assert.equal(r.headers.get('X-Content-Type-Options'), 'nosniff');
  assert.match(r.headers.get('Content-Type'), /application\/json/);
  const s = await t.call('chat', chat());
  assert.equal(s.headers.get('X-Content-Type-Options'), 'nosniff');
  await s.text();
});
