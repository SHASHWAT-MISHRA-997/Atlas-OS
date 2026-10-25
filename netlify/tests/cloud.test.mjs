// Tests for the ATLAS cloud function (netlify/lib/cloud.mjs). Model providers are FAKE fetch stubs.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHandler, memoryStore } from '../lib/cloud.mjs';

const KEY = 'test-provider-key-not-real';

function sseResponse(payloads) {
  return new Response(new ReadableStream({
    start(c) { for (const p of payloads) c.enqueue(new TextEncoder().encode('data: ' + p + '\n\n')); c.close(); },
  }), { headers: { 'Content-Type': 'text/event-stream' } });
}

function setup({ env = { GROQ_API_KEY: KEY }, upstream, clock } = {}) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return upstream ? upstream(String(url), init) : sseResponse([JSON.stringify({ choices: [{ delta: { content: 'Hello' } }] }),
      JSON.stringify({ choices: [{ delta: { content: ' there' }, finish_reason: 'stop' }] }), '[DONE]']);
  };
  let time = clock || new Date('2026-10-25T10:00:00Z');
  const handle = createHandler({ store: memoryStore(), env, fetchImpl, now: () => time });
  const call = (path, { method = 'GET', body, token } = {}) => handle(new Request('https://atlas.example/cloud/' + path, {
    method, headers: { ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  }));
  return { call, calls, advance: (ms) => { time = new Date(time.getTime() + ms); } };
}

async function claim(t, body = { name: 'Phone' }) {
  const r = await t.call('claim', { method: 'POST', body });
  assert.equal(r.status, 201);
  return (await r.json()).token;
}

async function events(response) {
  const text = await response.text();
  return text.trim().split('\n\n').map((block) => {
    const [ev, data] = block.split('\n');
    return { event: ev.slice(7), data: JSON.parse(data.slice(6)) };
  });
}

const chatBody = (extra = {}) => ({ provider: 'groq', model: 'llama-3.1-8b-instant', messages: [{ role: 'system', content: 'be brief' }, { role: 'user', content: 'hi' }], ...extra });

