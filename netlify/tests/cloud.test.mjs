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
  assert.deepEqual(fallback.models, ['gemini-flash-lite-latest'], 'the -latest alias: dated models are retired for new keys');
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
  assert.match(t.calls[1].url, /gemini-flash-lite-latest:generateContent$/);
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

test('Calendar and Gmail were removed: no Google sign-in, Calendar or Gmail hosts, and the strict window isolation is back', async () => {
  const { readFileSync, existsSync } = await import('node:fs');
  const toml = readFileSync(new URL('../../netlify.toml', import.meta.url), 'utf8');
  const csp = /Content-Security-Policy = "([^"]+)"/.exec(toml)[1];
  assert.doesNotMatch(csp, /accounts\.google\.com|gmail\.googleapis\.com|www\.googleapis\.com|oauth2\.googleapis\.com|frame-src/);
  assert.match(csp, /script-src 'self';/);
  assert.match(toml, /Cross-Origin-Opener-Policy = "same-origin"\r?\n/);
  assert.equal(existsSync(new URL('../../frontend/static/google.js', import.meta.url)), false);
  const app = readFileSync(new URL('../../frontend/static/app.js', import.meta.url), 'utf8');
  assert.doesNotMatch(app, /gmail\.googleapis|googleapis\.com\/calendar|\/static\/google\.js|\/config\.json|AtlasGoogle/);
  const t = setup();
  for (const path of ['google', 'calendar', 'gmail', 'oauth']) {
    assert.equal((await t.call(path, { method: 'POST', body: {} })).status, 404);
  }
  assert.equal(t.calls.length, 0);
});

