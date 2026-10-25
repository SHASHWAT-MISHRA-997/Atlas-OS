// ATLAS OS online edition: the server half, one Netlify Function under /cloud/*.
//
// Bring your own key: every visitor types their own AI provider key in the app. The key travels
// with each request over HTTPS, is used for that one provider call, and is never stored or logged
// here. The site owner's keys and Netlify AI Gateway credentials are never used, even if Netlify
// injects them into the environment, so nobody can spend the owner's quota or credits.
//
// It only forwards chat messages and lists models. Memories, chat history and tasks stay in the
// visitor's browser. Nothing here touches any computer.
//
// fetch and the provider table are injectable so tests run without Netlify or real models.

export const VERSION = '0.15.0';

const MAX_MESSAGES = 60;
const MAX_TOTAL_CHARS = 100_000;
const MAX_OUTPUT_TOKENS = 2048;
const MODEL_RE = /^[\w.:/@-]{1,120}$/;
const KEY_RE = /^[\x21-\x7e]{8,400}$/;

// Only providers with a free tier, at their official endpoints only. There is deliberately no way to point a provider at another URL, so the
// function cannot be used to send keys or traffic to arbitrary hosts.
export const PROVIDERS = {
  groq: {
    label: 'Groq', kind: 'openai', base: 'https://api.groq.com/openai/v1', keyUrl: 'https://console.groq.com/keys',
    note: 'Free tier with rate limits.', prefer: [/llama-3\.3-70b/, /llama-3\.1-8b/, /llama/],
    skip: /whisper|guard|tts|playai|orpheus|prompt|compound/i,
  },
  gemini: {
    label: 'Google Gemini', kind: 'gemini', base: 'https://generativelanguage.googleapis.com', keyUrl: 'https://aistudio.google.com/apikey',
    note: 'Free tier with limits. A paid Google key also lists paid models such as Gemini 4 Argon, billed to your Google account.', prefer: [/flash-lite/, /flash/], skip: /image|tts|embedding|aqa|live|audio|vision|learnlm|gemma/i,
    suggested: ['gemini-2.5-flash'],
  },
  openrouter: {
    label: 'OpenRouter', kind: 'openai', base: 'https://openrouter.ai/api/v1', keyUrl: 'https://openrouter.ai/settings/keys',
    note: 'Only its free models (IDs ending in ":free") are offered.', prefer: [/llama|deepseek|qwen|gemma/], skip: /^$/, only: /:free$/,
  },
  // Optional and paid (the owner chose to offer it): never a default, never an auto-switch target.
  openai: {
    label: 'OpenAI (paid)', kind: 'openai', base: 'https://api.openai.com/v1', keyUrl: 'https://platform.openai.com/api-keys', paid: true,
    note: 'Paid, no free tier: every message is billed to your own OpenAI account. GPT-6 Astra costs far more per message than the free providers.',
    prefer: [/^gpt-6-astra$/, /^gpt-6/, /^gpt-5/], tokensField: 'max_completion_tokens',
    skip: /embedding|tts|whisper|dall-e|image|audio|realtime|moderation|transcribe|search|babbage|davinci|instruct|codex/i,
  },
};
export const PROVIDER_ORDER = ['groq', 'gemini', 'openrouter', 'openai'];

const MAX_BODY = 400_000;
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' },
});
const fail = (status, code, detail) => json({ code, detail }, status);

/**
 * True when a browser says the request came from another website. The app itself always calls
 * from the same origin; other sites get no answer (and no CORS headers, so they could not read one).
 */
function fromOtherSite(req, url) {
  const site = req.headers.get('sec-fetch-site');
  if (site === 'cross-site' || site === 'same-site') return true;
  const origin = req.headers.get('origin');
  if (!origin || site === 'same-origin') return false;
  try { return new URL(origin).host !== url.host; } catch { return true; }
}

/** The provider with the visitor's key for this one request, or an error message. */
function withKey(providers, id, key) {
  const preset = typeof id === 'string' && Object.hasOwn(providers, id) ? providers[id] : null;
  if (!preset) return { error: 'Unknown provider.' };
  if (typeof key !== 'string' || !KEY_RE.test(key.trim())) return { error: 'Enter your ' + preset.label + ' API key (Model settings → API key).' };
  return { p: { id, ...preset, key: key.trim() } };
}

// ---------------------------------------------------------------- model calls