test('status lists only providers with a key and never returns keys', async () => {
  const t = setup({ env: { GROQ_API_KEY: KEY, OPENAI_API_KEY: 'gw-key-not-real', OPENAI_BASE_URL: 'https://gateway.example/openai/v1' } });
  const r = await t.call('status');
  const text = await r.text();
  const s = JSON.parse(text);
  assert.equal(s.claimed, false);
  assert.equal(s.me, null);
  assert.deepEqual(s.providers.map((p) => p.id), ['groq', 'openai']);
  assert.equal(s.providers[1].gateway, true);
  assert.match(s.providers[1].billing, /Netlify team's credits/);
  assert.equal(s.providers[0].gateway, false);
  assert.ok(!text.includes(KEY) && !text.includes('gw-key-not-real'));
});

test('first device claims; a second claim is refused', async () => {
  const t = setup();
  const token = await claim(t);
  const s = await (await t.call('status', { token })).json();
  assert.deepEqual(s.me, { kind: 'owner', name: 'Phone' });
  const again = await t.call('claim', { method: 'POST', body: { name: 'Stranger' } });
  assert.equal(again.status, 409);
});

test('an access code, when set in Netlify, is required to claim', async () => {
  const t = setup({ env: { GROQ_API_KEY: KEY, ATLAS_ACCESS_CODE: 'correct horse' } });
  assert.equal((await (await t.call('status')).json()).access_code_required, true);
  assert.equal((await t.call('claim', { method: 'POST', body: { name: 'x' } })).status, 403);
  assert.equal((await t.call('claim', { method: 'POST', body: { name: 'x', access_code: 'wrong' } })).status, 403);
  await claim(t, { name: 'x', access_code: 'correct horse' });
});

test('chat and models need a signed-in device', async () => {
  const t = setup();
  assert.equal((await t.call('chat', { method: 'POST', body: chatBody() })).status, 401);
  await claim(t);
  const r = await t.call('chat', { method: 'POST', body: chatBody(), token: 'not-a-real-token' });
  assert.equal(r.status, 401);
  assert.equal((await r.json()).code, 'unauthorized');
  assert.equal((await t.call('models?provider=groq')).status, 401);
  assert.equal(t.calls.length, 0, 'no provider was called');
});

test('streamed chat sends the server key upstream and ATLAS events to the browser', async () => {
  const t = setup();
  const token = await claim(t);
  const r = await t.call('chat', { method: 'POST', body: chatBody(), token });
  assert.equal(r.status, 200);
  assert.match(r.headers.get('content-type'), /event-stream/);
  const ev = await events(r);
  assert.deepEqual(ev.map((e) => e.event), ['start', 'delta', 'delta', 'done']);
  assert.equal(ev.filter((e) => e.event === 'delta').map((e) => e.data.text).join(''), 'Hello there');
  assert.equal(ev[3].data.finish_reason, 'stop');
  assert.equal(ev[3].data.local, false);
  const [call] = t.calls;
  assert.equal(call.url, 'https://api.groq.com/openai/v1/chat/completions');
  assert.equal(call.init.headers.Authorization, 'Bearer ' + KEY);
  const sent = JSON.parse(call.init.body);
  assert.equal(sent.model, 'llama-3.1-8b-instant');
  assert.equal(sent.stream, true);
  assert.equal(sent.messages.length, 2);
});

test('non-streamed chat returns the whole answer', async () => {
  const t = setup();
  const token = await claim(t);
  const r = await t.call('chat', { method: 'POST', body: chatBody({ stream: false }), token });
  const data = await r.json();
  assert.equal(data.answer, 'Hello there');
  assert.equal(data.provider, 'groq');
});

test('provider errors become a clear message without the key', async () => {
  const t = setup({ upstream: async () => new Response('{"error":{"message":"Invalid API Key"}}', { status: 401 }) });
  const token = await claim(t);
  const r = await t.call('chat', { method: 'POST', body: chatBody(), token });
  assert.equal(r.status, 502);
  const data = await r.json();
  assert.match(data.detail, /HTTP 401: Invalid API Key\. Check the API key set in Netlify\./);
  assert.ok(!JSON.stringify(data).includes(KEY));
});

test('an error in the middle of a stream ends with an error event', async () => {
  const t = setup({ upstream: async () => sseResponse([JSON.stringify({ choices: [{ delta: { content: 'Par' } }] }), JSON.stringify({ error: { message: 'overloaded' } })]) });
  const token = await claim(t);
  const ev = await events(await t.call('chat', { method: 'POST', body: chatBody(), token }));
  assert.deepEqual(ev.map((e) => e.event), ['start', 'delta', 'error']);
  assert.match(ev[2].data.detail, /overloaded/);
});

test('chat input is validated before any provider call', async () => {
  const t = setup();
  const token = await claim(t);
  const bad = [
    chatBody({ provider: 'openai' }),
    chatBody({ model: 'bad model id!' }),
    chatBody({ messages: [] }),
    chatBody({ messages: [{ role: 'system', content: 'only system' }] }),
    chatBody({ messages: [{ role: 'tool', content: 'x' }] }),
    chatBody({ messages: [{ role: 'user', content: 'x'.repeat(100_001) }] }),
  ];
  for (const body of bad) assert.equal((await t.call('chat', { method: 'POST', body, token })).status, 422, JSON.stringify(body).slice(0, 80));
  assert.equal(t.calls.length, 0);
});

test('output tokens are capped', async () => {
  const t = setup();
  const token = await claim(t);
  await (await t.call('chat', { method: 'POST', body: chatBody({ max_tokens: 999999 }), token })).text();
  assert.equal(JSON.parse(t.calls[0].init.body).max_tokens, 2048);
});

test('Gemini requests use the native API and its stream format', async () => {
  const t = setup({
    env: { GEMINI_API_KEY: KEY },
    upstream: async () => sseResponse([JSON.stringify({ candidates: [{ content: { parts: [{ text: 'Namaste' }] } }] }),
      JSON.stringify({ candidates: [{ content: { parts: [{ text: '!' }] }, finishReason: 'STOP' }], usageMetadata: { totalTokenCount: 9 } })]),
  });
  const token = await claim(t);
  const body = { provider: 'gemini', model: 'gemini-2.5-flash', messages: [{ role: 'system', content: 'sys' }, { role: 'user', content: 'a' }, { role: 'assistant', content: 'b' }, { role: 'user', content: 'c' }], stream: false };
  const data = await (await t.call('chat', { method: 'POST', body, token })).json();
  assert.equal(data.answer, 'Namaste!');
  assert.equal(data.usage.total_tokens, 9);
  const call = t.calls[0];
  assert.equal(call.url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse');
  assert.equal(call.init.headers['x-goog-api-key'], KEY);
  const sent = JSON.parse(call.init.body);
  assert.deepEqual(sent.systemInstruction, { parts: [{ text: 'sys' }] });
  assert.deepEqual(sent.contents.map((c) => c.role), ['user', 'model', 'user']);
});

test('Anthropic requests use the Messages API via the gateway URL', async () => {
  const t = setup({
    env: { ANTHROPIC_API_KEY: KEY, ANTHROPIC_BASE_URL: 'https://gateway.example/anthropic/' },
    upstream: async () => sseResponse([JSON.stringify({ type: 'content_block_delta', delta: { type: 'text_delta', text: 'Hi' } }),
      JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 3 } })]),
  });
  const token = await claim(t);
  const data = await (await t.call('chat', { method: 'POST', body: { ...chatBody({ provider: 'anthropic', model: 'claude-haiku-4-5' }), stream: false }, token })).json();
  assert.equal(data.answer, 'Hi');
  assert.equal(data.gateway, true);
  assert.equal(t.calls[0].url, 'https://gateway.example/anthropic/v1/messages');
  const sent = JSON.parse(t.calls[0].init.body);
  assert.equal(sent.system, 'be brief');
  assert.deepEqual(sent.messages, [{ role: 'user', content: 'hi' }]);
});

