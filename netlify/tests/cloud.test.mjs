// Tests for the ATLAS online function (netlify/lib/cloud.mjs). Model providers are FAKE fetch stubs.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHandler } from '../lib/cloud.mjs';

const KEY = 'visitor-key-not-real-123';

function sseResponse(payloads) {
  return new Response(new ReadableStream({
    start(c) { for (const p of payloads) c.enqueue(new TextEncoder().encode('data: ' + p + '\n\n')); c.close(); },
  }), { headers: { 'Content-Type': 'text/event-stream' } });
}

function setup({ upstream } = {}) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return upstream ? upstream(String(url), init) : sseResponse([JSON.stringify({ choices: [{ delta: { content: 'Hello' } }] }),
      JSON.stringify({ choices: [{ delta: { content: ' there' }, finish_reason: 'stop' }] }), '[DONE]']);
  };
  const handle = createHandler({ fetchImpl });
  const call = (path, { method = 'GET', body, raw } = {}) => handle(new Request('https://atlas.example/cloud/' + path, {
    method, headers: body || raw ? { 'Content-Type': 'application/json' } : {}, body: raw ?? (body ? JSON.stringify(body) : undefined),
  }));
  return { call, calls };
}

async function events(response) {
  const text = await response.text();
  return text.trim().split('\n\n').map((block) => {
    const [ev, data] = block.split('\n');
    return { event: ev.slice(7), data: JSON.parse(data.slice(6)) };
  });
}

const chatBody = (extra = {}) => ({ provider: 'groq', api_key: KEY, model: 'llama-3.1-8b-instant', messages: [{ role: 'system', content: 'be brief' }, { role: 'user', content: 'hi' }], ...extra });

test('status lists the providers a visitor can use with their own key', async () => {
  const s = await (await setup().call('status')).json();
  assert.equal(s.key_mode, 'bring-your-own');
  assert.deepEqual(s.providers.map((p) => p.id), ['groq', 'gemini', 'openrouter'], 'only providers with a free tier');
  assert.ok(s.providers.every((p) => p.key_url.startsWith('https://') && p.label && p.note));
});

test('the site owner\'s environment keys and AI Gateway are never used', async () => {
  const saved = { ...process.env };
  Object.assign(process.env, { GROQ_API_KEY: 'owner-key', OPENAI_API_KEY: 'gw-key', OPENAI_BASE_URL: 'https://gateway.example/v1' });
  try {
    const t = setup();
    const r = await t.call('chat', { method: 'POST', body: chatBody({ api_key: '' }) });
    assert.equal(r.status, 422);
    assert.match((await r.json()).detail, /Enter your Groq API key/);
    await (await t.call('chat', { method: 'POST', body: chatBody() })).text();
    assert.equal(t.calls.length, 1);
    assert.equal(t.calls[0].url, 'https://api.groq.com/openai/v1/chat/completions', 'official URL, not the gateway');
    assert.equal(t.calls[0].init.headers.Authorization, 'Bearer ' + KEY, 'the visitor\'s key, not the environment\'s');
  } finally {
    for (const k of ['GROQ_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL']) if (k in saved) process.env[k] = saved[k]; else delete process.env[k];
  }
});

test('streamed chat sends the visitor key upstream and ATLAS events to the browser', async () => {
  const t = setup();
  const r = await t.call('chat', { method: 'POST', body: chatBody() });
  assert.equal(r.status, 200);
  assert.match(r.headers.get('content-type'), /event-stream/);
  const ev = await events(r);
  assert.deepEqual(ev.map((e) => e.event), ['start', 'delta', 'delta', 'done']);
  assert.equal(ev.filter((e) => e.event === 'delta').map((e) => e.data.text).join(''), 'Hello there');
  assert.equal(ev[3].data.finish_reason, 'stop');
  assert.ok(!JSON.stringify(ev).includes(KEY));
  const [call] = t.calls;
  assert.equal(call.url, 'https://api.groq.com/openai/v1/chat/completions');
  assert.equal(call.init.headers.Authorization, 'Bearer ' + KEY);
  const sent = JSON.parse(call.init.body);
  assert.equal(sent.model, 'llama-3.1-8b-instant');
  assert.equal(sent.stream, true);
  assert.equal(sent.messages.length, 2);
  assert.ok(!('api_key' in sent));
});

test('non-streamed chat returns the whole answer', async () => {
  const data = await (await setup().call('chat', { method: 'POST', body: chatBody({ stream: false }) })).json();
  assert.equal(data.answer, 'Hello there');
  assert.equal(data.provider, 'groq');
});

test('provider errors become a clear message, with any echoed key removed', async () => {
  const t = setup({ upstream: async () => new Response('{"error":{"message":"Incorrect API key provided: ' + KEY + '"}}', { status: 401 }) });
  const r = await t.call('chat', { method: 'POST', body: chatBody() });
  assert.equal(r.status, 502);
  const data = await r.json();
  assert.match(data.detail, /HTTP 401: Incorrect API key provided: \[your key\]\. Check your API key\./);
  assert.ok(!JSON.stringify(data).includes(KEY));
});

test('an error in the middle of a stream ends with an error event', async () => {
  const t = setup({ upstream: async () => sseResponse([JSON.stringify({ choices: [{ delta: { content: 'Par' } }] }), JSON.stringify({ error: { message: 'overloaded' } })]) });
  const ev = await events(await t.call('chat', { method: 'POST', body: chatBody() }));
  assert.deepEqual(ev.map((e) => e.event), ['start', 'delta', 'error']);
  assert.match(ev[2].data.detail, /overloaded/);
});