function upstreamError(status, text, key) {
  let detail = '';
  try {
    const data = JSON.parse(text);
    const e = Array.isArray(data) ? data[0]?.error : data.error;
    detail = typeof e === 'string' ? e : (e && e.message) || data.message || '';
  } catch { detail = ''; }
  detail = String(detail || text || '').split(key || '\u0000').join('[your key]').replace(/\s+/g, ' ').slice(0, 300);
  const badKey = status === 401 || status === 403 || (status === 400 && /api[ _-]?key/i.test(detail));
  const hint = badKey ? ' Check your API key.'
    : status === 404 ? ' The model ID may be wrong or not available to this key.'
      : status === 429 ? ' Rate limit or free-tier quota reached; wait and try again.' : '';
  const err = new Error('Provider answered HTTP ' + status + (detail ? ': ' + detail : '') + '.' + hint);
  err.status = status;
  err.badKey = badKey;
  return err;
}

/** Splits a fetch response body into SSE `data:` payloads. */
async function* sseData(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let index;
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('');
      if (data) yield data;
    }
  }
  const tail = buffer.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('');
  if (tail) yield tail;
}

function requestFor(p, model, messages, maxTokens) {
  const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
  const turns = messages.filter((m) => m.role !== 'system');
  if (p.kind === 'openai') {
    return {
      url: p.base + '/chat/completions',
      headers: { Authorization: 'Bearer ' + p.key },
      body: { model, messages, stream: true, [p.tokensField || 'max_tokens']: maxTokens },
    };
  }
  return {
    url: p.base + '/v1beta/models/' + encodeURIComponent(model) + ':streamGenerateContent?alt=sse',
    headers: { 'x-goog-api-key': p.key },
    body: {
      contents: turns.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })),
      ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
      generationConfig: { maxOutputTokens: maxTokens },
    },
  };
}

/** Yields text pieces from the provider; fills `result` with finish reason and token usage when known. */
async function* generate(fetchImpl, p, model, messages, maxTokens, signal, result) {
  const r = requestFor(p, model, messages, maxTokens);
  const response = await fetchImpl(r.url, {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...r.headers },
    body: JSON.stringify(r.body),
  });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
  for await (const data of sseData(response.body)) {
    if (data === '[DONE]') break;
    let msg;
    try { msg = JSON.parse(data); } catch { continue; }
    if (msg.error) throw upstreamError(502, JSON.stringify(msg), p.key);
    if (p.kind === 'openai') {
      const choice = msg.choices && msg.choices[0];
      if (choice && choice.delta && choice.delta.content) yield choice.delta.content;
      if (choice && choice.finish_reason) result.finish_reason = choice.finish_reason;
      const usage = msg.usage || (msg.x_groq && msg.x_groq.usage);
      if (usage) result.usage = { total_tokens: usage.total_tokens };
    } else {
      const cand = msg.candidates && msg.candidates[0];
      for (const part of (cand && cand.content && cand.content.parts) || []) if (part.text && !part.thought) yield part.text;
      if (cand && cand.finishReason) result.finish_reason = cand.finishReason.toLowerCase();
      if (msg.usageMetadata && msg.usageMetadata.totalTokenCount) result.usage = { total_tokens: msg.usageMetadata.totalTokenCount };
    }
  }
}