test('model lists are filtered and fall back to a suggestion when listing fails', async () => {
  const t = setup({
    env: { GROQ_API_KEY: KEY, OPENAI_API_KEY: 'gw', OPENAI_BASE_URL: 'https://gateway.example/v1' },
    upstream: async (url) => (url.includes('groq')
      ? Response.json({ data: [{ id: 'whisper-large-v3' }, { id: 'gemma2-9b-it' }, { id: 'llama-3.1-8b-instant' }, { id: 'llama-guard-4' }] })
      : new Response('nope', { status: 404 })),
  });
  const token = await claim(t);
  assert.deepEqual((await (await t.call('models?provider=groq', { token })).json()).models, ['llama-3.1-8b-instant', 'gemma2-9b-it']);
  const fallback = await (await t.call('models?provider=openai', { token })).json();
  assert.deepEqual(fallback.models, ['gpt-5-mini']);
  assert.equal(fallback.suggested_only, true);
  assert.equal((await t.call('models?provider=anthropic', { token })).status, 422);
});

test('pairing links work once, expire, and only the owner can make them', async () => {
  const t = setup();
  const owner = await claim(t);
  const p = await (await t.call('pairing', { method: 'POST', body: { name: 'Laptop' }, token: owner })).json();
  assert.ok(p.code.length >= 40);
  const joined = await t.call('join', { method: 'POST', body: { code: p.code } });
  assert.equal(joined.status, 201);
  const device = (await joined.json()).token;
  assert.deepEqual((await (await t.call('status', { token: device })).json()).me, { kind: 'device', name: 'Laptop' });
  assert.equal((await t.call('join', { method: 'POST', body: { code: p.code } })).status, 403, 'single use');
  assert.equal((await t.call('pairing', { method: 'POST', body: {}, token: device })).status, 403, 'devices cannot pair');
  assert.equal((await t.call('devices', { token: device })).status, 403);

  const late = await (await t.call('pairing', { method: 'POST', body: {}, token: owner })).json();
  t.advance(11 * 60e3);
  assert.equal((await t.call('join', { method: 'POST', body: { code: late.code } })).status, 403, 'expired');
  assert.equal((await t.call('join', { method: 'POST', body: { code: '' } })).status, 403);
});

test('the owner can remove a device; a device can sign itself out', async () => {
  const t = setup();
  const owner = await claim(t);
  const pair = async () => (await (await t.call('join', { method: 'POST', body: { code: (await (await t.call('pairing', { method: 'POST', body: {}, token: owner })).json()).code } })).json()).token;
  const a = await pair();
  const b = await pair();
  const list = (await (await t.call('devices', { token: owner })).json()).devices;
  assert.equal(list.length, 2);
  assert.ok(list.every((d) => !('hash' in d)));
  assert.equal((await t.call('devices/' + list[0].id, { method: 'DELETE', token: owner })).status, 204);
  assert.equal((await t.call('chat', { method: 'POST', body: chatBody(), token: a })).status, 401);
  assert.equal((await t.call('me', { method: 'DELETE', token: b })).status, 204);
  assert.equal((await t.call('models?provider=groq', { token: b })).status, 401);
  assert.equal((await t.call('devices/ffffffffffff', { method: 'DELETE', token: owner })).status, 404);
});

test('owner reset needs an explicit confirmation and frees the claim', async () => {
  const t = setup();
  const owner = await claim(t);
  assert.equal((await t.call('me', { method: 'DELETE', body: {}, token: owner })).status, 422);
  assert.equal((await t.call('me', { method: 'DELETE', body: { confirm: 'RESET' }, token: owner })).status, 204);
  assert.equal((await (await t.call('status', { token: owner })).json()).claimed, false);
  await claim(t, { name: 'New phone' });
});

test('bad JSON and unknown paths are rejected', async () => {
  const t = setup();
  const r = await t.call('claim', { method: 'POST' });
  assert.equal(r.status, 201, 'empty body is allowed for claim');
  const handle = createHandler({ store: memoryStore(), env: {}, fetchImpl: async () => { throw new Error('no'); } });
  const bad = await handle(new Request('https://a.example/cloud/claim', { method: 'POST', body: '{nope' }));
  assert.equal(bad.status, 400);
  const token = (await r.json()).token;
  assert.equal((await t.call('nothing', { token })).status, 404);
});