test('speech endpoints: a real 1-second WAV is accepted, and every failing step returns the provider\'s own words', async () => {
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

test('Whisper words for silence ("Gracias.", seen on the owner\'s phone) are dropped; real speech is kept', async () => {
  const WAV = Buffer.from('RIFF$\u0000\u0000\u0000WAVEfmt fake test audio').toString('base64');
  let reply;
  const t = setup({ upstream: async () => Response.json(reply) });
  const call = async () => (await (await t.call('transcribe', { method: 'POST', body: { provider: 'groq', api_key: KEY, audio: WAV } })).json()).text;
  reply = { text: ' Gracias.', segments: [{ text: ' Gracias.', no_speech_prob: 0.93, avg_logprob: -0.9 }] };
  assert.equal(await call(), '', 'silence gives no words');
  assert.equal(t.calls[0].init.body.get('response_format'), 'verbose_json');
  assert.equal(t.calls[0].init.body.get('temperature'), '0');
  reply = { text: ' kal ka plan batao Thank you.', segments: [{ text: ' kal ka plan batao', no_speech_prob: 0.02 }, { text: ' Thank you.', no_speech_prob: 0.81 }] };
  assert.equal(await call(), 'kal ka plan batao');
  reply = { text: ' namaste atlas ' };
  assert.equal(await call(), 'namaste atlas', 'a reply without pieces is used as it is');
});

test("youtube: finds the top video with the visitor's Google key; refuses other providers", async () => {
  const t = setup({ upstream: () => new Response(JSON.stringify({ items: [{ id: { videoId: 'abcDEF12345' }, snippet: { title: 'Tum Hi Ho &amp; more &#39;live&#39;', channelTitle: 'T-Series' } }] })) });
  const call = (body) => t.call('youtube', { method: 'POST', body: { provider: 'gemini', api_key: KEY, ...body } });
  const found = await call({ query: 'tum hi ho arijit' });
  assert.equal(found.status, 200);
  assert.deepEqual(await found.json(), { id: 'abcDEF12345', title: "Tum Hi Ho & more 'live'", channel: 'T-Series', via: 'youtube' });
  const sent = new URL(t.calls[0].url);
  assert.equal(sent.origin + sent.pathname, 'https://www.googleapis.com/youtube/v3/search');
  assert.equal(sent.searchParams.get('q'), 'tum hi ho arijit');
  assert.equal(sent.searchParams.get('key'), KEY);
  assert.equal((await call({ query: '' })).status, 422);
  assert.equal((await call({ query: 'x'.repeat(201) })).status, 422);
  assert.equal((await t.call('youtube', { method: 'POST', body: { provider: 'groq', api_key: KEY, query: 'song' } })).status, 422);
  assert.equal(t.calls.length, 1, 'refused requests never reach Google');
});

test('youtube: an AI Studio key (bound to the Gemini API) finds the video with Gemini, checked on YouTube', async () => {
  // FAKE Google: the Data API refuses bound keys; Gemini answers with links; oEmbed knows two videos.
  const VIDEOS = { kesar111111: { title: 'Kesariya - Brahmastra | Arijit Singh', author_name: 'Sony Music India' }, other222222: { title: 'Cooking pasta at home', author_name: 'Chef' }, tumhiho1111: { title: '"Tum Hi Ho" Aashiqui 2 Full Song With Lyrics | Aditya Roy Kapur, Shraddha Kapoor', author_name: 'T-Series' } };
  const say = { search: '', plain: '', searchQuota: false };
  const asked = [];
  const t = setup({ upstream: (url, init) => {
    if (url.startsWith('https://www.googleapis.com/youtube/')) return new Response(JSON.stringify({ error: { message: 'Requests to this API youtube.googleapis.com method youtube.api.v3.V3DataSearchService.List are blocked. <b>x</b>' } }), { status: 403 });
    if (url.includes(':generateContent')) {
      // The first model is retired for this key, as gemini-2.5-flash was on the owner's key.
      if (url.includes('/models/gemini-flash-lite-latest:')) return new Response(JSON.stringify({ error: { message: 'This model is no longer available to new users.' } }), { status: 404 });
      assert.equal(init.headers['x-goog-api-key'], KEY);
      const search = !!JSON.parse(init.body).tools;
      asked.push(search ? 'search' : 'plain');
      // Free keys get no Google Search quota on Gemini 3 and newer (0 / 0 on the owner's key).
      if (search && say.searchQuota) return new Response(JSON.stringify({ error: { message: 'You exceeded your current quota, please check your plan and billing details.' } }), { status: 429 });
      return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: search ? say.search : say.plain }] } }] }));
    }
    const id = new URL(new URL(url).searchParams.get('url')).searchParams.get('v');
    return VIDEOS[id] ? new Response(JSON.stringify(VIDEOS[id])) : new Response('Bad Request', { status: 400 });
  } });
  const call = (query) => t.call('youtube', { method: 'POST', body: { provider: 'gemini', api_key: KEY, query } });
  // With Google Search: a made-up id and an unrelated video are skipped; the matching one is played.
  say.search = 'https://www.youtube.com/watch?v=fakefake123 then https://youtu.be/other222222 or https://www.youtube.com/watch?v=kesar111111&t=3';
  const found = await call('Kesariya Arijit Singh');
  assert.equal(found.status, 200);
  assert.deepEqual(await found.json(), { id: 'kesar111111', title: 'Kesariya - Brahmastra | Arijit Singh', channel: 'Sony Music India', via: 'search' });
  // No search quota (a free key): Gemini names the video from what it knows; still checked on YouTube.
  say.searchQuota = true;
  say.plain = 'https://www.youtube.com/watch?v=kesar111111';
  asked.length = 0;
  const known = await call('Kesariya Arijit Singh');
  assert.equal(known.status, 200);
  assert.equal((await known.json()).via, 'gemini');
  assert.ok(asked.includes('search') && asked.at(-1) === 'plain', asked.join());
  // A song title that leaves out the singer still counts (one of three words is enough).
  say.plain = 'https://www.youtube.com/watch?v=tumhiho1111';
  const tum = await call('Tum Hi Ho Arijit Singh');
  assert.equal((await tum.json()).id, 'tumhiho1111');
  // An unrelated video (no word matches) is never played: an honest error.
  say.plain = 'https://www.youtube.com/watch?v=other222222';
  const none = await call('Kesariya Arijit Singh');
  assert.equal(none.status, 502);
  const detail = (await none.json()).detail;
  assert.match(detail, /^Could not find a matching YouTube video for "Kesariya Arijit Singh" \(YouTube \(your key\): Requests to this API .* are blocked\. x; Google Search: You exceeded your current quota.*; Gemini: no matching video\)\.$/);
  assert.doesNotMatch(detail, /<b>/);
});

test('youtube: with ATLAS_YOUTUBE_KEY set, the site key finds the video first', async () => {
  const urls = [];
  const handle = createHandler({ youtubeKey: 'site-youtube-key-123', fetchImpl: async (url) => {
    urls.push(String(url));
    return new Response(JSON.stringify({ items: [{ id: { videoId: 'abcDEF12345' }, snippet: { title: 'Kesariya', channelTitle: 'Sony Music India' } }] }));
  } });
  const r = await handle(new Request('https://atlas.example/cloud/youtube', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: 'gemini', api_key: KEY, query: 'kesariya' }) }));
  assert.equal((await r.json()).id, 'abcDEF12345');
  assert.equal(urls.length, 1);
  assert.equal(new URL(urls[0]).searchParams.get('key'), 'site-youtube-key-123');
});

test('gemini chat models: the -latest aliases come first, so a new key never starts on a retired dated model', async () => {
  const t = setup({ upstream: async () => Response.json({ models: ['gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-3.5-flash-lite', 'gemini-flash-latest', 'gemini-flash-lite-latest']
    .map((id) => ({ name: 'models/' + id, supportedGenerationMethods: ['generateContent'] })) }) });
  const models = (await (await t.call('models', { method: 'POST', body: { provider: 'gemini', api_key: KEY } })).json()).models;
  assert.deepEqual(models.slice(0, 2), ['gemini-flash-lite-latest', 'gemini-flash-latest']);
});