async function listModels(fetchImpl, p) {
  let url = p.base + '/models';
  const headers = {};
  if (p.kind === 'openai') headers.Authorization = 'Bearer ' + p.key;
  if (p.kind === 'gemini') { url = p.base + '/v1beta/models?pageSize=200'; headers['x-goog-api-key'] = p.key; }
  const response = await fetchImpl(url, { headers });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
  const data = await response.json();
  let ids;
  if (p.kind === 'gemini') {
    ids = (data.models || []).filter((m) => (m.supportedGenerationMethods || []).includes('generateContent'))
      .map((m) => String(m.name).replace(/^models\//, ''));
  } else {
    ids = (data.data || []).map((m) => m.id);
  }
  ids = ids.filter((id) => typeof id === 'string' && MODEL_RE.test(id) && !p.skip.test(id) && (!p.only || p.only.test(id)));
  const rank = (id) => { const i = p.prefer.findIndex((re) => re.test(id)); return i < 0 ? p.prefer.length : i; };
  return [...new Set(ids)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

function validateChat(body, providers) {
  const { p, error } = withKey(providers, body.provider, body.api_key);
  if (error) return { error };
  if (typeof body.model !== 'string' || !MODEL_RE.test(body.model)) return { error: 'Enter a valid model ID.' };
  const msgs = body.messages;
  if (!Array.isArray(msgs) || !msgs.length || msgs.length > MAX_MESSAGES) return { error: 'Send between 1 and ' + MAX_MESSAGES + ' messages.' };
  let total = 0;
  for (const m of msgs) {
    if (!m || !['system', 'user', 'assistant'].includes(m.role) || typeof m.content !== 'string') return { error: 'Each message needs a role and text.' };
    total += m.content.length;
  }
  if (total > MAX_TOTAL_CHARS) return { error: 'The conversation is too long (over ' + MAX_TOTAL_CHARS.toLocaleString('en') + ' characters).' };
  if (!msgs.some((m) => m.role === 'user')) return { error: 'Send at least one user message.' };
  const maxTokens = Math.max(1, Math.min(MAX_OUTPUT_TOKENS, Number(body.max_tokens) || 1024));
  return { p, msgs: msgs.map((m) => ({ role: m.role, content: m.content })), maxTokens };
}

// ---------------------------------------------------------------- handler

export function createHandler({ fetchImpl = fetch, providers = PROVIDERS } = {}) {
  async function chat(req, body) {
    const v = validateChat(body, providers);
    if (v.error) return fail(422, 'invalid_request', v.error);
    const { p, msgs, maxTokens } = v;
    const model = body.model;
    const started = Date.now();
    const result = {};
    const meta = () => ({ provider: p.id, model, local: false, latency_ms: Date.now() - started, ...result });

    if (body.stream === false) {
      let answer = '';
      try {
        for await (const piece of generate(fetchImpl, p, model, msgs, maxTokens, req.signal, result)) answer += piece;
      } catch (err) {
        return fail(502, 'provider_error', err.message);
      }
      if (!answer.trim()) return fail(502, 'empty_answer', 'The model returned an empty answer.');
      return json({ ...meta(), answer });
    }

    const enc = new TextEncoder();
    const send = (controller, event, data) => controller.enqueue(enc.encode('event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n'));
    // Open the upstream first so a bad key or model is a normal HTTP error, not a broken stream.
    const iterator = generate(fetchImpl, p, model, msgs, maxTokens, req.signal, result);
    let first;
    try {
      first = await iterator.next();
    } catch (err) {
      return fail(502, 'provider_error', err.message);
    }
    const firstTokenMs = Date.now() - started;
    const stream = new ReadableStream({
      async start(controller) {
        send(controller, 'start', { provider: p.id, model, local: false });
        try {
          if (!first.done) send(controller, 'delta', { text: first.value });
          if (!first.done) for await (const piece of { [Symbol.asyncIterator]: () => iterator }) send(controller, 'delta', { text: piece });
          send(controller, 'done', { ...meta(), first_token_ms: firstTokenMs });
        } catch (err) {
          send(controller, 'error', { detail: err.message || 'Provider error.' });
        }
        controller.close();
      },
    });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'X-Content-Type-Options': 'nosniff' } });
  }

  return async function handle(req) {
    const url = new URL(req.url);
    const path = url.pathname.replace(/^\/cloud/, '').replace(/\/+$/, '') || '/';
    const method = req.method.toUpperCase();

    if (path === '/status' && method === 'GET') {
      return json({
        version: VERSION,
        key_mode: 'bring-your-own',
        providers: PROVIDER_ORDER.filter((id) => providers[id]).map((id) => ({
          id, label: providers[id].label, key_url: providers[id].keyUrl, note: providers[id].note, paid: !!providers[id].paid,
        })),
      });
    }
    if (method !== 'POST' || !['/chat', '/models'].includes(path)) return fail(404, 'not_found', 'Unknown ATLAS cloud endpoint.');
    if (fromOtherSite(req, url)) return fail(403, 'cross_site', 'ATLAS online only answers its own page.');
    // JSON only: a plain HTML form on another site cannot send this content type.
    if (!/^application\/json\s*(;|$)/i.test(req.headers.get('content-type') || '')) return fail(415, 'json_only', 'Send JSON (Content-Type: application/json).');
    if (Number(req.headers.get('content-length')) > MAX_BODY) return fail(413, 'too_large', 'Request too large.');

    const text = await req.text();
    if (text.length > MAX_BODY) return fail(413, 'too_large', 'Request too large.');
    let body;
    try { body = text ? JSON.parse(text) : {}; } catch { return fail(400, 'invalid_json', 'Request body must be JSON.'); }
    if (!body || typeof body !== 'object') return fail(400, 'invalid_json', 'Request body must be a JSON object.');

    try {
      if (path === '/chat') return await chat(req, body);
      const { p, error } = withKey(providers, body.provider, body.api_key);
      if (error) return fail(422, 'invalid_request', error);
      try {
        return json({ provider: p.id, models: await listModels(fetchImpl, p) });
      } catch (err) {
        if (err.badKey) return fail(502, 'provider_error', err.message);
        // Some providers do not list models for every key; offer the documented default so chat still works.
        return json({ provider: p.id, models: p.suggested || [], suggested_only: true, warning: 'Could not list models: ' + err.message });
      }
    } catch (err) {
      console.error('atlas cloud error:', err && err.name);
      return fail(500, 'server_error', 'ATLAS cloud had a problem. Try again.');
    }
  };
}
