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
  assert.deepEqual(s.providers.map((p) => p.id), ['groq', 'gemini', 'openrouter', 'openai']);
  assert.deepEqual(s.providers.filter((p) => p.paid).map((p) => p.id), ['openai'], 'the free providers come first; OpenAI is marked paid');
  assert.match(s.providers.find((p) => p.id === 'openai').note, /billed to your own OpenAI account/);
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

test('real-time voice models: Gemini Live and OpenAI Realtime models only; other providers refused', async () => {
  const t = setup({ upstream: async () => Response.json({ models: [
    { name: 'models/gemini-2.5-flash', supportedGenerationMethods: ['generateContent', 'countTokens'] },
    { name: 'models/gemini-live-2.5-flash', supportedGenerationMethods: ['bidiGenerateContent'] },
    { name: 'models/gemini-2.5-flash-native-audio-preview-12-2025', supportedGenerationMethods: ['countTokens', 'bidiGenerateContent'] },
    { name: 'models/bad model<script>', supportedGenerationMethods: ['bidiGenerateContent'] },
  ] }) });
  const r = await t.call('models', { method: 'POST', body: { provider: 'gemini', api_key: KEY, live: true } });
  assert.deepEqual((await r.json()).models, ['gemini-2.5-flash-native-audio-preview-12-2025', 'gemini-live-2.5-flash']);
  assert.equal(t.calls[0].init.headers['x-goog-api-key'], KEY);
  const plain = await t.call('models', { method: 'POST', body: { provider: 'gemini', api_key: KEY } });
  assert.ok(!(await plain.json()).models.some((m) => /live|native-audio/.test(m)), 'chat models stay chat models');
  const groq = await t.call('models', { method: 'POST', body: { provider: 'groq', api_key: KEY, live: true } });
  assert.equal(groq.status, 422);
  assert.match((await groq.json()).detail, /Gemini key or an OpenAI key/);
  const oa = setup({ upstream: async () => Response.json({ data: [{ id: 'gpt-6' }, { id: 'gpt-4o-realtime-preview' }, { id: 'gpt-realtime-mini' }, { id: 'gpt-realtime' }, { id: 'gpt-realtime-2025-08-28' }] }) });
  const openai = await (await oa.call('models', { method: 'POST', body: { provider: 'openai', api_key: KEY, live: true } })).json();
  assert.deepEqual(openai.models, ['gpt-realtime', 'gpt-realtime-2025-08-28', 'gpt-realtime-mini', 'gpt-4o-realtime-preview'], 'OpenAI realtime models only, released and full first');
  assert.equal(oa.calls[0].init.headers.Authorization, 'Bearer ' + KEY);
  const down = setup({ upstream: async () => new Response('{"error":{"message":"unavailable"}}', { status: 503 }) });
  const fallback = await (await down.call('models', { method: 'POST', body: { provider: 'gemini', api_key: KEY, live: true } })).json();
  assert.deepEqual(fallback.models, ['gemini-2.5-flash-native-audio-preview-12-2025']);
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

test('paid OpenAI (optional) uses its official URL, the visitor\'s key and max_completion_tokens', async () => {
  const t = setup();
  await (await t.call('chat', { method: 'POST', body: chatBody({ provider: 'openai', model: 'gpt-6-astra', max_tokens: 99999 }) })).text();
  assert.equal(t.calls[0].url, 'https://api.openai.com/v1/chat/completions');
  assert.equal(t.calls[0].init.headers.Authorization, 'Bearer ' + KEY);
  const sent = JSON.parse(t.calls[0].init.body);
  assert.equal(sent.max_completion_tokens, 2048);
  assert.equal('max_tokens' in sent, false);
});

// ---------------------------------------------------------------- v0.17: thinking and files

const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
const PDF = Buffer.from('%PDF-1.4 fake test pdf').toString('base64');
const withFiles = (attachments, extra = {}) => chatBody({ messages: [{ role: 'user', content: 'what is this?', attachments }], ...extra });

test('thinking level: Groq and OpenAI get reasoning_effort, OpenRouter its reasoning field, Gemini a thinking budget', async () => {
  const t = setup();
  await (await t.call('chat', { method: 'POST', body: chatBody({ thinking: 'high', stream: false }) })).json();
  let sent = JSON.parse(t.calls[0].init.body);
  assert.equal(sent.reasoning_effort, 'high');
  assert.equal(sent.max_tokens, 1024 + 14336, 'room for thinking on top of the answer');

  await (await t.call('chat', { method: 'POST', body: chatBody({ provider: 'openrouter', model: 'x/y:free', thinking: 'low', stream: false }) })).json();
  sent = JSON.parse(t.calls[1].init.body);
  assert.deepEqual(sent.reasoning, { effort: 'low', exclude: true });
  assert.equal(sent.reasoning_effort, undefined);

  const g = setup({ upstream: () => sseResponse([JSON.stringify({ candidates: [{ content: { parts: [{ text: 'hmm', thought: true }, { text: 'Answer' }] }, finishReason: 'STOP' }] })]) });
  const r = await (await g.call('chat', { method: 'POST', body: chatBody({ provider: 'gemini', model: 'gemini-2.5-flash', thinking: 'medium', stream: false }) })).json();
  assert.equal(r.answer, 'Answer', 'thoughts are not shown as the answer');
  assert.equal(r.thinking, 'medium');
  assert.deepEqual(JSON.parse(g.calls[0].init.body).generationConfig, { maxOutputTokens: 1024 + 6144, thinkingConfig: { thinkingBudget: 6144 } });

  const bad = await setup().call('chat', { method: 'POST', body: chatBody({ thinking: 'max' }) });
  assert.equal(bad.status, 422);
});

test('a model that cannot think answers again without the thinking setting, and says so', async () => {
  let n = 0;
  const t = setup({ upstream: () => (++n === 1
    ? new Response('{"error":{"message":"reasoning_effort is not supported with this model"}}', { status: 400 })
    : sseResponse([JSON.stringify({ choices: [{ delta: { content: 'ok' }, finish_reason: 'stop' }] }), '[DONE]'])) });
  const r = await (await t.call('chat', { method: 'POST', body: chatBody({ thinking: 'low', stream: false }) })).json();
  assert.equal(r.answer, 'ok');
  assert.equal(r.thinking, 'not supported by this model');
  assert.equal(t.calls.length, 2);
  assert.equal(JSON.parse(t.calls[1].init.body).reasoning_effort, undefined);
  // Any other 400 is a real error, not retried.
  const other = setup({ upstream: () => new Response('{"error":{"message":"bad model"}}', { status: 400 }) });
  assert.equal((await other.call('chat', { method: 'POST', body: chatBody({ thinking: 'low', stream: false }) })).status, 502);
  assert.equal(other.calls.length, 1);
});

test('images and PDFs: OpenAI-style parts, Gemini inline data, and PDFs refused for Groq', async () => {
  const t = setup();
  await (await t.call('chat', { method: 'POST', body: withFiles([{ mime: 'image/png', data: PNG, name: 'a.png' }], { stream: false }) })).json();
  const content = JSON.parse(t.calls[0].init.body).messages[0].content;
  assert.deepEqual(content[0], { type: 'text', text: 'what is this?' });
  assert.equal(content[1].image_url.url, 'data:image/png;base64,' + PNG);

  await (await t.call('chat', { method: 'POST', body: withFiles([{ mime: 'application/pdf', data: PDF, name: 'n<o>tes.pdf' }], { provider: 'openrouter', model: 'x/y:free', stream: false }) })).json();
  assert.deepEqual(JSON.parse(t.calls[1].init.body).messages[0].content[1], { type: 'file', file: { filename: 'notes.pdf', file_data: 'data:application/pdf;base64,' + PDF } });

  const g = setup({ upstream: () => sseResponse([JSON.stringify({ candidates: [{ content: { parts: [{ text: 'A PDF' }] } }] })]) });
  await (await g.call('chat', { method: 'POST', body: withFiles([{ mime: 'application/pdf', data: PDF }], { provider: 'gemini', model: 'gemini-2.5-flash', stream: false }) })).json();
  assert.deepEqual(JSON.parse(g.calls[0].init.body).contents[0].parts[1], { inlineData: { mimeType: 'application/pdf', data: PDF } });

  const groqPdf = await t.call('chat', { method: 'POST', body: withFiles([{ mime: 'application/pdf', data: PDF }]) });
  assert.equal(groqPdf.status, 422);
  assert.match((await groqPdf.json()).detail, /cannot read PDFs/);
  assert.equal(t.calls.length, 2, 'no provider call for a refused file');
});

test('attachments are validated: type, base64, count, size, and only on user messages', async () => {
  const t = setup();
  const refuse = async (body, re) => {
    const r = await t.call('chat', { method: 'POST', body });
    assert.equal(r.status, 422, JSON.stringify(body).slice(0, 80));
    assert.match((await r.json()).detail, re);
  };
  await refuse(withFiles([{ mime: 'text/html', data: PNG }]), /PNG, JPEG/);
  await refuse(withFiles([{ mime: 'image/svg+xml', data: PNG }]), /PNG, JPEG/);
  await refuse(withFiles([{ mime: 'image/png', data: 'not base64!' }]), /PNG, JPEG/);
  await refuse(withFiles(Array(5).fill({ mime: 'image/png', data: PNG })), /up to 4/);
  await refuse(withFiles([{ mime: 'image/png', data: 'A'.repeat(4_000_004) }]), /too large/);
  await refuse(chatBody({ messages: [{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'x', attachments: [{ mime: 'image/png', data: PNG }] }] }), /own messages/);
  assert.equal(t.calls.length, 0);
});

test('speech to text: Whisper on Groq, Gemini on Google, WAV only, no OpenRouter', async () => {
  const WAV = Buffer.from('RIFF$\u0000\u0000\u0000WAVEfmt fake test audio').toString('base64');
  const t = setup({ upstream: async (url) => (url.includes('groq')
    ? Response.json({ text: ' namaste atlas ' })
    : Response.json({ candidates: [{ content: { parts: [{ text: 'kal ka plan batao' }] } }] })) });
  const call = (provider, audio = WAV) => t.call('transcribe', { method: 'POST', body: { provider, api_key: KEY, audio } });
  const groq = await call('groq');
  assert.equal(groq.status, 200);
  assert.deepEqual(await groq.json(), { provider: 'groq', model: 'whisper-large-v3-turbo', text: 'namaste atlas' });
  assert.equal(t.calls[0].url, 'https://api.groq.com/openai/v1/audio/transcriptions');
  assert.equal(t.calls[0].init.headers.Authorization, 'Bearer ' + KEY);
  assert.equal(t.calls[0].init.body.get('model'), 'whisper-large-v3-turbo');
  assert.equal(t.calls[0].init.body.get('file').type, 'audio/wav');
  const gemini = await (await call('gemini')).json();
  assert.equal(gemini.text, 'kal ka plan batao');
  assert.match(t.calls[1].url, /gemini-2\.5-flash:generateContent$/);
  assert.equal(JSON.parse(t.calls[1].init.body).contents[0].parts[0].inlineData.mimeType, 'audio/wav');
  assert.equal((await call('openrouter')).status, 422);
  assert.equal((await call('groq', Buffer.from('not a wav file').toString('base64'))).status, 422);
  assert.equal((await call('groq', 'UklGR' + 'A'.repeat(3_000_000))).status, 422);
  assert.equal(t.calls.length, 2, 'refused requests never reach a provider');
});

test('natural voice: Gemini speech models (falls back to Pro on 404), OpenAI pcm, checked input', async () => {
  const PCM = Buffer.from([1, 0, 2, 0]).toString('base64');
  let flashMissing = false;
  const t = setup({ upstream: async (url) => {
    if (new URL(url).host === 'api.openai.com') return new Response(Buffer.from([3, 0, 4, 0]));
    if (flashMissing && url.includes('flash-preview-tts')) return new Response('{"error":{"message":"not found"}}', { status: 404 });
    return Response.json({ candidates: [{ content: { parts: [{ inlineData: { mimeType: 'audio/L16;codec=pcm;rate=24000', data: PCM } }] } }] });
  } });
  const call = (body) => t.call('speak', { method: 'POST', body: { api_key: KEY, ...body } });
  const gemini = await call({ provider: 'gemini', text: 'Namaste, kal ka plan ready hai.', voice: 'Kore' });
  assert.equal(gemini.status, 200);
  assert.deepEqual(await gemini.json(), { provider: 'gemini', model: 'gemini-2.5-flash-preview-tts', audio: PCM, rate: 24000 });
  assert.match(t.calls[0].url, /gemini-2\.5-flash-preview-tts:generateContent$/);
  assert.equal(t.calls[0].init.headers['x-goog-api-key'], KEY);
  const sent = JSON.parse(t.calls[0].init.body);
  assert.deepEqual(sent.generationConfig.responseModalities, ['AUDIO']);
  assert.equal(sent.generationConfig.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName, 'Kore');
  assert.match(sent.contents[0].parts[0].text, /Namaste, kal ka plan ready hai\.$/);
  flashMissing = true;
  assert.equal((await (await call({ provider: 'gemini', text: 'hello' })).json()).model, 'gemini-2.5-pro-preview-tts');
  const openai = await (await call({ provider: 'openai', text: 'hello', voice: 'marin' })).json();
  assert.equal(openai.audio, Buffer.from([3, 0, 4, 0]).toString('base64'));
  const last = t.calls[t.calls.length - 1];
  assert.equal(last.url, 'https://api.openai.com/v1/audio/speech');
  assert.equal(JSON.parse(last.init.body).response_format, 'pcm');
  const before = t.calls.length;
  assert.equal((await call({ provider: 'groq', text: 'hello' })).status, 422);
  assert.equal((await call({ provider: 'gemini', text: '' })).status, 422);
  assert.equal((await call({ provider: 'gemini', text: 'x'.repeat(1501) })).status, 422);
  assert.equal((await call({ provider: 'gemini', text: 'hi', voice: '../evil' })).status, 422);
  assert.equal(t.calls.length, before, 'refused requests never reach a provider');
});

test('Google Calendar and Gmail: the browser may reach only Google sign-in and the two read APIs; the function is no proxy for them', async () => {
  const { readFileSync } = await import('node:fs');
  const toml = readFileSync(new URL('../../netlify.toml', import.meta.url), 'utf8');
  const csp = Object.fromEntries(/Content-Security-Policy = "([^"]+)"/.exec(toml)[1].split(';').map((d) => d.trim().split(/\s+/)).map(([k, ...v]) => [k, v]));
  assert.deepEqual(csp['script-src'], ["'self'", 'https://accounts.google.com/gsi/client']);
  assert.deepEqual(csp['frame-src'], ['https://accounts.google.com/gsi/']);
  assert.deepEqual(csp['connect-src'].filter((h) => /^(https|wss):\/\/([a-z0-9-]+\.)*(google|googleapis)\.com(\/|$)/.test(h)).sort(), [
    'https://accounts.google.com/gsi/', 'https://gmail.googleapis.com/gmail/v1/', 'https://oauth2.googleapis.com/revoke',
    'https://www.googleapis.com/calendar/v3/', 'wss://generativelanguage.googleapis.com']);
  assert.match(toml, /Cross-Origin-Opener-Policy = "same-origin-allow-popups"/, 'the Google sign-in pop-up can report back');
  for (const f of ['app.js', 'google.js', 'cloud.js']) {
    assert.ok(!/[0-9]{6,}-[a-z0-9_]{8,}\.apps\.googleusercontent\.com/.test(readFileSync(new URL('../../frontend/static/' + f, import.meta.url), 'utf8')), 'no client ID in ' + f);
  }
  const t = setup();
  for (const path of ['google', 'calendar', 'gmail', 'oauth']) {
    assert.equal((await t.call(path, { method: 'POST', body: { url: 'https://gmail.googleapis.com/gmail/v1/users/me/messages' } })).status, 404);
  }
  assert.equal(t.calls.length, 0);
});

test('voice check: a real 1-second WAV is accepted, and every failing step returns the provider\'s own words', async () => {
  // One second of 16 kHz mono 16-bit silence, built the same way as the app's recorder.
  const n = 16000;
  const wav = Buffer.alloc(44 + n * 2);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + n * 2, 4); wav.write('WAVEfmt ', 8); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(16000, 24); wav.writeUInt32LE(32000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(n * 2, 40);
  const ok = setup({ upstream: async () => Response.json({ text: '' }) });
  const heard = await ok.call('transcribe', { method: 'POST', body: { provider: 'groq', api_key: KEY, audio: wav.toString('base64') } });
  assert.equal(heard.status, 200);
  assert.equal((await heard.json()).text, '', 'silence is an answer, not an error');
  assert.equal(ok.calls[0].init.body.get('file').size, wav.length);
  const quota = '{"error":{"code":429,"message":"You exceeded your current quota, please check your plan and billing details.","status":"RESOURCE_EXHAUSTED"}}';
  const t = setup({ upstream: async () => new Response(quota, { status: 429 }) });
  for (const [path, body] of [['speak', { provider: 'gemini', api_key: KEY, text: 'Hello, this is ATLAS. Your voice works.', voice: 'Puck' }],
    ['transcribe', { provider: 'gemini', api_key: KEY, audio: wav.toString('base64') }]]) {
    const r = await t.call(path, { method: 'POST', body });
    assert.equal(r.status, 502, path);
    assert.equal((await r.json()).detail, 'Provider answered HTTP 429: You exceeded your current quota, please check your plan and billing details. Rate limit or free-tier quota reached; wait and try again.', path);
  }
  // A real-time model list that fails for a reason other than the key: a usual model, with Google's reason as a warning.
  const down = setup({ upstream: async () => new Response('{"error":{"message":"The service is currently unavailable."}}', { status: 503 }) });
  const live = await (await down.call('models', { method: 'POST', body: { provider: 'gemini', api_key: KEY, live: true } })).json();
  assert.equal(live.suggested_only, true);
  assert.match(live.warning, /HTTP 503: The service is currently unavailable\./);
});

test('a wrong OpenRouter key is refused even though OpenRouter lists its models to anyone (seen on the real API)', async () => {
  const t = setup({ upstream: async (url, init) => (url.endsWith('/api/v1/key')
    ? (init.headers.Authorization === 'Bearer ' + KEY ? Response.json({ data: { label: 'ok' } }) : new Response('{"error":{"message":"Missing Authentication header","code":401}}', { status: 401 }))
    : Response.json({ data: [{ id: 'google/gemma-4-31b-it:free' }] })) });
  const wrong = await t.call('models', { method: 'POST', body: { provider: 'openrouter', api_key: 'sk-or-wrong-key-0000' } });
  assert.equal(wrong.status, 502);
  assert.match((await wrong.json()).detail, /HTTP 401.*Check your API key/);
  assert.equal(t.calls[0].url, 'https://openrouter.ai/api/v1/key');
  assert.equal(t.calls[0].init.headers.Authorization, 'Bearer sk-or-wrong-key-0000');
  assert.equal(t.calls.length, 1, 'the model list is not fetched for a wrong key');
  const right = await (await t.call('models', { method: 'POST', body: { provider: 'openrouter', api_key: KEY } })).json();
  assert.deepEqual(right.models, ['google/gemma-4-31b-it:free']);
});