test('chat input is validated before any provider call', async () => {
  const t = setup();
  const bad = [
    chatBody({ provider: 'ollama' }),
    chatBody({ provider: 'openai' }),
    chatBody({ provider: 'anthropic' }),
    chatBody({ provider: '__proto__' }),
    chatBody({ provider: 'toString' }),
    chatBody({ api_key: 'short' }),
    chatBody({ api_key: 'has spaces in it ok' }),
    chatBody({ api_key: 42 }),
    chatBody({ model: 'bad model id!' }),
    chatBody({ messages: [] }),
    chatBody({ messages: [{ role: 'system', content: 'only system' }] }),
    chatBody({ messages: [{ role: 'tool', content: 'x' }] }),
    chatBody({ messages: [{ role: 'user', content: 'x'.repeat(100_001) }] }),
  ];
  for (const body of bad) assert.equal((await t.call('chat', { method: 'POST', body })).status, 422, JSON.stringify(body).slice(0, 80));
  assert.equal(t.calls.length, 0);
});

test('output tokens are capped', async () => {
  const t = setup();
  await (await t.call('chat', { method: 'POST', body: chatBody({ max_tokens: 999999 }) })).text();
  assert.equal(JSON.parse(t.calls[0].init.body).max_tokens, 2048);
});

test('Gemini requests use the native API and its stream format', async () => {
  const t = setup({
    upstream: async () => sseResponse([JSON.stringify({ candidates: [{ content: { parts: [{ text: 'Namaste' }] } }] }),
      JSON.stringify({ candidates: [{ content: { parts: [{ text: '!' }] }, finishReason: 'STOP' }], usageMetadata: { totalTokenCount: 9 } })]),
  });
  const body = { provider: 'gemini', api_key: KEY, model: 'gemini-2.5-flash', messages: [{ role: 'system', content: 'sys' }, { role: 'user', content: 'a' }, { role: 'assistant', content: 'b' }, { role: 'user', content: 'c' }], stream: false };
  const data = await (await t.call('chat', { method: 'POST', body })).json();
  assert.equal(data.answer, 'Namaste!');
  assert.equal(data.usage.total_tokens, 9);
  const call = t.calls[0];
  assert.equal(call.url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse');
  assert.equal(call.init.headers['x-goog-api-key'], KEY);
  const sent = JSON.parse(call.init.body);
  assert.deepEqual(sent.systemInstruction, { parts: [{ text: 'sys' }] });
  assert.deepEqual(sent.contents.map((c) => c.role), ['user', 'model', 'user']);
});

test('OpenRouter uses its OpenAI-compatible endpoint', async () => {
  const t = setup();
  await (await t.call('chat', { method: 'POST', body: chatBody({ provider: 'openrouter', model: 'meta-llama/llama-3.3-70b-instruct:free' }) })).text();
  assert.equal(t.calls[0].url, 'https://openrouter.ai/api/v1/chat/completions');
});

test('model lists are filtered; listing errors fall back to a suggestion, bad keys do not', async () => {
  const t = setup({
    upstream: async (url) => (url.includes('groq')
      ? Response.json({ data: [{ id: 'whisper-large-v3' }, { id: 'gemma2-9b-it' }, { id: 'llama-3.1-8b-instant' }, { id: 'llama-guard-4' }] })
      : url.includes('openrouter') ? Response.json({ data: [{ id: 'openai/gpt-5' }, { id: 'meta-llama/llama-3.3-70b-instruct:free' }, { id: 'mistralai/mistral-7b:free' }] })
        : new Response('{"error":{"message":"not found"}}', { status: 404 })),
  });
  const list = async (provider, key = KEY) => t.call('models', { method: 'POST', body: { provider, api_key: key } });
  assert.deepEqual((await (await list('groq')).json()).models, ['llama-3.1-8b-instant', 'gemma2-9b-it']);
  assert.equal(t.calls[0].init.headers.Authorization, 'Bearer ' + KEY);
  assert.deepEqual((await (await list('openrouter')).json()).models, ['meta-llama/llama-3.3-70b-instruct:free', 'mistralai/mistral-7b:free'], 'free models only');
  const fallback = await (await list('gemini')).json();
  assert.deepEqual(fallback.models, ['gemini-2.5-flash']);
  assert.equal(fallback.suggested_only, true);
  assert.match(fallback.warning, /not found/);
  assert.equal((await t.call('models', { method: 'POST', body: { provider: 'groq' } })).status, 422);
});

test('a rejected key is reported when listing models (Groq 401, Gemini 400)', async () => {
  const t = setup({ upstream: async (url) => (url.includes('groq')
    ? new Response('{"error":{"message":"Invalid API Key"}}', { status: 401 })
    : new Response('[{"error":{"code":400,"message":"API key not valid. Please pass a valid API key."}}]', { status: 400 })) });
  for (const [provider, text] of [['groq', /Invalid API Key\. Check your API key/], ['gemini', /API key not valid.*Check your API key/]]) {
    const r = await t.call('models', { method: 'POST', body: { provider, api_key: KEY } });
    assert.equal(r.status, 502, provider);
    assert.match((await r.json()).detail, text);
  }
});

test('only status (GET) and chat/models (POST) exist; bad JSON is refused', async () => {
  const t = setup();
  assert.equal((await t.call('chat')).status, 404);
  assert.equal((await t.call('claim', { method: 'POST', body: {} })).status, 404);
  assert.equal((await t.call('status', { method: 'POST', body: {} })).status, 404);
  assert.equal((await t.call('chat', { method: 'POST', raw: '{nope' })).status, 400);
  assert.equal((await t.call('chat', { method: 'POST', raw: 'null' })).status, 400);
  assert.equal(t.calls.length, 0);
});
